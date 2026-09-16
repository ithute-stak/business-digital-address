from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import Settings, get_settings


service_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ServicePrincipal:
    client_id: str
    scopes: frozenset[str]
    managed: bool


class ManagedServiceVerifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.jwks = PyJWKClient(settings.auth_jwks_url)

    def verify(self, token: str) -> ServicePrincipal:
        signing_key = self.jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=self.settings.auth_issuer.rstrip("/"),
            audience=self.settings.auth_audience,
            options={"require": ["exp", "iat", "nbf", "sub", "aud", "azp", "scope", "token_use"]},
        )
        if claims.get("token_use") != "service" or claims.get("service_auth") != "managed":
            raise HTTPException(status_code=401, detail="managed Ithute service token required")

        client_id = str(claims.get("azp") or "").strip()
        if not client_id or claims.get("sub") != f"service:{client_id}":
            raise HTTPException(status_code=401, detail="invalid service identity")

        raw_scope = claims.get("scope")
        if not isinstance(raw_scope, str):
            raise HTTPException(status_code=401, detail="invalid service scope")
        scopes = frozenset(value for value in raw_scope.split() if value)
        return ServicePrincipal(client_id=client_id, scopes=scopes, managed=True)


@lru_cache
def managed_service_verifier() -> ManagedServiceVerifier:
    return ManagedServiceVerifier(get_settings())


def require_service_scope(required_scope: str):
    def dependency(
        credentials: HTTPAuthorizationCredentials | None = Depends(service_bearer),
        dev_service: str | None = Header(default=None, alias="X-BDA-Dev-Service"),
        settings: Settings = Depends(get_settings),
    ) -> ServicePrincipal:
        if credentials is not None:
            if credentials.scheme.lower() != "bearer":
                raise HTTPException(status_code=401, detail="managed Ithute service token required")
            try:
                principal = managed_service_verifier().verify(credentials.credentials)
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=401, detail="invalid Ithute service token") from exc
        else:
            if settings.environment.lower() == "production" or not dev_service:
                raise HTTPException(status_code=401, detail="managed Ithute service token required")
            client_id = dev_service.strip()
            scopes = settings.dev_service_scopes.get(client_id, frozenset())
            if not scopes:
                raise HTTPException(status_code=401, detail="unknown development service identity")
            principal = ServicePrincipal(client_id=client_id, scopes=scopes, managed=False)

        if required_scope not in principal.scopes:
            raise HTTPException(status_code=403, detail=f"service scope required: {required_scope}")
        return principal

    return dependency
