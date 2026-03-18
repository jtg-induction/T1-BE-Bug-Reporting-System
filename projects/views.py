import logging

from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.http import QueryDict
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ParseError, PermissionDenied
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.tasks import send_invitation_email
from core.utils import JiraClient, JiraClientException
from projects.filters import ProjectFilter, ProjectMemberFilter
from projects.models import Project, ProjectMember
from projects.serializers import ProjectMemberSerializer, ProjectSerializer
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
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = [
        "key",
        "title",
        "project_members__role",
        "member__first_name",
        "member__last_name",
        "member__email",
        "member__designation",
        "role",
    ]

    field_maps = {
        "list": {
            "key": "key",
            "title": "title",
            "project_role": "project_members__role",
        },
        "get_all_members": {
            "first_name": "member__first_name",
            "last_name": "member__last_name",
            "email": "member__email",
            "designation": "member__designation",
            "role": "role",
        },
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
                new_key = f"{mapped}__{lookup}" if lookup else mapped
                new_params[new_key] = value
            else:
                new_params[key] = value

        return new_params

    def filter_queryset(self, queryset):
        if self.action == "get_all_members":
            self.filterset_class = ProjectMemberFilter
        else:
            self.filterset_class = ProjectFilter

        mapping = self.field_maps.get(self.action, {})
        transformed_data = self._remap_params(
            self.request.query_params, mapping
        )

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
                    queryset = backend().filter_queryset(
                        self.request, queryset, self
                    )
        finally:
            self.request._request.GET = original_params

        return queryset

    def get_serializer_class(self):
        if self.action == "get_all_members":
            return ProjectMemberSerializer
        elif self.action == "get_available_members":
            return UserSerializer
        return ProjectSerializer

    def get_queryset(self):
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
        status = self.request.GET.get("status", None)
        if self.action == "retrieve":
            return projects.filter(archive_filter | active_filter)
        elif self.action == "list" and status == "archived":
            return projects.filter(archive_filter)
        return projects.filter(active_filter)

    def create(self, request, *args, **kwargs):
        """
        Handles the creation of a new project and syncs it with Jira.

        Uses a database transaction to safely create the local project,
        assign the creator as an Admin member, create the project in Jira via the API,
        and update the local record with the resulting Jira project ID.
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

        instance = self.get_object()
        is_admin = ProjectMember.objects.filter(
            project=instance,
            member=request.user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        ).exists()
        if not is_admin:
            raise PermissionDenied(
                "You must be an active Admin of this project to update its details."
            )

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
                    projectId=instance.jira_project_id,
                )

                response_serializer = ProjectSerializer(
                    instance, context={"request": request}
                )
                return Response(
                    response_serializer.data,
                    status=status.HTTP_201_CREATED,
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

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="invite")
    def invite_member(self, request, pk=None):
        inviter = request.user
        invited = User.objects.filter(id=request.data["user_id"]).first()
        role = request.data["role"]
        project = Project.objects.filter(id=pk).first()

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
        user = request.user
        project = Project.objects.filter(id=pk).first()

        if not project:
            raise NotFound("Project does not exist")

        pm_instance = ProjectMember.objects.filter(
            member=user, project=project
        ).first()

        if pm_instance:
            if pm_instance.status == ProjectMember.Status.ACTIVE:
                raise ParseError("You are already in this project")

            elif pm_instance.status == ProjectMember.Status.INVITED:
                pm_instance.status = ProjectMember.Status.ACTIVE
                pm_instance.save()
                return Response(
                    {"detail": "Added to project successfully"},
                    status=status.HTTP_200_OK,
                )

            else:
                raise ParseError("You are not invited to this project")
        else:
            raise ParseError("You are not invited to this project")

    @action(detail=True, methods=["post"], url_path="reject")
    def reject_invite(self, request, pk=None):
        user = request.user
        project = Project.objects.filter(id=pk).first()

        if not project:
            raise NotFound("Project does not exist")

        pm_instance = ProjectMember.objects.filter(
            member=user, project=project
        ).first()

        if pm_instance:
            if pm_instance.status == ProjectMember.Status.ACTIVE:
                raise ParseError("You are already in this project")

            elif pm_instance.status == ProjectMember.Status.INVITED:
                pm_instance.status = ProjectMember.Status.REJECTED
                pm_instance.save()
                return Response(
                    {"detail": "Rejected project invite successfully"},
                    status=status.HTTP_200_OK,
                )

            else:
                raise ParseError("You are not invited to this project")
        else:
            raise ParseError("You are not invited to this project")

    @action(detail=True, methods=["post"], url_path="revoke")
    def revoke_member(self, request, pk=None):
        admin = request.user
        member = request.data["user_id"]
        project = Project.objects.filter(id=pk).first()

        if not project:
            raise NotFound("Project does not exist")

        if not member:
            raise NotFound("User does not exist")

        is_admin = ProjectMember.objects.filter(
            project__id=pk, member=admin, role=ProjectMember.Role.ADMIN
        ).exists()

        is_member_admin = ProjectMember.objects.filter(
            project__id=pk, member__id=member, role=ProjectMember.Role.ADMIN
        )

        if admin == member:
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
            if is_member_admin:
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
        admin = request.user
        member = User.objects.filter(id=request.data["user_id"]).first()
        role = request.data["role"]
        project = Project.objects.filter(id=pk).first()

        if not project:
            raise NotFound("Project does not exist")

        if not member:
            raise NotFound("User does not exist")

        pm_admin = ProjectMember.objects.filter(
            member=admin, project=project
        ).first()
        pm_member = ProjectMember.objects.filter(
            member=member, project=project
        ).first()

        if role == 2:
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
                return PermissionDenied(
                    "You are not the owner of this project"
                )

        pm_admin = ProjectMember.objects.filter(
            member=admin, project=project
        ).first()
        pm_member = ProjectMember.objects.filter(
            member=member, project=project
        ).first()

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
        user = request.user
        project_id = pk

        if not ProjectMember.objects.filter(
            project__id=project_id, member=user, role=ProjectMember.Role.ADMIN
        ).exists():
            raise PermissionDenied("You are not an admin of this project")

        if not Project.objects.filter(id=pk).exists():
            raise NotFound("Project does not exist")

        members = User.objects.exclude(
            user_projects__project=project_id,
            user_projects__status=ProjectMember.Status.ACTIVE,
        )

        serializer = self.get_serializer(
            members, many=True, context={"user": user}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive_project(self, request, pk=None):
        user = request.user
        project_id = pk
        project = Project.objects.filter(id=project_id).first()

        if not project:
            raise NotFound("Project does not exist")

        if project.status == Project.Status.ARCHIVED:
            raise ParseError("Project already archived")

        if not ProjectMember.objects.filter(
            project__id=project_id, member=user, role=ProjectMember.Role.ADMIN
        ).exists():
            raise PermissionDenied("You are not an admin of this project")

        access_token = user.jira_access_token
        raw_url = project.jira_url

        try:
            jira_client = JiraClient(raw_url, request.user.email, access_token)
        except ValueError as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            with transaction.atomic():
                project.status = Project.Status.ARCHIVED
                project.archived_at = timezone.now()
                project.save()

                jira_client.archive_project(project.jira_project_id)

                return Response(
                    {"detail": "Project Archived"},
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
            logger.exception("Unexpected error during project creation")
            return Response(
                {"error": "A database error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["post"], url_path="unarchive")
    def unarchive_project(self, request, pk=None):
        user = request.user
        project_id = pk
        project = Project.objects.filter(id=project_id).first()

        if not project:
            raise NotFound("Project does not exist")

        if project.status == Project.Status.ACTIVE:
            raise ParseError("Project already active")

        if not ProjectMember.objects.filter(
            project__id=project_id, member=user, role=ProjectMember.Role.ADMIN
        ).exists():
            raise PermissionDenied("You are not an admin of this project")

        access_token = user.jira_access_token
        raw_url = project.jira_url

        try:
            jira_client = JiraClient(raw_url, request.user.email, access_token)
        except ValueError as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            with transaction.atomic():
                project.status = Project.Status.ACTIVE
                project.archived_at = None
                project.save()

                jira_client.unarchive_project(project.jira_project_id)

                return Response(
                    {"detail": "Project Unarchived"},
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
            logger.exception("Unexpected error during project creation")
            return Response(
                {"error": "A database error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
