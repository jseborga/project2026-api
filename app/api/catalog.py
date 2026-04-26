"""Catálogo APU del proyecto: rubros + ítems + insumos en una sola call.

La UI los muestra juntos (tabla items agrupada por rubro, panel insumos
opcional). Devolverlos en un endpoint reduce ida-vuelta y simplifica el
cache del lado cliente.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.projects import Ref
from app.core.odoo import OdooError, get_client
from app.core.security import current_session

router = APIRouter(prefix="/projects/{project_id}/catalog", tags=["catalog"])


class RubroOut(BaseModel):
    id: int
    name: str
    sequence: int
    item_count: int
    total_amount: float
    incidence_pct: float


class LineOut(BaseModel):
    """Una `apu.line`: insumo dentro de un item APU (descompone el costo directo)."""
    id: int
    insumo: Ref | None
    type: str  # mat | mo | eq | sub
    quantity: float
    uom: str | None
    price_unit: float
    subtotal: float
    notes: str | None


class ItemOut(BaseModel):
    id: int
    name: str
    rubro: Ref | None
    sequence: int
    uom: str | None
    qty: float
    unit_cost: float
    ref_price: float
    actual_cost: float
    incidence_pct: float
    is_complementary: bool
    lines: list[LineOut]


class InsumoOut(BaseModel):
    id: int
    name: str
    type: str  # mat | mo | eq | sub
    uom: str | None
    price_unit: float
    total_qty: float
    total_amount: float
    linked_item: Ref | None
    odoo_product: Ref | None


class CatalogOut(BaseModel):
    project_id: int
    rubros: list[RubroOut]
    items: list[ItemOut]
    insumos: list[InsumoOut]


def _check_project_access(client, session, project_id: int) -> None:
    """Verifica que el proyecto exista y esté en empresas permitidas."""
    rec = client.search_read(
        "project.project",
        [["id", "=", project_id], ["company_id", "in", session["allowed_company_ids"]]],
        ["id"],
        login=session["login"],
        password_or_key=session["key"],
        limit=1,
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado o sin acceso")


@router.get("", response_model=CatalogOut)
def get_catalog(project_id: int, session=Depends(current_session)):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado")

    try:
        _check_project_access(client, session, project_id)

        rubros_raw = client.search_read(
            "apu.rubro",
            [["project_id", "=", project_id]],
            ["id", "name", "sequence", "item_count", "total_amount", "incidence_pct"],
            login=session["login"],
            password_or_key=session["key"],
            order="sequence asc, name asc",
        )

        items_raw = client.search_read(
            "apu.item",
            [["project_id", "=", project_id]],
            ["id", "name", "rubro_id", "sequence", "uom",
             "cantidad_contrato", "costo_directo", "precio_referencia",
             "actual_total_cost", "incidence_pct", "is_complementary",
             "line_ids"],
            login=session["login"],
            password_or_key=session["key"],
            order="rubro_id asc, sequence asc, name asc",
        )

        # Lectura batch de TODAS las líneas (apu.line) de los items del proyecto
        all_line_ids: list[int] = []
        for it in items_raw:
            all_line_ids.extend(it.get("line_ids") or [])
        lines_by_id: dict[int, dict] = {}
        if all_line_ids:
            lines_raw = client.read(
                "apu.line",
                all_line_ids,
                ["id", "apu_id", "insumo_id", "type", "quantity",
                 "uom", "price_unit", "price_subtotal", "notes"],
                login=session["login"],
                password_or_key=session["key"],
            )
            lines_by_id = {ln["id"]: ln for ln in lines_raw}

        insumos_raw = client.search_read(
            "apu.insumo",
            [["project_id", "=", project_id]],
            ["id", "name", "type", "uom", "price_unit",
             "total_qty_budget", "total_amount_budget",
             "linked_item_id", "odoo_product_id"],
            login=session["login"],
            password_or_key=session["key"],
            order="type asc, name asc",
        )
    except OdooError as e:
        raise HTTPException(status_code=502, detail=f"Odoo: {e}")

    return CatalogOut(
        project_id=project_id,
        rubros=[
            RubroOut(
                id=r["id"], name=r["name"], sequence=r.get("sequence") or 0,
                item_count=r.get("item_count") or 0,
                total_amount=r.get("total_amount") or 0.0,
                incidence_pct=r.get("incidence_pct") or 0.0,
            ) for r in rubros_raw
        ],
        items=[
            ItemOut(
                id=it["id"], name=it["name"],
                rubro=Ref.from_pair(it.get("rubro_id")),
                sequence=it.get("sequence") or 0,
                uom=it.get("uom") or None,
                qty=it.get("cantidad_contrato") or 0.0,
                unit_cost=it.get("costo_directo") or 0.0,
                ref_price=it.get("precio_referencia") or 0.0,
                actual_cost=it.get("actual_total_cost") or 0.0,
                incidence_pct=it.get("incidence_pct") or 0.0,
                is_complementary=bool(it.get("is_complementary")),
                lines=[
                    LineOut(
                        id=ln["id"],
                        insumo=Ref.from_pair(ln.get("insumo_id")),
                        type=ln.get("type") or "mat",
                        quantity=ln.get("quantity") or 0.0,
                        uom=ln.get("uom") or None,
                        price_unit=ln.get("price_unit") or 0.0,
                        subtotal=ln.get("price_subtotal") or 0.0,
                        notes=ln.get("notes") or None,
                    )
                    for ln_id in (it.get("line_ids") or [])
                    if (ln := lines_by_id.get(ln_id)) is not None
                ],
            ) for it in items_raw
        ],
        insumos=[
            InsumoOut(
                id=i["id"], name=i["name"],
                type=i.get("type") or "mat",
                uom=i.get("uom") or None,
                price_unit=i.get("price_unit") or 0.0,
                total_qty=i.get("total_qty_budget") or 0.0,
                total_amount=i.get("total_amount_budget") or 0.0,
                linked_item=Ref.from_pair(i.get("linked_item_id")),
                odoo_product=Ref.from_pair(i.get("odoo_product_id")),
            ) for i in insumos_raw
        ],
    )
