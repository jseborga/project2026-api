from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.odoo import OdooError, get_client
from app.core.security import current_session, make_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    login: str
    api_key: str
    company_id: int | None = None  # opcional: pre-seleccionar empresa


class CompanyOut(BaseModel):
    id: int
    name: str


class SessionOut(BaseModel):
    uid: int
    user_name: str
    company_id: int
    company_name: str
    allowed_companies: list[CompanyOut]


@router.post("/login", response_model=SessionOut)
def login(body: LoginIn, response: Response):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado (falta ODOO_URL/ODOO_DB)")
    try:
        sess = client.authenticate(body.login, body.api_key)
    except OdooError as e:
        raise HTTPException(status_code=401, detail=str(e))

    active = body.company_id or sess.company_id
    allowed_ids = [c["id"] for c in sess.allowed_companies] or [sess.company_id]
    if active not in allowed_ids:
        raise HTTPException(status_code=403, detail="company_id no permitido para este usuario")

    token = make_token({
        "uid": sess.uid,
        "login": body.login,
        "key": body.api_key,        # OJO: por simplicidad guardamos en JWT; en prod va a server-side store
        "company_id": active,
        "allowed_company_ids": allowed_ids,
    })

    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=settings.jwt_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )

    return SessionOut(
        uid=sess.uid,
        user_name=sess.user_name,
        company_id=active,
        company_name=next((c["name"] for c in sess.allowed_companies if c["id"] == active), sess.company_name),
        allowed_companies=[CompanyOut(**c) for c in sess.allowed_companies],
    )


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(settings.cookie_name)


class SwitchCompanyIn(BaseModel):
    company_id: int


@router.post("/switch_company", response_model=SessionOut)
def switch_company(body: SwitchCompanyIn, response: Response, session=Depends(current_session)):
    """Cambia la empresa activa sin pedir credenciales nuevamente.

    Valida que la empresa pedida esté en `allowed_company_ids` de la sesión y
    re-emite la cookie con el nuevo company_id.
    """
    if body.company_id not in session["allowed_company_ids"]:
        raise HTTPException(status_code=403, detail="company_id no permitido para este usuario")

    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado")

    # Releemos sesión para devolver datos frescos (nombre de empresa actualizado)
    sess = client.authenticate(session["login"], session["key"])

    token = make_token({
        "uid": session["uid"],
        "login": session["login"],
        "key": session["key"],
        "company_id": body.company_id,
        "allowed_company_ids": session["allowed_company_ids"],
    })
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=settings.jwt_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )

    return SessionOut(
        uid=sess.uid,
        user_name=sess.user_name,
        company_id=body.company_id,
        company_name=next(
            (c["name"] for c in sess.allowed_companies if c["id"] == body.company_id),
            sess.company_name,
        ),
        allowed_companies=[CompanyOut(**c) for c in sess.allowed_companies],
    )


@router.get("/me", response_model=SessionOut)
def me(session=Depends(current_session)):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Gateway sin Odoo configurado")
    sess = client.authenticate(session["login"], session["key"])
    return SessionOut(
        uid=sess.uid,
        user_name=sess.user_name,
        company_id=session["company_id"],
        company_name=next(
            (c["name"] for c in sess.allowed_companies if c["id"] == session["company_id"]),
            sess.company_name,
        ),
        allowed_companies=[CompanyOut(**c) for c in sess.allowed_companies],
    )
