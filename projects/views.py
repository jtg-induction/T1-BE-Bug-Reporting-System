import logging

from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.utils import JiraClient, JiraClientException
from projects.models import Project, ProjectMember
from projects.serializers import ProjectSerializer

logger = logging.getLogger(__name__)


class ProjectViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for managing projects.
    Provides endpoints to list, retrieve, and create projects,
    with custom logic for integrating with Jira during project creation.
    """

    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]

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
