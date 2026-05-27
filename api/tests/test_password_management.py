from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _register_and_login(username="alice", password="secret123"):
    client.post("/api/auth/register", json={"username": username, "password": password})
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    return resp.json()["token"]


def _admin_header():
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


class TestChangePassword:
    def test_change_password_success(self, clean_db):
        token = _register_and_login("eve", "oldpass")
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.put("/api/auth/change-password", json={
            "old_password": "oldpass", "new_password": "newpass"
        }, headers=headers)
        assert resp.status_code == 204

        # Verify can login with new password
        login_resp = client.post("/api/auth/login", json={"username": "eve", "password": "newpass"})
        assert login_resp.status_code == 200

        # Verify old password no longer works
        login_resp2 = client.post("/api/auth/login", json={"username": "eve", "password": "oldpass"})
        assert login_resp2.status_code == 401

    def test_change_password_wrong_old_password(self, clean_db):
        token = _register_and_login("frank", "correct")
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.put("/api/auth/change-password", json={
            "old_password": "wrong", "new_password": "newpass"
        }, headers=headers)
        assert resp.status_code == 400
        assert "旧密码错误" in resp.json()["detail"]

    def test_change_password_requires_auth(self, clean_db):
        resp = client.put("/api/auth/change-password", json={
            "old_password": "x", "new_password": "y"
        })
        assert resp.status_code == 401


class TestAdminCreateUser:
    def test_create_user_success(self, clean_db):
        resp = client.post("/api/admin/users", json={
            "username": "newuser", "password": "aB@12345"
        }, headers=_admin_header())
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["role"] == "user"

    def test_create_user_default_password(self, clean_db):
        resp = client.post("/api/admin/users", json={
            "username": "defaultpwuser"
        }, headers=_admin_header())
        assert resp.status_code == 201

        # Verify can login with default password
        login_resp = client.post("/api/auth/login", json={
            "username": "defaultpwuser", "password": "aB@12345"
        })
        assert login_resp.status_code == 200

    def test_create_user_duplicate_username(self, clean_db):
        client.post("/api/admin/users", json={"username": "dup"}, headers=_admin_header())
        resp = client.post("/api/admin/users", json={"username": "dup"}, headers=_admin_header())
        assert resp.status_code == 409
        assert "用户名已存在" in resp.json()["detail"]

    def test_create_user_empty_username(self, clean_db):
        resp = client.post("/api/admin/users", json={"username": "  "}, headers=_admin_header())
        assert resp.status_code == 400

    def test_create_user_requires_admin(self, clean_db):
        token = _register_and_login("bob", "pw")
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.post("/api/admin/users", json={"username": "hack"}, headers=headers)
        assert resp.status_code == 403


class TestAdminResetPassword:
    def test_reset_password_success(self, clean_db):
        token = _register_and_login("carol", "oldpw")
        resp = client.put("/api/admin/users/carol/reset-password", json={
            "new_password": "resetpw"
        }, headers=_admin_header())
        assert resp.status_code == 204

        # Verify old password fails
        old = client.post("/api/auth/login", json={"username": "carol", "password": "oldpw"})
        assert old.status_code == 401

        # Verify new password works
        new = client.post("/api/auth/login", json={"username": "carol", "password": "resetpw"})
        assert new.status_code == 200

    def test_reset_password_default_value(self, clean_db):
        _register_and_login("dave", "original")
        resp = client.put("/api/admin/users/dave/reset-password", json={}, headers=_admin_header())
        assert resp.status_code == 204

        login = client.post("/api/auth/login", json={"username": "dave", "password": "aB@12345"})
        assert login.status_code == 200

    def test_reset_password_user_not_found(self, clean_db):
        resp = client.put("/api/admin/users/ghost/reset-password", json={
            "new_password": "x"
        }, headers=_admin_header())
        assert resp.status_code == 404

    def test_reset_password_requires_admin(self, clean_db):
        token = _register_and_login("eve", "pw")
        headers = {"Authorization": f"Bearer {token}"}
        _register_and_login("target", "pw")
        resp = client.put("/api/admin/users/target/reset-password", json={
            "new_password": "x"
        }, headers=headers)
        assert resp.status_code == 403
