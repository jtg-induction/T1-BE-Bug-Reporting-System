import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

User = get_user_model()


@pytest.mark.django_db
class UserUpdateAPIViewTestCase(APITestCase):
    """
    Test suite for verifying user profile update functionality.
    """

    url = reverse("users:me")
    login = reverse("core:login")

    def setUp(self):
        """
        Set up a test user and authenticate via JWT to obtain access and refresh tokens.
        """
        self.first_name = "test"
        self.last_name = "user"
        self.email = "test@testuser.com"
        self.password = "tester"
        self.designation = "M"
        self.jiraID = "abcd"
        self.phone = "1234567890"
        self.dob = "1993-12-03"
        self.jira_access_token = "dummy-jira-token"

        User.objects.create_user(
            first_name=self.first_name,
            last_name=self.last_name,
            email=self.email,
            password=self.password,
            designation=self.designation,
            jiraID=self.jiraID,
            jira_access_token=self.jira_access_token,
        )

        response = self.client.post(
            self.login, {"email": self.email, "password": self.password}
        )
        access = response.data["access"]
        refresh = response.cookies["refresh"]
        self.client.cookies["refresh"] = refresh
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + access)

    def test_update_user_with_wrong_access_token(self):
        """
        Verify that requests with an invalid access token are rejected with a 401 status.
        """
        self.client.credentials(HTTP_AUTHORIZATION="Bearer a-fake-access-token")
        response = self.client.get(self.url)
        self.assertEqual(401, response.status_code)

    def test_updating_updatable_fields(self):
        """
        Verify that fields like first_name, last_name, and designation can be successfully updated.
        """
        user_data = {
            "first_name": "new first name",
            "last_name": "new last name",
            "designation": "TL",
        }
        response = self.client.patch(self.url, user_data)
        self.assertTrue(
            "first_name" in response.data
            and "last_name" in response.data
            and "designation" in response.data
        )
        self.assertEqual(200, response.status_code)

    def test_non_updatable_fields(self):
        """
        Verify that attempting to update read-only fields (like jiraID) results in a 400 error.
        """
        user_data = {
            "jiraID": "xyz",
        }
        response = self.client.patch(self.url, user_data)
        self.assertTrue("jiraID" in response.data)
        self.assertEqual(400, response.status_code)

    def test_invalid_phone(self):
        """
        Verify that a phone number with an incorrect length results in a 400 validation error.
        """
        user_data = {
            "phone": "12345",
        }
        response = self.client.patch(self.url, user_data)
        self.assertEqual(400, response.status_code)

    def test_invalid_date_format(self):
        """
        Verify that a date of birth in an incorrect format (DD-MM-YYYY) results in a 400 error.
        """
        user_data = {
            "date_of_birth": "12-03-1998",
        }
        response = self.client.patch(self.url, user_data)
        self.assertEqual(400, response.status_code)


@pytest.mark.django_db
class UserGetAPIViewTestCase(APITestCase):
    """
    Test suite for verifying the retrieval of current user profile information.
    """

    url = reverse("users:me")
    login = reverse("core:login")

    def setUp(self):
        """
        Set up a test user and authenticate session.
        """
        self.first_name = "test"
        self.last_name = "user"
        self.email = "test@testuser.com"
        self.password = "tester"
        self.designation = "M"
        self.jiraID = "abcd"
        self.phone = "1234567890"
        self.dob = "1993-12-03"
        self.jira_access_token = "dummy-jira-token"

        user = User.objects.create_user(
            first_name=self.first_name,
            last_name=self.last_name,
            email=self.email,
            password=self.password,
            designation=self.designation,
            jiraID=self.jiraID,
            jira_access_token=self.jira_access_token,
        )

        self.created_at = user.created_at
        self.updated_at = user.updated_at

        response = self.client.post(
            self.login, {"email": self.email, "password": self.password}
        )
        access = response.data["access"]
        refresh = response.cookies["refresh"]
        self.client.cookies["refresh"] = refresh
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + access)

    def test_user_info(self):
        """
        Verify that the profile endpoint returns the correct user data fields.
        """
        response = self.client.get(self.url)
        data = response.data
        self.assertEqual(self.first_name, data["first_name"])
        self.assertEqual(self.last_name, data["last_name"])
        self.assertEqual(self.email, data["email"])
        self.assertEqual(self.designation, data["designation"])
        self.assertEqual(self.jiraID, data["jiraID"])
        self.assertEqual(200, response.status_code)

    def test_get_user_with_wrong_access_token(self):
        """
        Verify that profile retrieval is denied for unauthorized requests.
        """
        self.client.credentials(HTTP_AUTHORIZATION="Bearer a-fake-access-token")
        response = self.client.get(self.url)
        self.assertEqual(401, response.status_code)
