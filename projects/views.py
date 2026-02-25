import requests
from rest_framework import viewsets, mixins, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from requests.auth import HTTPBasicAuth

from .models import Project, ProjectMember
from .serializers import ProjectSerializer


class ProjectViewSet(mixins.CreateModelMixin,
                     mixins.ListModelMixin,
                     mixins.RetrieveModelMixin,
                     mixins.UpdateModelMixin,
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
        archived_qs = Project.objects.filter(status=Project.Status.ARCHIVED)
        serializer = self.get_serializer(archived_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        key = serializer.validated_data.get('key')
        title = serializer.validated_data.get('title')
        access_token = request.user.jira_access_token
        raw_url = serializer.validated_data.get('jira_url')

        if not raw_url.startswith('http'):
            base_url = f"https://{raw_url}"
        else:
            base_url = raw_url
        base_url = base_url.rstrip('/')

        jira_api_endpoint = f"{base_url}/rest/api/3/project"

        jira_payload = {
            "key": key,
            "name": title,
            "projectTypeKey": "software",
            "leadAccountId": request.user.jiraID
        }

        auth = HTTPBasicAuth(request.user.email, access_token)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(jira_api_endpoint, json=jira_payload, headers=headers, auth=auth)
            response_data = response.json()

            if response.status_code == 201:
                project = serializer.save(
                    jira_project_id=response_data.get("id"),
                    jira_url=base_url
                )
                ProjectMember.objects.create(
                    project=project,
                    member=request.user,
                    inviter=request.user,
                    role=ProjectMember.Role.ADMIN,
                    status=ProjectMember.Status.ACTIVE
                )

                return Response(serializer.data, status=status.HTTP_201_CREATED)
            else:
                return Response(
                    {"error": "Failed to create project in Jira.", "jira_details": response_data},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except requests.exceptions.RequestException as e:
            return Response(
                {"error": "Network error while contacting Jira.", "details": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

    def update(self, request, *args, **kwargs):

        instance = self.get_object()
        is_admin = ProjectMember.objects.filter(
            project=instance,
            member=request.user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE
        ).exists()
        if not is_admin:
            raise PermissionDenied("You must be an active Admin of this project to update its details.")

        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
