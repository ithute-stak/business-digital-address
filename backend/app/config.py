from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://bda:bda_dev_password@db:5432/bda"
    environment: str = "development"
    official_domain: str = "business.ls"
    cors_origins: str = "http://localhost:3000"

    auth_issuer: str = "https://auth.ithute.co.ls"
    auth_jwks_url: str = "https://auth.ithute.co.ls/.well-known/jwks.json"
    auth_audience: str = "business-digital-address"
    auth_required: bool = True

    ithute_token_url: str = "https://auth.ithute.co.ls/v1/auth/service-token"
    ithute_service_client_id: str = "business-digital-address"
    ithute_service_client_secret: str | None = None
    ithute_invite_url: str = "https://auth.ithute.co.ls/v1/platform/identity-invitations"
    ithute_mail_base_url: str = "https://api.ithute.co.ls/api/v1/platform/mail"
    enable_real_mail_provisioning: bool = False
    external_email_verification_ttl_minutes: int = 30

    model_config = SettingsConfigDict(env_prefix="BDA_", case_sensitive=False, extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
