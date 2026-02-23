import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from core.models import EmailVerification
from rest_framework.test import APITestCase
import uuid 

User = get_user_model()

@pytest.mark.django_db
class EmailLinkGenerateAPIViewTestCase(APITestCase):
    url = reverse('core:generate-email-link')
    
    def test_email_link_generation(self):
        """
        Test to verify that a post call with invalid passwords
        """
        user_data = {
            "email": "test@testuser.com",
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(200, response.status_code)
        
    def test_email_link_re_generation_without_expiry(self):
        """
        Test to verify that a post call with invalid passwords
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
        Test to verify that a post call with invalid passwords
        """
        user_data = {
            "email": "test@testuser.com",
        }
        token = EmailVerification.objects.create(email="test@testuser.com")
        token.isDeleted = True
        token.save()
        response = self.client.post(self.url, user_data)
        self.assertTrue("You are already registered" in response.data["detail"])
        self.assertEqual(400, response.status_code)

@pytest.mark.django_db
class EmailVerifyLinkAPIViewTestCase(APITestCase):
    url = reverse('core:verify-link')
    
    def setUp(self):
        self.email = "john@snow.com"
        self.verification = EmailVerification.objects.create(email=self.email)
        
    def test_email_verify_link(self):
        """
        Test to verify that a post call with invalid passwords
        """
        response = self.client.post(self.url, query_params={"token": self.verification.verification_token})
        self.assertEqual(200, response.status_code)
        
    def test_no_token(self):
        response = self.client.post(self.url)
        self.assertEqual(400, response.status_code)
        
    def test_invalid_token(self):
        response = self.client.post(self.url, query_params={"token": uuid.uuid4()})
        self.assertEqual(401, response.status_code)
        
    def test_email_generation_for_registered_user(self):
        self.verification.isDeleted = True
        response = self.client.post(self.url, query_params={"token": self.verification.verification_token})
        self.assertEqual(200, response.status_code)


@pytest.mark.django_db
class UserRegistrationAPIViewTestCase(APITestCase):
    url = reverse('core:register')
    
    def setUp(self):
        self.email = "test@testuser.com"
        self.token = EmailVerification.objects.create(email=self.email)
    
    def test_register_without_verification_token(self):
        """
        Test to verify that a post call with invalid passwords
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
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(400, response.status_code)
    
    def test_invalid_password(self):
        """
        Test to verify that a post call with invalid passwords
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
            "token": self.token.verification_token
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(400, response.status_code)

    def test_user_registration(self):
        """
        Test to verify that a post call with user valid data
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
            "token": self.token.verification_token
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(201, response.status_code)
        self.assertTrue("refresh" in response.cookies)
        self.assertFalse("refresh" in response.data)
        self.assertTrue("access" in response.data)
    
    def test_user_registration_without_dob(self):
        """
        Test to verify that a post call with user valid data
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
            "token": self.token.verification_token
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(201, response.status_code)
        
    def test_user_registration_without_jira(self):
        """
        Test to verify that a post call with user valid data
        """
        user_data = {
            "email": "test@testuser.com",
            "first_name": "tester",
            "last_name": "1",
            "password": "123123",
            "confirm_password": "123123",
            "designation": "M",
            "phone": "1234567890",
            "token": self.token.verification_token
        }
        response = self.client.post(self.url, user_data)
        self.assertTrue('This field is required.' in response.data['jiraID'])
        self.assertEqual(400, response.status_code)

    def test_unique_email_validation(self):
        """
        Test to verify that a post call with already exists email
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
            "token": self.token.verification_token
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
            "token": self.token.verification_token
        }
        response = self.client.post(self.url, user_data_2)
        self.assertEqual(401, response.status_code)
        
    def test_invalid_date_format(self):
        """
        Test to verify that a post call with invalid date_of_birth
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
            "date_of_birth": "12-12-1222"
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(400, response.status_code)
        
    def test_invalid_phone_format(self):
        """
        Test to verify that a post call with invalid date_of_birth
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
            "token": self.token.verification_token
        }
        response = self.client.post(self.url, user_data)
        self.assertEqual(400, response.status_code)

@pytest.mark.django_db
class UserLoginAPIViewTestCase(APITestCase):
    url = reverse("core:login")
    register = reverse("core:register")

    def setUp(self):
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
            "token": token.verification_token
        }
        self.client.post(self.register, user_data)

    def test_authentication_without_password(self):
        response = self.client.post(self.url, {"email": self.email})
        self.assertTrue('This field is required.' in response.data['password'])
        self.assertEqual(400, response.status_code)
        
    def test_refresh_in_cookie(self):
        response = self.client.post(self.url, {"email": self.email, "password": self.password})
        self.assertTrue("refresh" in response.cookies)
        self.assertFalse("refresh" in response.data)
        self.assertTrue("access" in response.data)
        self.assertEqual(200, response.status_code)

    def test_authentication_with_wrong_password(self):
        response = self.client.post(self.url, {"email": self.email, "password": "I_know"})
        self.assertEqual(401, response.status_code)
        
    def test_authentication_with_wrong_credentials(self):
        response = self.client.post(self.url, {"email": "abcd@g.com", "password": "I_know"})
        self.assertEqual(401, response.status_code)

    def test_authentication_with_valid_data(self):
        response = self.client.post(self.url, {"email": self.email, "password": self.password})
        self.assertTrue("access" in response.data)
        self.assertEqual(200, response.status_code)

