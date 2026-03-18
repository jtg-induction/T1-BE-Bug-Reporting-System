from datetime import timedelta

from celery import current_app
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import QueryDict
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from comments.models import Comment
from core.utils import JiraClient, JiraClientException
from projects.models import Project, ProjectMember
from projects.serializers import ProjectSerializer
from tickets.filters import TicketFilter
from tickets.models import Ticket, TicketSubscriber
from tickets.serializers import (
    TicketListSerializer,
    TicketReadSerializer,
    TicketWriteSerializer,
)
from tickets.tasks import (
    notify_new_subscriber,
    notify_reporter_resolved,
    notify_ticket_subscribers,
    send_deadline_reminder,
    send_ticket_assignment_email,
)

User = get_user_model()


class UserTicketViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    ViewSet for listing tickets associated with the authenticated user.
    """

    serializer_class = TicketListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Retrieves tickets where the user is the assignee, reporter, or an active subscriber.
        """
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

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = [
        "id",
        "title",
        "reporter__email",
        "assignee__email",
        "severity",
        "status",
        "deadline",
        "created_at",
    ]

    field_maps = {
        "list": {
            "reporter": "reporter__email",
            "assignee": "assignee__email",
        }
    }

    def _remap_params(self, query_params, mapping):
        """
        Transforms API-facing keys into internal database-facing keys.
        Handles both standard filters (field__lookup) and the 'ordering' key.
        """
        new_params = QueryDict(mutable=True)

        for key, value in query_params.items():
            if key == "ordering":
                desc = value.startswith("-")
                field = value.lstrip("-")
                mapped = mapping.get(field)
                if mapped:
                    new_params[key] = f"-{mapped}" if desc else mapped
                else:
                    new_params[key] = value
                continue

            parts = key.split("__")
            field = parts[0]
            lookup = "__".join(parts[1:]) if len(parts) > 1 else ""

            mapped = mapping.get(field)
            if mapped:
                key = f"{mapped}__{lookup}" if lookup else mapped
                new_params[key] = value
            else:
                new_params[key] = value

        return new_params

    def filter_queryset(self, queryset):
        """
        Applies remapped query parameters to the queryset.
        """
        self.filterset_class = TicketFilter
        mapping = self.field_maps.get(self.action, {})

        if not mapping and not self.request.query_params:
            return super().filter_queryset(queryset)

        transformed_data = self._remap_params(self.request.query_params, mapping)

        filterset = self.filterset_class(
            data=transformed_data,
            queryset=queryset,
            request=self.request,
        )
        if filterset.is_valid():
            queryset = filterset.qs

        original_params = self.request._request.GET
        try:
            self.request._request.GET = transformed_data
            for backend in self.filter_backends:
                if issubclass(backend, OrderingFilter):
                    queryset = backend().filter_queryset(self.request, queryset, self)
        finally:
            self.request._request.GET = original_params

        return queryset


class ProjectTicketViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing tickets within a specific project context.
    Provides CRUD operations and actions like subscribe/unsubscribe, move ticket to another project, importing ticket from Jira .
    """

    lookup_url_kwarg = "ticket_id"

    def get_serializer_class(self):
        """
        Determines the appropriate serializer based on the action being performed.
        """
        if self.action == "list":
            return TicketListSerializer
        if self.action == "retrieve":
            return TicketReadSerializer
        if self.action == "movable_projects":
            return ProjectSerializer
        return TicketWriteSerializer

    def get_queryset(self):
        """
        Retrieves all tickets associated with the given project ID.
        """
        return Ticket.objects.filter(
            project_id=self.kwargs.get("project_id")
        ).select_related("assignee", "reporter", "project")

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = [
        "id",
        "title",
        "reporter__email",
        "assignee__email",
        "severity",
        "status",
        "deadline",
        "created_at",
    ]

    field_maps = {
        "list": {
            "reporter": "reporter__email",
            "assignee": "assignee__email",
        }
    }

    def _remap_params(self, query_params, mapping):
        """
        Transforms API-facing keys into internal database-facing keys.
        Handles both standard filters (field__lookup) and the 'ordering' key.
        """
        new_params = QueryDict(mutable=True)

        for key, value in query_params.items():
            if key == "ordering":
                desc = value.startswith("-")
                field = value.lstrip("-")
                mapped = mapping.get(field)
                if mapped:
                    new_params[key] = f"-{mapped}" if desc else mapped
                else:
                    new_params[key] = value
                continue

            parts = key.split("__")
            field = parts[0]
            lookup = "__".join(parts[1:]) if len(parts) > 1 else ""

            mapped = mapping.get(field)
            if mapped:
                key = f"{mapped}__{lookup}" if lookup else mapped
                new_params[key] = value
            else:
                new_params[key] = value

        return new_params

    def filter_queryset(self, queryset):
        """
        Applies remapped query parameters to the queryset.
        """
        self.filterset_class = TicketFilter
        mapping = self.field_maps.get(self.action, {})

        if not mapping and not self.request.query_params:
            return super().filter_queryset(queryset)

        transformed_data = self._remap_params(self.request.query_params, mapping)

        filterset = self.filterset_class(
            data=transformed_data,
            queryset=queryset,
            request=self.request,
        )
        if filterset.is_valid():
            queryset = filterset.qs

        original_params = self.request._request.GET
        try:
            self.request._request.GET = transformed_data
            for backend in self.filter_backends:
                if issubclass(backend, OrderingFilter):
                    queryset = backend().filter_queryset(self.request, queryset, self)
        finally:
            self.request._request.GET = original_params

        return queryset

    def create(self, request, *args, **kwargs):
        """
        Creates a new ticket within a project and syncs it to Jira.
        Sets up initial subscriptions and schedules deadline reminders.
        """
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

        try:
            with transaction.atomic():
                ticket = serializer.save(project=project, reporter=user)

                if project.jira_url and user.jira_access_token:
                    jira_client = JiraClient(
                        project.jira_url, user.email, user.jira_access_token
                    )

                    assignee_id = (
                        ticket.assignee.jiraID
                        if ticket.assignee and hasattr(ticket.assignee, "jiraID")
                        else None
                    )
                    deadline_str = (
                        ticket.deadline.strftime("%Y-%m-%d")
                        if ticket.deadline
                        else None
                    )
                    severity_str = (
                        ticket.get_severity_display() if ticket.severity else None
                    )

                    jira_response = jira_client.create_ticket(
                        project_key=project.key,
                        title=ticket.title,
                        description=ticket.description,
                        severity=severity_str,
                        assignee_id=assignee_id,
                        deadline=deadline_str,
                    )

                    ticket.jira_key = jira_response.get("key")
                    ticket.save(update_fields=["jira_key"])

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

        except JiraClientException as e:
            return Response(
                {"error": str(e), "jira_details": e.response_data},
                status=e.status_code
                if e.status_code
                else status.HTTP_503_SERVICE_UNAVAILABLE,
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
        """
        Subscribes the authenticated user to the ticket and notifies other subscribers.
        """
        ticket = self.get_object()
        user = request.user

        subscription, created = TicketSubscriber.objects.update_or_create(
            user=user,
            ticket=ticket,
            defaults={"status": TicketSubscriber.Status.SUBSCRIBED},
        )

        subscriber_name = user.email
        notify_new_subscriber.delay(
            ticket_id=str(ticket.id),
            new_subscriber_email=user.email,
            new_subscriber_name=subscriber_name,
        )

        return Response(
            {"message": f"Successfully subscribed to {ticket.title}"},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def unsubscribe(self, request, project_id=None, ticket_id=None):
        """
        Unsubscribes the authenticated user from the ticket.
        """
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
        """
        Updates an existing ticket. Includes handling for moving tickets between projects,
        syncing updates with Jira, and re-evaluating deadline reminders.
        """
        ticket = self.get_object()
        project = ticket.project
        user = request.user
        data = request.data.copy()

        if "deadline" in data and data["deadline"] == "":
            data["deadline"] = None

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

                notify_ticket_subscribers.delay(
                    ticket_id=str(ticket.id),
                    changes=[
                        {
                            "field": "Project",
                            "old": project.title,
                            "new": new_project.title,
                        }
                    ],
                )

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

        def get_safe_str(val, is_long=False):
            if not val:
                return "None"
            s = str(val)
            return s[:97] + "..." if is_long and len(s) > 100 else s

        original_state = {
            "Title": ticket.title,
            "Description": get_safe_str(ticket.description, True),
            "Severity": ticket.get_severity_display() if ticket.severity else "None",
            "Deadline": ticket.deadline.strftime("%Y-%m-%d")
            if ticket.deadline
            else "None",
            "Assignee": ticket.assignee.email if ticket.assignee else "Unassigned",
            "Status": ticket.get_status_display(),
        }

        changes = []

        try:
            with transaction.atomic():
                serializer = self.get_serializer(
                    ticket, data=general_data, partial=True
                )
                serializer.is_valid(raise_exception=True)
                updated_ticket = serializer.save(updated_by=user)

                updated_state = {
                    "Title": updated_ticket.title,
                    "Description": get_safe_str(updated_ticket.description, True),
                    "Severity": updated_ticket.get_severity_display()
                    if updated_ticket.severity
                    else "None",
                    "Deadline": updated_ticket.deadline.strftime("%Y-%m-%d")
                    if updated_ticket.deadline
                    else "None",
                    "Assignee": updated_ticket.assignee.email
                    if updated_ticket.assignee
                    else "Unassigned",
                }

                for field in [
                    "Title",
                    "Description",
                    "Severity",
                    "Deadline",
                    "Assignee",
                ]:
                    if original_state[field] != updated_state[field]:
                        changes.append(
                            {
                                "field": field,
                                "old": original_state[field],
                                "new": updated_state[field],
                            }
                        )

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

                if (
                    project.jira_url
                    and user.jira_access_token
                    and updated_ticket.jira_key
                ):
                    jira_client = JiraClient(
                        project.jira_url, user.email, user.jira_access_token
                    )

                    update_kwargs = {}
                    if "title" in data:
                        update_kwargs["title"] = updated_ticket.title
                    if "description" in data:
                        update_kwargs["description"] = updated_ticket.description
                    if "severity" in data:
                        update_kwargs["severity"] = (
                            updated_ticket.get_severity_display()
                        )

                    if "assignee" in data:
                        if updated_ticket.assignee and hasattr(
                            updated_ticket.assignee, "jiraID"
                        ):
                            update_kwargs["assignee_id"] = (
                                updated_ticket.assignee.jiraID
                            )
                        else:
                            update_kwargs["clear_assignee"] = True

                    if "deadline" in data:
                        if updated_ticket.deadline:
                            update_kwargs["deadline"] = (
                                updated_ticket.deadline.strftime("%Y-%m-%d")
                            )
                        else:
                            update_kwargs["clear_deadline"] = True

                    if update_kwargs:
                        jira_client.update_ticket(
                            updated_ticket.jira_key, **update_kwargs
                        )

        except JiraClientException as e:
            return Response(
                {
                    "error": f"General update failed via Jira: {str(e)}",
                    "jira_details": e.response_data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
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

                    new_status_display = dict(Ticket.Status.choices).get(
                        ticket.status, "Unknown"
                    )
                    changes.append(
                        {
                            "field": "Status",
                            "old": original_state["Status"],
                            "new": new_status_display,
                        }
                    )

                    skip_jira_transition = (
                        ticket.prev_status == Ticket.Status.IN_PROGRESS
                        and ticket.status == Ticket.Status.RESOLVED
                    ) or (
                        ticket.prev_status == Ticket.Status.RESOLVED
                        and ticket.status == Ticket.Status.IN_PROGRESS
                    )

                    if not skip_jira_transition:
                        jira_client = JiraClient(
                            project.jira_url, user.email, user.jira_access_token
                        )
                        jira_client.transition_ticket(
                            ticket.jira_key, ticket.get_status_display()
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

                changes = [c for c in changes if c["field"] != "Status"]
                if changes:
                    notify_ticket_subscribers.delay(
                        ticket_id=str(ticket.id), changes=changes
                    )

                return Response(
                    {
                        "data": read_serializer.data,
                        "message": f"Details saved, but Jira status sync failed: {str(e)}",
                    },
                    status=status.HTTP_200_OK,
                )

        if changes:
            notify_ticket_subscribers.delay(ticket_id=str(ticket.id), changes=changes)

        read_serializer = TicketReadSerializer(ticket, context={"request": request})
        return Response(read_serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        """
        Deletes a ticket locally and removes the linked issue from Jira.
        Revokes any pending deadline reminder tasks.
        """
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

        task_id_to_revoke = None

        try:
            with transaction.atomic():
                jira_url = project.jira_url
                jira_token = user.jira_access_token
                jira_key = ticket.jira_key
                task_id_to_revoke = ticket.reminder_task_id

                ticket.delete()

                if jira_url and jira_token and jira_key:
                    jira_client = JiraClient(jira_url, user.email, jira_token)
                    jira_client.delete_ticket(jira_key)

            if task_id_to_revoke:
                current_app.control.revoke(task_id_to_revoke, terminate=True)

            return Response(status=status.HTTP_204_NO_CONTENT)

        except JiraClientException as e:
            return Response(
                {"error": str(e), "jira_details": e.response_data},
                status=e.status_code if e.status_code else status.HTTP_400_BAD_REQUEST,
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
        """
        Returns a list of active projects sharing the same Jira instance
        where the user has an Admin role, allowing for ticket transfers.
        """
        current_project = get_object_or_404(Project, id=project_id)

        admin_project_ids = ProjectMember.objects.filter(
            member=request.user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        ).values_list("project_id", flat=True)
        compatible_projects = Project.objects.filter(
            id__in=admin_project_ids, status=1, jira_url=current_project.jira_url
        ).exclude(id=current_project.id)

        serializer = self.get_serializer(compatible_projects, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="jira-import-list")
    def jira_import_list(self, request, project_id=None):
        """
        Fetches tickets from Jira for the current project, with an optional custom JQL filter
        sent in the request body.

        Expected payload: {"jql": 'status="In Progress"'} (optional)
        """
        project = get_object_or_404(Project, id=project_id)
        user = request.user
        jql = request.data.get("jql", None)

        if project.status != 1:
            raise ValidationError(
                {"project": "Cannot import tickets from an inactive project."}
            )

        is_member = ProjectMember.objects.filter(
            project=project, member=user, status=ProjectMember.Status.ACTIVE
        ).exists()

        if not is_member:
            raise PermissionDenied(
                "You do not have permission to view tickets for this project."
            )

        try:
            jira_client = JiraClient(
                project.jira_url, user.email, user.jira_access_token
            )

            response_data = jira_client.get_project_issues(
                project.key, additional_jql=jql
            )
            jira_issues = response_data.get("issues", [])

        except Exception as e:
            return Response(
                {"error": "Failed to fetch tickets from Jira.", "details": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_jira_keys = set(
            Ticket.objects.filter(project=project)
            .exclude(jira_key__isnull=True)
            .exclude(jira_key="")
            .values_list("jira_key", flat=True)
        )

        local_user_account_ids = set(
            User.objects.exclude(jiraID__isnull=True)
            .exclude(jiraID="")
            .values_list("jiraID", flat=True)
        )

        importable_tickets = []

        for issue in jira_issues:
            jira_key = issue.get("key")
            jira_id = issue.get("id")
            fields = issue.get("fields", {})

            if jira_key in existing_jira_keys:
                continue

            reporter_account_id = fields.get("reporter", {}).get("accountId")

            if (
                not reporter_account_id
                or reporter_account_id not in local_user_account_ids
            ):
                continue

            raw_description = fields.get("description")
            text_description = (
                JiraClient.extract_text_from_adf(raw_description)
                if raw_description
                else ""
            )
            importable_tickets.append(
                {
                    "jira_id": jira_id,
                    "jira_key": jira_key,
                    "title": fields.get("summary", ""),
                    "description": text_description,
                }
            )

        return Response(importable_tickets, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="import-ticket")
    def import_ticket(self, request, project_id=None):
        """
        Imports a specific ticket from Jira into the local database,
        including its full comment history.
        Expects a payload like {"jira_key": "EX4-11"}.
        """
        project = get_object_or_404(Project, id=project_id)
        user = request.user
        jira_identifier = request.data.get("jira_key")

        if not jira_identifier:
            return Response(
                {"error": "The 'jira_key' field is required in the payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if project.status != 1:
            raise ValidationError(
                {"project": "Cannot import tickets into an inactive project."}
            )

        is_admin = ProjectMember.objects.filter(
            project=project,
            member=user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        ).exists()

        if not is_admin:
            raise PermissionDenied(
                "You do not have permission to import tickets. Admin role required."
            )

        if Ticket.objects.filter(project=project, jira_key=jira_identifier).exists():
            return Response(
                {"error": "This ticket has already been imported."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            jira_client = JiraClient(
                project.jira_url, user.email, user.jira_access_token
            )
            jira_issue = jira_client.get_ticket(jira_identifier)
        except JiraClientException as e:
            return Response(
                {
                    "error": f"Failed to fetch ticket from Jira: {str(e)}",
                    "details": e.response_data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        fields = jira_issue.get("fields", {})
        actual_jira_key = jira_issue.get("key")

        if Ticket.objects.filter(project=project, jira_key=actual_jira_key).exists():
            return Response(
                {"error": "This ticket has already been imported."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reporter_account_id = fields.get("reporter", {}).get("accountId")
        if not reporter_account_id:
            return Response(
                {"error": "Jira ticket has no reporter."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reporter_user = User.objects.filter(jiraID=reporter_account_id).first()
        if not reporter_user:
            return Response(
                {"error": "The Jira reporter is not registered in our system."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assignee_dict = fields.get("assignee")
        assignee_user = None
        if assignee_dict:
            assignee_account_id = assignee_dict.get("accountId")
            assignee_user = User.objects.filter(jiraID=assignee_account_id).first()

        title = fields.get("summary", "Imported Ticket")
        raw_description = fields.get("description")
        description = (
            JiraClient.adf_to_markdown(raw_description)
            if raw_description
            else "No description provided."
        )

        priority_name = fields.get("priority", {}).get("name", "").lower()
        severity_map = {
            "highest": Ticket.Severity.HIGHEST,
            "high": Ticket.Severity.HIGH,
            "medium": Ticket.Severity.MID,
            "low": Ticket.Severity.LOW,
            "lowest": Ticket.Severity.LOWEST,
        }
        severity = severity_map.get(priority_name, Ticket.Severity.LOW)

        status_category = (
            fields.get("status", {}).get("statusCategory", {}).get("key", "")
        )
        status_map = {
            "new": Ticket.Status.OPEN,
            "indeterminate": Ticket.Status.IN_PROGRESS,
            "done": Ticket.Status.CLOSED,
        }

        ticket_status = status_map.get(status_category, Ticket.Status.OPEN)

        deadline_str = fields.get("duedate")
        deadline = None
        if deadline_str:
            from datetime import datetime

            from django.utils.dateparse import parse_date

            parsed_date = parse_date(deadline_str)
            if parsed_date:
                deadline = timezone.make_aware(
                    datetime.combine(parsed_date, datetime.min.time())
                )

        try:
            with transaction.atomic():
                ticket = Ticket.objects.create(
                    title=title,
                    description=description,
                    project=project,
                    reporter=reporter_user,
                    assignee=assignee_user,
                    status=ticket_status,
                    severity=severity,
                    deadline=deadline,
                    jira_key=actual_jira_key,
                )

                users_to_subscribe = {ticket.reporter}
                if ticket.assignee:
                    users_to_subscribe.add(ticket.assignee)

                subscriptions = [
                    TicketSubscriber(
                        user=u,
                        ticket=ticket,
                        status=TicketSubscriber.Status.SUBSCRIBED,
                    )
                    for u in users_to_subscribe
                ]
                TicketSubscriber.objects.bulk_create(subscriptions)

                jira_comments_data = fields.get("comment", {}).get("comments", [])
                comments_to_create = []

                if jira_comments_data:
                    first_comment = jira_comments_data[0]

                    c_jira_id = first_comment.get("id")
                    c_author_dict = first_comment.get("author", {})
                    c_author_account_id = c_author_dict.get("accountId")
                    c_author_display_name = c_author_dict.get(
                        "displayName", "Unknown Jira User"
                    )

                    c_author_user = None
                    if c_author_account_id:
                        c_author_user = User.objects.filter(
                            jiraID=c_author_account_id
                        ).first()

                    c_body_raw = first_comment.get("body")
                    c_body_md = (
                        JiraClient.adf_to_markdown(c_body_raw) if c_body_raw else ""
                    )

                    comments_to_create.append(
                        Comment(
                            ticket=ticket,
                            description=c_body_md,
                            author=c_author_user,
                            author_name=c_author_display_name,
                            jira_id=c_jira_id,
                        )
                    )

                if comments_to_create:
                    Comment.objects.bulk_create(comments_to_create)

            read_serializer = TicketReadSerializer(ticket, context={"request": request})
            return Response(read_serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {"error": "Failed to save the imported ticket.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
