"""
Phase 8 auth/health API tests. Kept separate from core/tests.py (the
Phase 7 admin smoke tests) rather than merged in, since manage.py test
discovers both tests.py and tests_*.py modules fine and this keeps the
two phases' test concerns apart.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class HealthTests(APITestCase):
    def test_health_is_public(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"ok": True})


class AuthTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="alice", password="correct-horse", email="alice@example.com",
        )

    def test_login_with_correct_credentials(self):
        response = self.client.post(
            reverse("auth-login"), {"username": "alice", "password": "correct-horse"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "alice")

    def test_login_with_wrong_password_is_rejected(self):
        response = self.client.post(
            reverse("auth-login"), {"username": "alice", "password": "wrong"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_requires_login(self):
        response = self.client.get(reverse("auth-me"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_me_after_login_reflects_session(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(reverse("auth-me"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "alice")

    def test_logout_ends_session(self):
        self.client.login(username="alice", password="correct-horse")
        logout_response = self.client.post(reverse("auth-logout"))
        self.assertEqual(logout_response.status_code, status.HTTP_204_NO_CONTENT)
        me_response = self.client.get(reverse("auth-me"))
        self.assertEqual(me_response.status_code, status.HTTP_403_FORBIDDEN)
