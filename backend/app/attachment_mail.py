from __future__ import annotations

import base64
from urllib.parse import quote

import httpx

from .ithute import IthutePlatformClient, IthutePlatformError, MailSendResult
from .models import MessageAttachment


def send_official_copy_with_attachments(
    client: IthutePlatformClient,
    *,
    binding_id: str,
    external_reference: str,
    recipient: str,
    subject: str,
    text: str,
    attachments: list[MessageAttachment],
) -> MailSendResult:
    if not client.settings.enable_real_mail_forwarding:
        raise IthutePlatformError("real external mail forwarding is disabled")
    if not binding_id.strip():
        raise IthutePlatformError("official mailbox binding is not configured")
    if not attachments:
        return client.send_official_copy(
            binding_id=binding_id,
            external_reference=external_reference,
            recipient=recipient,
            subject=subject,
            text=text,
        )

    token = client._service_token(audience="ithute-mail", scope="mail.send")
    response = httpx.post(
        f"{client.settings.ithute_mail_base_url.rstrip('/')}/mailboxes/{quote(binding_id.strip(), safe='')}/send-with-attachments",
        json={
            "external_reference": external_reference.strip(),
            "recipient": recipient.strip().lower(),
            "subject": subject,
            "text": text,
            "attachments": [
                {
                    "filename": item.filename,
                    "content_type": item.content_type,
                    "content_base64": base64.b64encode(item.content).decode("ascii"),
                }
                for item in attachments
            ],
        },
        headers={"authorization": f"Bearer {token}"},
        timeout=client.timeout_seconds,
    )
    client._raise_for_status(response, "Ithute Mail attachment forwarding submission failed")
    data = response.json()
    if not isinstance(data, dict) or not data.get("delivery_id") or not data.get("status"):
        raise IthutePlatformError("Ithute Mail returned an invalid attachment forwarding response")
    return MailSendResult(
        delivery_id=str(data["delivery_id"]),
        status=str(data["status"]),
        provider_message_id=str(data["provider_message_id"]) if data.get("provider_message_id") else None,
        error=str(data["error"]) if data.get("error") else None,
    )
