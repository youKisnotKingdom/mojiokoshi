"""Tests for user management (admin only)."""
import re


def get_csrf_token(client, url="/admin/users/new"):
    response = client.get(url)
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    return match.group(1) if match else ""


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
