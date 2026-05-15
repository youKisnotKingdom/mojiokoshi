"""Tests for user management (admin only)."""
import re


def get_csrf_token(client, url="/admin/users/new"):
    response = client.get(url)
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    return match.group(1) if match else ""


def create_ldap_user(db, user_id="123456", external_id="ldap-hanako", display_name="LDAP Hanako"):
    from app.models.user import User, UserRole
    from app.services.auth import get_password_hash

    user = User(
        user_id=user_id,
        external_auth_provider="ldap",
        external_auth_id=external_id,
        password_hash=get_password_hash("local-password-not-used"),
        display_name=display_name,
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestUserList:
    def test_admin_can_view_users(self, admin_client):
        response = admin_client.get("/admin/users")
        assert response.status_code == 200
        assert "ユーザー管理" in response.text

    def test_regular_user_cannot_view_users(self, user_client):
        response = user_client.get("/admin/users", follow_redirects=False)
        assert response.status_code == 403

    def test_anonymous_cannot_view_users(self, client):
        response = client.get("/admin/users", follow_redirects=False)
        assert response.status_code == 401

    def test_admin_can_see_ldap_identity_in_user_list(self, admin_client, db):
        create_ldap_user(db)

        response = admin_client.get("/admin/users")

        assert response.status_code == 200
        assert "アプリID" in response.text
        assert "LDAP Hanako" in response.text
        assert "LDAP ID" in response.text
        assert "ldap-hanako" in response.text
        assert "LDAP表示名" in response.text


class TestCreateUser:
    def test_admin_can_create_user(self, admin_client):
        csrf = get_csrf_token(admin_client)
        response = admin_client.post(
            "/admin/users/new",
            data={
                "display_name": "New User",
                "password": "NewUserPass1",
                "role": "user",
                "csrf_token": csrf,
            },
        )
        assert response.status_code == 200
        assert "New User" in response.text

    def test_missing_csrf_rejected(self, admin_client):
        response = admin_client.post(
            "/admin/users/new",
            data={
                "display_name": "Test",
                "password": "TestPass1",
                "role": "user",
                "csrf_token": "",
            },
        )
        assert response.status_code == 403

    def test_anonymous_cannot_create_user(self, client):
        response = client.post(
            "/admin/users/new",
            data={"display_name": "Test", "password": "TestPass1", "role": "user", "csrf_token": ""},
            follow_redirects=False,
        )
        assert response.status_code == 401


class TestUpdateUser:
    def test_admin_can_update_user(self, admin_client, regular_user):
        csrf = get_csrf_token(admin_client, f"/admin/users/{regular_user.user_id}")
        response = admin_client.post(
            f"/admin/users/{regular_user.user_id}",
            data={
                "display_name": "Updated Name",
                "role": "user",
                "is_active": "true",
                "csrf_token": csrf,
            },
        )
        assert response.status_code == 200
        assert "更新しました" in response.text

    def test_admin_can_reset_local_user_password(self, admin_client, db, regular_user):
        from app.services import auth as auth_service

        csrf = get_csrf_token(admin_client, f"/admin/users/{regular_user.user_id}")
        response = admin_client.post(
            f"/admin/users/{regular_user.user_id}/reset-password",
            data={
                "new_password": "ResetPass123",
                "csrf_token": csrf,
            },
        )

        assert response.status_code == 200
        assert "パスワードをリセットしました" in response.text
        db.refresh(regular_user)
        assert auth_service.verify_password("ResetPass123", regular_user.password_hash)
        assert auth_service.authenticate_user(db, regular_user.user_id, "ResetPass123") == regular_user

    def test_ldap_user_edit_page_shows_ldap_identity_and_hides_password_reset(self, admin_client, db):
        user = create_ldap_user(db)

        response = admin_client.get(f"/admin/users/{user.user_id}")

        assert response.status_code == 200
        assert "LDAP ID" in response.text
        assert "ldap-hanako" in response.text
        assert "LDAPログイン時にLDAP側の表示名で更新されます" in response.text
        assert "readonly" in response.text
        assert "パスワードリセット" not in response.text

    def test_ldap_user_display_name_is_not_overwritten_from_admin_form(self, admin_client, db):
        user = create_ldap_user(db)
        csrf = get_csrf_token(admin_client, f"/admin/users/{user.user_id}")

        response = admin_client.post(
            f"/admin/users/{user.user_id}",
            data={
                "display_name": "Manual Name",
                "role": "user",
                "is_active": "true",
                "csrf_token": csrf,
            },
        )

        assert response.status_code == 200
        db.refresh(user)
        assert user.display_name == "LDAP Hanako"

    def test_admin_can_manage_ldap_user_role_in_app(self, admin_client, db):
        from app.models.user import UserRole

        user = create_ldap_user(db)
        csrf = get_csrf_token(admin_client, f"/admin/users/{user.user_id}")

        response = admin_client.post(
            f"/admin/users/{user.user_id}",
            data={
                "display_name": "Manual Name",
                "role": "admin",
                "is_active": "true",
                "csrf_token": csrf,
            },
        )

        assert response.status_code == 200
        db.refresh(user)
        assert user.display_name == "LDAP Hanako"
        assert user.role == UserRole.ADMIN

    def test_ldap_user_password_reset_is_rejected(self, admin_client, db):
        user = create_ldap_user(db)
        csrf = get_csrf_token(admin_client, f"/admin/users/{user.user_id}")

        response = admin_client.post(
            f"/admin/users/{user.user_id}/reset-password",
            data={
                "new_password": "NewPass123",
                "csrf_token": csrf,
            },
        )

        assert response.status_code == 400
        assert "LDAPユーザーのパスワードはLDAP側で管理してください" in response.text

    def test_cannot_deactivate_self(self, admin_client, admin_user):
        csrf = get_csrf_token(admin_client, f"/admin/users/{admin_user.user_id}")
        response = admin_client.post(
            f"/admin/users/{admin_user.user_id}",
            data={
                "display_name": admin_user.display_name,
                "role": "admin",
                # is_active not sent → False
                "csrf_token": csrf,
            },
        )
        assert response.status_code == 200
        assert "無効化することはできません" in response.text
