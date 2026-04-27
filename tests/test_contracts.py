"""Tests del endpoint /projects/{id}/contracts."""

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
    def __init__(self, pos=None, lines=None, sale_installed=False):
        self.pos = pos or []
        self.lines = lines or []
        self.sale_installed = sale_installed

    def search_read(self, model, domain, fields, *, login, password_or_key, **kwargs):
        if model == "project.project":
            return [{"id": 2}]
        if model == "purchase.order":
            return self.pos
        if model == "ir.module.module":
            # Si sale_management está instalado
            return [{"id": 1}] if self.sale_installed else []
        return []

    def read(self, model, ids, fields, *, login, password_or_key, **kwargs):
        if model == "purchase.order.line":
            idset = set(ids)
            return [ln for ln in self.lines if ln["id"] in idset]
        return []


def test_contracts_requires_auth():
    with TestClient(app) as c:
        r = c.get("/projects/2/contracts")
        assert r.status_code == 401


def test_contracts_empty_when_no_pos():
    fake = FakeClient()
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.contracts.get_client", return_value=fake):
            r = c.get("/projects/2/contracts")
    assert r.status_code == 200
    assert r.json() == {"project_id": 2, "purchase_orders": [], "sale_orders_supported": False}


def test_contracts_returns_pos_with_lines():
    fake = FakeClient(
        pos=[{
            "id": 11, "name": "PO/2026/00011",
            "partner_id": [55, "Subcontratista X"],
            "partner_ref": "REF-001",
            "state": "purchase", "invoice_status": "to invoice",
            "date_order": "2026-04-20 10:00:00",
            "date_planned": "2026-05-15 10:00:00",
            "currency_id": [62, "BOB"],
            "amount_untaxed": 8500.0, "amount_total": 9690.0,
            "origin": "Plan v3",
            "order_line": [101, 102],
        }],
        lines=[
            {"id": 101, "name": "Mampostería sector A",
             "product_id": [123, "Mampostería m²"], "product_uom": [1, "m²"],
             "product_qty": 100.0, "qty_received": 50.0, "qty_invoiced": 25.0,
             "price_unit": 50.0, "price_subtotal": 5000.0, "price_total": 5700.0,
             "date_planned": "2026-05-10 10:00:00", "order_id": [11, "PO/2026/00011"]},
            {"id": 102, "name": "Estructura adicional",
             "product_id": False, "product_uom": [1, "m²"],
             "product_qty": 70.0, "qty_received": 0.0, "qty_invoiced": 0.0,
             "price_unit": 50.0, "price_subtotal": 3500.0, "price_total": 3990.0,
             "date_planned": False, "order_id": [11, "PO/2026/00011"]},
        ],
        sale_installed=False,
    )
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.contracts.get_client", return_value=fake):
            r = c.get("/projects/2/contracts")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sale_orders_supported"] is False
    assert len(body["purchase_orders"]) == 1
    po = body["purchase_orders"][0]
    assert po["partner"] == {"id": 55, "name": "Subcontratista X"}
    assert po["state"] == "purchase"
    assert po["invoice_status"] == "to invoice"
    assert po["amount_total"] == 9690.0
    assert len(po["lines"]) == 2
    line1 = po["lines"][0]
    assert line1["product"] == {"id": 123, "name": "Mampostería m²"}
    assert line1["qty"] == 100.0
    assert line1["qty_received"] == 50.0
    assert line1["qty_invoiced"] == 25.0


def test_contracts_detects_sale_module_installed():
    fake = FakeClient(sale_installed=True)
    with TestClient(app) as c:
        _auth(c)
        with patch("app.api.contracts.get_client", return_value=fake):
            r = c.get("/projects/2/contracts")
    assert r.json()["sale_orders_supported"] is True
