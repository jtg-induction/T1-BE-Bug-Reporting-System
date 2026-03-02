import logging

import requests
from django.contrib.auth import get_user_model
from django.db import transaction
from requests.auth import HTTPBasicAuth
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ParseError, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.tasks import send_invitation_email
from core.utils import JiraClient, JiraClientException
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

    def get_serializer_class(self):
        if self.action == "get_all_members":
            return ProjectMemberSerializer
        elif self.action == "get_available_members":
            return UserSerializer
        return ProjectSerializer

    def get_queryset(self):
        """
        Returns a queryset of active projects where the currently authenticated user
        is an active member.
        """
        return Project.objects.filter(
            status=Project.Status.ACTIVE,
            project_members__member=self.request.user,
            project_members__status=ProjectMember.Status.ACTIVE,
        )

    @action(detail=False, methods=["get"], url_path="archived")
    def archived_projects(self, request):
        """
        Custom endpoint to retrieve a list of archived projects
        where the current user is an active member.
        """
        archived_qs = Project.objects.filter(
            status=Project.Status.ARCHIVED,
            project_members__member=request.user,
            project_members__status=ProjectMember.Status.ACTIVE,
        )
        serializer = self.get_serializer(archived_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

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
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

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
                {"error": str(e), "jira_details": e.response_data}, status=status_code
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

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        key = instance.key
        title = serializer.validated_data.get("title")
        description = serializer.validated_data.get("description")
        access_token = request.user.jira_access_token
        raw_url = instance.jira_url

        if not raw_url.startswith("http"):
            base_url = f"https://{raw_url}"
        else:
            base_url = raw_url
        base_url = base_url.rstrip("/")

        jira_api_endpoint = f"{base_url}/rest/api/3/project/{instance.jira_project_id}"

        jira_payload = {
            "key": key,
            "name": title,
            "description": description,
            "projectTypeKey": "software",
            "leadAccountId": request.user.jiraID,
        }

        auth = HTTPBasicAuth(request.user.email, access_token)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}

        try:
            with transaction.atomic():
                super().update(request, *args, **kwargs)

                response = requests.put(
                    jira_api_endpoint, json=jira_payload, headers=headers, auth=auth
                )
                response_data = response.json()

                if response.status_code == 200:
                    response_serializer = ProjectSerializer(
                        instance, context={"request": request}
                    )
                    return Response(
                        response_serializer.data, status=status.HTTP_201_CREATED
                    )

                else:
                    error_msg = response_data.get(
                        "errorMessages", ["Unknown Jira Error"]
                    )[0]
                    raise ValueError(f"Jira rejected the project: {error_msg}")

        except ValueError as e:
            return Response(
                {"error": str(e), "jira_details": response_data},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except requests.exceptions.RequestException as e:
            return Response(
                {
                    "error": "Network error while contacting Jira. Project creation cancelled.",
                    "details": str(e),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
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

        if not inviter:
            raise NotFound("User does not exist")

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
            {"detail": "User invited to project"}, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"], url_path="accept")
    def accept_invite(self, request, pk=None):
        user = request.user
        project = Project.objects.filter(id=pk).first()

        if not project:
            raise NotFound("Project does not exist")

        pm_instance = ProjectMember.objects.filter(member=user, project=project).first()

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

        pm_instance = ProjectMember.objects.filter(member=user, project=project).first()

        if pm_instance:
            if pm_instance.status == ProjectMember.Status.ACTIVE:
                raise ParseError("You are already in this project")

            elif pm_instance.status == ProjectMember.Status.INVITED:
                pm_instance.status = ProjectMember.Status.REJECTED
                pm_instance.save()
                return Response(
                    {"detail": "Added to project successfully"},
                    status=status.HTTP_200_OK,
                )

            else:
                raise ParseError("You are not invited to this project")
        else:
            raise ParseError("You are not invited to this project")

    @action(detail=True, methods=["post"], url_path="revoke")
    def revoke_member(self, request, pk=None):
        admin = request.user
        member = User.objects.filter(id=request.data["user_id"]).first()
        project = Project.objects.filter(id=pk).first()

        if not project:
            raise NotFound("Project does not exist")

        if not member:
            raise NotFound("User does not exist")

        is_admin = ProjectMember.objects.filter(project__id=pk, member=admin).first()

        if is_admin:
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
                        {"detail": "User removed from project"},
                        status=status.HTTP_200_OK,
                    )

                else:
                    raise NotFound("User not in the Project")

        else:
            if member == admin:
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

            raise PermissionDenied("Only admins can remove members from a project")

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

        pm_admin = ProjectMember.objects.filter(member=admin, project=project).first()
        pm_member = ProjectMember.objects.filter(member=member, project=project).first()

        if role == 2:
            if project.owner == admin:
                if pm_member.role != ProjectMember.Role.ADMIN:
                    pm_member.role = ProjectMember.Role.ADMIN
                    pm_member.save()

                project.owner = member
                project.save()
                return Response(
                    {"detail": "Owner of project changed"}, status=status.HTTP_200_OK
                )
            else:
                return PermissionDenied("You are not the owner of this project")

        pm_admin = ProjectMember.objects.filter(member=admin, project=project).first()
        pm_member = ProjectMember.objects.filter(member=member, project=project).first()

        if pm_admin.role == ProjectMember.Role.ADMIN:
            if pm_member.role == ProjectMember.Role.ADMIN and project.owner != admin:
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

        serializer = self.get_serializer(members, many=True, context={"user": user})
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

        serializer = self.get_serializer(members, many=True, context={"user": user})
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

        if not raw_url.startswith("http"):
            base_url = f"https://{raw_url}"
        else:
            base_url = raw_url
        base_url = base_url.rstrip("/")

        jira_api_endpoint = (
            f"{base_url}/rest/api/3/project/{project.jira_project_id}/archive"
        )

        auth = HTTPBasicAuth(request.user.email, access_token)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}

        try:
            with transaction.atomic():
                project.status = Project.Status.ARCHIVED
                project.save()

                response = requests.post(jira_api_endpoint, headers=headers, auth=auth)

                if response.status_code == 204:
                    return Response(
                        {"detail": "Project archived"}, status=status.HTTP_200_OK
                    )

                else:
                    response_data = response.json()
                    error_msg = response_data.get(
                        "errorMessages", ["Unknown Jira Error"]
                    )[0]
                    raise ValueError(f"Jira rejected the project: {error_msg}")

        except ValueError as e:
            return Response(
                {"error": str(e), "jira_details": response_data},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except requests.exceptions.RequestException as e:
            return Response(
                {
                    "error": "Network error while contacting Jira. Project creation cancelled.",
                    "details": str(e),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
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

        if not raw_url.startswith("http"):
            base_url = f"https://{raw_url}"
        else:
            base_url = raw_url
        base_url = base_url.rstrip("/")

        jira_api_endpoint = (
            f"{base_url}/rest/api/3/project/{project.jira_project_id}/restore"
        )

        auth = HTTPBasicAuth(request.user.email, access_token)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}

        try:
            with transaction.atomic():
                project.status = Project.Status.ACTIVE
                project.save()

                response = requests.post(jira_api_endpoint, headers=headers, auth=auth)

                if response.status_code == 200:
                    return Response(
                        {"detail": "Project unarchived"}, status=status.HTTP_200_OK
                    )

                else:
                    response_data = response.json()
                    error_msg = response_data.get(
                        "errorMessages", ["Unknown Jira Error"]
                    )[0]
                    raise ValueError(f"Jira rejected the project: {error_msg}")

        except ValueError as e:
            return Response(
                {"error": str(e), "jira_details": response_data},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except requests.exceptions.RequestException as e:
            return Response(
                {
                    "error": "Network error while contacting Jira. Project creation cancelled.",
                    "details": str(e),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            return Response(
                {"error": "A database error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
