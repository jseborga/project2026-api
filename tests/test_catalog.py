"""Tests del endpoint /projects/{id}/catalog."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.security import make_token
from app.main import app


def _auth(client: TestClient, *, company_id: int = 2, allowed: list[int] | None = None) -> None:
    token = make_token({
        "uid": 99,
        "login": "test@example.com",
        "key": "test-key",
        "company_id": company_id,
        "allowed_company_ids": allowed or [company_id],
    })
    client.cookies.set("tramo_session", token)


class FakeClient:
    """Mock de OdooClient: devuelve datos por modelo según .data."""

    def __init__(self, data: dict[str, list[dict]]):
        self.data = data
        self.calls: list[tuple] = []

    def search_read(self, model, domain, fields, *, login, password_or_key, **kwargs):
        self.calls.append((model, domain, tuple(fields)))
        return self.data.get(model, [])

    def read(self, model, ids, fields, *, login, password_or_key, **kwargs):
        self.calls.append((model, "read", tuple(ids)))
        records = self.data.get(model, [])
        idset = set(ids)
        return [r for r in records if r["id"] in idset]


def test_catalog_requires_auth():
    with TestClient(app) as client:
        r = client.get("/projects/2/catalog")
        assert r.status_code == 401


def test_catalog_404_when_project_inaccesible():
    fake = FakeClient({"project.project": []})  # vacío = sin acceso
    with TestClient(app) as client:
        _auth(client)
        with patch("app.api.catalog.get_client", return_value=fake):
            r = client.get("/projects/999/catalog")
    assert r.status_code == 404


def test_catalog_returns_grouped_payload():
    fake = FakeClient({
        "project.project": [{"id": 2}],
        "apu.rubro": [
            {"id": 6, "name": "Actividades Previas", "sequence": 10, "item_count": 3,
             "total_amount": 19504.24, "incidence_pct": 22.8},
            {"id": 7, "name": "Obra Fina", "sequence": 10, "item_count": 5,
             "total_amount": 53982.38, "incidence_pct": 63.1},
        ],
        "apu.item": [
            {"id": 30, "name": "PICADO DE CERAMICA", "rubro_id": [6, "Actividades Previas"],
             "sequence": 10, "uom": "m2", "cantidad_contrato": 23.1,
             "costo_directo": 32.81, "precio_referencia": 64.53, "actual_total_cost": 0.0,
             "incidence_pct": 1.66, "is_complementary": False, "line_ids": [101, 102]},
            {"id": 26, "name": "REVOQUE", "rubro_id": [7, "Obra Fina"],
             "sequence": 10, "uom": "m2", "cantidad_contrato": 158.73,
             "costo_directo": 70.43, "precio_referencia": 130.44, "actual_total_cost": 0.0,
             "incidence_pct": 22.16, "is_complementary": False, "line_ids": []},
        ],
        "apu.line": [
            {"id": 101, "apu_id": [30, "PICADO DE CERAMICA"], "insumo_id": [60, "ARENA FINA"],
             "type": "mat", "quantity": 0.05, "uom": "m3", "price_unit": 185.0,
             "price_subtotal": 9.25, "notes": False},
            {"id": 102, "apu_id": [30, "PICADO DE CERAMICA"], "insumo_id": [70, "Albañil"],
             "type": "mo", "quantity": 0.5, "uom": "h", "price_unit": 25.0,
             "price_subtotal": 12.5, "notes": False},
        ],
        "apu.insumo": [
            {"id": 59, "name": "CAMION VOLQUETA", "type": "eq", "uom": "h",
             "price_unit": 110.0, "total_qty_budget": 16.0, "total_amount_budget": 1760.0,
             "linked_item_id": False, "odoo_product_id": [55, "Camión 10m³"]},
            {"id": 41, "name": "AGROFILM", "type": "mat", "uom": "m2",
             "price_unit": 10.91, "total_qty_budget": 0.0, "total_amount_budget": 0.0,
             "linked_item_id": False, "odoo_product_id": False},
        ],
    })

    with TestClient(app) as client:
        _auth(client, company_id=2, allowed=[1, 2])
        with patch("app.api.catalog.get_client", return_value=fake):
            r = client.get("/projects/2/catalog")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"] == 2
    assert len(body["rubros"]) == 2
    assert body["rubros"][0]["name"] == "Actividades Previas"
    assert len(body["items"]) == 2
    it = body["items"][0]
    assert it["rubro"] == {"id": 6, "name": "Actividades Previas"}
    assert it["uom"] == "m2"
    assert it["qty"] == 23.1
    assert len(body["insumos"]) == 2
    assert body["insumos"][0]["type"] == "eq"
    assert body["insumos"][0]["odoo_product"] == {"id": 55, "name": "Camión 10m³"}
    assert body["insumos"][1]["odoo_product"] is None

    # Verifica que se llamaron los 5 modelos correctos
    models = [c[0] for c in fake.calls]
    assert "project.project" in models
    assert "apu.rubro" in models
    assert "apu.item" in models
    assert "apu.insumo" in models
    assert "apu.line" in models  # batch read

    # El item con líneas las trae con su composición de costo
    item_with_lines = next(it for it in body["items"] if it["id"] == 30)
    assert len(item_with_lines["lines"]) == 2
    types = {ln["type"] for ln in item_with_lines["lines"]}
    assert types == {"mat", "mo"}
    assert item_with_lines["lines"][0]["insumo"]["name"] == "ARENA FINA"
    # Item sin líneas
    item_no_lines = next(it for it in body["items"] if it["id"] == 26)
    assert item_no_lines["lines"] == []
