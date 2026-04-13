"""Tests for authentication endpoints."""
import re

import pytest


def get_csrf_token(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    return match.group(1) if match else ""


class TestLoginPage:
    def test_login_page_renders(self, client):
        response = client.get("/auth/login")
        assert response.status_code == 200
        assert "ログイン" in response.text

    def test_login_page_has_csrf_token(self, client):
        response = client.get("/auth/login")
        assert 'name="csrf_token"' in response.text

    def test_redirect_if_already_logged_in(self, admin_client):
        response = admin_client.get("/auth/login", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/"


class TestLogin:
    def test_successful_login(self, client, admin_user):
        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={"user_id": "000001", "password": "AdminPass1", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "session" in response.cookies

    def test_invalid_password(self, client, admin_user):
        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={"user_id": "000001", "password": "WrongPass1", "csrf_token": csrf},
        )
        assert response.status_code == 401
        assert "正しくありません" in response.text

    def test_invalid_user_id(self, client):
        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={"user_id": "999999", "password": "SomePass1", "csrf_token": csrf},
        )
        assert response.status_code == 401

    def test_missing_csrf_token(self, client, admin_user):
        response = client.post(
            "/auth/login",
            data={"user_id": "000001", "password": "AdminPass1", "csrf_token": ""},
        )
        assert response.status_code == 403

    def test_inactive_user_cannot_login(self, client, db):
        from app.models.user import User, UserRole
        from app.services.auth import get_password_hash

        inactive = User(
            user_id="000099",
            password_hash=get_password_hash("InactivePass1"),
            display_name="Inactive",
            role=UserRole.USER,
            is_active=False,
        )
        db.add(inactive)
        db.commit()

        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={"user_id": "000099", "password": "InactivePass1", "csrf_token": csrf},
        )
        assert response.status_code == 401


class TestLogout:
    def test_logout_redirects(self, admin_client):
        response = admin_client.get("/auth/logout", follow_redirects=False)
        assert response.status_code in (302, 303)

    def test_access_protected_page_after_logout(self, admin_client):
        admin_client.get("/auth/logout", follow_redirects=True)
        # After logout, accessing protected page returns 401 (not authenticated)
        response = admin_client.get("/transcription", follow_redirects=False)
        assert response.status_code == 401


class TestPasswordValidation:
    def test_empty_password_rejected(self):
        from pydantic import ValidationError
        from app.schemas.user import UserCreate
        from app.models.user import UserRole

        with pytest.raises(ValidationError):
            UserCreate(display_name="Test", password="   ", role=UserRole.USER)

    def test_short_password_accepted(self):
        from app.schemas.user import UserCreate
        from app.models.user import UserRole

        user = UserCreate(display_name="Test", password="abc", role=UserRole.USER)
        assert user.password == "abc"

    def test_no_uppercase_accepted(self):
        from app.schemas.user import UserCreate
        from app.models.user import UserRole

        user = UserCreate(display_name="Test", password="password1", role=UserRole.USER)
        assert user.password == "password1"

    def test_valid_password_accepted(self):
        from app.schemas.user import UserCreate
        from app.models.user import UserRole

        user = UserCreate(display_name="Test", password="ValidPass1", role=UserRole.USER)
        assert user.password == "ValidPass1"
