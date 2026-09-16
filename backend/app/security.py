from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import Settings, get_settings


bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class UserPrincipal:
    sub: str
    email: str | None = None
    is_platform_admin: bool = False


class AuthVerifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.jwks = PyJWKClient(settings.auth_jwks_url)

    def verify(self, token: str) -> UserPrincipal:
        signing_key = self.jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=self.settings.auth_issuer,
            audience=self.settings.auth_audience,
            options={"require": ["exp", "iat", "sub", "token_use"]},
        )
        if claims.get("token_use") != "access" or claims.get("service_auth"):
            raise HTTPException(status_code=401, detail="Ithute human access token required")
        sub = str(claims.get("sub") or "").strip()
        if not sub:
            raise HTTPException(status_code=401, detail="token subject is missing")
        email = claims.get("email")
        return UserPrincipal(
            sub=sub,
            email=str(email) if email else None,
            is_platform_admin=claims.get("is_platform_admin") is True,
        )


@lru_cache
def verifier() -> AuthVerifier:
    return AuthVerifier(get_settings())


def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> UserPrincipal:
    if not settings.auth_required:
        if settings.environment.lower() == "production":
            raise HTTPException(status_code=503, detail="authentication cannot be disabled in production")
        return UserPrincipal(sub="development-user", email="dev@local.invalid", is_platform_admin=False)
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Ithute Auth bearer token required")
    try:
        return verifier().verify(credentials.credentials)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid Ithute Auth token") from exc
