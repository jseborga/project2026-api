"""Endpoints de escritura del plan (Fase 4).

- PATCH /projects/{id}/plan/lines/{line_id}
  Update de campos de una línea. Respeta el state-machine de apu.project.plan:
  · state == 'draft'  → todos los campos editables (incluido name, dates, duration)
  · state ∈ {baseline, approved, execution} → solo "actuals" (progress_pct,
    actual_start, actual_finish) — la baseline contractual queda intacta
  · state == 'closed' → 409 Conflict (read-only)

- POST /projects/{id}/plan/unlock
  Vuelve el plan a 'draft' (escribe el campo state directamente).
  Esto es un escape hatch — el flujo idiomático en Odoo es no salir de
  baseline, pero el state field es escribible y a veces hace falta.
"""

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.odoo import OdooError, get_client
from app.core.security import current_session

router = APIRouter(prefix="/projects/{project_id}/plan", tags=["plan-write"])


# Campos siempre editables (datos de ejecución, no afectan baseline contractual)
ACTUALS_FIELDS = {"progress_pct", "actual_start", "actual_finish"}

# Campos que solo se pueden tocar en state='draft'
PLAN_FIELDS = {
    "name", "code", "duration_days",
    "generic_start_day", "generic_finish_day",
    "labor_crew_units", "equipment_crew_units",
    "milestone_category",
}

ALLOWED_FIELDS = ACTUALS_FIELDS | PLAN_FIELDS


class LinePatchIn(BaseModel):
    """Body parcial — solo los campos que se quieren cambiar.

    Usar None / no incluirlos los deja igual. Para limpiar una fecha real,
    pasar string vacío "" (que se convierte a False en Odoo).
    """
    name: str | None = None
    code: str | None = None
    duration_days: int | None = Field(default=None, ge=0)
    generic_start_day: int | None = Field(default=None, ge=1)
    generic_finish_day: int | None = Field(default=None, ge=1)
    progress_pct: float | None = Field(default=None, ge=0, le=100)
    actual_start: str | None = None
    actual_finish: str | None = None


class LinePatchOut(BaseModel):
    id: int
    updated: list[str]
    plan_state: str


def _get_plan_state(client, session, plan_id: int) -> str:
    """Lee el state del plan (cabecera). Lanza 404 si no existe / sin acceso."""
    rows = client.search_read(
        "apu.project.plan",
        [["id", "=", plan_id], ["company_id", "in", session["allowed_company_ids"]]],
        ["id", "state"],
        login=session["login"],
        password_or_key=session["key"],
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Plan no encontrado o sin acceso")
    return rows[0].get("state") or "draft"


def _resolve_active_plan_id(client, session, project_id: int) -> int:
    """Encuentra el plan activo del proyecto + valida acceso por compañía."""
    proj = client.search_read(
        "project.project",
        [["id", "=", project_id], ["company_id", "in", session["allowed_company_ids"]]],
        ["id", "apu_active_plan_id"],
        login=session["login"],
        password_or_key=session["key"],
        limit=1,
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado o sin acceso")
    plan_ref = proj[0].get("apu_active_plan_id")
    if not plan_ref:
        raise HTTPException(status_code=404, detail="Este proyecto no tiene plan APU activo")
    return plan_ref[0]


@router.patch("/lines/{line_id}", response_model=LinePatchOut)
def update_line(
    project_id: int,
    line_id: int,
    body: LinePatchIn = Body(...),
    session=Depends(current_session),
):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado")

    try:
        plan_id = _resolve_active_plan_id(client, session, project_id)
        state = _get_plan_state(client, session, plan_id)

        # Verifica que la línea pertenece a ese plan
        ln = client.search_read(
            "apu.project.plan.line",
            [["id", "=", line_id], ["plan_id", "=", plan_id]],
            ["id"],
            login=session["login"], password_or_key=session["key"],
            limit=1,
        )
        if not ln:
            raise HTTPException(status_code=404, detail="Línea no encontrada en este plan")

        if state == "closed":
            raise HTTPException(status_code=409, detail="El plan está cerrado: read-only")

        # Filtrar campos según state
        proposed = body.model_dump(exclude_unset=True, exclude_none=False)
        # Nota: exclude_unset=True omite los que no llegaron en JSON; los None que
        # SÍ vinieron quedan (pero los limpiamos abajo si no son actuals que
        # acepten None).

        write_payload: dict = {}
        rejected: list[str] = []
        for key, val in proposed.items():
            if key not in ALLOWED_FIELDS:
                rejected.append(key)
                continue
            if state != "draft" and key in PLAN_FIELDS:
                rejected.append(key)
                continue
            # Convertir "" → False para fechas (limpiar)
            if val == "" and key in {"actual_start", "actual_finish"}:
                write_payload[key] = False
            elif val is not None:
                write_payload[key] = val

        if not write_payload:
            detail = "No hay campos para actualizar"
            if rejected:
                detail += f" (rechazados por state='{state}': {', '.join(rejected)})"
            raise HTTPException(status_code=400, detail=detail)

        client.execute_kw(
            "apu.project.plan.line", "write",
            [[line_id], write_payload],
            login=session["login"], password_or_key=session["key"],
        )
    except OdooError as e:
        raise HTTPException(status_code=502, detail=f"Odoo: {e}")

    return LinePatchOut(id=line_id, updated=list(write_payload.keys()), plan_state=state)


class UnlockOut(BaseModel):
    plan_id: int
    previous_state: str
    new_state: str


@router.post("/unlock", response_model=UnlockOut)
def unlock_plan(project_id: int, session=Depends(current_session)):
    """Vuelve el plan a state='draft'.

    Atajo para destrabar la edición estructural. Equivale a despublicar la
    baseline. Quien lo usa asume responsabilidad — Odoo no provee un botón
    estándar para esto (la baseline se considera contractual).
    """
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado")

    try:
        plan_id = _resolve_active_plan_id(client, session, project_id)
        previous_state = _get_plan_state(client, session, plan_id)

        if previous_state == "draft":
            raise HTTPException(status_code=409, detail="El plan ya está en borrador")

        client.execute_kw(
            "apu.project.plan", "write",
            [[plan_id], {"state": "draft"}],
            login=session["login"], password_or_key=session["key"],
        )
    except OdooError as e:
        raise HTTPException(status_code=502, detail=f"Odoo: {e}")

    return UnlockOut(plan_id=plan_id, previous_state=previous_state, new_state="draft")
