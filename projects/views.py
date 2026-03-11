from django.db import transaction
from rest_framework import viewsets, mixins, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from projects.models import Project, ProjectMember
from projects.serializers import ProjectSerializer
from core.utils import JiraClient, JiraClientException 

class ProjectViewSet(mixins.CreateModelMixin,
                     mixins.ListModelMixin,
                     mixins.RetrieveModelMixin,
                     viewsets.GenericViewSet):

    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Project.objects.filter(
            status=Project.Status.ACTIVE,
            project_members__member=self.request.user,
            project_members__status=ProjectMember.Status.ACTIVE
        ).distinct()

    @action(detail=False, methods=['get'], url_path='archived')
    def archived_projects(self, request):
        archived_qs = Project.objects.filter(
            status=Project.Status.ARCHIVED, 
            project_members__member=request.user,
            project_members__status=ProjectMember.Status.ACTIVE
        ).distinct()
        serializer = self.get_serializer(archived_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        key = serializer.validated_data.get('key')
        title = serializer.validated_data.get('title')
        description = serializer.validated_data.get('description')
        raw_url = serializer.validated_data.get('jira_url')
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
                    jira_project_id="" 
                )
                
                ProjectMember.objects.create(
                    project=project,
                    member=request.user,
                    inviter=request.user,
                    role=ProjectMember.Role.ADMIN,
                    status=ProjectMember.Status.ACTIVE
                )

                jira_response = jira_client.create_project(
                    key=key,
                    name=title,
                    description=description,
                    lead_account_id=request.user.jiraID
                )

                project.jira_project_id = jira_response.get("id")
                project.save(update_fields=['jira_project_id'])
                
                response_serializer = ProjectSerializer(project, context={'request': request})
                return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        except JiraClientException as e:
            status_code = status.HTTP_400_BAD_REQUEST if e.status_code else status.HTTP_503_SERVICE_UNAVAILABLE
            return Response(
                {"error": str(e), "jira_details": e.response_data},
                status=status_code
            )
        except Exception as e:
            return Response(
                {"error": "A database error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
