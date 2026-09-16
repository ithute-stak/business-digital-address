from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.server import app


client = TestClient(app)


def create_business() -> dict:
    suffix = uuid.uuid4().hex[:8].upper()
    response = client.post(
        "/api/v1/businesses",
        json={
            "registration_number": f"PORTAL-{suffix}",
            "tin": f"TIN-{suffix}",
            "legal_name": f"Portal Test {suffix}",
            "trading_name": "Portal Test",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_portal_snapshot_contains_real_business_data() -> None:
    business = create_business()
    response = client.get(f"/api/v1/businesses/{business['id']}/portal")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["business"]["tin"] == business["tin"]
    assert payload["business"]["official_address"]["address"].endswith("@business.ls")
    assert payload["summary"]["authorised_members"] == 1
    assert payload["summary"]["official_messages"] == 0
    assert len(payload["members"]) == 1
    assert any(row["action"] == "business.created" for row in payload["audit"])


def test_portal_member_invitation_is_safely_deferred_without_platform_secret() -> None:
    business = create_business()
    response = client.post(
        f"/api/v1/businesses/{business['id']}/members",
        json={
            "display_name": "Second Member",
            "role": "member",
            "preferred_channel": "email",
            "email": f"member-{uuid.uuid4().hex[:8]}@example.com",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending_platform"
    snapshot = client.get(f"/api/v1/businesses/{business['id']}/portal").json()
    assert len(snapshot["members"]) == 2
    assert snapshot["summary"]["pending_actions"] >= 1


def test_portal_external_email_controls_update_snapshot() -> None:
    business = create_business()
    email = f"accounts-{uuid.uuid4().hex[:8]}@example.com"
    created = client.post(
        f"/api/v1/businesses/{business['id']}/external-emails",
        json={"email": email, "forward_official_mail": True},
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["verification_code"]

    verified = client.post(
        f"/api/v1/businesses/{business['id']}/external-emails/{item['id']}/verify",
        json={"code": item["verification_code"]},
    )
    assert verified.status_code == 200, verified.text

    updated = client.patch(
        f"/api/v1/businesses/{business['id']}/external-emails/{item['id']}",
        json={"forward_official_mail": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["forward_official_mail"] is False

    snapshot = client.get(f"/api/v1/businesses/{business['id']}/portal").json()
    assert snapshot["summary"]["verified_external_emails"] == 1
    assert snapshot["external_emails"][0]["status"] == "verified"
