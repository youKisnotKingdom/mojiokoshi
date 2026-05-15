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
        assert response.headers["location"] == "/transcription/upload"

    def test_login_page_keeps_six_digit_user_id_input_when_ldap_enabled(self, client, monkeypatch):
        from app.routers import auth as auth_router

        monkeypatch.setattr(auth_router.settings, "ldap_enabled", True)

        response = client.get("/auth/login")

        assert response.status_code == 200
        assert "ユーザーID / LDAP ID" not in response.text
        assert "ユーザーID" in response.text
        assert 'maxlength="6"' in response.text
        assert 'pattern="\\d{6}"' in response.text


class TestLogin:
    def test_successful_login(self, client, admin_user):
        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={"user_id": "000001", "password": "AdminPass1", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/transcription/upload"
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
        assert "CSRFトークンが無効です" in response.text

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

    def test_ldap_login_creates_local_linked_user(self, client, db, monkeypatch):
        from app.models.user import User, UserRole
        from app.services import auth as auth_service
        from app.services.ldap_auth import LDAPAuthenticatedUser

        monkeypatch.setattr(auth_service.settings, "ldap_enabled", True)
        monkeypatch.setattr(
            auth_service.ldap_auth,
            "authenticate_ldap_user",
            lambda user_id, password: LDAPAuthenticatedUser(
                external_id="taro",
                display_name="LDAP Taro",
                is_admin=False,
            )
            if user_id == "taro" and password == "ldap-pass"
            else None,
        )

        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={"user_id": "taro", "password": "ldap-pass", "csrf_token": csrf},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert "session" in response.cookies
        user = db.query(User).filter(User.external_auth_provider == "ldap").one()
        assert user.external_auth_id == "taro"
        assert user.display_name == "LDAP Taro"
        assert user.role == UserRole.USER
        assert user.user_id.isdigit()
        assert len(user.user_id) == 6

    def test_ldap_login_uses_six_digit_external_id_as_app_user_id(self, client, db, monkeypatch):
        from app.models.user import UserRole
        from app.services import auth as auth_service
        from app.services.ldap_auth import LDAPAuthenticatedUser

        monkeypatch.setattr(auth_service.settings, "ldap_enabled", True)
        monkeypatch.setattr(auth_service.settings, "ldap_bootstrap_admin_user_ids", "")
        monkeypatch.setattr(
            auth_service.ldap_auth,
            "authenticate_ldap_user",
            lambda user_id, password: LDAPAuthenticatedUser(
                external_id="123456",
                display_name="LDAP User",
                is_admin=False,
            )
            if user_id == "123456" and password == "ldap-pass"
            else None,
        )

        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={"user_id": "123456", "password": "ldap-pass", "csrf_token": csrf},
            follow_redirects=False,
        )

        assert response.status_code == 302
        user = auth_service.get_user_by_external_auth(db, "ldap", "123456")
        assert user is not None
        assert user.user_id == "123456"
        assert user.role == UserRole.USER

    def test_ldap_bootstrap_admin_ids_grant_initial_app_admin_role(self, client, db, monkeypatch):
        from app.models.user import UserRole
        from app.services import auth as auth_service
        from app.services.ldap_auth import LDAPAuthenticatedUser

        monkeypatch.setattr(auth_service.settings, "ldap_enabled", True)
        monkeypatch.setattr(auth_service.settings, "ldap_default_role", "user")
        monkeypatch.setattr(auth_service.settings, "ldap_bootstrap_admin_user_ids", "123456,999999")
        monkeypatch.setattr(
            auth_service.ldap_auth,
            "authenticate_ldap_user",
            lambda user_id, password: LDAPAuthenticatedUser(
                external_id="123456",
                display_name="LDAP Admin",
                is_admin=False,
            ),
        )

        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={"user_id": "123456", "password": "ldap-pass", "csrf_token": csrf},
            follow_redirects=False,
        )

        assert response.status_code == 302
        user = auth_service.get_user_by_external_auth(db, "ldap", "123456")
        assert user is not None
        assert user.role == UserRole.ADMIN

    def test_ldap_linked_user_can_login_with_app_user_id(self, client, db, monkeypatch):
        from app.models.user import User, UserRole
        from app.services import auth as auth_service
        from app.services.auth import get_password_hash
        from app.services.ldap_auth import LDAPAuthenticatedUser

        linked_user = User(
            user_id="123456",
            external_auth_provider="ldap",
            external_auth_id="taro",
            password_hash=get_password_hash("local-password-should-not-work"),
            display_name="Old Name",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(linked_user)
        db.commit()

        seen_credentials = []
        monkeypatch.setattr(auth_service.settings, "ldap_enabled", True)
        monkeypatch.setattr(
            auth_service.ldap_auth,
            "authenticate_ldap_user",
            lambda user_id, password: (
                seen_credentials.append((user_id, password))
                or LDAPAuthenticatedUser(
                    external_id="taro",
                    display_name="LDAP Taro",
                    is_admin=False,
                )
            )
            if user_id == "taro" and password == "ldap-pass"
            else None,
        )

        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={"user_id": "123456", "password": "ldap-pass", "csrf_token": csrf},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert seen_credentials == [("taro", "ldap-pass")]
        db.refresh(linked_user)
        assert linked_user.display_name == "LDAP Taro"
        assert linked_user.external_auth_id == "taro"
        assert linked_user.role == UserRole.ADMIN

    def test_ldap_linked_user_rejects_local_password(self, client, db, monkeypatch):
        from app.models.user import User, UserRole
        from app.services import auth as auth_service
        from app.services.auth import get_password_hash

        linked_user = User(
            user_id="123456",
            external_auth_provider="ldap",
            external_auth_id="taro",
            password_hash=get_password_hash("local-password-should-not-work"),
            display_name="LDAP Taro",
            role=UserRole.USER,
            is_active=True,
        )
        db.add(linked_user)
        db.commit()

        monkeypatch.setattr(auth_service.settings, "ldap_enabled", True)
        monkeypatch.setattr(auth_service.ldap_auth, "authenticate_ldap_user", lambda *_: None)

        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={
                "user_id": "123456",
                "password": "local-password-should-not-work",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )

        assert response.status_code == 401

    def test_local_password_login_can_be_disabled(self, client, admin_user, monkeypatch):
        from app.services import auth as auth_service

        monkeypatch.setattr(auth_service.settings, "local_password_login_enabled", False)
        monkeypatch.setattr(auth_service.ldap_auth, "authenticate_ldap_user", lambda *_: None)

        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={"user_id": "000001", "password": "AdminPass1", "csrf_token": csrf},
            follow_redirects=False,
        )

        assert response.status_code == 401

    def test_ldap_login_uses_app_default_role_not_ldap_admin_flag(self, client, db, monkeypatch):
        from app.models.user import UserRole
        from app.services import auth as auth_service
        from app.services.ldap_auth import LDAPAuthenticatedUser

        monkeypatch.setattr(auth_service.settings, "ldap_enabled", True)
        monkeypatch.setattr(
            auth_service.ldap_auth,
            "authenticate_ldap_user",
            lambda user_id, password: LDAPAuthenticatedUser(
                external_id="admin-ldap",
                display_name="LDAP Admin",
                is_admin=True,
            ),
        )

        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={"user_id": "admin-ldap", "password": "ldap-pass", "csrf_token": csrf},
            follow_redirects=False,
        )

        assert response.status_code == 302
        user = auth_service.get_user_by_external_auth(db, "ldap", "admin-ldap")
        assert user is not None
        assert user.role == UserRole.USER

    def test_inactive_ldap_linked_user_cannot_login_by_ldap_id(self, client, db, monkeypatch):
        from app.models.user import User, UserRole
        from app.services import auth as auth_service
        from app.services.auth import get_password_hash
        from app.services.ldap_auth import LDAPAuthenticatedUser

        linked_user = User(
            user_id="123456",
            external_auth_provider="ldap",
            external_auth_id="taro",
            password_hash=get_password_hash("local-password-should-not-work"),
            display_name="LDAP Taro",
            role=UserRole.ADMIN,
            is_active=False,
        )
        db.add(linked_user)
        db.commit()

        monkeypatch.setattr(auth_service.settings, "ldap_enabled", True)
        monkeypatch.setattr(
            auth_service.ldap_auth,
            "authenticate_ldap_user",
            lambda user_id, password: LDAPAuthenticatedUser(
                external_id="taro",
                display_name="LDAP Taro",
                is_admin=True,
            )
            if user_id == "taro" and password == "ldap-pass"
            else None,
        )

        csrf = get_csrf_token(client)
        response = client.post(
            "/auth/login",
            data={"user_id": "taro", "password": "ldap-pass", "csrf_token": csrf},
            follow_redirects=False,
        )

        assert response.status_code == 401
        db.refresh(linked_user)
        assert linked_user.role == UserRole.ADMIN
        assert linked_user.is_active is False


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
