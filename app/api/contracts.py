"""Contratos del proyecto: purchase orders (subcontratos).

Sale orders se omiten porque el módulo `sale` no está instalado en el Odoo
del usuario. Si en el futuro se instala, agregar lectura de sale.order acá.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.projects import Ref
from app.core.odoo import OdooError, get_client
from app.core.security import current_session

router = APIRouter(prefix="/projects/{project_id}/contracts", tags=["contracts"])


class POLine(BaseModel):
    id: int
    name: str
    product: Ref | None
    uom: Ref | None
    qty: float
    qty_received: float
    qty_invoiced: float
    price_unit: float
    subtotal: float
    total: float
    date_planned: str | None


class PurchaseOrderOut(BaseModel):
    id: int
    name: str
    partner: Ref | None
    partner_ref: str | None
    state: str            # draft|sent|to approve|purchase|done|cancel
    invoice_status: str   # no|to invoice|invoiced|partial
    date_order: str | None
    date_planned: str | None
    currency: Ref | None
    amount_untaxed: float
    amount_total: float
    origin: str | None
    lines: list[POLine]


class ContractsOut(BaseModel):
    project_id: int
    purchase_orders: list[PurchaseOrderOut]
    sale_orders_supported: bool   # false en este Odoo (sin módulo sale)


PO_FIELDS = [
    "id", "name", "partner_id", "partner_ref",
    "state", "invoice_status",
    "date_order", "date_planned",
    "currency_id", "amount_untaxed", "amount_total",
    "origin", "order_line",
]

POL_FIELDS = [
    "id", "name", "product_id", "product_uom",
    "product_qty", "qty_received", "qty_invoiced",
    "price_unit", "price_subtotal", "price_total",
    "date_planned", "order_id",
]


def _check_project(client, session, project_id: int) -> None:
    rec = client.search_read(
        "project.project",
        [["id", "=", project_id], ["company_id", "in", session["allowed_company_ids"]]],
        ["id"],
        login=session["login"], password_or_key=session["key"],
        limit=1,
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado o sin acceso")


def _check_sale_module(client, session) -> bool:
    """Devuelve True si sale.order existe (módulo `sale` instalado)."""
    try:
        rows = client.search_read(
            "ir.module.module",
            [["name", "=", "sale_management"], ["state", "=", "installed"]],
            ["id"],
            login=session["login"], password_or_key=session["key"],
            limit=1,
        )
        return bool(rows)
    except OdooError:
        return False


@router.get("", response_model=ContractsOut)
def get_contracts(project_id: int, session=Depends(current_session)):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado")

    try:
        _check_project(client, session, project_id)

        pos_raw = client.search_read(
            "purchase.order",
            [["project_id", "=", project_id]],
            PO_FIELDS,
            login=session["login"], password_or_key=session["key"],
            order="date_order desc, id desc",
        )

        # Lectura batch de líneas para todas las POs encontradas
        all_line_ids: list[int] = []
        for po in pos_raw:
            all_line_ids.extend(po.get("order_line") or [])
        lines_by_id: dict[int, dict] = {}
        if all_line_ids:
            lines = client.read(
                "purchase.order.line", all_line_ids, POL_FIELDS,
                login=session["login"], password_or_key=session["key"],
            )
            lines_by_id = {ln["id"]: ln for ln in lines}

        sale_supported = _check_sale_module(client, session)
    except OdooError as e:
        raise HTTPException(status_code=502, detail=f"Odoo: {e}")

    pos_out = []
    for po in pos_raw:
        po_lines = []
        for ln_id in (po.get("order_line") or []):
            ln = lines_by_id.get(ln_id)
            if not ln:
                continue
            po_lines.append(POLine(
                id=ln["id"],
                name=ln.get("name") or "",
                product=Ref.from_pair(ln.get("product_id")),
                uom=Ref.from_pair(ln.get("product_uom")),
                qty=ln.get("product_qty") or 0.0,
                qty_received=ln.get("qty_received") or 0.0,
                qty_invoiced=ln.get("qty_invoiced") or 0.0,
                price_unit=ln.get("price_unit") or 0.0,
                subtotal=ln.get("price_subtotal") or 0.0,
                total=ln.get("price_total") or 0.0,
                date_planned=str(ln.get("date_planned")) if ln.get("date_planned") else None,
            ))
        pos_out.append(PurchaseOrderOut(
            id=po["id"],
            name=po.get("name") or "",
            partner=Ref.from_pair(po.get("partner_id")),
            partner_ref=po.get("partner_ref") or None,
            state=po.get("state") or "draft",
            invoice_status=po.get("invoice_status") or "no",
            date_order=str(po.get("date_order")) if po.get("date_order") else None,
            date_planned=str(po.get("date_planned")) if po.get("date_planned") else None,
            currency=Ref.from_pair(po.get("currency_id")),
            amount_untaxed=po.get("amount_untaxed") or 0.0,
            amount_total=po.get("amount_total") or 0.0,
            origin=po.get("origin") or None,
            lines=po_lines,
        ))

    return ContractsOut(
        project_id=project_id,
        purchase_orders=pos_out,
        sale_orders_supported=sale_supported,
    )
