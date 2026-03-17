from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from projects.models import Project, ProjectMember
from tickets.models import Ticket, TicketSubscriber

User = get_user_model()


@pytest.mark.django_db
class ProjectTicketViewSetTestCase(APITestCase):
    login = reverse("core:login")

    def setUp(self):
        self.admin_user = User.objects.create_user(
            first_name="Admin",
            last_name="User",
            email="admin@test.com",
            password="tester",
            designation="M",
            jiraID="admin-jira-id",
            jira_access_token="admin_token",
        )

        self.dev_user = User.objects.create_user(
            first_name="Dev",
            last_name="User",
            email="dev@test.com",
            password="tester",
            designation="SD",
            jiraID="dev-jira-id",
            jira_access_token="dev_token",
        )

        response = self.client.post(
            self.login, {"email": "admin@test.com", "password": "tester"}
        )
        self.access = response.data.get("access", "")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.access)

        self.project1 = Project.objects.create(
            title="Project 1",
            description="First project",
            status=Project.Status.ACTIVE,
            owner=self.admin_user,
            key="PROJ1",
            jira_url="https://test.atlassian.net",
            jira_project_id="10001",
        )
        ProjectMember.objects.create(
            project=self.project1,
            member=self.admin_user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        )
        ProjectMember.objects.create(
            project=self.project1,
            member=self.dev_user,
            role=ProjectMember.Role.DEV,
            status=ProjectMember.Status.ACTIVE,
        )

        self.project2 = Project.objects.create(
            title="Project 2",
            description="Second project",
            status=Project.Status.ACTIVE,
            owner=self.admin_user,
            key="PROJ2",
            jira_url="https://test.atlassian.net",
            jira_project_id="10002",
        )
        ProjectMember.objects.create(
            project=self.project2,
            member=self.admin_user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        )

        self.ticket = Ticket.objects.create(
            project=self.project1,
            reporter=self.admin_user,
            assignee=self.dev_user,
            title="Test Ticket",
            description="Test Description",
            jira_id="PROJ1-123",
            status=Ticket.Status.OPEN,
        )

        self.list_url = f"/api/projects/{self.project1.id}/tickets/"
        self.detail_url = f"/api/projects/{self.project1.id}/tickets/{self.ticket.id}/"

    @patch("requests.request")
    def test_create_ticket_success_as_admin(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.text = "dummy"
        mock_resp.json.return_value = {"id": "10002", "key": "PROJ1-124"}
        mock_request.return_value = mock_resp

        data = {
            "title": "New Ticket",
            "description": "New description",
            "assignee": self.dev_user.id,
            "severity": Ticket.Severity.HIGH,
        }

        response = self.client.post(self.list_url, data)
        self.assertEqual(201, response.status_code)
        self.assertEqual(response.data["jira_id"], "PROJ1-124")
        self.assertTrue(Ticket.objects.filter(jira_id="PROJ1-124").exists())
        self.assertTrue(
            TicketSubscriber.objects.filter(
                ticket__jira_id="PROJ1-124", user=self.dev_user
            ).exists()
        )

    def test_create_ticket_denied_for_dev(self):
        self.client.force_authenticate(self.dev_user)

        data = {"title": "New Ticket", "description": "New description"}
        response = self.client.post(self.list_url, data)
        self.assertEqual(403, response.status_code)

    @patch("requests.request")
    def test_create_ticket_jira_rejection(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "dummy"
        mock_resp.json.return_value = {"errorMessages": ["Jira Field Required"]}
        mock_request.return_value = mock_resp

        data = {"title": "Fail Ticket", "description": "Fail description"}
        response = self.client.post(self.list_url, data)

        self.assertEqual(400, response.status_code)
        self.assertFalse(Ticket.objects.filter(title="Fail Ticket").exists())

    @patch("requests.request")
    def test_update_ticket_status_success(self, mock_request):
        def request_side_effect(method, url, **kwargs):
            mock_resp = MagicMock()
            if method == "GET" and "transitions" in url:
                mock_resp.status_code = 200
                mock_resp.text = "dummy"
                mock_resp.json.return_value = {
                    "transitions": [{"id": "21", "to": {"name": "In Progress"}}]
                }
            elif method == "POST" and "transitions" in url:
                mock_resp.status_code = 204
                mock_resp.text = "dummy"
                mock_resp.json.return_value = {}
            else:
                mock_resp.status_code = 200
                mock_resp.text = "dummy"
                mock_resp.json.return_value = {}
            return mock_resp

        mock_request.side_effect = request_side_effect

        data = {"status": Ticket.Status.IN_PROGRESS}
        response = self.client.patch(self.detail_url, data)

        self.assertEqual(200, response.status_code)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.IN_PROGRESS)

    def test_move_ticket_success(self):
        TicketSubscriber.objects.create(
            user=self.dev_user,
            ticket=self.ticket,
            status=TicketSubscriber.Status.SUBSCRIBED,
        )

        data = {"project_id": str(self.project2.id)}
        response = self.client.patch(self.detail_url, data)

        self.assertEqual(200, response.status_code)
        self.ticket.refresh_from_db()

        self.assertEqual(self.ticket.project, self.project2)
        self.assertIsNone(self.ticket.assignee)
        self.assertFalse(
            TicketSubscriber.objects.filter(
                user=self.dev_user, ticket=self.ticket
            ).exists()
        )

    def test_move_ticket_denied_for_non_admin(self):
        self.client.force_authenticate(self.dev_user)

        data = {"project_id": str(self.project2.id)}
        response = self.client.patch(self.detail_url, data)

        self.assertEqual(403, response.status_code)

    def test_delete_ticket_denied_for_dev(self):
        self.client.force_authenticate(self.dev_user)

        response = self.client.delete(self.detail_url)
        self.assertEqual(403, response.status_code)
        self.assertTrue(Ticket.objects.filter(id=self.ticket.id).exists())

    def test_subscribe_ticket(self):
        url = f"{self.detail_url}subscribe/"
        response = self.client.post(url)

        self.assertEqual(200, response.status_code)
        self.assertTrue(
            TicketSubscriber.objects.filter(
                user=self.admin_user,
                ticket=self.ticket,
                status=TicketSubscriber.Status.SUBSCRIBED,
            ).exists()
        )

    def test_unsubscribe_ticket(self):
        TicketSubscriber.objects.create(
            user=self.admin_user,
            ticket=self.ticket,
            status=TicketSubscriber.Status.SUBSCRIBED,
        )
        url = f"{self.detail_url}unsubscribe/"
        response = self.client.post(url)

        self.assertEqual(200, response.status_code)
        sub = TicketSubscriber.objects.get(user=self.admin_user, ticket=self.ticket)
        self.assertEqual(sub.status, TicketSubscriber.Status.UNSUBSCRIBED)

    def test_get_movable_projects(self):
        url = f"{self.detail_url}movable_projects/"
        response = self.client.get(url)

        self.assertEqual(200, response.status_code)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], str(self.project2.id))

    @patch("requests.request")
    def test_jira_import_list_success(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "dummy"
        mock_resp.json.return_value = {
            "issues": [
                {
                    "id": "1001",
                    "key": "PROJ1-999",
                    "fields": {
                        "summary": "Import Me",
                        "reporter": {"accountId": "admin-jira-id"},
                        "description": {
                            "type": "doc",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Plain text desc"}
                                    ],
                                }
                            ],
                        },
                    },
                }
            ],
            "nextPageToken": None,
        }
        mock_request.return_value = mock_resp

        url = f"{self.list_url}jira-import-list/"
        response = self.client.get(url)

        self.assertEqual(200, response.status_code)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["jira_key"], "PROJ1-999")
        self.assertEqual(response.data[0]["description"].strip(), "Plain text desc")

    @patch("requests.request")
    def test_import_ticket_success(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "dummy"
        mock_resp.json.return_value = {
            "key": "PROJ1-1000",
            "fields": {
                "summary": "Newly Imported Ticket",
                "reporter": {"accountId": "admin-jira-id"},
                "assignee": {"accountId": "dev-jira-id"},
                "description": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Hello"}],
                        }
                    ],
                },
                "status": {"statusCategory": {"key": "indeterminate"}},
                "priority": {"name": "High"},
                "comment": {"comments": []},
            },
        }
        mock_request.return_value = mock_resp

        url = f"{self.list_url}import-ticket/"
        data = {"jira_id": "PROJ1-1000"}

        response = self.client.post(url, data)
        self.assertEqual(201, response.status_code)

        imported_ticket = Ticket.objects.get(jira_id="PROJ1-1000")
        self.assertEqual(imported_ticket.title, "Newly Imported Ticket")
        self.assertEqual(imported_ticket.status, Ticket.Status.IN_PROGRESS)
        self.assertEqual(imported_ticket.severity, Ticket.Severity.HIGH)
        self.assertEqual(imported_ticket.assignee, self.dev_user)

    def test_import_ticket_already_exists(self):
        url = f"{self.list_url}import-ticket/"
        data = {"jira_id": "PROJ1-123"}

        response = self.client.post(url, data)
        self.assertEqual(400, response.status_code)
        self.assertIn("already been imported", response.data["error"])
