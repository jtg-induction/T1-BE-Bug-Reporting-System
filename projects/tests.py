import pytest
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase
from requests.exceptions import RequestException
from projects.models import Project, ProjectMember

User = get_user_model()


@pytest.mark.django_db
class ProjectViewSetTestCase(APITestCase):
    login = reverse("core:login")
    list_url = reverse("project-list")
    archived_url = reverse("project-archived-projects")

    def setUp(self):
        self.user = User.objects.create_user(
            first_name="test",
            last_name="user",
            email="test@testuser.com",
            password="tester",
            designation="M",
            jiraID="abcd",
            jira_access_token="test_access_token"
        )
        self.user2 = User.objects.create_user(
            first_name="test2",
            last_name="user2",
            email="test2@testuser.com",
            password="tester2",
            designation="M",
            jiraID="abcde",
            jira_access_token="test_access_token2"
        )

        response = self.client.post(self.login, {"email": "test@testuser.com", "password": "tester"})
        self.access = response.data.get("access", "")
        if not self.access and "refresh" in response.cookies:
            self.refresh = response.cookies["refresh"]
            self.client.cookies["refresh"] = self.refresh

        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + self.access)

        self.active_project = Project.objects.create(
            title="Active Project",
            description="Active description",
            status=Project.Status.ACTIVE,
            owner=self.user,
            key="ACT",
            jira_url="https://test.atlassian.net",
            jira_project_id="10000"
        )
        ProjectMember.objects.create(
            project=self.active_project,
            member=self.user,
            inviter=self.user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE
        )

        self.archived_project = Project.objects.create(
            title="Archived Project",
            description="Archived description",
            status=Project.Status.ARCHIVED,
            owner=self.user,
            key="ARC",
            jira_url="https://test.atlassian.net",
            jira_project_id="10001"
        )
        ProjectMember.objects.create(
            project=self.archived_project,
            member=self.user,
            inviter=self.user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE
        )

        self.detail_url = reverse("project-detail", kwargs={"pk": self.active_project.pk})

    def test_access_with_invalid_token(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer a-fake-access-token')
        response = self.client.get(self.list_url)
        self.assertEqual(401, response.status_code)

    def test_list_active_projects(self):
        response = self.client.get(self.list_url)
        self.assertEqual(200, response.status_code)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], str(self.active_project.id))

    def test_list_archived_projects(self):
        response = self.client.get(self.archived_url)
        self.assertEqual(200, response.status_code)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], str(self.archived_project.id))

    def test_retrieve_active_project(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(200, response.status_code)
        self.assertEqual(response.data["id"], str(self.active_project.id))
        self.assertEqual(response.data["title"], self.active_project.title)

    def test_create_project_missing_fields(self):
        data = {
            "title": "New Project"
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(400, response.status_code)

    @patch('requests.post')
    def test_create_project_success(self, mock_post):
        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {"id": "10002"}

        data = {
            "title": "New Project",
            "description": "New project description",
            "key": "NEW",
            "jira_url": "https://new.atlassian.net"
        }

        response = self.client.post(self.list_url, data)
        self.assertEqual(201, response.status_code)
        self.assertEqual(response.data["jira_project_id"], "10002")
        self.assertEqual(response.data["title"], "New Project")
        
        project_exists = Project.objects.filter(key="NEW").exists()
        self.assertTrue(project_exists)
        
        member_exists = ProjectMember.objects.filter(
            project__key="NEW",
            member=self.user,
            role=ProjectMember.Role.ADMIN
        ).exists()
        self.assertTrue(member_exists)

    @patch('requests.post')
    def test_create_project_jira_rejection(self, mock_post):
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {"errorMessages": ["Project key already exists"]}

        data = {
            "title": "Failed Project",
            "description": "Will fail",
            "key": "FAIL",
            "jira_url": "https://fail.atlassian.net"
        }

        response = self.client.post(self.list_url, data)
        self.assertEqual(400, response.status_code)
        
        project_exists = Project.objects.filter(key="FAIL").exists()
        self.assertFalse(project_exists)

    @patch('requests.post')
    def test_create_project_network_error(self, mock_post):
        mock_post.side_effect = RequestException("Connection timeout")

        data = {
            "title": "Timeout Project",
            "description": "Will timeout",
            "key": "TIME",
            "jira_url": "https://time.atlassian.net"
        }

        response = self.client.post(self.list_url, data)
        self.assertEqual(503, response.status_code)
        
        project_exists = Project.objects.filter(key="TIME").exists()
        self.assertFalse(project_exists)

    def test_list_projects_different_user(self):
        response = self.client.post(self.login, {"email": "test2@testuser.com", "password": "tester2"})
        access = response.data.get("access", "")
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + access)

        response = self.client.get(self.list_url)
        self.assertEqual(200, response.status_code)
        self.assertEqual(len(response.data), 0)