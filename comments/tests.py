from unittest.mock import MagicMock, patch

import pytest
from ddf import G
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from comments.models import Comment
from projects.models import Project, ProjectMember
from tickets.models import Ticket

User = get_user_model()


@pytest.mark.django_db
class CommentViewSetTestCase(APITestCase):
    login = reverse("core:login")

    def setUp(self):
        self.user1 = G(User)
        self.user1.set_password("tester")
        self.user1.save()

        self.user2 = G(User)
        self.user3 = G(User)

        response = self.client.post(
            self.login, {"email": self.user1.email, "password": "tester"}
        )
        self.access = response.data.get("access", "")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.access)

        self.project = G(
            Project,
            status=Project.Status.ACTIVE,
            owner=self.user1,
            key="PROJ1",
            jira_url="https://test.atlassian.net",
        )

        G(
            ProjectMember,
            project=self.project,
            member=self.user1,
            role=ProjectMember.Role.DEV,
            status=ProjectMember.Status.ACTIVE,
        )
        G(
            ProjectMember,
            project=self.project,
            member=self.user2,
            role=ProjectMember.Role.DEV,
            status=ProjectMember.Status.ACTIVE,
        )

        self.ticket = G(
            Ticket,
            project=self.project,
            reporter=self.user1,
            title="Test Ticket",
            jira_key="PROJ1-123",
            status=Ticket.Status.OPEN,
        )

        self.comment = G(
            Comment,
            ticket=self.ticket,
            author=self.user2,
            description="Initial Comment",
            jira_id="JIRA-COM-1",
        )
        self.list_url = (
            f"/api/projects/{self.project.id}/tickets/{self.ticket.id}/comments/"
        )
        self.detail_url = f"{self.list_url}{self.comment.id}/"

    def test_list_comments(self):
        """Test retrieving all comments for a ticket."""
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["description"], "Initial Comment")
        self.assertFalse(results[0]["can_edit"])

    @patch("requests.Session.request")
    def test_create_comment_success(self, mock_request):
        """Test creating a comment and syncing it to Jira."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.text = "dummy"
        mock_resp.json.return_value = {"id": "JIRA-COM-999"}
        mock_request.return_value = mock_resp

        data = {"description": "This is a new comment."}
        response = self.client.post(self.list_url, data)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["description"], "This is a new comment.")
        self.assertEqual(response.data["jira_id"], "JIRA-COM-999")
        self.assertTrue(response.data["can_edit"])
        self.assertTrue(Comment.objects.filter(jira_id="JIRA-COM-999").exists())

    def test_create_comment_not_project_member(self):
        """Test that a non-project member cannot comment on the ticket."""
        self.client.force_authenticate(user=self.user3)
        data = {"description": "Hello."}
        response = self.client.post(self.list_url, data)

        self.assertEqual(response.status_code, 403)

    def test_create_comment_inactive_project(self):
        """Test that you cannot comment on tickets in an inactive project."""
        self.project.status = Project.Status.ARCHIVED
        self.project.save()

        data = {"description": "Testing inactive project."}
        response = self.client.post(self.list_url, data)

        self.assertEqual(response.status_code, 403)

    @patch("requests.Session.request")
    def test_update_comment_success(self, mock_request):
        """Test that a user can update their own comment."""
        my_comment = G(
            Comment,
            ticket=self.ticket,
            author=self.user1,
            description="My original comment",
            jira_id="JIRA-COM-2",
        )
        my_detail_url = f"{self.list_url}{my_comment.id}/"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "dummy"
        mock_resp.json.return_value = {}
        mock_request.return_value = mock_resp

        data = {"description": "I fixed a typo here."}
        response = self.client.patch(my_detail_url, data)

        self.assertEqual(response.status_code, 200)
        my_comment.refresh_from_db()
        self.assertEqual(my_comment.description, "I fixed a typo here.")

    def test_update_comment_permission_denied(self):
        """Test that user1 cannot update user2's comment."""
        data = {"description": "Changing another users comment!"}
        response = self.client.patch(self.detail_url, data)

        self.assertEqual(response.status_code, 403)

    @patch("requests.Session.request")
    def test_delete_comment_success(self, mock_request):
        """Test that a user can delete their own comment."""
        my_comment = G(
            Comment,
            ticket=self.ticket,
            author=self.user1,
            description="I am going to delete this",
            jira_id="JIRA-COM-3",
        )
        my_detail_url = f"{self.list_url}{my_comment.id}/"

        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.text = ""
        mock_resp.json.return_value = {}
        mock_request.return_value = mock_resp

        response = self.client.delete(my_detail_url)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Comment.objects.filter(id=my_comment.id).exists())

    def test_delete_comment_permission_denied(self):
        """Test that user1 cannot delete user2's comment."""
        response = self.client.delete(self.detail_url)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Comment.objects.filter(id=self.comment.id).exists())
