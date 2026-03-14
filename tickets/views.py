from datetime import timedelta

import requests
from celery import current_app
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from requests.auth import HTTPBasicAuth
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.tasks import (
    notify_reporter_resolved,
    notify_ticket_subscribers,
    send_deadline_reminder,
    send_ticket_assignment_email,
)
from projects.models import Project, ProjectMember
from projects.serializers import ProjectSerializer
from tickets.models import Ticket, TicketSubscriber
from tickets.serializers import (
    TicketListSerializer,
    TicketReadSerializer,
    TicketWriteSerializer,
)


class UserTicketViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = TicketListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return (
            Ticket.objects.filter(
                Q(assignee=user)
                | Q(reporter=user)
                | Q(
                    subscribers__user=user,
                    subscribers__status=TicketSubscriber.Status.SUBSCRIBED,
                )
            )
            .distinct()
            .order_by("-created_at")
        )


class ProjectTicketViewSet(viewsets.ModelViewSet):
    lookup_url_kwarg = "ticket_id"

    def get_serializer_class(self):
        if self.action == "list":
            return TicketListSerializer
        if self.action == "retrieve":
            return TicketReadSerializer
        if self.action == "movable_projects":
            return ProjectSerializer
        return TicketWriteSerializer

    def get_queryset(self):
        return Ticket.objects.filter(
            project_id=self.kwargs.get("project_id")
        ).select_related("assignee", "reporter", "project")

    def create(self, request, *args, **kwargs):
        project_id = self.kwargs.get("project_id")
        project = get_object_or_404(Project, id=project_id)
        user = request.user

        if project.status != 1:
            raise ValidationError(
                {"project": "Cannot add tickets to an inactive project."}
            )

        is_admin = ProjectMember.objects.filter(
            project=project,
            member=user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        ).exists()

        if not is_admin:
            raise PermissionDenied(
                "You do not have permission to create tickets in this project. Admin role required."
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        response_data = {}

        try:
            with transaction.atomic():
                ticket = serializer.save(project=project, reporter=user)

                if project.jira_url and user.jira_access_token:
                    url = f"{project.jira_url.rstrip('/')}/rest/api/3/issue"
                    auth = HTTPBasicAuth(user.email, user.jira_access_token)
                    headers = {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    }

                    fields = {
                        "project": {"key": project.key},
                        "summary": ticket.title,
                        "issuetype": {"name": "Task"},
                        "description": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": ticket.description
                                            or "No description provided.",
                                        }
                                    ],
                                }
                            ],
                        },
                    }

                    if ticket.severity:
                        fields["priority"] = {"name": ticket.get_severity_display()}

                    if ticket.assignee and hasattr(ticket.assignee, "jira_account_id"):
                        fields["assignee"] = {"id": ticket.assignee.jira_account_id}

                    if ticket.deadline:
                        fields["duedate"] = ticket.deadline.strftime("%Y-%m-%d")

                    payload = {"fields": fields}

                    response = requests.post(
                        url, json=payload, headers=headers, auth=auth, timeout=10
                    )

                    try:
                        response_data = response.json()
                    except ValueError:
                        response_data = {"error": response.text}

                    if response.status_code == 201:
                        ticket.jira_id = response_data.get("key")
                        ticket.save(update_fields=["jira_id"])
                    else:
                        error_msgs = response_data.get("errorMessages", [])
                        field_errors = response_data.get("errors", {})
                        raise ValueError(
                            f"Jira rejected the ticket. Errors: {field_errors or error_msgs}"
                        )

                if ticket.assignee:
                    send_ticket_assignment_email.delay(
                        email=ticket.assignee.email,
                        ticket_id=str(ticket.id),
                        ticket_title=ticket.title,
                        project_id=str(project.id),
                        project_title=project.title,
                    )

                users_to_subscribe = {ticket.reporter}

                if ticket.assignee:
                    users_to_subscribe.add(ticket.assignee)

                subscriptions = [
                    TicketSubscriber(
                        user=user_to_sub,
                        ticket=ticket,
                        status=TicketSubscriber.Status.SUBSCRIBED,
                    )
                    for user_to_sub in users_to_subscribe
                ]
                TicketSubscriber.objects.bulk_create(subscriptions)

                if ticket.deadline:
                    now = timezone.now()
                    one_day_before = ticket.deadline - timedelta(days=1)
                    two_hours_before = ticket.deadline - timedelta(hours=2)

                    if one_day_before > now:
                        task = send_deadline_reminder.apply_async(
                            args=[ticket.id], eta=one_day_before
                        )
                        ticket.reminder_task_id = task.id
                        ticket.save(update_fields=["reminder_task_id"])

                    elif two_hours_before > now:
                        task = send_deadline_reminder.apply_async(
                            args=[ticket.id],
                            kwargs={"is_two_hour": True},
                            eta=two_hours_before,
                        )
                        ticket.reminder_task_id = task.id
                        ticket.save(update_fields=["reminder_task_id"])

                read_serializer = TicketReadSerializer(
                    ticket, context={"request": request}
                )
                return Response(read_serializer.data, status=status.HTTP_201_CREATED)

        except ValueError as e:
            return Response(
                {"error": str(e), "jira_details": response_data},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except requests.exceptions.RequestException as e:
            return Response(
                {
                    "error": "Network error while contacting Jira. Ticket creation cancelled.",
                    "details": str(e),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            return Response(
                {
                    "error": "An internal server error occurred. Ticket creation cancelled.",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["post"])
    def subscribe(self, request, project_id=None, ticket_id=None):
        ticket = self.get_object()
        user = request.user

        subscription, created = TicketSubscriber.objects.update_or_create(
            user=user,
            ticket=ticket,
            defaults={"status": TicketSubscriber.Status.SUBSCRIBED},
        )

        return Response(
            {"message": f"Successfully subscribed to {ticket.title}"},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def unsubscribe(self, request, project_id=None, ticket_id=None):
        ticket = self.get_object()
        user = request.user

        subscription, created = TicketSubscriber.objects.update_or_create(
            user=user,
            ticket=ticket,
            defaults={"status": TicketSubscriber.Status.UNSUBSCRIBED},
        )

        return Response(
            {"message": f"Successfully unsubscribed from {ticket.title}"},
            status=status.HTTP_200_OK,
        )

    def update(self, request, *args, **kwargs):
        ticket = self.get_object()
        project = ticket.project
        user = request.user
        data = request.data.copy()

        if project.status != 1:
            raise ValidationError(
                {"project": "Cannot update tickets in an inactive project."}
            )

        is_reporter = ticket.reporter == user
        is_assignee = ticket.assignee == user
        is_admin = ProjectMember.objects.filter(
            project=project,
            member=user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        ).exists()

        new_project_id = data.pop("project_id", None)

        if new_project_id and str(new_project_id) != str(project.id):
            if not is_admin:
                raise PermissionDenied("Only admins can move tickets to a new project.")

            new_project = get_object_or_404(Project, id=new_project_id, status=1)

            is_new_admin = ProjectMember.objects.filter(
                project=new_project,
                member=user,
                role=ProjectMember.Role.ADMIN,
                status=ProjectMember.Status.ACTIVE,
            ).exists()

            if not is_new_admin:
                raise PermissionDenied(
                    "Admin role required in the destination project."
                )

            new_member_ids = ProjectMember.objects.filter(
                project=new_project, status=ProjectMember.Status.ACTIVE
            ).values_list("member_id", flat=True)

            unassign = False
            if (
                ticket.assignee_id is not None
                and ticket.assignee_id not in new_member_ids
            ):
                ticket.assignee = None
                unassign = True

            try:
                with transaction.atomic():
                    ticket.project = new_project
                    update_fields = ["project"]
                    if unassign:
                        update_fields.append("assignee")

                    ticket.save(update_fields=update_fields)

                    TicketSubscriber.objects.filter(ticket=ticket).exclude(
                        user_id__in=new_member_ids
                    ).delete()

                read_serializer = TicketReadSerializer(
                    ticket, context={"request": request}
                )
                return Response(read_serializer.data, status=status.HTTP_200_OK)

            except Exception as e:
                return Response(
                    {"error": f"Move failed: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if not (is_reporter or is_assignee or is_admin):
            raise PermissionDenied("You do not have permission to edit this ticket.")

        if not is_admin and not is_reporter:
            for field in data.keys():
                if field != "status":
                    raise PermissionDenied(
                        f"Assignees can only update the status. Cannot edit '{field}'."
                    )

        new_status_val = data.get("status")
        status_changed = False
        if new_status_val is not None and int(new_status_val) != ticket.status:
            if int(new_status_val) == Ticket.Status.CLOSED and not is_reporter:
                raise PermissionDenied("Only the reporter can mark a ticket as Closed.")
            status_changed = True

        general_data = data.copy()
        general_data.pop("status", None)

        old_task_id = ticket.reminder_task_id
        jira_auth = (
            HTTPBasicAuth(user.email, user.jira_access_token)
            if user.jira_access_token
            else None
        )
        jira_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            with transaction.atomic():
                serializer = self.get_serializer(
                    ticket, data=general_data, partial=True
                )
                serializer.is_valid(raise_exception=True)
                updated_ticket = serializer.save(updated_by=user)

                if "deadline" in general_data:
                    if old_task_id:
                        current_app.control.revoke(old_task_id, terminate=True)

                    if updated_ticket.deadline:
                        now = timezone.now()
                        one_day_before = updated_ticket.deadline - timedelta(days=1)
                        two_hours_before = updated_ticket.deadline - timedelta(hours=2)

                        target_eta, is_2h = None, False
                        if one_day_before > now:
                            target_eta = one_day_before
                        elif two_hours_before > now:
                            target_eta, is_2h = two_hours_before, True

                        if target_eta:
                            task = send_deadline_reminder.apply_async(
                                args=[updated_ticket.id],
                                kwargs={"is_two_hour": is_2h},
                                eta=target_eta,
                            )
                            updated_ticket.reminder_task_id = task.id
                            updated_ticket.save(update_fields=["reminder_task_id"])

                if project.jira_url and jira_auth and updated_ticket.jira_id:
                    fields = {}
                    if "title" in data:
                        fields["summary"] = updated_ticket.title
                    if "description" in data:
                        fields["description"] = {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": updated_ticket.description
                                            or "No description.",
                                        }
                                    ],
                                }
                            ],
                        }
                    if "severity" in data:
                        fields["priority"] = {
                            "name": updated_ticket.get_severity_display()
                        }

                    if "assignee" in data:
                        if updated_ticket.assignee and hasattr(
                            updated_ticket.assignee, "jira_account_id"
                        ):
                            fields["assignee"] = {
                                "id": updated_ticket.assignee.jira_account_id
                            }
                        else:
                            fields["assignee"] = None

                    if "deadline" in data:
                        fields["duedate"] = updated_ticket.deadline.strftime("%Y-%m-%d")

                    if fields:
                        url = f"{project.jira_url.rstrip('/')}/rest/api/3/issue/{updated_ticket.jira_id}"
                        res = requests.put(
                            url,
                            json={"fields": fields},
                            auth=jira_auth,
                            headers=jira_headers,
                            timeout=10,
                        )
                        if res.status_code != 204:
                            raise ValueError(f"Jira rejected field updates: {res.text}")

        except Exception as e:
            return Response(
                {"error": f"General update failed: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if status_changed:
            try:
                with transaction.atomic():
                    ticket.prev_status = ticket.status
                    ticket.status = int(new_status_val)
                    ticket.status_updated_at = timezone.now()
                    ticket.updated_by = user
                    ticket.status_updated_by = user
                    if ticket.status == Ticket.Status.CLOSED:
                        ticket.closed_at = timezone.now()
                    ticket.save()

                    if project.jira_url and jira_auth and ticket.jira_id:
                        jira_url = project.jira_url.rstrip("/")

                        t_res = requests.get(
                            f"{jira_url}/rest/api/3/issue/{ticket.jira_id}/transitions",
                            auth=jira_auth,
                            headers=jira_headers,
                            timeout=10,
                        )
                        if t_res.status_code == 200:
                            transitions = t_res.json().get("transitions", [])

                            status_map = {
                                "open": "to do",
                                "in progress": "in progress",
                                "resolved": "in progress",
                                "closed": "done",
                            }
                            jira_target = status_map.get(
                                ticket.get_status_display().lower()
                            )

                            trans_id = next(
                                (
                                    t["id"]
                                    for t in transitions
                                    if t["to"]["name"].lower() == jira_target
                                ),
                                None,
                            )

                            if trans_id:
                                m_res = requests.post(
                                    f"{jira_url}/rest/api/3/issue/{ticket.jira_id}/transitions",
                                    json={"transition": {"id": trans_id}},
                                    auth=jira_auth,
                                    headers=jira_headers,
                                    timeout=10,
                                )
                                if m_res.status_code != 204:
                                    raise ValueError(
                                        f"Jira status update rejected: {m_res.text}"
                                    )
                            else:
                                raise ValueError(
                                    f"No valid Jira transition for status: {jira_target}"
                                )

                    notify_ticket_subscribers.delay(
                        ticket_id=str(ticket.id), new_status=ticket.get_status_display()
                    )
                    if ticket.status == Ticket.Status.RESOLVED:
                        notify_reporter_resolved.delay(
                            reporter_email=ticket.reporter.email,
                            ticket_title=ticket.title,
                            ticket_id=str(ticket.id),
                            project_id=str(project.id),
                        )

            except Exception as e:
                read_serializer = TicketReadSerializer(
                    ticket, context={"request": request}
                )
                return Response(
                    {
                        "data": read_serializer.data,
                        "error": f"Details saved, but Jira status sync failed: {str(e)}",
                    },
                    status=status.HTTP_200_OK,
                )

        read_serializer = TicketReadSerializer(ticket, context={"request": request})
        return Response(read_serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        ticket = self.get_object()
        project = ticket.project
        user = request.user

        if project.status != 1:
            raise ValidationError(
                {"project": "Cannot delete tickets in an inactive project."}
            )

        is_admin = ProjectMember.objects.filter(
            project=project,
            member=user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        ).exists()

        if not is_admin:
            raise PermissionDenied("You do not have permission to delete this ticket.")

        response_data = {}
        task_id_to_revoke = None

        try:
            with transaction.atomic():
                jira_url = project.jira_url
                jira_token = user.jira_access_token
                jira_id = ticket.jira_id
                task_id_to_revoke = ticket.reminder_task_id

                ticket.delete()

                if jira_url and jira_token and jira_id:
                    url = f"{jira_url.rstrip('/')}/rest/api/3/issue/{jira_id}"
                    auth = HTTPBasicAuth(user.email, jira_token)
                    headers = {"Accept": "application/json"}

                    response = requests.delete(url, headers=headers, auth=auth)

                    if response.status_code != 204:
                        try:
                            response_data = response.json()
                        except ValueError:
                            response_data = {"error": response.text}

                        error_msgs = response_data.get("errorMessages", [])
                        field_errors = response_data.get("errors", {})
                        error_detail = (
                            field_errors or error_msgs or response_data.get("error")
                        )
                        raise ValueError(
                            f"Jira rejected the deletion. Errors: {error_detail}"
                        )

            if task_id_to_revoke:
                current_app.control.revoke(task_id_to_revoke, terminate=True)

            return Response(status=status.HTTP_204_NO_CONTENT)

        except ValueError as e:
            return Response(
                {"error": str(e), "jira_details": response_data},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except requests.exceptions.RequestException as e:
            return Response(
                {
                    "error": "Network error while contacting Jira. Ticket deletion cancelled.",
                    "details": str(e),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            return Response(
                {
                    "error": "An internal server error occurred. Ticket deletion cancelled.",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"], url_path="movable_projects")
    def movable_projects(self, request, project_id=None, ticket_id=None):
        current_project = get_object_or_404(Project, id=project_id)

        admin_project_ids = ProjectMember.objects.filter(
            member=request.user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        ).values_list("project_id", flat=True)
        print(admin_project_ids)
        compatible_projects = Project.objects.filter(
            id__in=admin_project_ids, status=1, jira_url=current_project.jira_url
        ).exclude(id=current_project.id)

        serializer = self.get_serializer(compatible_projects, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)


def extract_text_from_adf(adf_node):
    """Recursively extract plain text from Jira's Atlassian Document Format (ADF)."""
    if not adf_node or not isinstance(adf_node, dict):
        return ""

    text = ""
    if adf_node.get("type") == "text":
        text += adf_node.get("text", "")

    for child in adf_node.get("content", []):
        text += extract_text_from_adf(child)

    if adf_node.get("type") in ["paragraph", "heading", "listItem"]:
        text += "\n"

    return text
