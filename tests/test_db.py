"""Smoke tests de la capa de DB — Fase 7.0.

Valida:
- engine + session se crean contra SQLite,
- los mixins (UUID PK, timestamps, soft-delete) funcionan,
- /health/db responde 200,
- la migración 0001 corre limpia contra una DB vacía.
"""

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base, reset_engine_for_tests
from app.main import app
from app.models import User


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    """Aísla cada test con una SQLite distinta y resetea el engine global."""
    db_file = tmp_path / "test.db"
    monkeypatch.setattr("app.core.config.settings.database_url", f"sqlite:///{db_file}")
    reset_engine_for_tests()

    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        reset_engine_for_tests()


def test_user_create_sets_uuid_and_timestamps(db_session):
    u = User(
        email="alice@example.com",
        password_hash="$2b$dummy",
        display_name="Alice",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)

    assert isinstance(u.id, uuid.UUID)
    assert isinstance(u.created_at, datetime)
    assert isinstance(u.updated_at, datetime)
    assert u.deleted_at is None
    assert u.is_active is True


def test_user_email_unique(db_session):
    db_session.add(User(email="dup@example.com", password_hash="x"))
    db_session.commit()

    db_session.add(User(email="dup@example.com", password_hash="y"))
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_health_db_endpoint(tmp_path, monkeypatch):
    db_file = tmp_path / "h.db"
    monkeypatch.setattr("app.core.config.settings.database_url", f"sqlite:///{db_file}")
    reset_engine_for_tests()

    # Crear schema antes de que el endpoint pegue (el endpoint solo hace SELECT 1,
    # así que en realidad no necesita schema — pero igual lo dejamos limpio).
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    engine.dispose()

    with TestClient(app) as client:
        r = client.get("/health/db")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    reset_engine_for_tests()


def test_database_url_normalization():
    """EasyPanel/Heroku/Railway dan formatos que SQLAlchemy 2.x rechaza."""
    from app.core.config import Settings

    # postgres:// (legacy Heroku) → postgresql+psycopg://
    s = Settings(database_url="postgres://u:p@h:5432/db")
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"

    # postgresql:// (sin driver) → postgresql+psycopg://
    s = Settings(database_url="postgresql://u:p@h:5432/db")
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"

    # postgresql+psycopg:// pasa sin tocar
    s = Settings(database_url="postgresql+psycopg://u:p@h:5432/db")
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"

    # SQLite no se toca
    s = Settings(database_url="sqlite:///./local.db")
    assert s.database_url == "sqlite:///./local.db"


def test_alembic_migration_runs_on_empty_db(tmp_path, monkeypatch):
    """La migración 0001 debe correr sin errores y crear la tabla users."""
    import os
    import subprocess
    import sys

    db_file = tmp_path / "mig.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file}"

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Usar `python -m alembic` para garantizar que invocamos el del venv actual.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic failed: {result.stderr}"

    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        from sqlalchemy import inspect
        insp = inspect(conn)
        assert "users" in insp.get_table_names()
        assert "alembic_version" in insp.get_table_names()
    engine.dispose()
