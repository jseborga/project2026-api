from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import auth, catalog, contracts, cost_entries, plan, plan_write, projects
from app.core.config import settings
from app.core.db import get_db

app = FastAPI(
    title="Tramo PM API",
    version="0.1.0",
    description="Gateway entre Tramo PM (frontend) y Odoo 18 CE",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin] if settings.frontend_origin else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}


@app.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1")).scalar()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"db unavailable: {type(e).__name__}")


app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(catalog.router)
app.include_router(plan.router)
app.include_router(plan_write.router)
app.include_router(cost_entries.router)
app.include_router(contracts.router)
