from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database (gateway propio — usuarios, proyectos nativos, etc.)
    # Dev default: SQLite local. Prod (EasyPanel): postgresql+psycopg://...
    database_url: str = "sqlite:///./tramo_pm.db"

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # EasyPanel / Heroku / Railway suelen dar "postgres://..." (legacy)
        # que SQLAlchemy 2.x ya no reconoce. "postgresql://..." sin driver
        # explícito asume psycopg2, que no está en deps. Forzamos psycopg3
        # (que sí está) en ambos casos.
        if v.startswith("postgres://"):
            return "postgresql+psycopg://" + v[len("postgres://"):]
        if v.startswith("postgresql://") and not v.startswith("postgresql+"):
            return "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    # Odoo
    odoo_url: str = ""
    odoo_db: str = ""
    odoo_user: str = ""
    odoo_api_key: str = ""

    # JWT (sesiones del frontend)
    jwt_secret: str = "dev-not-for-prod"
    jwt_alg: str = "HS256"
    jwt_ttl_seconds: int = 60 * 60 * 8

    # CORS / cookie
    frontend_origin: str = "https://base-project2026.q8waob.easypanel.host"
    cookie_name: str = "tramo_session"
    cookie_secure: bool = True
    # Para gateway cross-subdomain ("base-project2026" ↔ "base-project2026-api")
    # default debe ser "none" + secure=true. SameSite=lax bloquea la cookie en
    # fetch cross-origin desde el frontend.
    cookie_samesite: str = "none"

    # Logging
    log_level: str = "INFO"


settings = Settings()
