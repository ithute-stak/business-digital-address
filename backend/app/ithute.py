from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .config import Settings
from .services import OFFICIAL_LOCAL_PART_PREFIX


class IthutePlatformError(RuntimeError):
    pass


@dataclass(frozen=True)
class MailboxProvisionResult:
    binding_id: str
    mailbox_id: str
    address: str
    status: str


@dataclass(frozen=True)
class MailSendResult:
    delivery_id: str
    status: str
    provider_message_id: str | None
    error: str | None


class IthutePlatformClient:
    def __init__(self, settings: Settings, *, timeout_seconds: float = 10.0):
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    def _service_token(self, *, audience: str, scope: str) -> str:
        secret = (self.settings.ithute_service_client_secret or "").strip()
        if not secret:
            raise IthutePlatformError("Ithute managed service credential is not configured")
        response = httpx.post(
            self.settings.ithute_token_url,
            json={
                "client_id": self.settings.ithute_service_client_id,
                "client_secret": secret,
                "audience": audience,
                "scope": scope,
            },
            timeout=self.timeout_seconds,
        )
        self._raise_for_status(response, "Ithute Auth service token request failed")
        payload = response.json()
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise IthutePlatformError("Ithute Auth did not return an access token")
        return token

    @staticmethod
    def _raise_for_status(response: httpx.Response, context: str) -> None:
        if response.is_success:
            return
        detail: Any = None
        try:
            payload = response.json()
            detail = payload.get("detail") if isinstance(payload, dict) else None
        except ValueError:
            detail = None
        suffix = f": {detail}" if detail else f" (HTTP {response.status_code})"
        raise IthutePlatformError(context + suffix)

    def invite_identity(
        self,
        *,
        external_reference: str,
        display_name: str,
        preferred_channel: str,
        email: str | None,
        phone: str | None,
    ) -> dict[str, Any]:
        token = self._service_token(audience="ithute-auth", scope="identity.invite")
        payload: dict[str, Any] = {
            "external_reference": external_reference,
            "display_name": display_name,
            "preferred_channel": preferred_channel,
        }
        if preferred_channel == "email":
            payload["email"] = email
        else:
            payload["phone"] = phone
        response = httpx.post(
            self.settings.ithute_invite_url,
            json=payload,
            headers={"authorization": f"Bearer {token}"},
            timeout=self.timeout_seconds,
        )
        self._raise_for_status(response, "Ithute trusted identity invitation failed")
        data = response.json()
        if not isinstance(data, dict) or not data.get("id"):
            raise IthutePlatformError("Ithute Auth returned an invalid invitation response")
        return data

    def activated_invitations_for_subject(self, *, user_sub: str) -> list[dict[str, Any]]:
        """Return consumed invitations created by this BDA service for one Auth subject."""

        normalized_sub = user_sub.strip()
        if not normalized_sub:
            raise IthutePlatformError("Ithute Auth subject is required")
        token = self._service_token(audience="ithute-auth", scope="identity.invite")
        response = httpx.get(
            f"{self.settings.ithute_invite_url.rstrip('/')}/activated-sub/{quote(normalized_sub, safe='')}",
            headers={"authorization": f"Bearer {token}"},
            timeout=self.timeout_seconds,
        )
        self._raise_for_status(response, "Ithute activated invitation lookup failed")
        data = response.json()
        if not isinstance(data, list):
            raise IthutePlatformError("Ithute Auth returned an invalid activated invitation response")
        result: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                raise IthutePlatformError("Ithute Auth returned an invalid activated invitation item")
            invitation_id = item.get("id")
            external_reference = item.get("external_reference")
            activated_sub = item.get("activated_sub")
            if not invitation_id or not external_reference or activated_sub != normalized_sub:
                raise IthutePlatformError("Ithute Auth returned an invalid activated invitation item")
            result.append(item)
        return result

    def provision_mailbox(
        self,
        *,
        external_reference: str,
        domain_name: str,
        local_part: str,
        display_name: str,
        quota_bytes: int = 1024**3,
    ) -> MailboxProvisionResult:
        # This check lives at the platform-client boundary so explicit/manual API
        # calls cannot bypass the same kill switch used by automatic provisioning.
        if not self.settings.enable_real_mail_provisioning:
            raise IthutePlatformError("real Ithute Mail provisioning is disabled")

        normalized_local_part = local_part.strip().lower()
        if not normalized_local_part.startswith(OFFICIAL_LOCAL_PART_PREFIX):
            raise IthutePlatformError("official mailbox is outside the reserved BDA namespace")

        token = self._service_token(audience="ithute-mail", scope="mailbox.create")
        response = httpx.post(
            f"{self.settings.ithute_mail_base_url.rstrip('/')}/mailboxes",
            json={
                "external_reference": external_reference,
                "domain_name": domain_name,
                "local_part": normalized_local_part,
                "display_name": display_name,
                "quota_bytes": quota_bytes,
            },
            headers={"authorization": f"Bearer {token}"},
            timeout=self.timeout_seconds,
        )
        self._raise_for_status(response, "Ithute Mail mailbox provisioning failed")
        data = response.json()
        required = ("binding_id", "mailbox_id", "address", "status")
        if not isinstance(data, dict) or any(not data.get(key) for key in required):
            raise IthutePlatformError("Ithute Mail returned an invalid mailbox response")
        return MailboxProvisionResult(
            binding_id=str(data["binding_id"]),
            mailbox_id=str(data["mailbox_id"]),
            address=str(data["address"]),
            status=str(data["status"]),
        )

    def send_official_copy(
        self,
        *,
        binding_id: str,
        external_reference: str,
        recipient: str,
        subject: str,
        text: str,
    ) -> MailSendResult:
        """Submit one verified external copy through the product-owned mailbox.

        BDA never receives or handles the mailbox SMTP credential. Ithute derives
        the sender from the owned binding and makes the external reference
        idempotent on its side.
        """

        if not self.settings.enable_real_mail_forwarding:
            raise IthutePlatformError("real external mail forwarding is disabled")
        if not binding_id.strip():
            raise IthutePlatformError("official mailbox binding is not configured")

        token = self._service_token(audience="ithute-mail", scope="mail.send")
        response = httpx.post(
            f"{self.settings.ithute_mail_base_url.rstrip('/')}/mailboxes/{quote(binding_id.strip(), safe='')}/send",
            json={
                "external_reference": external_reference.strip(),
                "recipient": recipient.strip().lower(),
                "subject": subject,
                "text": text,
            },
            headers={"authorization": f"Bearer {token}"},
            timeout=self.timeout_seconds,
        )
        self._raise_for_status(response, "Ithute Mail forwarding submission failed")
        data = response.json()
        if not isinstance(data, dict) or not data.get("delivery_id") or not data.get("status"):
            raise IthutePlatformError("Ithute Mail returned an invalid forwarding response")
        return MailSendResult(
            delivery_id=str(data["delivery_id"]),
            status=str(data["status"]),
            provider_message_id=str(data["provider_message_id"]) if data.get("provider_message_id") else None,
            error=str(data["error"]) if data.get("error") else None,
        )
