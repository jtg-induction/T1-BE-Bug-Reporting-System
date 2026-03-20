import logging
import re
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.db.models import Count, F, Q
from django.db.models.functions import TruncDay
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ParseError, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.tasks import send_invitation_email
from core.utils import JiraClient, JiraClientException
from projects.filters import ProjectFilter, ProjectMemberFilter
from projects.models import Project, ProjectMember
from projects.permissions import IsAdmin
from projects.serializers import ProjectMemberSerializer, ProjectSerializer
from tickets.models import Ticket
from users.serializers import UserSerializer

logger = logging.getLogger(__name__)
User = get_user_model()


class ProjectViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for managing projects.

    Provides endpoints to list, retrieve, and create projects,
    with custom logic for integrating with Jira during project creation.
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]

    def filter_queryset(self, queryset):
        """
        Selects and applies the appropriate filter class based on the current action.
        """
        if self.action == "get_all_members":
            self.filterset_class = ProjectMemberFilter
        else:
            self.filterset_class = ProjectFilter

        fs = self.filterset_class(
            data=self.request.query_params,
            queryset=queryset,
            request=self.request,
        )

        if fs.is_valid():
            return fs.qs

        return queryset

    def get_serializer_class(self):
        """
        Returns the serializer class based on the requested action.
        """
        if self.action == "get_all_members":
            return ProjectMemberSerializer
        elif self.action == "get_available_members":
            return UserSerializer
        return ProjectSerializer

    def get_queryset(self):
        """
        Retrieves projects where the user is an active member.
        Supports filtering by 'archived' status via query parameters.
        """
        archive_filter = models.Q(
            status=Project.Status.ARCHIVED,
            project_members__role=ProjectMember.Role.ADMIN,
            project_members__member=self.request.user,
            project_members__status=ProjectMember.Status.ACTIVE,
        )
        active_filter = models.Q(
            status=Project.Status.ACTIVE,
            project_members__member=self.request.user,
            project_members__status=ProjectMember.Status.ACTIVE,
        )
        projects = Project.objects.distinct()
        project_status = self.request.GET.get("status", None)
        if self.action == "retrieve":
            return projects.filter(archive_filter | active_filter)
        elif self.action == "list" and project_status == "archived":
            return projects.filter(archive_filter)
        return projects.filter(active_filter)

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        """
        if self.action in [
            "partial_update",
            "update",
            "invite_member",
            "get_available_members",
            "archive_project",
            "unarchive_project",
        ]:
            return [IsAdmin()]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        """
        Creates a local project and syncs it with Jira.

        Uses an atomic transaction to create the Project and ProjectMember records,
        calls the Jira API to create the remote project, and stores the Jira ID locally.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        key = serializer.validated_data.get("key")
        title = serializer.validated_data.get("title")
        description = serializer.validated_data.get("description")
        raw_url = serializer.validated_data.get("jira_url")
        access_token = request.user.jira_access_token

        try:
            jira_client = JiraClient(raw_url, request.user.email, access_token)
        except ValueError as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                project = serializer.save(
                    jira_url=jira_client.base_url,
                    owner=request.user,
                    jira_project_id="",
                )

                ProjectMember.objects.create(
                    project=project,
                    member=request.user,
                    inviter=request.user,
                    role=ProjectMember.Role.ADMIN,
                    status=ProjectMember.Status.ACTIVE,
                )

                jira_response = jira_client.create_project(
                    key=key,
                    name=title,
                    description=description,
                    lead_account_id=request.user.jiraID,
                )

                project.jira_project_id = jira_response.get("id")
                project.save(update_fields=["jira_project_id"])

                response_serializer = ProjectSerializer(
                    project, context={"request": request}
                )
                return Response(
                    response_serializer.data, status=status.HTTP_201_CREATED
                )

        except JiraClientException as e:
            status_code = (
                status.HTTP_400_BAD_REQUEST
                if e.status_code
                else status.HTTP_503_SERVICE_UNAVAILABLE
            )
            return Response(
                {"error": str(e), "jira_details": e.response_data},
                status=status_code,
            )

        except Exception as e:
            logger.exception("Unexpected error during project creation")
            return Response(
                {"error": "A database error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def update(self, request, *args, **kwargs):
        """
        Updates project details locally and syncs changes to Jira.
        """
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        key = instance.key
        title = serializer.validated_data.get("title")
        description = serializer.validated_data.get("description")
        access_token = request.user.jira_access_token
        raw_url = instance.jira_url

        try:
            jira_client = JiraClient(raw_url, request.user.email, access_token)
        except ValueError as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                super().update(request, *args, **kwargs)

                jira_client.update_project(
                    key=key,
                    name=title,
                    description=description,
                    lead_account_id=request.user.jiraID,
                    project_id=instance.jira_project_id,
                )

                response_serializer = ProjectSerializer(
                    instance, context={"request": request}
                )
                return Response(
                    response_serializer.data,
                    status=status.HTTP_200_OK,
                )

        except JiraClientException as e:
            status_code = (
                status.HTTP_400_BAD_REQUEST
                if e.status_code
                else status.HTTP_503_SERVICE_UNAVAILABLE
            )
            return Response(
                {"error": str(e), "jira_details": e.response_data},
                status=status_code,
            )

        except Exception as e:
            logger.exception("Unexpected error during project updation")
            return Response(
                {"error": "A database error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def perform_update(self, serializer):
        """
        Function for adding the updating user to the instance during save.
        """
        serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="invite")
    def invite_member(self, request, pk=None):
        """
        Invites a user to the project. Creates a ProjectMember record with
        an 'INVITED' status and triggers an invitation email asynchronously.
        """
        inviter = request.user
        invited = User.objects.filter(id=request.data["user_id"]).first()
        role = request.data["role"]
        project = self.get_object()

        if not project:
            raise NotFound("Project does not exist")

        if not invited:
            raise NotFound("Invited User does not exist")

        pm_instance = ProjectMember.objects.filter(
            member=invited, project=project
        ).first()

        if pm_instance:
            if pm_instance.status == ProjectMember.Status.ACTIVE:
                raise ParseError("User already in this project")

            pm_instance.status = ProjectMember.Status.INVITED
            pm_instance.role = ProjectMember.Role(role)
            pm_instance.inviter = inviter
            pm_instance.save()

        else:
            ProjectMember.objects.create(
                member=invited,
                inviter=inviter,
                project=project,
                role=ProjectMember.Role(role),
            )

        send_invitation_email.delay(pk, project.title, invited.email)
        return Response(
            {"detail": "User invited to project"},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="accept")
    def accept_invite(self, request, pk=None):
        """
        Accepts a pending project invitation for the current user.
        """
        return self._handle_invitation_response(
            project_id=pk,
            new_status=ProjectMember.Status.ACTIVE,
            success_msg="Added to project successfully",
        )

    @action(detail=True, methods=["post"], url_path="reject")
    def reject_invite(self, request, pk=None):
        """
        Rejects a pending project invitation for the current user.
        """
        return self._handle_invitation_response(
            project_id=pk,
            new_status=ProjectMember.Status.REJECTED,
            success_msg="Rejected project invite successfully",
        )

    def _handle_invitation_response(self, project_id, new_status, success_msg):
        """
        Internal helper to change ProjectMember status for invitation responses.
        """
        user = self.request.user

        if not Project.objects.filter(id=project_id).exists():
            raise NotFound("Project does not exist")

        pm_instance = ProjectMember.objects.filter(
            member=user, project_id=project_id
        ).first()

        if not pm_instance:
            raise ParseError("You are not invited to this project")

        if pm_instance.status == ProjectMember.Status.ACTIVE:
            raise ParseError(
                "You are already an active member of this project"
            )

        if pm_instance.status != ProjectMember.Status.INVITED:
            raise ParseError(
                "There is no pending invitation for you to respond to"
            )

        pm_instance.status = new_status
        pm_instance.save(update_fields=["status"])

        return Response({"detail": success_msg}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="revoke")
    def revoke_member(self, request, pk=None):
        """
        Removes a user from a project or allows a user to leave.
        Admins can remove members; only the Owner can remove other Admins.
        """
        admin = request.user
        member = request.data["user_id"] if request.data else None
        project = self.get_object()

        if not project:
            raise NotFound("Project does not exist")

        if not member:
            raise ParseError("User not provided")

        is_admin = ProjectMember.objects.filter(
            project__id=pk, member=admin, role=ProjectMember.Role.ADMIN
        ).exists()

        admin_member = ProjectMember.objects.filter(
            project__id=pk, member__id=member, role=ProjectMember.Role.ADMIN
        )

        if str(admin.id) == member:
            if project.owner == member:
                raise PermissionDenied(
                    "Owner has to make someone else the owner before leaving the project"
                )
            else:
                pm_instance = ProjectMember.objects.filter(
                    project__id=pk, member=member
                ).first()

                if pm_instance:
                    pm_instance.status = ProjectMember.Status.REVOKED
                    pm_instance.save()

                    return Response(
                        {"detail": "You are removed from project"},
                        status=status.HTTP_200_OK,
                    )

        if is_admin:
            if admin_member.exists():
                if project.owner == admin:
                    pm_instance = ProjectMember.objects.filter(
                        project__id=pk, member=member
                    ).first()

                    if pm_instance:
                        pm_instance.status = ProjectMember.Status.REVOKED
                        pm_instance.save()

                        return Response(
                            {"detail": "You are removed from project"},
                            status=status.HTTP_200_OK,
                        )
                else:
                    raise PermissionDenied(
                        "Admins can be removed by owner only"
                    )
            else:
                pm_instance = ProjectMember.objects.filter(
                    project__id=pk, member=member
                ).first()

                if pm_instance:
                    pm_instance.status = ProjectMember.Status.REVOKED
                    pm_instance.save()

                    return Response(
                        {"detail": "User removed from project"},
                        status=status.HTTP_200_OK,
                    )
        else:
            raise NotFound("Only Admins can remove from the Project")

    @action(detail=True, methods=["post"], url_path="role")
    def change_role(self, request, pk=None):
        """
        Changes the role of a project member.
        Only Admins can promote someone to Admin
        Owner can transfer ownership to anyone
        """
        admin = request.user
        member = (
            User.objects.filter(id=request.data["user_id"]).first()
            if request.data
            else None
        )
        role = request.data["role"] if request.data else None
        project = self.get_object()

        if not project:
            raise NotFound("Project does not exist")

        if not member:
            raise NotFound("User does not exist or not provided")

        if not role:
            raise ParseError("Provide a Role for this user")

        pm_admin = ProjectMember.objects.filter(
            member=admin, project=project
        ).first()
        pm_member = ProjectMember.objects.filter(
            member=member, project=project
        ).first()

        if role == ProjectMember.Role.ADMIN.value:
            if project.owner == admin:
                if pm_member.role != ProjectMember.Role.ADMIN:
                    pm_member.role = ProjectMember.Role.ADMIN
                    pm_member.save()

                project.owner = member
                project.save()
                return Response(
                    {"detail": "Owner of project changed"},
                    status=status.HTTP_200_OK,
                )
            else:
                raise PermissionDenied("You are not the owner of this project")

        if pm_admin.role == ProjectMember.Role.ADMIN:
            if (
                pm_member.role == ProjectMember.Role.ADMIN
                and project.owner != admin
            ):
                raise ParseError("Can't change role of another admin")

            else:
                pm_member.role = ProjectMember.Role(role)
                pm_member.save(update_fields=["role"])
                return Response(
                    {"detail": "User role changed"}, status=status.HTTP_200_OK
                )

        else:
            raise PermissionDenied("Only admins can change role")

    @action(detail=True, methods=["get"], url_path="members")
    def get_all_members(self, request, pk=None):
        """
        Returns a paginated list of all active members in a specific project.
        """
        user = request.user
        project_id = pk

        if not Project.objects.filter(id=pk).exists():
            raise NotFound("Project does not exist")

        if not ProjectMember.objects.filter(
            project__id=project_id, member=user
        ).exists():
            raise NotFound("User not in this project")

        members = ProjectMember.objects.filter(
            project__id=project_id, status=ProjectMember.Status.ACTIVE
        ).select_related("member")

        if not members:
            raise NotFound("Project does not exist")

        members = self.filter_queryset(members)
        page = self.paginate_queryset(members)
        if page is not None:
            serializer = self.get_serializer(
                page, many=True, context={"user": user}
            )
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(
            members, many=True, context={"user": user}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="available_members")
    def get_available_members(self, request, pk=None):
        """
        Lists all users in the system who are NOT currently active members of the project.
        """
        user = request.user
        project = self.get_object()

        if not Project.objects.filter(id=pk).exists():
            raise NotFound("Project does not exist")

        members = User.objects.exclude(
            user_projects__project=project,
            user_projects__status=ProjectMember.Status.ACTIVE,
        )

        serializer = self.get_serializer(
            members, many=True, context={"user": user}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive_project(self, request, pk=None):
        """
        Sets the project status to 'ARCHIVED' and syncs the status to Jira.
        """
        user = request.user
        project = Project.objects.get(id=pk)
        new_status = Project.Status.ARCHIVED
        error_msg = "Project Archiving Failed"
        return self._toggle_project_status(
            user=user,
            project=project,
            new_status=new_status,
            error_msg=error_msg,
        )

    @action(detail=True, methods=["post"], url_path="unarchive")
    def unarchive_project(self, request, pk=None):
        """
        Sets the project status back to 'ACTIVE' and syncs the status to Jira.
        """
        user = request.user
        project = Project.objects.get(id=pk)
        new_status = Project.Status.ACTIVE
        error_msg = "Project Unarchiving Failed"
        return self._toggle_project_status(
            user=user,
            project=project,
            new_status=new_status,
            error_msg=error_msg,
        )

    def _toggle_project_status(self, user, project, new_status, error_msg):
        """
        Internal logic for changing project status and updating Jira state.
        """
        is_archiving = new_status == Project.Status.ARCHIVED

        if not project:
            raise NotFound("Project does not exist")

        if project.status == new_status:
            if not is_archiving:
                raise ParseError("Project already active")
            raise ParseError("Project already archived")

        access_token = user.jira_access_token
        raw_url = project.jira_url

        try:
            jira_client = JiraClient(raw_url, user.email, access_token)
        except ValueError as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            with transaction.atomic():
                project.status = new_status
                project.archived_at = None
                project.save()

                if is_archiving:
                    jira_client.archive_project(project.jira_project_id)

                    return Response(
                        {"detail": "Project Archived Successfully"},
                        status=status.HTTP_200_OK,
                    )
                else:
                    jira_client.unarchive_project(project.jira_project_id)

                    return Response(
                        {"detail": "Project Unarchived Successfully"},
                        status=status.HTTP_200_OK,
                    )

        except JiraClientException as e:
            status_code = (
                status.HTTP_400_BAD_REQUEST
                if e.status_code
                else status.HTTP_503_SERVICE_UNAVAILABLE
            )
            return Response(
                {"error": str(e), "jira_details": e.response_data},
                status=status_code,
            )

        except Exception as e:
            logger.exception(error_msg)
            return Response(
                {"error": "A database error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"], url_path="summary")
    def project_summary(self, request, pk=None):
        if not ProjectMember.objects.filter(
            project__id=pk, member=request.user
        ).exists():
            raise PermissionDenied("You are not a member of this Project")

        query = request.query_params
        now = timezone.now()
        filter_date_format = "%Y-%m-%d"

        base_qs = Ticket.objects.filter(project__id=pk)

        user_ids_raw = query.get("user-ids", "")
        uuid_pattern = (
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        )
        user_ids = re.findall(uuid_pattern, user_ids_raw.lower())
        if user_ids:
            base_qs = base_qs.filter(assignee__id__in=user_ids)

        start_date = query.get("start-date")
        end_date = query.get("end-date")
        section = query.get("section")

        if not start_date and not end_date:
            start_dt = (now - timedelta(days=now.weekday())).date()
            end_dt = now.date()
        else:
            start_dt = (
                datetime.strptime(start_date, filter_date_format).date()
                if start_date
                else None
            )
            end_dt = (
                datetime.strptime(end_date, filter_date_format).date()
                if end_date
                else None
            )

        data = {}

        if not section or section == "deadline":
            deadline_qs = base_qs.filter(deadline__isnull=False)
            if start_dt:
                deadline_qs = deadline_qs.filter(deadline__date__gte=start_dt)
            if end_dt:
                deadline_qs = deadline_qs.filter(deadline__date__lte=end_dt)

            data["deadline_chart"] = (
                deadline_qs.annotate(day=TruncDay("deadline"))
                .values("day")
                .annotate(
                    missed=Count(
                        "id",
                        filter=Q(closed_at__date__gt=F("deadline__date"))
                        | Q(closed_at__isnull=True, deadline__lt=now),
                    ),
                    completed_on_time=Count(
                        "id", filter=Q(closed_at__date=F("deadline__date"))
                    ),
                    completed_before_time=Count(
                        "id", filter=Q(closed_at__date__lt=F("deadline__date"))
                    ),
                )
                .order_by("day")
            )

        if not section or section in ["status", "priority"]:
            created_qs = base_qs
            if start_dt:
                created_qs = created_qs.filter(created_at__date__gte=start_dt)
            if end_dt:
                created_qs = created_qs.filter(created_at__date__lte=end_dt)

            if not section:
                timeline = now - timedelta(
                    seconds=locals().get("history_time", 86400)
                )
                data["ticket_summary"] = created_qs.aggregate(
                    completed=Count("id", filter=Q(status=4)),
                    missed_deadline=Count(
                        "id", filter=Q(deadline__lt=now) & ~Q(status=4)
                    ),
                    total=Count("id"),
                    near_deadline=Count(
                        "id",
                        filter=Q(deadline__gte=now, deadline__lte=timeline),
                    ),
                )

            if not section or section == "status":
                data["ticket_status"] = created_qs.aggregate(
                    open=Count("id", filter=Q(status=1)),
                    in_progress=Count("id", filter=Q(status=2)),
                    resolved=Count("id", filter=Q(status=3)),
                    closed=Count("id", filter=Q(status=4)),
                )

            if not section or section == "priority":
                data["ticket_severity"] = created_qs.aggregate(
                    lowest=Count("id", filter=Q(severity=1)),
                    low=Count("id", filter=Q(severity=2)),
                    medium=Count("id", filter=Q(severity=3)),
                    high=Count("id", filter=Q(severity=4)),
                    highest=Count("id", filter=Q(severity=5)),
                )

        return Response(data)
