"""Cliente Odoo via XML-RPC.

Diseñado para ser sincrono y usado dentro de funciones async via run_in_threadpool
de FastAPI cuando haga falta. Para fase 0+1 con poco tráfico, ejecutar synchronous
desde endpoints async es aceptable porque XML-RPC es lento de todos modos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from xmlrpc.client import ServerProxy

from app.core.config import settings


class OdooError(Exception):
    """Cualquier error elevado por la API de Odoo."""


@dataclass
class OdooSession:
    """Resultado de un authenticate exitoso."""

    uid: int
    user_name: str
    company_id: int
    company_name: str
    allowed_companies: list[dict]   # [{"id": 1, "name": "..."}]


class OdooClient:
    """Cliente fino contra Odoo XML-RPC.

    Stateless por diseño: cada llamada lleva las credenciales que correspondan.
    `authenticate` es la única llamada que NO requiere uid (devuelve uno).
    """

    def __init__(self, url: str, db: str):
        self.url = url.rstrip("/")
        self.db = db
        self._common = ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
        self._object = ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)

    # ── Auth ───────────────────────────────────────────────────────────────

    def authenticate(self, login: str, password_or_key: str) -> OdooSession:
        """Login. `password_or_key` puede ser API key o contraseña.

        Devuelve datos de sesión + listado de empresas permitidas para multi-company.
        """
        try:
            uid = self._common.authenticate(self.db, login, password_or_key, {})
        except Exception as e:
            raise OdooError(f"authenticate falló: {e}") from e
        if not uid:
            raise OdooError("Credenciales inválidas")

        user = self.read("res.users", [uid], ["name", "company_id", "company_ids"], login, password_or_key)[0]
        company_id = user["company_id"][0]
        company_name = user["company_id"][1]
        allowed_ids = user["company_ids"]
        allowed = self.read(
            "res.company", allowed_ids, ["id", "name"], login, password_or_key
        ) if allowed_ids else []

        return OdooSession(
            uid=uid,
            user_name=user["name"],
            company_id=company_id,
            company_name=company_name,
            allowed_companies=allowed,
        )

    # ── Operaciones genéricas ──────────────────────────────────────────────

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list,
        kwargs: dict | None = None,
        *,
        login: str,
        password_or_key: str,
    ) -> Any:
        """Wrapper directo de execute_kw."""
        try:
            return self._object.execute_kw(
                self.db,
                self._uid_for(login, password_or_key),
                password_or_key,
                model,
                method,
                args,
                kwargs or {},
            )
        except Exception as e:
            raise OdooError(f"execute_kw {model}.{method} falló: {e}") from e

    def search_read(
        self,
        model: str,
        domain: list,
        fields: list[str],
        login: str,
        password_or_key: str,
        *,
        limit: int = 0,
        offset: int = 0,
        order: str = "",
        context: dict | None = None,
    ) -> list[dict]:
        kwargs: dict = {"fields": fields}
        if limit:
            kwargs["limit"] = limit
        if offset:
            kwargs["offset"] = offset
        if order:
            kwargs["order"] = order
        if context:
            kwargs["context"] = context
        return self.execute_kw(model, "search_read", [domain], kwargs, login=login, password_or_key=password_or_key)

    def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str],
        login: str,
        password_or_key: str,
    ) -> list[dict]:
        if not ids:
            return []
        return self.execute_kw(model, "read", [ids, fields], login=login, password_or_key=password_or_key)

    # ── Cache de uid por (login,key) para evitar re-authenticate por call ──

    _uid_cache: dict[tuple[str, str], int] = {}

    def _uid_for(self, login: str, key: str) -> int:
        cached = self._uid_cache.get((login, key))
        if cached:
            return cached
        uid = self._common.authenticate(self.db, login, key, {})
        if not uid:
            raise OdooError("Credenciales inválidas")
        self._uid_cache[(login, key)] = uid
        return uid


# Singleton de conveniencia. None si las settings aún no tienen URL/DB.
def get_client() -> OdooClient | None:
    if not settings.odoo_url or not settings.odoo_db:
        return None
    return OdooClient(settings.odoo_url, settings.odoo_db)
