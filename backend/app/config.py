import json
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://bda:bda_dev_password@db:5432/bda"
    environment: str = "development"

    # Bootstrap defaults only. The active portal URL and official email domain
    # are stored in the platform_configuration database row and can be changed
    # later without modifying application code.
    portal_base_url: str = "https://business.ithute.co.ls"
    official_domain: str = "ithute.co.ls"
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

    # Development-only simulator identities. Production ignores these and
    # requires a database-managed Ithute service JWT with service_auth=managed.
    dev_service_scopes_json: str = (
        '{"trade-simulator":["business.register"],'
        '"rsl-simulator":["official-message.send"]}'
    )

    # Bind each machine identity to one agency identity. The official-message
    # API does not accept an arbitrary agency code from the caller, preventing
    # one valid service identity from impersonating another agency.
    agency_service_bindings_json: str = (
        '{"rsl-simulator":{"code":"rsl-simulator","name":"RSL Simulator"}}'
    )

    model_config = SettingsConfigDict(env_prefix="BDA_", case_sensitive=False, extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def dev_service_scopes(self) -> dict[str, frozenset[str]]:
        try:
            parsed = json.loads(self.dev_service_scopes_json or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        result: dict[str, frozenset[str]] = {}
        for client_id, values in parsed.items():
            if not isinstance(client_id, str) or not isinstance(values, list):
                continue
            scopes = frozenset(
                value.strip()
                for value in values
                if isinstance(value, str) and value.strip()
            )
            if scopes:
                result[client_id.strip()] = scopes
        return result

    @property
    def agency_service_bindings(self) -> dict[str, dict[str, str]]:
        try:
            parsed = json.loads(self.agency_service_bindings_json or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        result: dict[str, dict[str, str]] = {}
        for client_id, item in parsed.items():
            if not isinstance(client_id, str) or not isinstance(item, dict):
                continue
            code = item.get("code")
            name = item.get("name")
            if not isinstance(code, str) or not code.strip() or not isinstance(name, str) or not name.strip():
                continue
            result[client_id.strip()] = {"code": code.strip().lower(), "name": name.strip()}
        return result


@lru_cache
def get_settings() -> Settings:
    return Settings()
