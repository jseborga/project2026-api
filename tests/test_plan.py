"""Tests del endpoint /projects/{id}/plan."""

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
    def __init__(self, data):
        self.data = data
        self.calls = []

    def search_read(self, model, domain, fields, *, login, password_or_key, **kwargs):
        self.calls.append((model, domain))
        return self.data.get(model, [])

    def read(self, model, ids, fields, *, login, password_or_key, **kwargs):
        self.calls.append((model, "read", tuple(ids)))
        return [r for r in self.data.get(model, []) if r["id"] in set(ids)]


def test_plan_requires_auth():
    with TestClient(app) as client:
        r = client.get("/projects/2/plan")
        assert r.status_code == 401


def test_plan_404_when_no_access():
    fake = FakeClient({"project.project": []})
    with TestClient(app) as client:
        _auth(client)
        with patch("app.api.plan.get_client", return_value=fake):
            r = client.get("/projects/999/plan")
    assert r.status_code == 404


def test_plan_404_when_no_active_plan():
    fake = FakeClient({"project.project": [{"id": 5, "apu_active_plan_id": False}]})
    with TestClient(app) as client:
        _auth(client)
        with patch("app.api.plan.get_client", return_value=fake):
            r = client.get("/projects/5/plan")
    assert r.status_code == 404
    assert "plan APU activo" in r.json()["detail"]


def test_plan_returns_full_payload():
    fake = FakeClient({
        "project.project": [{"id": 2, "apu_active_plan_id": [11, "Plan V1"]}],
        "apu.project.plan": [{
            "id": 11, "name": "Plan V1",
            "project_id": [2, "Analisis Patologico BCP"],
            "company_id": [2, "SSA"], "currency_id": [62, "BOB"],
            "active": True, "state": "baseline",
            "baseline_date": "2026-04-13",
            "baseline_locked_at": "2026-04-14 01:04:18",
            "baseline_locked_by_id": [2, "Administrator"],
            "control_period_mode": "week", "crew_count": 8,
            "critical_activity_count": 2, "execution_ready": False,
            "execution_readiness_pct": 0.0, "earned_amount": 701.53,
        }],
        "apu.project.plan.line": [
            {"id": 113, "name": "Actividades Previas", "code": "G01", "parent_id": False,
             "level": 1, "sequence": 10, "duration_days": 8,
             "generic_start_day": 1, "generic_finish_day": 8,
             "early_start_day": 1, "early_finish_day": 8,
             "late_start_day": 1, "late_finish_day": 8,
             "actual_start": False, "actual_finish": False, "progress_pct": 0.0,
             "is_critical": False, "milestone_category": False,
             "labor_crew_id": False, "equipment_crew_id": False},
            {"id": 114, "name": "Instalacion de Faenas", "code": "1",
             "parent_id": [113, "G01 Actividades Previas"], "level": 2,
             "sequence": 20, "duration_days": 3,
             "generic_start_day": 1, "generic_finish_day": 3,
             "early_start_day": 1, "early_finish_day": 3,
             "late_start_day": 1, "late_finish_day": 3,
             "actual_start": False, "actual_finish": False, "progress_pct": 0.0,
             "is_critical": False, "milestone_category": False,
             "labor_crew_id": [3, "Cuadrilla MO 1"],
             "equipment_crew_id": False},
        ],
        "apu.project.plan.link": [
            {"id": 70, "predecessor_line_id": [114, "[1] Instalacion"],
             "successor_line_id": [115, "[2] Picado"],
             "link_type": "fs", "lag_days": -1},
        ],
    })

    with TestClient(app) as client:
        _auth(client, company_id=2, allowed=[1, 2])
        with patch("app.api.plan.get_client", return_value=fake):
            r = client.get("/projects/2/plan")

    assert r.status_code == 200, r.text
    body = r.json()

    # Plan header
    assert body["plan"]["id"] == 11
    assert body["plan"]["baseline_locked"] is True
    assert body["plan"]["baseline_locked_by"] == {"id": 2, "name": "Administrator"}
    assert body["plan"]["currency"] == {"id": 62, "name": "BOB"}
    assert body["plan"]["control_period_mode"] == "week"
    assert body["plan"]["state"] == "baseline"

    # Lines
    assert len(body["lines"]) == 2
    group = body["lines"][0]
    assert group["level"] == 1 and group["parent_id"] is None
    activity = body["lines"][1]
    assert activity["level"] == 2 and activity["parent_id"] == 113
    assert activity["labor_crew"] == {"id": 3, "name": "Cuadrilla MO 1"}

    # Links
    assert body["links"] == [{"id": 70, "from_line": 114, "to_line": 115, "type": "fs", "lag_days": -1}]
