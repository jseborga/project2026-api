"""Tests del endpoint /projects.

No tocan Odoo real: monkeypatchean el cliente con un fake.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.security import make_token
from app.main import app


def _auth_cookie(client: TestClient, *, company_id: int = 1, allowed: list[int] | None = None) -> None:
    token = make_token({
        "uid": 99,
        "login": "test@example.com",
        "key": "test-key",
        "company_id": company_id,
        "allowed_company_ids": allowed or [company_id],
    })
    client.cookies.set("tramo_session", token)


def test_list_projects_requires_auth():
    with TestClient(app) as client:
        r = client.get("/projects")
        assert r.status_code == 401


def test_list_projects_returns_503_without_odoo():
    """Sin ODOO_URL real, debe degradar a 503 (no 500)."""
    with TestClient(app) as client:
        _auth_cookie(client)
        with patch("app.api.projects.get_client", return_value=None):
            r = client.get("/projects")
            assert r.status_code == 503


def test_list_projects_filters_by_company(monkeypatch):
    """Verifica que el dominio enviado a Odoo incluye company_id de la sesión."""
    captured: dict = {}

    class FakeClient:
        def search_read(self, model, domain, fields, *, login, password_or_key, **kwargs):
            captured["model"] = model
            captured["domain"] = domain
            captured["fields"] = fields
            captured["context"] = kwargs.get("context")
            return [{
                "id": 7,
                "name": "Edificio Mirador",
                "partner_id": [3, "Inversiones del Plata"],
                "company_id": [1, "Mi Empresa"],
                "currency_id": [2, "BOB"],
                "user_id": [9, "Lucia Fernández"],
                "account_id": [22, "MIRA-001"],
                "apu_active_plan_id": [55, "Plan v3"],
                "date_start": "2026-01-12",
                "date": "2026-09-30",
                "apu_actual_total_cost": 1018400.0,
                "apu_actual_margin_pct": 12.5,
                "apu_execution_readiness_pct": 78.0,
                "apu_execution_ready": False,
            }]

    with TestClient(app) as client:
        _auth_cookie(client, company_id=1, allowed=[1, 2])
        with patch("app.api.projects.get_client", return_value=FakeClient()):
            r = client.get("/projects")

    assert r.status_code == 200, r.text
    assert captured["model"] == "project.project"
    assert ["company_id", "=", 1] in captured["domain"]
    assert ["active", "=", True] in captured["domain"]  # only_active default
    assert captured["context"] == {"allowed_company_ids": [1, 2]}

    body = r.json()
    assert len(body) == 1
    p = body[0]
    assert p["id"] == 7
    assert p["partner"] == {"id": 3, "name": "Inversiones del Plata"}
    assert p["currency"] == {"id": 2, "name": "BOB"}
    assert p["active_plan"] == {"id": 55, "name": "Plan v3"}
    assert p["actual_total_cost"] == 1018400.0


def test_list_projects_search_param_adds_ilike(monkeypatch):
    captured: dict = {}

    class FakeClient:
        def search_read(self, model, domain, fields, *, login, password_or_key, **kwargs):
            captured["domain"] = domain
            return []

    with TestClient(app) as client:
        _auth_cookie(client)
        with patch("app.api.projects.get_client", return_value=FakeClient()):
            r = client.get("/projects?search=mirador")

    assert r.status_code == 200
    assert ["name", "ilike", "mirador"] in captured["domain"]


def test_get_project_404_when_not_found(monkeypatch):
    class FakeClient:
        def search_read(self, *args, **kwargs):
            return []

    with TestClient(app) as client:
        _auth_cookie(client)
        with patch("app.api.projects.get_client", return_value=FakeClient()):
            r = client.get("/projects/999")
    assert r.status_code == 404
