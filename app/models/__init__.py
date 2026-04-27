"""Modelos ORM — importar todos acá para que Alembic los vea en Base.metadata."""

from app.models.user import User

__all__ = ["User"]
