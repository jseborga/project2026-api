"""apu.cost.entry — registro de consumo manual del proyecto.

Crea entries con cost_stage='manual' (los stages purchase/bill/cash los crea
Odoo automático desde POs/bills/caja). resource_type debe coincidir con el
type del insumo (mat/mo/eq/sub) o ser 'oh' (overhead).
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.projects import Ref
from app.core.odoo import OdooError, get_client
from app.core.security import current_session

router = APIRouter(prefix="/projects/{project_id}/cost-entries", tags=["cost-entries"])


class CostEntryOut(BaseModel):
    id: int
    name: str
    date: str
    cost_stage: str           # manual | purchase | bill | cash
    resource_type: str        # mat | mo | eq | sub | oh
    apu_item: Ref | None
    insumo: Ref | None
    partner: Ref | None
    employee: Ref | None
    quantity: float
    unit_cost: float
    amount: float
    notes: str | None
    auto_generated: bool
    counts_as_actual: bool


class CostEntryCreate(BaseModel):
    name: str = Field(..., min_length=1)
    date: str | None = None  # default hoy si no se manda
    apu_item_id: int                                # required: contra qué APU se imputa
    insumo_id: int | None = None
    partner_id: int | None = None
    employee_id: int | None = None
    quantity: float = Field(..., ge=0)
    unit_cost: float = Field(..., ge=0)
    resource_type: str | None = None  # mat|mo|eq|sub|oh; si None, se deduce del insumo
    notes: str | None = None


CE_FIELDS = [
    "id", "name", "date", "project_id",
    "cost_stage", "resource_type",
    "apu_item_id", "insumo_id", "partner_id", "employee_id",
    "quantity", "unit_cost", "amount", "notes",
    "auto_generated", "counts_as_actual",
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


def _to_out(rec: dict) -> CostEntryOut:
    return CostEntryOut(
        id=rec["id"], name=rec.get("name") or "",
        date=rec.get("date") or "",
        cost_stage=rec.get("cost_stage") or "manual",
        resource_type=rec.get("resource_type") or "mat",
        apu_item=Ref.from_pair(rec.get("apu_item_id")),
        insumo=Ref.from_pair(rec.get("insumo_id")),
        partner=Ref.from_pair(rec.get("partner_id")),
        employee=Ref.from_pair(rec.get("employee_id")),
        quantity=rec.get("quantity") or 0.0,
        unit_cost=rec.get("unit_cost") or 0.0,
        amount=rec.get("amount") or 0.0,
        notes=rec.get("notes") or None,
        auto_generated=bool(rec.get("auto_generated")),
        counts_as_actual=bool(rec.get("counts_as_actual")),
    )


@router.get("", response_model=list[CostEntryOut])
def list_cost_entries(
    project_id: int,
    session=Depends(current_session),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    only_manual: bool = Query(False, description="Filtrar solo entries cargados a mano (excluye PO/bill/cash autogenerados)"),
):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado")
    try:
        _check_project(client, session, project_id)
        domain: list = [["project_id", "=", project_id]]
        if only_manual:
            domain.append(["cost_stage", "=", "manual"])
        rows = client.search_read(
            "apu.cost.entry", domain, CE_FIELDS,
            login=session["login"], password_or_key=session["key"],
            limit=limit, offset=offset, order="date desc, id desc",
        )
    except OdooError as e:
        raise HTTPException(status_code=502, detail=f"Odoo: {e}")
    return [_to_out(r) for r in rows]


@router.post("", response_model=CostEntryOut, status_code=201)
def create_cost_entry(
    project_id: int,
    body: CostEntryCreate,
    session=Depends(current_session),
):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado")
    try:
        _check_project(client, session, project_id)

        # Validar que el item APU pertenece al proyecto
        item = client.search_read(
            "apu.item",
            [["id", "=", body.apu_item_id], ["project_id", "=", project_id]],
            ["id"],
            login=session["login"], password_or_key=session["key"],
            limit=1,
        )
        if not item:
            raise HTTPException(status_code=400, detail="apu_item_id no pertenece a este proyecto")

        # Resolver resource_type si no se mandó
        rt = body.resource_type
        if not rt and body.insumo_id:
            ins = client.read(
                "apu.insumo", [body.insumo_id], ["type", "project_id"],
                login=session["login"], password_or_key=session["key"],
            )
            if ins and ins[0].get("project_id") and ins[0]["project_id"][0] == project_id:
                rt = ins[0].get("type") or "mat"
        if not rt:
            rt = "mat"
        if rt not in {"mat", "mo", "eq", "sub", "oh"}:
            raise HTTPException(status_code=400, detail=f"resource_type inválido: {rt}")

        payload = {
            "name": body.name,
            "date": body.date or date.today().isoformat(),
            "project_id": project_id,
            "cost_stage": "manual",
            "resource_type": rt,
            "apu_item_id": body.apu_item_id,
            "quantity": body.quantity,
            "unit_cost": body.unit_cost,
        }
        if body.insumo_id is not None:
            payload["insumo_id"] = body.insumo_id
        if body.partner_id is not None:
            payload["partner_id"] = body.partner_id
        if body.employee_id is not None:
            payload["employee_id"] = body.employee_id
        if body.notes:
            payload["notes"] = body.notes

        new_id = client.execute_kw(
            "apu.cost.entry", "create", [payload],
            login=session["login"], password_or_key=session["key"],
        )

        rec = client.read(
            "apu.cost.entry", [new_id], CE_FIELDS,
            login=session["login"], password_or_key=session["key"],
        )[0]
    except OdooError as e:
        raise HTTPException(status_code=502, detail=f"Odoo: {e}")

    return _to_out(rec)


@router.delete("/{entry_id}", status_code=204)
def delete_cost_entry(
    project_id: int, entry_id: int,
    session=Depends(current_session),
):
    """Elimina un entry. Solo manual; los autogenerados (PO/bill/cash) no se tocan."""
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado")
    try:
        _check_project(client, session, project_id)
        rec = client.search_read(
            "apu.cost.entry",
            [["id", "=", entry_id], ["project_id", "=", project_id]],
            ["id", "cost_stage", "auto_generated"],
            login=session["login"], password_or_key=session["key"],
            limit=1,
        )
        if not rec:
            raise HTTPException(status_code=404, detail="Entry no encontrado en este proyecto")
        if rec[0].get("cost_stage") != "manual" or rec[0].get("auto_generated"):
            raise HTTPException(status_code=409, detail="Solo se pueden eliminar entries manuales no autogenerados")

        client.execute_kw(
            "apu.cost.entry", "unlink", [[entry_id]],
            login=session["login"], password_or_key=session["key"],
        )
    except OdooError as e:
        raise HTTPException(status_code=502, detail=f"Odoo: {e}")
