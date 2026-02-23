import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase
from django.utils import timezone

User = get_user_model()

@pytest.mark.django_db
class UserUpdateAPIViewTestCase(APITestCase):
    url = reverse('users:me')
    login = reverse("core:login")
    
    def setUp(self):
        self.first_name = "test"
        self.last_name = "user"
        self.email = "test@testuser.com"
        self.password = "tester"
        self.designation = "M"
        self.jiraID = "abcd"
        self.phone = "1234567890"
        self.dob = "1993-12-03"
        
        
        User.objects.create_user(
            first_name=self.first_name,
            last_name=self.last_name,
            email=self.email,
            password=self.password,
            designation=self.designation,
            jiraID=self.jiraID
            )
        
        response = self.client.post(self.login, {"email": self.email, "password": self.password})
        access = response.data["access"]
        refresh = response.cookies["refresh"]
        self.client.cookies["refresh"] = refresh
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + access)
        
    def test_update_user_with_wrong_access_token(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer a-fake-access-token')
        response = self.client.get(self.url)
        self.assertEqual(401, response.status_code)
    
    def test_updating_updatable_fields(self):
        """
        Test to verify that a post call with invalid passwords
        """
        user_data = {
            "first_name": "new first name",
            "last_name": "new last name",
            "designation": "TL"
        }
        response = self.client.patch(self.url, user_data)
        self.assertTrue("first_name" in  response.data and "last_name" in response.data and "designation" in response.data)
        self.assertEqual(200, response.status_code)
        
    def test_non_updatable_fields(self):
        """
        Test to verify that a post call with invalid passwords
        """
        user_data = {
            "jiraID": "xyz",
        }
        response = self.client.patch(self.url, user_data)
        self.assertTrue("jiraID" in response.data)
        self.assertEqual(400, response.status_code)
        
    def test_invalid_phone(self):
        """
        Test to verify that a post call with invalid passwords
        """
        user_data = {
            "phone": "12345",
        }
        response = self.client.patch(self.url, user_data)
        self.assertEqual(400, response.status_code)
        
    def test_invalid_date_format(self):
        """
        Test to verify that a post call with invalid passwords
        """
        user_data = {
            "date_of_birth": "12-03-1998",
        }
        response = self.client.patch(self.url, user_data)
        self.assertEqual(400, response.status_code)
        
@pytest.mark.django_db
class UserGetAPIViewTestCase(APITestCase):
    url = reverse('users:me')
    login = reverse("core:login")
    
    def setUp(self):
        self.first_name = "test"
        self.last_name = "user"
        self.email = "test@testuser.com"
        self.password = "tester"
        self.designation = "M"
        self.jiraID = "abcd"
        self.phone = "1234567890"
        self.dob = "1993-12-03"
        
        user = User.objects.create_user(
            first_name=self.first_name,
            last_name=self.last_name,
            email=self.email,
            password=self.password,
            designation=self.designation,
            jiraID=self.jiraID
            )
        
        self.created_at = user.created_at
        self.updated_at = user.updated_at
        
        response = self.client.post(self.login, {"email": self.email, "password": self.password})
        access = response.data["access"]
        refresh = response.cookies["refresh"]
        self.client.cookies["refresh"] = refresh
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + access)
        
    def test_user_info(self):
        response = self.client.get(self.url)
        data = response.data
        self.assertEqual(self.first_name, data["first_name"])
        self.assertEqual(self.last_name, data["last_name"])
        self.assertEqual(self.email, data["email"])
        self.assertEqual(self.designation, data["designation"])
        self.assertEqual(self.jiraID, data["jiraID"])
        self.assertEqual(200, response.status_code)
        
    def test_get_user_with_wrong_access_token(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer a-fake-access-token')
        response = self.client.get(self.url)
        self.assertEqual(401, response.status_code)
