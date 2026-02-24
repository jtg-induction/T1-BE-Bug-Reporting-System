import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

User = get_user_model()


@pytest.mark.django_db
class UserMeAPIViewTestCase(APITestCase):
    url = reverse("users:me")
    login = reverse("core:login")

    def setUp(self):

        self.user = User.objects.create_user(
            first_name="test",
            last_name="user",
            email="test@testuser.com",
            password="tester",
            designation="M",
            jiraID="abcd",
        )
        self.user2 = User.objects.create_user(
            first_name="test2",
            last_name="user2",
            email="test2@testuser.com",
            password="tester2",
            designation="M",
            jiraID="abcde",
        )

        response = self.client.post(
            self.login, {"email": "test@testuser.com", "password": "tester"}
        )
        self.access1 = response.data["access"]
        self.refresh1 = response.cookies["refresh"]
        self.client.cookies["refresh"] = self.refresh1
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.access1)

    def test_access_with_invalid_token(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer a-fake-access-token")
        response = self.client.get(self.url)
        self.assertEqual(401, response.status_code)

    def test_access_with_valid_token(self):
        response = self.client.get(self.url)
        data = response.data
        self.assertEqual(self.user.first_name, data["first_name"])
        self.assertEqual(self.user.last_name, data["last_name"])
        self.assertEqual(self.user.email, data["email"])
        self.assertEqual(str(self.user.id), data["user_id"])
        self.assertEqual(200, response.status_code)


@pytest.mark.django_db
class UserProfileAPIViewTestCase(APITestCase):
    login = reverse("core:login")

    def setUp(self):

        self.user = User.objects.create_user(
            first_name="test",
            last_name="user",
            email="test@testuser.com",
            password="tester",
            designation="M",
            jiraID="abcd",
            phone="1234567890",
        )
        self.user2 = User.objects.create_user(
            first_name="test2",
            last_name="user2",
            email="test2@testuser.com",
            password="tester2",
            designation="M",
            jiraID="abcde",
            phone="1234567891",
        )

        self.url = reverse("users:user-detail", kwargs={"pk": self.user.pk})
        response = self.client.post(
            self.login, {"email": "test@testuser.com", "password": "tester"}
        )
        self.access = response.data["access"]
        self.refresh = response.cookies["refresh"]
        self.client.cookies["refresh"] = self.refresh
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.access)

    def test_access_with_invalid_token(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer a-fake-access-token")
        response = self.client.get(self.url)
        self.assertEqual(401, response.status_code)

    def test_access_with_valid_token(self):
        response = self.client.get(self.url)
        data = response.data
        self.assertEqual(self.user.first_name, data["first_name"])
        self.assertEqual(self.user.last_name, data["last_name"])
        self.assertEqual(self.user.email, data["email"])
        self.assertEqual(self.user.designation, data["designation"])
        self.assertEqual(self.user.phone, data["phone"])
        self.assertEqual(self.user.jiraID, data["jiraID"])
        self.assertEqual(self.user.date_of_birth, data["date_of_birth"])
        self.assertEqual(200, response.status_code)
        self.assertTrue(data["is_owner"])

    def test_update_with_valid_token(self):
        user_data = {
            "first_name": "new first name",
            "last_name": "new last name",
        }
        response = self.client.put(self.url, user_data)
        get_response = self.client.get(self.url)
        data = get_response.data
        self.assertEqual(data["first_name"], user_data["first_name"])
        self.assertEqual(data["last_name"], user_data["last_name"])
        self.assertEqual(200, response.status_code)

    def test_access_with_diff_valid_token(self):

        response = self.client.post(
            self.login, {"email": "test2@testuser.com", "password": "tester2"}
        )
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
        self.assertEqual(self.user.jiraID, data["jiraID"])
        self.assertEqual(self.user.date_of_birth, data["date_of_birth"])
        self.assertEqual(200, response.status_code)
        self.assertFalse(data["is_owner"])

    def test_update_diff_valid_token(self):

        response = self.client.post(
            self.login, {"email": "test2@testuser.com", "password": "tester2"}
        )
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
        response = self.client.put(self.url, user_data)
        self.assertEqual(403, response.status_code)

        response = self.client.get(self.url)
        after_update = response.data
        self.assertEqual(before_update["first_name"], after_update["first_name"])
        self.assertEqual(before_update["last_name"], after_update["last_name"])
        self.assertEqual(before_update["email"], after_update["email"])
        self.assertEqual(before_update["designation"], after_update["designation"])
        self.assertEqual(before_update["phone"], after_update["phone"])
        self.assertEqual(before_update["jiraID"], after_update["jiraID"])
        self.assertEqual(before_update["date_of_birth"], after_update["date_of_birth"])
