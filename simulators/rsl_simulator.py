from __future__ import annotations

import argparse
import json
import uuid

from common import post_bda


def main() -> None:
    parser = argparse.ArgumentParser(description="Deliver an official message through the RSL simulator identity.")
    parser.add_argument("--tin", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--classification", default="official")
    parser.add_argument("--message-id", default=f"rsl-sim-{uuid.uuid4()}")
    args = parser.parse_args()

    result = post_bda(
        "/api/v1/integrations/agencies/messages",
        {
            "tin": args.tin,
            "external_message_id": args.message_id,
            "subject": args.subject,
            "body_text": args.body,
            "classification": args.classification,
        },
        client_id="rsl-simulator",
        scope="official-message.send",
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
