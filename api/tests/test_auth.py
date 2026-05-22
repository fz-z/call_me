import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestAuthRegister:
    def test_register_success(self, clean_db):
        resp = client.post("/api/auth/register", json={
            "username": "alice", "password": "secret123"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["username"] == "alice"
        assert data["user"]["role"] == "user"

    def test_register_duplicate_username(self, clean_db):
        client.post("/api/auth/register", json={"username": "bob", "password": "x"})
        resp = client.post("/api/auth/register", json={"username": "bob", "password": "y"})
        assert resp.status_code == 400
        assert "already taken" in resp.json()["detail"].lower()

    def test_login_success(self, clean_db):
        client.post("/api/auth/register", json={"username": "carol", "password": "pw123"})
        resp = client.post("/api/auth/login", json={"username": "carol", "password": "pw123"})
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["username"] == "carol"

    def test_login_wrong_password(self, clean_db):
        client.post("/api/auth/register", json={"username": "dave", "password": "correct"})
        resp = client.post("/api/auth/login", json={"username": "dave", "password": "wrong"})
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, clean_db):
        resp = client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
        assert resp.status_code == 401

    def test_unauthenticated_request(self, clean_db):
        resp = client.get("/api/agents")
        assert resp.status_code == 401

    def test_invalid_token(self, clean_db):
        resp = client.get("/api/agents", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401

    def test_admin_login(self, clean_db):
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "admin"


def _auth_header(username="alice", password="secret123"):
    """Helper: register user and return auth header dict."""
    client.post("/api/auth/register", json={"username": username, "password": password})
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _admin_header():
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}
