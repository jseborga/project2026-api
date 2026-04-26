"""Tests de escritura del plan: PATCH líneas + POST unlock."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.security import make_token
from app.main import app


def _auth(client: TestClient, *, company_id: int = 2, allowed: list[int] | None = None) -> None:
    token = make_token({
        "uid": 99, "login": "test@example.com", "key": "test-key",
        "company_id": company_id,
        "allowed_company_ids": allowed or [company_id],
    })
    client.cookies.set("tramo_session", token)


class FakeClient:
    """Mock con state mutable para simular el ciclo de vida."""
    def __init__(self, plan_state="draft"):
        self.plan_state = plan_state
        self.writes: list[tuple] = []

    def search_read(self, model, domain, fields, *, login, password_or_key, **kwargs):
        if model == "project.project":
            return [{"id": 2, "apu_active_plan_id": [11, "Plan V1"]}]
        if model == "apu.project.plan":
            return [{"id": 11, "state": self.plan_state}]
        if model == "apu.project.plan.line":
            return [{"id": 113}]
        return []

    def execute_kw(self, model, method, args, kwargs=None, *, login, password_or_key):
        self.writes.append((model, method, args, kwargs or {}))
        if model == "apu.project.plan" and method == "write":
            payload = args[1]
            if "state" in payload:
                self.plan_state = payload["state"]
        return True


# ── PATCH /lines/{id} ────────────────────────────────────────────────────

def test_patch_requires_auth():
    with TestClient(app) as c:
        r = c.patch("/projects/2/plan/lines/113", json={"name": "X"})
        assert r.status_code == 401


def test_patch_draft_allows_all_fields():
    fake = FakeClient(plan_state="draft")
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.plan_write.get_client", return_value=fake):
            r = c.patch("/projects/2/plan/lines/113", json={
                "name": "Nueva", "duration_days": 5, "progress_pct": 25.0
            })
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["updated"]) == {"name", "duration_days", "progress_pct"}
    # Verifica que el write fue al modelo correcto
    writes = [w for w in fake.writes if w[0] == "apu.project.plan.line"]
    assert len(writes) == 1
    assert writes[0][1] == "write"
    assert writes[0][2][1] == {"name": "Nueva", "duration_days": 5, "progress_pct": 25.0}


def test_patch_baseline_only_allows_actuals():
    """Con baseline locked, name/duration deben ser rechazados; progress_pct OK."""
    fake = FakeClient(plan_state="baseline")
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.plan_write.get_client", return_value=fake):
            r = c.patch("/projects/2/plan/lines/113", json={
                "name": "intento de cambio",
                "duration_days": 99,
                "progress_pct": 80.0,
                "actual_start": "2026-04-20",
            })
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["updated"]) == {"progress_pct", "actual_start"}
    assert body["plan_state"] == "baseline"
    # name y duration no se escribieron
    writes = [w for w in fake.writes if w[0] == "apu.project.plan.line"]
    payload = writes[0][2][1]
    assert "name" not in payload
    assert "duration_days" not in payload
    assert payload["progress_pct"] == 80.0
    assert payload["actual_start"] == "2026-04-20"


def test_patch_baseline_rejects_only_plan_fields_returns_400():
    fake = FakeClient(plan_state="baseline")
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.plan_write.get_client", return_value=fake):
            r = c.patch("/projects/2/plan/lines/113", json={"name": "X"})
    assert r.status_code == 400
    assert "rechazados" in r.json()["detail"]


def test_patch_closed_returns_409():
    fake = FakeClient(plan_state="closed")
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.plan_write.get_client", return_value=fake):
            r = c.patch("/projects/2/plan/lines/113", json={"progress_pct": 50.0})
    assert r.status_code == 409


def test_patch_clear_actual_with_empty_string():
    fake = FakeClient(plan_state="execution")
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.plan_write.get_client", return_value=fake):
            r = c.patch("/projects/2/plan/lines/113", json={"actual_start": ""})
    assert r.status_code == 200
    payload = [w for w in fake.writes if w[0] == "apu.project.plan.line"][0][2][1]
    assert payload == {"actual_start": False}  # "" → False (limpia el campo)


# ── POST /unlock ─────────────────────────────────────────────────────────

def test_unlock_baseline_to_draft():
    fake = FakeClient(plan_state="baseline")
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.plan_write.get_client", return_value=fake):
            r = c.post("/projects/2/plan/unlock")
    assert r.status_code == 200, r.text
    assert r.json() == {"plan_id": 11, "previous_state": "baseline", "new_state": "draft"}
    assert fake.plan_state == "draft"


def test_unlock_already_draft_returns_409():
    fake = FakeClient(plan_state="draft")
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.plan_write.get_client", return_value=fake):
            r = c.post("/projects/2/plan/unlock")
    assert r.status_code == 409
