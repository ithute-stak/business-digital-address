from __future__ import annotations

import argparse
import json
import uuid

from common import post_bda


def main() -> None:
    parser = argparse.ArgumentParser(description="Register a business through the Trade simulator service identity.")
    parser.add_argument("--registration", required=True)
    parser.add_argument("--tin", required=True)
    parser.add_argument("--legal-name", required=True)
    parser.add_argument("--trading-name")
    parser.add_argument("--owner-name")
    parser.add_argument("--owner-email")
    parser.add_argument("--owner-phone")
    parser.add_argument("--preferred-channel", choices=("email", "phone"), default="phone")
    parser.add_argument("--source-reference", default=f"trade-sim-{uuid.uuid4()}")
    args = parser.parse_args()

    owner = None
    if args.owner_name:
        owner = {
            "display_name": args.owner_name,
            "preferred_channel": args.preferred_channel,
            "email": args.owner_email,
            "phone": args.owner_phone,
        }

    payload = {
        "source_reference": args.source_reference,
        "registration_number": args.registration,
        "tin": args.tin,
        "legal_name": args.legal_name,
        "trading_name": args.trading_name,
        "owner": owner,
    }
    result = post_bda(
        "/api/v1/integrations/trade/businesses",
        payload,
        client_id="trade-simulator",
        scope="business.register",
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
