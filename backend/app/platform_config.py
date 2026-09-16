from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PlatformConfiguration


def normalize_portal_base_url(value: str, *, production: bool) -> str:
    raw = value.strip()
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise ValueError("portal base URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("portal base URL must be an absolute http(s) URL")
    if production and parsed.scheme != "https":
        raise ValueError("portal base URL must use https in production")
    if parsed.query or parsed.fragment:
        raise ValueError("portal base URL must not contain query or fragment")
    path = parsed.path.rstrip("/")
    if path:
        raise ValueError("portal base URL must not contain a path")
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def normalize_email_domain(value: str) -> str:
    raw = value.strip().lower().rstrip(".")
    if raw.startswith("@"):
        raw = raw[1:]
    if "://" in raw or "/" in raw or "@" in raw or not raw:
        raise ValueError("official email domain must be a DNS domain name")
    if len(raw) > 253:
        raise ValueError("official email domain is too long")
    labels = raw.split(".")
    if len(labels) < 2:
        raise ValueError("official email domain must contain at least one dot")
    for label in labels:
        if not label or len(label) > 63 or label.startswith("-") or label.endswith("-"):
            raise ValueError("official email domain contains an invalid DNS label")
        if not all(ch.isalnum() or ch == "-" for ch in label):
            raise ValueError("official email domain contains an invalid DNS label")
    return raw


def get_platform_configuration(db: Session) -> PlatformConfiguration:
    row = db.scalar(select(PlatformConfiguration).where(PlatformConfiguration.id == 1))
    if row is None:
        raise HTTPException(
            status_code=503,
            detail="platform configuration is not initialized; run database migrations",
        )
    return row
