from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from requests.exceptions import RequestException
from rest_framework.test import APITestCase

from projects.models import Project, ProjectMember

User = get_user_model()


@pytest.mark.django_db
class ProjectViewSetTestCase(APITestCase):
    """
    Test suite for project management API endpoints.
    Verifies project retrieval, creation, and Jira API integration.
    """

    def setUp(self):
        """
        Initializes test users, projects, and configures the test client with JWT credentials.
        """
        self.login = reverse("core:login")
        self.list_url = reverse("project-list")
        self.archived_url = reverse("project-archived-projects")
        self.user = User.objects.create_user(
            first_name="test",
            last_name="user",
            email="test@testuser.com",
            password="tester",
            designation="M",
            jiraID="abcd",
            jira_access_token="test_access_token",
        )
        self.user2 = User.objects.create_user(
            first_name="test2",
            last_name="user2",
            email="test2@testuser.com",
            password="tester2",
            designation="M",
            jiraID="abcde",
            jira_access_token="test_access_token2",
        )

        response = self.client.post(self.login, {"email": "test@testuser.com", "password": "tester"})

        if isinstance(response.data, dict):
            self.access = response.data.get("access") or response.data.get("data", {}).get("access", "")
        else:
            self.access = ""

        if not self.access and "refresh" in response.cookies:
            self.refresh = response.cookies["refresh"]
            self.client.cookies["refresh"] = self.refresh

        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.access)

        self.active_project = Project.objects.create(
            title="Active Project",
            description="Active description",
            status=Project.Status.ACTIVE,
            owner=self.user,
            key="ACT",
            jira_url="https://test.atlassian.net",
            jira_project_id="10000",
        )
        ProjectMember.objects.create(
            project=self.active_project,
            member=self.user,
            inviter=self.user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        )

        self.archived_project = Project.objects.create(
            title="Archived Project",
            description="Archived description",
            status=Project.Status.ARCHIVED,
            owner=self.user,
            key="ARC",
            jira_url="https://test.atlassian.net",
            jira_project_id="10001",
        )
        ProjectMember.objects.create(
            project=self.archived_project,
            member=self.user,
            inviter=self.user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        )

        self.detail_url = reverse("project-detail", kwargs={"pk": self.active_project.pk})

    def _get_actual_data(self, response):
        """
        Helper method to safely extract data whether it's wrapped in a dict or returned as a raw list.
        """
        if isinstance(response.data, dict):
            return response.data.get("data", response.data)
        return response.data

    def test_access_with_invalid_token(self):
        """
        Verifies that unauthenticated requests to the project list are rejected.
        """
        self.client.credentials(HTTP_AUTHORIZATION="Bearer a-fake-access-token")
        response = self.client.get(self.list_url)
        self.assertEqual(401, response.status_code)

    def test_list_active_projects(self):
        """
        Ensures a user can retrieve a list of their active projects.
        """
        response = self.client.get(self.list_url)
        self.assertEqual(200, response.status_code)

        actual_data = self._get_actual_data(response)

        self.assertEqual(len(actual_data), 1)
        self.assertEqual(actual_data[0]["id"], str(self.active_project.id))

    def test_list_archived_projects(self):
        """
        Ensures a user can retrieve a list of their archived projects.
        """
        response = self.client.get(self.archived_url)
        self.assertEqual(200, response.status_code)

        actual_data = self._get_actual_data(response)

        self.assertEqual(len(actual_data), 1)
        self.assertEqual(actual_data[0]["id"], str(self.archived_project.id))

    def test_retrieve_active_project(self):
        """
        Verifies that a user can fetch details of a specific active project.
        """
        response = self.client.get(self.detail_url)
        self.assertEqual(200, response.status_code)

        actual_data = self._get_actual_data(response)

        self.assertEqual(actual_data["id"], str(self.active_project.id))
        self.assertEqual(actual_data["title"], self.active_project.title)

    def test_create_project_missing_fields(self):
        """
        Confirms that project creation fails if required fields are missing.
        """
        data = {"title": "New Project"}
        response = self.client.post(self.list_url, data)
        self.assertEqual(400, response.status_code)

    @patch("core.utils.requests.request")
    def test_create_project_success(self, mock_post):
        """
        Mocks a successful Jira API response and verifies the local project and member are created.
        """
        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {"id": "10002"}

        data = {
            "title": "New Project",
            "description": "New project description",
            "key": "NEW",
            "jira_url": "https://new.atlassian.net",
        }

        response = self.client.post(self.list_url, data)
        self.assertEqual(201, response.status_code)

        actual_data = self._get_actual_data(response)

        self.assertEqual(actual_data["jira_project_id"], "10002")
        self.assertEqual(actual_data["title"], "New Project")

        project_exists = Project.objects.filter(key="NEW").exists()
        self.assertTrue(project_exists)

        member_exists = ProjectMember.objects.filter(
            project__key="NEW", member=self.user, role=ProjectMember.Role.ADMIN
        ).exists()
        self.assertTrue(member_exists)

    @patch("core.utils.requests.request")
    def test_create_project_jira_rejection(self, mock_post):
        """
        Verifies that if Jira rejects the project creation, the local project is not saved.
        """
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {"errorMessages": ["Project key already exists"]}

        data = {
            "title": "Failed Project",
            "description": "Will fail",
            "key": "FAIL",
            "jira_url": "https://fail.atlassian.net",
        }

        response = self.client.post(self.list_url, data)
        self.assertEqual(400, response.status_code)

        project_exists = Project.objects.filter(key="FAIL").exists()
        self.assertFalse(project_exists)

    @patch("core.utils.requests.request")
    def test_create_project_network_error(self, mock_post):
        """
        Ensures a 503 is returned and no local project is saved if the network connection to Jira fails.
        """
        mock_post.side_effect = RequestException("Connection timeout")

        data = {
            "title": "Timeout Project",
            "description": "Will timeout",
            "key": "TIME",
            "jira_url": "https://time.atlassian.net",
        }

        response = self.client.post(self.list_url, data)
        self.assertEqual(503, response.status_code)

        project_exists = Project.objects.filter(key="TIME").exists()
        self.assertFalse(project_exists)

    def test_list_projects_different_user(self):
        """
        Verifies that a user can only see projects they are actively a member of.
        """
        response = self.client.post(self.login, {"email": "test2@testuser.com", "password": "tester2"})

        if isinstance(response.data, dict):
            access = response.data.get("access") or response.data.get("data", {}).get("access", "")
        else:
            access = ""

        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + access)

        response = self.client.get(self.list_url)
        self.assertEqual(200, response.status_code)

        actual_data = self._get_actual_data(response)

        self.assertEqual(len(actual_data), 0)
