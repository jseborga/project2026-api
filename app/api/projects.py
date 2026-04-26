from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.odoo import OdooError, get_client
from app.core.security import current_session

router = APIRouter(prefix="/projects", tags=["projects"])


class Ref(BaseModel):
    """Representación normalizada de un campo many2one de Odoo `[id, name]`."""

    id: int
    name: str

    @classmethod
    def from_pair(cls, value: list | bool | None) -> "Ref | None":
        if not value or value is False:
            return None
        return cls(id=value[0], name=value[1])


class ProjectOut(BaseModel):
    id: int
    name: str
    partner: Ref | None
    company: Ref | None
    currency: Ref | None
    manager: Ref | None
    analytic_account: Ref | None
    active_plan: Ref | None
    date_start: str | None
    date_end: str | None
    actual_total_cost: float | None
    actual_margin_pct: float | None
    execution_readiness_pct: float | None
    execution_ready: bool | None


PROJECT_FIELDS = [
    "id", "name",
    "partner_id", "company_id", "currency_id", "user_id",
    "account_id", "apu_active_plan_id",
    "date_start", "date",
    "apu_actual_total_cost", "apu_actual_margin_pct",
    "apu_execution_readiness_pct", "apu_execution_ready",
]


def _to_out(rec: dict) -> ProjectOut:
    return ProjectOut(
        id=rec["id"],
        name=rec.get("name") or "",
        partner=Ref.from_pair(rec.get("partner_id")),
        company=Ref.from_pair(rec.get("company_id")),
        currency=Ref.from_pair(rec.get("currency_id")),
        manager=Ref.from_pair(rec.get("user_id")),
        analytic_account=Ref.from_pair(rec.get("account_id")),
        active_plan=Ref.from_pair(rec.get("apu_active_plan_id")),
        date_start=rec.get("date_start") or None,
        date_end=rec.get("date") or None,
        actual_total_cost=rec.get("apu_actual_total_cost"),
        actual_margin_pct=rec.get("apu_actual_margin_pct"),
        execution_readiness_pct=rec.get("apu_execution_readiness_pct"),
        execution_ready=rec.get("apu_execution_ready"),
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(
    session=Depends(current_session),
    only_active: bool = Query(True, description="Filtrar solo proyectos activos"),
    search: str | None = Query(None, min_length=1, description="Filtra por nombre (ilike)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado")

    domain: list = [["company_id", "=", session["company_id"]]]
    if only_active:
        domain.append(["active", "=", True])
    if search:
        domain.append(["name", "ilike", search])

    try:
        records = client.search_read(
            "project.project",
            domain,
            PROJECT_FIELDS,
            login=session["login"],
            password_or_key=session["key"],
            limit=limit,
            offset=offset,
            order="name asc",
            context={"allowed_company_ids": session["allowed_company_ids"]},
        )
    except OdooError as e:
        raise HTTPException(status_code=502, detail=f"Odoo: {e}")

    return [_to_out(r) for r in records]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, session=Depends(current_session)):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado")

    try:
        records = client.search_read(
            "project.project",
            [["id", "=", project_id], ["company_id", "in", session["allowed_company_ids"]]],
            PROJECT_FIELDS,
            login=session["login"],
            password_or_key=session["key"],
            limit=1,
            context={"allowed_company_ids": session["allowed_company_ids"]},
        )
    except OdooError as e:
        raise HTTPException(status_code=502, detail=f"Odoo: {e}")

    if not records:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado o sin acceso")
    return _to_out(records[0])
