# Trade and RSL service integrations

Business Digital Address separates human portal authentication from government/system-to-system integrations.

## Production authentication

Production callers must obtain a database-managed Ithute Auth service token for audience `business-digital-address`.

Required identities/scopes for the current prototype:

| Client | Scope | Purpose |
| --- | --- | --- |
| `trade-simulator` | `business.register` | Register a business, TIN and optional owner invitation |
| `rsl-simulator` | `official-message.send` | Deliver an official message to the business resolved by TIN |

The Business Digital Address API rejects legacy environment-secret service tokens. Accepted JWTs must be RS256-signed by Ithute Auth and contain `token_use=service`, `service_auth=managed`, matching `sub=service:<azp>`, audience `business-digital-address`, and the required scope.

## Endpoints

### Trade registration

`POST /api/v1/integrations/trade/businesses`

The request includes the source reference, registration number, TIN, legal/trading names and optionally an owner contact. The service derives the official email domain from the database-backed platform configuration. Exact replays are idempotent; conflicting reuse of an existing registration number or TIN returns HTTP 409.

### Official agency message

`POST /api/v1/integrations/agencies/messages`

The caller supplies TIN, its external message ID, subject/body and classification. Agency identity is derived from the authenticated service client; callers cannot choose an arbitrary agency code. The official inbox delivery is stored as delivered before any optional external-forward row is queued. Exact replays are idempotent, while reusing an external message ID for different content returns HTTP 409.

## Local simulator mode

When `BDA_ENVIRONMENT` is not `production`, localhost development may use `X-BDA-Dev-Service` with the configured simulator identities. This shortcut does not operate in production. The Python scripts under `simulators/` use this mode automatically for localhost unless `ITHUTE_SERVICE_CLIENT_SECRET` is supplied.

## Remaining production prerequisite

Before these simulator identities are used against a non-local Business Digital Address environment, Ithute Auth must grant them the `business-digital-address` audience and the least-privilege scopes above. No plaintext simulator secret belongs in this repository.
