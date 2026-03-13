import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

User = get_user_model()


@pytest.mark.django_db
class UserProfileAPIViewTestCase(APITestCase):
    """
    Test suite for user profile API endpoints.
    Verifies authentication, profile retrieval, and update permissions.
    """

    login = reverse("core:login")

    def setUp(self):
        """
        Initializes test users, sets up URLs, logs in the primary user,
        and configures the test client with JWT credentials.
        """
        self.user = User.objects.create_user(
            first_name="test",
            last_name="user",
            email="test@testuser.com",
            password="tester",
            designation="M",
            jiraID="abcd",
            phone="1234567890",
            jira_access_token="test_access_token",
        )
        self.user2 = User.objects.create_user(
            first_name="test2",
            last_name="user2",
            email="test2@testuser.com",
            password="tester2",
            designation="M",
            jiraID="abcde",
            phone="1234567891",
            jira_access_token="test_access_token2",
        )

        self.url = reverse("users:user-detail", kwargs={"pk": self.user.pk})
        response = self.client.post(self.login, {"email": "test@testuser.com", "password": "tester"})
        self.access = response.data["access"]
        self.refresh = response.cookies["refresh"]
        self.client.cookies["refresh"] = self.refresh
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.access)

    def test_access_with_invalid_token(self):
        """
        Verifies that requests with an invalid access token are rejected with a 401 Unauthorized status.
        """
        self.client.credentials(HTTP_AUTHORIZATION="Bearer a-fake-access-token")
        response = self.client.get(self.url)
        self.assertEqual(401, response.status_code)

    def test_access_with_valid_token(self):
        """
        Ensures a properly authenticated user can successfully retrieve their own profile data.
        """
        response = self.client.get(self.url)
        data = response.data
        self.assertEqual(self.user.first_name, data["first_name"])
        self.assertEqual(self.user.last_name, data["last_name"])
        self.assertEqual(self.user.email, data["email"])
        self.assertEqual(self.user.designation, data["designation"])
        self.assertEqual(self.user.phone, data["phone"])
        self.assertEqual(self.user.date_of_birth, data["date_of_birth"])
        self.assertEqual(200, response.status_code)
        self.assertTrue(data["can_edit"])

    def test_update_with_valid_token(self):
        """
        Confirms that an authenticated user can successfully update their own profile details.
        """
        user_data = {
            "first_name": "new first name",
            "last_name": "new last name",
        }
        response = self.client.patch(self.url, user_data)
        get_response = self.client.get(self.url)
        data = get_response.data
        self.assertEqual(data["first_name"], user_data["first_name"])
        self.assertEqual(data["last_name"], user_data["last_name"])
        self.assertEqual(200, response.status_code)

    def test_access_with_diff_valid_token(self):
        """
        Verifies that a user can view another user's profile but does not receive edit permissions.
        """
        response = self.client.post(self.login, {"email": "test2@testuser.com", "password": "tester2"})
        access = response.data["access"]
        refresh = response.cookies["refresh"]
        self.client.cookies["refresh"] = refresh
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + access)

        response = self.client.get(self.url)
        data = response.data
        self.assertEqual(self.user.first_name, data["first_name"])
        self.assertEqual(self.user.last_name, data["last_name"])
        self.assertEqual(self.user.email, data["email"])
        self.assertEqual(self.user.designation, data["designation"])
        self.assertEqual(self.user.phone, data["phone"])
        self.assertEqual(self.user.date_of_birth, data["date_of_birth"])
        self.assertEqual(200, response.status_code)
        self.assertFalse(data["can_edit"])

    def test_update_diff_valid_token(self):
        """
        Ensures that a user is forbidden (403) from updating another user's profile
        and that no changes are actually made to the target profile.
        """
        response = self.client.post(self.login, {"email": "test2@testuser.com", "password": "tester2"})
        access = response.data["access"]
        refresh = response.cookies["refresh"]
        self.client.cookies["refresh"] = refresh
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + access)

        response = self.client.get(self.url)
        before_update = response.data
        user_data = {
            "first_name": "new first name",
            "last_name": "new last name",
        }
        response = self.client.patch(self.url, user_data)
        self.assertEqual(403, response.status_code)

        response = self.client.get(self.url)
        after_update = response.data
        self.assertEqual(before_update["first_name"], after_update["first_name"])
        self.assertEqual(before_update["last_name"], after_update["last_name"])
        self.assertEqual(before_update["email"], after_update["email"])
        self.assertEqual(before_update["designation"], after_update["designation"])
        self.assertEqual(before_update["phone"], after_update["phone"])
        self.assertEqual(before_update["date_of_birth"], after_update["date_of_birth"])
