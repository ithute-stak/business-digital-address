from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.security import UserPrincipal, require_user
from app.server import app


client = TestClient(app)


def _create_business(prefix: str) -> dict:
    suffix = uuid.uuid4().hex[:10].upper()
    response = client.post(
        "/api/v1/businesses",
        json={
            "registration_number": f"{prefix}-{suffix}",
            "tin": f"TIN-{prefix}-{suffix}",
            "legal_name": f"{prefix} Business {suffix}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _platform_admin() -> UserPrincipal:
    return UserPrincipal(
        sub="platform-admin-test",
        email="owner@example.invalid",
        is_platform_admin=True,
    )


def test_default_runtime_domains_are_database_backed_interim_values() -> None:
    response = client.get("/api/v1/platform/config")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["portal_base_url"] == "https://business.ithute.co.ls"
    assert payload["official_email_domain"] == "ithute.co.ls"


def test_non_admin_cannot_change_platform_addressing() -> None:
    response = client.patch(
        "/api/v1/platform/config",
        json={"official_email_domain": "future.example"},
    )
    assert response.status_code == 403, response.text


def test_platform_admin_can_change_domains_without_code_and_existing_addresses_stay_stable() -> None:
    before = _create_business("BEFORE")
    assert before["official_address"]["address"].endswith("@ithute.co.ls")

    app.dependency_overrides[require_user] = _platform_admin
    try:
        changed = client.patch(
            "/api/v1/platform/config",
            json={
                "portal_base_url": "https://future-business.example",
                "official_email_domain": "future-business.example",
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["portal_base_url"] == "https://future-business.example"
        assert changed.json()["official_email_domain"] == "future-business.example"

        after = _create_business("AFTER")
        assert after["official_address"]["address"].endswith("@future-business.example")

        original = client.get(f"/api/v1/businesses/{before['id']}")
        assert original.status_code == 200, original.text
        assert original.json()["official_address"]["address"].endswith("@ithute.co.ls")
    finally:
        restored = client.patch(
            "/api/v1/platform/config",
            json={
                "portal_base_url": "https://business.ithute.co.ls",
                "official_email_domain": "ithute.co.ls",
            },
        )
        assert restored.status_code == 200, restored.text
        app.dependency_overrides.pop(require_user, None)
