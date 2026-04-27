"""Usuarios del gateway (auth propia — Fase 7.1 monta el flujo completo).

Por ahora solo schema; los endpoints /auth/register, /auth/login local,
hashing con bcrypt, etc. se cablean en la siguiente sub-fase.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPKMixin


class User(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
