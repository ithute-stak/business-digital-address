from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.server import app


client = TestClient(app)


def create_business_with_message() -> tuple[dict, dict]:
    suffix = uuid.uuid4().hex[:10].upper()
    registration = f"LAUNCH-{suffix}"
    tin = f"TIN-{suffix}"
    business_response = client.post(
        "/api/v1/businesses",
        json={
            "registration_number": registration,
            "tin": tin,
            "legal_name": f"Launch Test {suffix}",
        },
    )
    assert business_response.status_code == 201, business_response.text
    business = business_response.json()

    agency_code = f"rsl-{suffix.lower()}"
    agency = client.post("/api/v1/dev/agencies", json={"code": agency_code, "name": "RSL Launch Test"})
    assert agency.status_code == 201, agency.text

    message_response = client.post(
        "/api/v1/dev/official-messages",
        json={
            "tin": tin,
            "agency_code": agency_code,
            "external_message_id": f"MSG-{suffix}",
            "subject": "Launch correspondence test",
            "body_text": "This validates inbox state, acknowledgement and receipts.",
            "classification": "official",
        },
    )
    assert message_response.status_code == 201, message_response.text
    return business, message_response.json()


def test_launch_inbox_state_acknowledgement_and_receipt_flow() -> None:
    business, message = create_business_with_message()
    business_id = business["id"]
    message_id = message["id"]

    inbox = client.get(f"/api/v1/businesses/{business_id}/inbox")
    assert inbox.status_code == 200, inbox.text
    payload = inbox.json()
    assert payload["total"] == 1
    assert payload["unread"] == 1
    assert payload["items"][0]["subject"] == "Launch correspondence test"
    assert payload["items"][0]["state"]["is_read"] is False

    state = client.patch(
        f"/api/v1/businesses/{business_id}/messages/{message_id}/state",
        json={"is_read": True, "starred": True},
    )
    assert state.status_code == 200, state.text
    assert state.json()["is_read"] is True
    assert state.json()["starred"] is True
    assert state.json()["read_at"] is not None

    starred = client.get(f"/api/v1/businesses/{business_id}/inbox?starred_only=true")
    assert starred.status_code == 200, starred.text
    assert starred.json()["total"] == 1
    assert starred.json()["unread"] == 0

    ack = client.post(f"/api/v1/businesses/{business_id}/messages/{message_id}/acknowledgements")
    assert ack.status_code == 201, ack.text
    ack_payload = ack.json()
    assert ack_payload["actor_sub"] == "development-user"

    repeated = client.post(f"/api/v1/businesses/{business_id}/messages/{message_id}/acknowledgements")
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == ack_payload["id"]

    receipt = client.get(f"/api/v1/businesses/{business_id}/messages/{message_id}/receipt")
    assert receipt.status_code == 200, receipt.text
    receipt_payload = receipt.json()
    assert receipt_payload["receipt_id"].startswith("BDA-")
    assert receipt_payload["business"]["registration_number"] == business["registration_number"]
    assert receipt_payload["external_message_id"] == message["external_message_id"]
    assert len(receipt_payload["acknowledgements"]) == 1


def test_launch_inbox_search_archive_and_delivery_retry_guards() -> None:
    business, message = create_business_with_message()
    business_id = business["id"]
    message_id = message["id"]

    matched = client.get(f"/api/v1/businesses/{business_id}/inbox?q=Launch%20correspondence")
    assert matched.status_code == 200, matched.text
    assert matched.json()["total"] == 1

    missing = client.get(f"/api/v1/businesses/{business_id}/inbox?q=does-not-exist")
    assert missing.status_code == 200, missing.text
    assert missing.json()["total"] == 0

    archived = client.patch(
        f"/api/v1/businesses/{business_id}/messages/{message_id}/state",
        json={"archived": True},
    )
    assert archived.status_code == 200, archived.text

    normal = client.get(f"/api/v1/businesses/{business_id}/inbox")
    assert normal.status_code == 200, normal.text
    assert normal.json()["total"] == 0

    archive_view = client.get(f"/api/v1/businesses/{business_id}/inbox?archived=true")
    assert archive_view.status_code == 200, archive_view.text
    archive_payload = archive_view.json()
    assert archive_payload["total"] == 1

    official_delivery = next(
        row for row in archive_payload["items"][0]["deliveries"] if row["channel"] == "official_inbox"
    )
    retry = client.post(
        f"/api/v1/businesses/{business_id}/messages/{message_id}/deliveries/{official_delivery['id']}/retry"
    )
    assert retry.status_code == 409, retry.text
    assert "only external forwarding deliveries" in retry.json()["detail"]


def test_correspondence_migration_and_openapi_routes_are_present() -> None:
    schema = client.get("/openapi.json")
    assert schema.status_code == 200, schema.text
    paths = schema.json()["paths"]
    assert "/api/v1/businesses/{business_id}/inbox" in paths
    assert "/api/v1/businesses/{business_id}/messages/{message_id}/acknowledgements" in paths
    assert "/api/v1/businesses/{business_id}/messages/{message_id}/receipt" in paths
    assert "/api/v1/integrations/agencies/messages/{external_message_id}/attachments" in paths
    assert "/api/v1/admin/operations" in paths
