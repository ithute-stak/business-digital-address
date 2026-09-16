from __future__ import annotations

import json
import os
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def _json_request(url: str, payload: dict, headers: dict[str, str] | None = None) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", "accept": "application/json", **(headers or {})},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def service_headers(*, client_id: str, scope: str) -> dict[str, str]:
    base_url = os.getenv("BDA_BASE_URL", "http://localhost:8100").rstrip("/")
    secret = os.getenv("ITHUTE_SERVICE_CLIENT_SECRET", "").strip()
    if secret:
        auth_url = os.getenv("ITHUTE_AUTH_URL", "https://auth.ithute.co.ls").rstrip("/")
        result = _json_request(
            f"{auth_url}/v1/auth/service-token",
            {
                "client_id": client_id,
                "client_secret": secret,
                "audience": "business-digital-address",
                "scope": scope,
            },
        )
        return {"authorization": f"Bearer {result['access_token']}"}

    parsed = urlparse(base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("ITHUTE_SERVICE_CLIENT_SECRET is required outside localhost development")
    return {"X-BDA-Dev-Service": client_id}


def post_bda(path: str, payload: dict, *, client_id: str, scope: str) -> dict:
    base_url = os.getenv("BDA_BASE_URL", "http://localhost:8100").rstrip("/")
    return _json_request(
        f"{base_url}{path}",
        payload,
        headers=service_headers(client_id=client_id, scope=scope),
    )
