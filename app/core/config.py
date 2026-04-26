from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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
    cookie_samesite: str = "lax"

    # Logging
    log_level: str = "INFO"


settings = Settings()
