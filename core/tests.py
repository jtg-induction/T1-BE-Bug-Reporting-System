import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from core.models import EmailVerification

User = get_user_model()


@pytest.mark.django_db
class EmailLinkGenerateAPIViewTestCase(APITestCase):
    """
    Tests for the email verification link generation endpoint.
    """

    url = reverse("core:generate-email-link")
    register = reverse("core:register")

    def setUp(self):
        self.email = "test@testuser.com"
        self.token = EmailVerification.objects.create(email=self.email)

    def test_email_link_generation(self):
        """
        Test that a verification email is successfully generated for a new email.
        """
        user_data = {
            "email": "test@testuser.com",
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(200, response.status_code)

    def test_email_link_re_generation_without_expiry(self):
        """
        Test that requesting a link again before the old one expires returns a
        message indicating the mail was already sent.
        """
        user_data = {
            "email": "test@testuser.com",
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(200, response.status_code)

        response = self.client.post(self.url, user_data)
        self.assertTrue("Mail already sent to your email" in response.data["detail"])
        self.assertEqual(200, response.status_code)

    def test_email_link_generation_for_registered_user(self):
        """
        Test that email generation fails if the user is already registered
        (simulated by a soft-deleted verification token).
        """
        user_data = {
            "email": "test@testuser.com",
            "first_name": "tester",
            "last_name": "1",
            "password": "123123",
            "confirm_password": "123123",
            "designation": "M",
            "phone": "1234567890",
            "jiraID": "abcd",
            "jira_access_token": "test_access_token",
            "token": self.token.verification_token,
        }

        self.client.post(self.register, user_data)
        response = self.client.post(self.url, {"email": self.email})
        self.assertTrue("You are already registered" in response.data["detail"])
        self.assertEqual(400, response.status_code)


@pytest.mark.django_db
class UserRegistrationAPIViewTestCase(APITestCase):
    """
    Tests for the User Registration endpoint.
    """

    url = reverse("core:register")

    def setUp(self):
        """Set up a valid verification token for registration tests."""
        self.email = "test@testuser.com"
        self.token = EmailVerification.objects.create(email=self.email)

    def test_register_without_verification_token(self):
        """
        Test that registration fails if the verification token is missing.
        """
        user_data = {
            "email": self.email,
            "first_name": "tester",
            "last_name": "1",
            "password": "password",
            "confirm_password": "password",
            "designation": "M",
            "phone": "1234567890",
            "jiraID": "abcd",
            "jira_access_token": "test_access_token",
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(400, response.status_code)

    def test_invalid_password(self):
        """
        Test that registration fails if password and confirm_password do not match.
        """
        user_data = {
            "email": self.email,
            "first_name": "tester",
            "last_name": "1",
            "password": "password",
            "confirm_password": "INVALID_PASSWORD",
            "designation": "M",
            "phone": "1234567890",
            "jiraID": "abcd",
            "jira_access_token": "test_access_token",
            "token": self.token.verification_token,
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(400, response.status_code)

    def test_user_registration(self):
        """
        Test successful user registration with valid data and token.
        """
        user_data = {
            "email": "test@testuser.com",
            "first_name": "tester",
            "last_name": "1",
            "password": "123123",
            "confirm_password": "123123",
            "designation": "M",
            "phone": "1234567890",
            "jiraID": "abcd",
            "date_of_birth": "1999-12-12",
            "jira_access_token": "test_access_token",
            "token": self.token.verification_token,
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(201, response.status_code)
        self.assertTrue("refresh" in response.cookies)
        self.assertFalse("refresh" in response.data)
        self.assertTrue("access" in response.data)

    def test_user_registration_without_dob(self):
        """
        Test that registration succeeds even if date_of_birth is omitted.
        """
        user_data = {
            "email": "test@testuser.com",
            "first_name": "tester",
            "last_name": "1",
            "password": "123123",
            "confirm_password": "123123",
            "designation": "M",
            "phone": "1234567890",
            "jiraID": "abcd",
            "jira_access_token": "test_access_token",
            "token": self.token.verification_token,
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(201, response.status_code)

    def test_user_registration_without_jira(self):
        """
        Test that registration fails if the required jiraID field is missing.
        """
        user_data = {
            "email": "test@testuser.com",
            "first_name": "tester",
            "last_name": "1",
            "password": "123123",
            "confirm_password": "123123",
            "designation": "M",
            "phone": "1234567890",
            "jira_access_token": "test_access_token",
            "token": self.token.verification_token,
        }
        response = self.client.post(self.url, user_data)
        self.assertTrue("This field is required." in response.data["jiraID"])
        self.assertEqual(400, response.status_code)

    def test_unique_email_validation(self):
        """
        Test that registering an email that already exists in the system fails.
        """
        user_data_1 = {
            "email": "test@testuser.com",
            "first_name": "tester",
            "last_name": "1",
            "password": "123123",
            "confirm_password": "123123",
            "designation": "M",
            "phone": "1234567890",
            "jiraID": "abcd",
            "jira_access_token": "test_access_token",
            "token": self.token.verification_token,
        }
        response = self.client.post(self.url, user_data_1)
        self.assertEqual(201, response.status_code)

        user_data_2 = {
            "email": "test@testuser.com",
            "first_name": "tester",
            "last_name": "1",
            "password": "123123",
            "confirm_password": "123123",
            "designation": "M",
            "phone": "1234567890",
            "jiraID": "abcd",
            "jira_access_token": "test_access_token",
            "token": self.token.verification_token,
        }
        response = self.client.post(self.url, user_data_2)
        self.assertEqual(400, response.status_code)

    def test_invalid_date_format(self):
        """
        Test that registration fails if date_of_birth is in the wrong format.
        """
        user_data = {
            "email": "test@testuser.com",
            "first_name": "tester",
            "last_name": "1",
            "password": "password",
            "confirm_password": "password",
            "designation": "M",
            "phone": "1234567890",
            "jiraID": "abcd",
            "jira_access_token": "test_access_token",
            "date_of_birth": "12-12-1222",
            "token": self.token.verification_token,
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(400, response.status_code)

    def test_invalid_phone_format(self):
        """
        Test that registration fails if phone number does not meet validation rules.
        """
        user_data = {
            "email": "test@testuser.com",
            "first_name": "tester",
            "last_name": "1",
            "password": "password",
            "confirm_password": "password",
            "designation": "M",
            "phone": "12345",
            "jiraID": "abcd",
            "date_of_birth": "12-12-1222",
            "jira_access_token": "test_access_token",
            "token": self.token.verification_token,
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(400, response.status_code)


@pytest.mark.django_db
class UserLoginAPIViewTestCase(APITestCase):
    """
    Tests for the User Login endpoint.
    """

    url = reverse("core:login")
    register = reverse("core:register")

    def setUp(self):
        """Pre-register a user to test login functionality."""
        self.email = "test@testuser.com"
        self.password = "123123"
        token = EmailVerification.objects.create(email=self.email)
        user_data = {
            "email": "test@testuser.com",
            "first_name": "tester",
            "last_name": "1",
            "password": self.password,
            "confirm_password": self.password,
            "designation": "M",
            "phone": "1234567890",
            "jiraID": "abcd",
            "jira_access_token": "test_access_token",
            "token": token.verification_token,
        }
        self.client.post(self.register, user_data)

    def test_authentication_without_password(self):
        """Test that login fails if the password field is missing."""
        response = self.client.post(self.url, {"email": self.email})
        self.assertTrue("This field is required." in response.data["password"])
        self.assertEqual(400, response.status_code)

    def test_refresh_in_cookie(self):
        """Test that a successful login sets the refresh token in HttpOnly cookies."""
        response = self.client.post(
            self.url, {"email": self.email, "password": self.password}
        )
        self.assertTrue("refresh" in response.cookies)
        self.assertFalse("refresh" in response.data)
        self.assertTrue("access" in response.data)
        self.assertEqual(200, response.status_code)

    def test_authentication_with_wrong_password(self):
        """Test that login fails with an incorrect password."""
        response = self.client.post(
            self.url, {"email": self.email, "password": "I_know"}
        )
        self.assertEqual(401, response.status_code)

    def test_authentication_with_wrong_credentials(self):
        """Test that login fails for a non-existent email address."""
        response = self.client.post(
            self.url, {"email": "abcd@g.com", "password": "I_know"}
        )
        self.assertEqual(401, response.status_code)

    def test_authentication_with_valid_data(self):
        """Test that login succeeds with correct credentials and returns an access token."""
        response = self.client.post(
            self.url, {"email": self.email, "password": self.password}
        )
        self.assertTrue("access" in response.data)
        self.assertEqual(200, response.status_code)
