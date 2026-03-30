from unittest.mock import patch

import pytest
from ddf import G
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
        self.active_url = f"{self.list_url}?status=2"
        self.archived_url = f"{self.list_url}?status=1"

        self.user = G(User)
        self.user.set_password("tester")
        self.user.save()

        self.user2 = G(User)
        self.user2.set_password("tester2")
        self.user2.save()

        response = self.client.post(
            self.login, {"email": self.user.email, "password": "tester"}
        )

        if isinstance(response.data, dict):
            self.access = response.data.get("access") or response.data.get(
                "data", {}
            ).get("access", "")
        else:
            self.access = ""

        if not self.access and "refresh" in response.cookies:
            self.refresh = response.cookies["refresh"]
            self.client.cookies["refresh"] = self.refresh

        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.access)

        self.active_project = G(
            Project,
            title="Active Project",
            description="Active description",
            status=Project.Status.ACTIVE,
            owner=self.user,
            key="ACT",
            jira_url="https://test.atlassian.net",
            jira_project_id="10000",
        )
        G(
            ProjectMember,
            project=self.active_project,
            member=self.user,
            inviter=self.user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        )

        self.archived_project = G(
            Project,
            title="Archived Project",
            description="Archived description",
            status=Project.Status.ARCHIVED,
            owner=self.user,
            key="ARC",
            jira_url="https://test.atlassian.net",
            jira_project_id="10001",
        )
        G(
            ProjectMember,
            project=self.archived_project,
            member=self.user,
            inviter=self.user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        )

        self.detail_url = reverse(
            "project-detail", kwargs={"pk": self.active_project.pk}
        )

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
        response = self.client.get(self.active_url)
        self.assertEqual(200, response.status_code)

        actual_data = self._get_actual_data(response).get("results")
        self.assertEqual(len(actual_data), 1)
        self.assertEqual(actual_data[0]["id"], str(self.active_project.id))

    def test_list_archived_projects(self):
        """
        Ensures a user can retrieve a list of their archived projects.
        """
        response = self.client.get(self.archived_url)
        self.assertEqual(200, response.status_code)

        actual_data = self._get_actual_data(response).get("results")

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

    @patch("core.utils.requests.Session.request")
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

    @patch("core.utils.requests.Session.request")
    def test_create_project_jira_rejection(self, mock_post):
        """
        Verifies that if Jira rejects the project creation, the local project is not saved.
        """
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {
            "errorMessages": ["Project key already exists"]
        }

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

    @patch("core.utils.requests.Session.request")
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
        response = self.client.post(
            self.login, {"email": self.user2.email, "password": "tester2"}
        )

        if isinstance(response.data, dict):
            access = response.data.get("access") or response.data.get("data", {}).get(
                "access", ""
            )
        else:
            access = ""

        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + access)

        response = self.client.get(self.list_url)
        self.assertEqual(200, response.status_code)

        actual_data = self._get_actual_data(response).get("results")

        self.assertEqual(len(actual_data), 0)

    @patch("requests.Session.request")
    def test_update_project_success(self, mock_put):
        """Verifies that an admin can successfully update project details locally and in Jira."""
        mock_put.return_value.status_code = 200
        mock_put.return_value.json.return_value = {}

        url = reverse("project-detail", args=[self.active_project.id])

        response = self.client.patch(
            url, {"title": "Updated Title", "description": "Updated Desc"}
        )

        self.assertEqual(response.status_code, 200)
        self.active_project.refresh_from_db()
        self.assertEqual(self.active_project.title, "Updated Title")

    def test_update_project_not_admin(self):
        """Ensures that non-admin members are forbidden from updating project details."""
        G(
            ProjectMember,
            project=self.active_project,
            member=self.user2,
            inviter=self.user,
            role=ProjectMember.Role.DEV,
            status=ProjectMember.Status.ACTIVE,
        )
        self.client.force_authenticate(self.user2)
        url = reverse("project-detail", args=[self.active_project.id])
        response = self.client.put(url, {"title": "Hack"})

        self.assertEqual(response.status_code, 403)

    @patch("requests.Session.request")
    def test_update_project_jira_error(self, mock_put):
        """Validates that Jira API validation errors are correctly bubbled up as 400 Bad Request."""
        mock_put.return_value.status_code = 400
        mock_put.return_value.json.return_value = {"errorMessages": ["Some Jira error"]}

        url = reverse("project-detail", args=[self.active_project.id])
        response = self.client.patch(url, {"title": "Fail"})

        self.assertEqual(response.status_code, 400)

    @patch("requests.Session.request")
    def test_update_project_network_error(self, mock_put):
        """Confirms that network timeouts during Jira updates result in a 503 Service Unavailable response."""
        mock_put.side_effect = RequestException("timeout")

        url = reverse("project-detail", args=[self.active_project.id])
        response = self.client.patch(url, {"title": "Fail"})

        self.assertEqual(response.status_code, 503)

    @patch("requests.Session.request")
    def test_archive_project_success(self, mock_post):
        """Verifies successful project archiving in both the local database and Jira."""
        mock_post.return_value.status_code = 204

        url = reverse("project-archive-project", args=[self.active_project.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.active_project.refresh_from_db()
        self.assertEqual(self.active_project.status, Project.Status.ARCHIVED)

    def test_archive_already_archived(self):
        """Ensures that attempting to archive an already archived project returns a 400 error."""
        url = reverse("project-archive-project", args=[self.archived_project.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 400)

    def test_archive_not_admin(self):
        """Ensures that users without admin privileges cannot archive projects."""
        self.client.force_authenticate(self.user2)

        url = reverse("project-archive-project", args=[self.active_project.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 403)

    @patch("requests.Session.request")
    def test_unarchive_project_success(self, mock_post):
        """Verifies successful restoration of an archived project locally and in Jira."""
        mock_post.return_value.status_code = 200

        url = reverse("project-unarchive-project", args=[self.archived_project.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.archived_project.refresh_from_db()
        self.assertEqual(self.archived_project.status, Project.Status.ACTIVE)

    def test_get_all_members_success(self):
        """Confirms that an authorized user can retrieve the full list of project members."""
        url = reverse("project-get-all-members", args=[self.active_project.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(response.data) >= 1)

    def test_get_members_not_in_project(self):
        """Ensures users cannot view membership lists for projects they belong to."""
        self.client.force_authenticate(self.user2)

        url = reverse("project-get-all-members", args=[self.active_project.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_get_available_members_success(self):
        """Verifies that admins can retrieve a list of users available to be invited to the project."""
        url = reverse("project-get-available-members", args=[self.active_project.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

    def test_get_available_members_not_admin(self):
        """Ensures only admins can access the list of potential project invitees."""
        self.client.force_authenticate(self.user2)

        url = reverse("project-get-available-members", args=[self.active_project.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)

    def test_invite_member_success(self):
        """Validates that an admin can successfully invite a new user to a project."""
        url = reverse("project-invite-member", args=[self.active_project.id])

        response = self.client.post(
            url, {"user_id": self.user2.id, "role": ProjectMember.Role.DEV}
        )

        self.assertEqual(response.status_code, 201)

        exists = ProjectMember.objects.filter(
            project=self.active_project, member=self.user2
        ).exists()

        self.assertTrue(exists)

    def test_accept_invite_success(self):
        """Confirms that a user can successfully accept a pending project invitation."""
        G(
            ProjectMember,
            project=self.active_project,
            member=self.user2,
            inviter=self.user,
            role=ProjectMember.Role.DEV,
            status=ProjectMember.Status.INVITED,
        )

        self.client.force_authenticate(self.user2)

        url = reverse("project-accept-invite", args=[self.active_project.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)

        pm = ProjectMember.objects.get(project=self.active_project, member=self.user2)

        self.assertEqual(pm.status, ProjectMember.Status.ACTIVE)

    def test_reject_invite_success(self):
        """Confirms that a user can successfully reject a pending project invitation."""
        G(
            ProjectMember,
            project=self.active_project,
            member=self.user2,
            inviter=self.user,
            role=ProjectMember.Role.DEV,
            status=ProjectMember.Status.INVITED,
        )

        self.client.force_authenticate(self.user2)

        url = reverse("project-reject-invite", args=[self.active_project.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)

        pm = ProjectMember.objects.get(project=self.active_project, member=self.user2)

        self.assertEqual(pm.status, ProjectMember.Status.REJECTED)

    def test_revoke_member_success(self):
        """Verifies that an admin can successfully revoke a user's membership from a project."""
        G(
            ProjectMember,
            project=self.active_project,
            member=self.user2,
            inviter=self.user,
            role=ProjectMember.Role.DEV,
            status=ProjectMember.Status.ACTIVE,
        )

        url = reverse("project-revoke-member", args=[self.active_project.id])

        response = self.client.post(url, {"user_id": self.user2.id})

        self.assertEqual(response.status_code, 200)

        pm = ProjectMember.objects.get(project=self.active_project, member=self.user2)

        self.assertEqual(pm.status, ProjectMember.Status.REVOKED)

    def test_change_role_success(self):
        """Validates that an admin can successfully change the role of another project member."""
        G(
            ProjectMember,
            project=self.active_project,
            member=self.user2,
            inviter=self.user,
            role=ProjectMember.Role.DEV,
            status=ProjectMember.Status.ACTIVE,
        )

        url = reverse("project-change-role", args=[self.active_project.id])

        response = self.client.post(url, {"user_id": self.user2.id, "role": 2})

        self.assertEqual(response.status_code, 200)

        pm = ProjectMember.objects.get(project=self.active_project, member=self.user2)

        self.assertEqual(pm.role, ProjectMember.Role.ADMIN.value)
