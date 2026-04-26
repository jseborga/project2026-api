from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body


def test_login_without_odoo_returns_503():
    """Sin ODOO_URL configurada, login debe responder 503 limpio (no 500)."""
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"login": "x@y.com", "api_key": "k"})
        assert r.status_code == 503


def test_me_without_cookie_returns_401():
    with TestClient(app) as client:
        r = client.get("/auth/me")
        assert r.status_code == 401
