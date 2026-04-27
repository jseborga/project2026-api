"""Mixins reusables para todos los modelos del gateway.

Diseñados desde Fase 7.0 con offline-first (Fase 10) en mente:
- UUIDs en lugar de autoincrement → un cliente offline puede generar IDs
  sin coordinar con el server.
- Soft delete + `updated_at` → la cola de sync puede preguntar "qué cambió
  desde mi último pull" sin perder registros borrados.
- `client_id` + `op_id` → idempotencia para reaplicar mutaciones encoladas
  sin duplicar (el server reconoce por op_id que ya las procesó).

Hoy (Fase 7) los campos sync se aceptan pero quedan NULL — se activan al
introducir el endpoint de sync en Fase 10.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPKMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )


class SyncMixin:
    """Campos de soporte para offline-first sync (Fase 10).

    client_id: identifica el dispositivo/instalación que generó la mutación.
    op_id: ID idempotente de la operación (la cola lo manda; el server
    rechaza duplicados por unique constraint).
    """

    client_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    op_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
