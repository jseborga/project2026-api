from __future__ import annotations

import time
from typing import Any

import jwt
from fastapi import HTTPException, Request, status

from app.core.config import settings


def make_token(payload: dict[str, Any]) -> str:
    now = int(time.time())
    body = {
        **payload,
        "iat": now,
        "exp": now + settings.jwt_ttl_seconds,
    }
    return jwt.encode(body, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Token inválido: {e}")


def current_session(request: Request) -> dict[str, Any]:
    """Dependency: extrae y valida la cookie de sesión."""
    raw = request.cookies.get(settings.cookie_name)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sin sesión")
    return decode_token(raw)
