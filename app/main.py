from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth
from app.core.config import settings

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


app.include_router(auth.router)
