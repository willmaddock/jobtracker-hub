"""Real cookie sessions and enforced CSRF, isolated by Django's test database."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.exceptions import PermissionDenied
from core.api_errors import api_exception_handler
from accounts.models import Workspace


class AuthContractTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="alice", password="pw123456")
        self.other = get_user_model().objects.create_user(username="bob", password="pw123456")
        self.a = Workspace.objects.create(owner=self.user, name="A")
        self.b = Workspace.objects.create(owner=self.user, name="B")
        self.c = Workspace.objects.create(owner=self.other, name="C")
        self.client = APIClient(enforce_csrf_checks=True)

    def token(self, client=None):
        return (client or self.client).get("/api/auth/csrf").data["csrfToken"]

    def login(self, client=None, username="alice"):
        client = client or self.client
        return client.post("/api/auth/login", {"username": username, "password": "pw123456"}, format="json", HTTP_X_CSRFTOKEN=self.token(client))

    def test_anonymous_login_requires_csrf(self):
        response = self.client.post("/api/auth/login", {"username": "alice", "password": "pw123456"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "csrf_failed")
        self.assertNotIn("sessionid", self.client.cookies)
        response = self.client.post("/api/auth/login", {}, HTTP_X_CSRFTOKEN="invalid")
        self.assertEqual(response.status_code, 403)

    def test_login_rotation_create_read_logout(self):
        old = self.token()
        self.assertEqual(self.login().status_code, 200)
        response = self.client.post("/api/workspaces/", {"name": "New"}, HTTP_X_CSRFTOKEN=old)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "csrf_failed")
        token = self.token()
        response = self.client.post("/api/workspaces/", {"name": "New"}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "New")
        self.assertEqual(self.client.get(f'/api/workspaces/{response.data["id"]}/insights/').status_code, 200)
        response = self.client.post("/api/auth/logout", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_invalid_credentials_and_validation(self):
        response = self.client.post("/api/auth/login", {"username": "alice", "password": "wrong"}, HTTP_X_CSRFTOKEN=self.token())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["code"], "invalid_credentials")
        response = self.client.post("/api/auth/login", {}, HTTP_X_CSRFTOKEN=self.token())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "validation_error")
        self.assertIn("username", response.data)

    def test_basic_credentials_do_not_authenticate(self):
        response = self.client.get("/api/auth/me", HTTP_AUTHORIZATION="Basic YWxpY2U6cHcxMjM0NTY=")
        self.assertEqual(response.status_code, 401)

    def test_authenticated_unsafe_requests_and_origin_require_csrf(self):
        self.login()
        for url in ("/api/auth/logout", "/api/workspaces/"):
            self.assertEqual(self.client.post(url, {"name": "bad"}).status_code, 403)
        response = self.client.post("/api/workspaces/", {"name": "bad"}, HTTP_X_CSRFTOKEN=self.token(), HTTP_ORIGIN="https://foreign.example")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "csrf_failed")

    def test_shared_session_tabs_and_separate_users(self):
        self.login()
        tab = APIClient(enforce_csrf_checks=True)
        tab.cookies = self.client.cookies.copy()
        for client, workspace in ((self.client, self.a), (tab, self.b), (self.client, self.a)):
            self.assertEqual(client.get(f"/api/workspaces/{workspace.pk}/insights/").status_code, 200)
            response = client.get(f"/api/workspaces/{self.c.pk}/insights/")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.data["code"], "not_found")
        bob = APIClient(enforce_csrf_checks=True)
        self.login(bob, "bob")
        self.assertEqual([w["id"] for w in bob.get("/api/workspaces/").data], [self.c.pk])
        self.assertEqual(bob.get(f"/api/workspaces/{self.a.pk}/insights/").status_code, 404)
        self.client.post("/api/auth/logout", HTTP_X_CSRFTOKEN=self.token())
        self.assertEqual(tab.get("/api/auth/me").status_code, 401)
        self.assertEqual(bob.get("/api/auth/me").status_code, 200)

    def test_permission_denied_stays_403(self):
        response = api_exception_handler(PermissionDenied("Not permitted."), {})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "permission_denied")

    def test_session_responses_not_cached(self):
        for url in ("/api/auth/csrf", "/api/auth/me"):
            self.assertIn("no-store", self.client.get(url)["Cache-Control"])
