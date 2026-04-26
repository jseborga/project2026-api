"""Plan APU del proyecto: cabecera + líneas (jerárquicas) + dependencias.

Endpoint pensado para alimentar un Gantt read-only en el frontend (fase 3).
La edición de líneas (write_kw a apu.project.plan.line) viene en fase 4.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.projects import Ref
from app.core.odoo import OdooError, get_client
from app.core.security import current_session

router = APIRouter(prefix="/projects/{project_id}/plan", tags=["plan"])


class PlanHeader(BaseModel):
    id: int
    name: str
    project: Ref | None
    company: Ref | None
    currency: Ref | None
    active: bool
    baseline_date: str | None
    baseline_locked: bool
    baseline_locked_at: str | None
    baseline_locked_by: Ref | None
    control_period_mode: str | None  # week | fortnight | month
    crew_count: int
    critical_count: int
    execution_ready: bool
    execution_readiness_pct: float
    earned_amount: float


class PlanLine(BaseModel):
    id: int
    name: str
    code: str | None
    level: int                    # 1 = grupo (sin parent), 2+ = actividad
    parent_id: int | None
    sequence: int
    duration_days: int
    generic_start_day: int        # día relativo (1-based) desde inicio del plan
    generic_finish_day: int
    early_start_day: int | None
    early_finish_day: int | None
    late_start_day: int | None
    late_finish_day: int | None
    actual_start: str | None
    actual_finish: str | None
    is_critical: bool
    milestone_category: str | None  # internal | control | contractual
    labor_crew: Ref | None
    equipment_crew: Ref | None


class PlanLink(BaseModel):
    id: int
    from_line: int                # predecessor
    to_line: int                  # successor
    type: str                     # fs | ss | ff | sf
    lag_days: int


class PlanOut(BaseModel):
    plan: PlanHeader
    lines: list[PlanLine]
    links: list[PlanLink]


PLAN_FIELDS = [
    "id", "name", "project_id", "company_id", "currency_id", "active",
    "baseline_date", "baseline_locked_at", "baseline_locked_by_id",
    "control_period_mode", "crew_count", "critical_activity_count",
    "execution_ready", "execution_readiness_pct", "earned_amount",
]

LINE_FIELDS = [
    "id", "name", "code", "parent_id", "level", "sequence",
    "duration_days", "generic_start_day", "generic_finish_day",
    "early_start_day", "early_finish_day", "late_start_day", "late_finish_day",
    "actual_start", "actual_finish", "is_critical", "milestone_category",
    "labor_crew_id", "equipment_crew_id",
]

LINK_FIELDS = [
    "id", "predecessor_line_id", "successor_line_id", "link_type", "lag_days",
]


@router.get("", response_model=PlanOut)
def get_plan(project_id: int, session=Depends(current_session)):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado")

    try:
        # Proyecto + plan activo
        project = client.search_read(
            "project.project",
            [["id", "=", project_id], ["company_id", "in", session["allowed_company_ids"]]],
            ["id", "apu_active_plan_id"],
            login=session["login"],
            password_or_key=session["key"],
            limit=1,
        )
        if not project:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado o sin acceso")
        plan_ref = project[0].get("apu_active_plan_id")
        if not plan_ref:
            raise HTTPException(status_code=404, detail="Este proyecto no tiene plan APU activo")
        plan_id = plan_ref[0]

        plan_raw = client.read(
            "apu.project.plan", [plan_id], PLAN_FIELDS,
            login=session["login"], password_or_key=session["key"],
        )[0]

        lines_raw = client.search_read(
            "apu.project.plan.line",
            [["plan_id", "=", plan_id]],
            LINE_FIELDS,
            login=session["login"], password_or_key=session["key"],
            order="sequence asc, id asc",
        )

        links_raw = client.search_read(
            "apu.project.plan.link",
            [["plan_id", "=", plan_id]],
            LINK_FIELDS,
            login=session["login"], password_or_key=session["key"],
        )
    except OdooError as e:
        raise HTTPException(status_code=502, detail=f"Odoo: {e}")

    locked_by = Ref.from_pair(plan_raw.get("baseline_locked_by_id"))
    locked_at = plan_raw.get("baseline_locked_at") or None

    plan = PlanHeader(
        id=plan_raw["id"],
        name=plan_raw["name"],
        project=Ref.from_pair(plan_raw.get("project_id")),
        company=Ref.from_pair(plan_raw.get("company_id")),
        currency=Ref.from_pair(plan_raw.get("currency_id")),
        active=bool(plan_raw.get("active")),
        baseline_date=plan_raw.get("baseline_date") or None,
        baseline_locked=bool(locked_at),
        baseline_locked_at=str(locked_at) if locked_at else None,
        baseline_locked_by=locked_by,
        control_period_mode=plan_raw.get("control_period_mode") or None,
        crew_count=plan_raw.get("crew_count") or 0,
        critical_count=plan_raw.get("critical_activity_count") or 0,
        execution_ready=bool(plan_raw.get("execution_ready")),
        execution_readiness_pct=plan_raw.get("execution_readiness_pct") or 0.0,
        earned_amount=plan_raw.get("earned_amount") or 0.0,
    )

    lines = [
        PlanLine(
            id=ln["id"], name=ln["name"], code=ln.get("code") or None,
            level=ln.get("level") or 1,
            parent_id=(ln["parent_id"][0] if ln.get("parent_id") else None),
            sequence=ln.get("sequence") or 0,
            duration_days=ln.get("duration_days") or 0,
            generic_start_day=ln.get("generic_start_day") or 0,
            generic_finish_day=ln.get("generic_finish_day") or 0,
            early_start_day=ln.get("early_start_day"),
            early_finish_day=ln.get("early_finish_day"),
            late_start_day=ln.get("late_start_day"),
            late_finish_day=ln.get("late_finish_day"),
            actual_start=str(ln.get("actual_start")) if ln.get("actual_start") else None,
            actual_finish=str(ln.get("actual_finish")) if ln.get("actual_finish") else None,
            is_critical=bool(ln.get("is_critical")),
            milestone_category=ln.get("milestone_category") or None,
            labor_crew=Ref.from_pair(ln.get("labor_crew_id")),
            equipment_crew=Ref.from_pair(ln.get("equipment_crew_id")),
        )
        for ln in lines_raw
    ]

    links = [
        PlanLink(
            id=l["id"],
            from_line=l["predecessor_line_id"][0],
            to_line=l["successor_line_id"][0],
            type=l.get("link_type") or "fs",
            lag_days=l.get("lag_days") or 0,
        )
        for l in links_raw
    ]

    return PlanOut(plan=plan, lines=lines, links=links)
