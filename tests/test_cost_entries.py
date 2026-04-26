"""Tests del endpoint /projects/{id}/cost-entries."""

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
    def __init__(self, data=None):
        self.data = data or {}
        self.created: list[dict] = []
        self.deleted: list[int] = []

    def search_read(self, model, domain, fields, *, login, password_or_key, **kwargs):
        if model == "project.project":
            return [{"id": 2}]
        if model == "apu.item":
            return [{"id": 22}]
        if model == "apu.cost.entry":
            return self.data.get("entries", [])
        return []

    def read(self, model, ids, fields, *, login, password_or_key, **kwargs):
        if model == "apu.insumo":
            return [{"id": ids[0], "type": "mat", "project_id": [2, "Test"]}]
        if model == "apu.cost.entry":
            entries = self.data.get("entries", [])
            return [e for e in entries if e["id"] in set(ids)]
        return []

    def execute_kw(self, model, method, args, kwargs=None, *, login, password_or_key):
        if model == "apu.cost.entry" and method == "create":
            payload = args[0]
            self.created.append(dict(payload))  # snapshot del payload original
            # Simular respuesta Odoo: many2one fields se vuelven [id, "name"]
            stored = dict(payload)
            stored["id"] = 999
            for fk in ["apu_item_id", "insumo_id", "partner_id", "employee_id"]:
                if isinstance(stored.get(fk), int):
                    stored[fk] = [stored[fk], f"#{stored[fk]}"]
            stored["amount"] = payload.get("quantity", 0) * payload.get("unit_cost", 0)
            stored["counts_as_actual"] = True
            stored["auto_generated"] = False
            self.data.setdefault("entries", []).append(stored)
            return 999
        if model == "apu.cost.entry" and method == "unlink":
            self.deleted.extend(args[0])
            self.data["entries"] = [e for e in self.data.get("entries", []) if e["id"] not in args[0]]
            return True
        return True


def test_list_requires_auth():
    with TestClient(app) as c:
        r = c.get("/projects/2/cost-entries")
        assert r.status_code == 401


def test_list_returns_entries():
    fake = FakeClient(data={"entries": [
        {"id": 1, "name": "Test", "date": "2026-04-26", "cost_stage": "manual",
         "resource_type": "mat", "apu_item_id": [22, "Faenas"], "insumo_id": False,
         "partner_id": False, "employee_id": False,
         "quantity": 1.0, "unit_cost": 500.0, "amount": 500.0, "notes": False,
         "auto_generated": False, "counts_as_actual": True},
    ]})
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.cost_entries.get_client", return_value=fake):
            r = c.get("/projects/2/cost-entries")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["amount"] == 500.0
    assert body[0]["apu_item"] == {"id": 22, "name": "Faenas"}


def test_create_minimal():
    fake = FakeClient()
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.cost_entries.get_client", return_value=fake):
            r = c.post("/projects/2/cost-entries", json={
                "name": "Cemento usado en zapata Z-12",
                "apu_item_id": 22,
                "insumo_id": 41,
                "quantity": 50,
                "unit_cost": 1.66,
            })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["amount"] == 50 * 1.66
    assert body["cost_stage"] == "manual"
    # resource_type derivado del insumo (mock devuelve 'mat')
    assert body["resource_type"] == "mat"
    # Verifica payload enviado a create
    assert len(fake.created) == 1
    payload = fake.created[0]
    assert payload["project_id"] == 2
    assert payload["cost_stage"] == "manual"
    assert payload["apu_item_id"] == 22
    assert payload["insumo_id"] == 41
    assert "date" in payload  # default = today


def test_create_rejects_item_from_other_project():
    """item validation: si search_read de apu.item devuelve vacío → 400."""
    class FakeNoItem(FakeClient):
        def search_read(self, model, *args, **kwargs):
            if model == "apu.item":
                return []
            return super().search_read(model, *args, **kwargs)
    fake = FakeNoItem()
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.cost_entries.get_client", return_value=fake):
            r = c.post("/projects/2/cost-entries", json={
                "name": "X", "apu_item_id": 9999, "quantity": 1, "unit_cost": 1,
            })
    assert r.status_code == 400
    assert "no pertenece" in r.json()["detail"]


def test_delete_manual_entry():
    fake = FakeClient(data={"entries": [
        {"id": 5, "cost_stage": "manual", "auto_generated": False},
    ]})
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.cost_entries.get_client", return_value=fake):
            r = c.delete("/projects/2/cost-entries/5")
    assert r.status_code == 204
    assert 5 in fake.deleted


def test_delete_autogenerated_returns_409():
    fake = FakeClient(data={"entries": [
        {"id": 7, "cost_stage": "purchase", "auto_generated": True},
    ]})
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.cost_entries.get_client", return_value=fake):
            r = c.delete("/projects/2/cost-entries/7")
    assert r.status_code == 409
