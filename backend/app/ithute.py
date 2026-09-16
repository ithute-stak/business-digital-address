from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings


class IthutePlatformError(RuntimeError):
    pass


@dataclass(frozen=True)
class MailboxProvisionResult:
    binding_id: str
    mailbox_id: str
    address: str
    status: str


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

    def provision_mailbox(
        self,
        *,
        external_reference: str,
        domain_name: str,
        local_part: str,
        display_name: str,
        quota_bytes: int = 1024**3,
    ) -> MailboxProvisionResult:
        token = self._service_token(audience="ithute-mail", scope="mailbox.create")
        response = httpx.post(
            f"{self.settings.ithute_mail_base_url.rstrip('/')}/mailboxes",
            json={
                "external_reference": external_reference,
                "domain_name": domain_name,
                "local_part": local_part,
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
