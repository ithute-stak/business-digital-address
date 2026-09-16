# Business Digital Address

Business Digital Address is a standalone product for registering and managing the official digital communication address of a business. It is designed to integrate with the Ithute platform without putting business, TIN, official-message, or government-agency data inside the Ithute database.

## Product boundary

**This repository owns:**

- businesses and registration numbers
- TIN mapping
- business memberships and authorised users
- official business digital addresses
- verified custom business email destinations
- official inbox messages and delivery history
- government/agency integration records
- future optional business mail archive metadata
- database-backed runtime addressing configuration

**Ithute owns:**

- central human identity and authentication
- password/passkey/MFA/recovery
- managed machine identities and scoped service tokens
- trusted identity invitations
- mail infrastructure and mailbox provisioning
- DNS infrastructure
- Push/Realtime and future Notification Gateway

The Business Digital Address application never stores a user's Ithute password.

## Current temporary domains

Until a dedicated Business Digital Address domain is acquired, the product uses:

- Portal: `https://business.ithute.co.ls`
- Official business email domain: `ithute.co.ls`

These are not compiled into the business rules as permanent values. PostgreSQL stores the active `portal_base_url` and `official_email_domain` in the singleton `platform_configuration` row. An Ithute platform administrator can update them through `PATCH /api/v1/platform/config` without changing application source code.

A later portal-domain switch still requires matching DNS, Caddy and Ithute Auth redirect configuration. A later mail-domain switch requires the new mail domain to be provisioned in Ithute Mail. Existing official addresses are never silently rewritten when the configured domain changes; they should be retained as aliases or migrated deliberately.

## First usable flow

```text
Trade / business registration
              |
        managed service JWT
        business.register
              |
              v
      Business Digital Address
      registration number + TIN
              |
        +-----+------------------+
        |                        |
        v                        v
   Ithute Auth              Ithute Mail
 invite/activate owner     provision address
                                 |
                                 v
                     b<registration>@ithute.co.ls
                                 |
                                 v
                           Official inbox
                                 ^
                                 |
                         official-message.send
                         managed service JWT
                                 |
                          RSL / agency service
```

The configured official address is the canonical government/business communication destination. A verified external company email is an additional delivery destination; forwarding must never remove the official copy.

## Trade and agency integrations

The machine integration surface is deliberately separate from the human portal:

- `POST /api/v1/integrations/trade/businesses` requires a managed Ithute service token for audience `business-digital-address` with scope `business.register`.
- `POST /api/v1/integrations/agencies/messages` requires a managed Ithute service token for audience `business-digital-address` with scope `official-message.send`.

The backend accepts only Ithute RS256 service JWTs carrying `token_use=service`, `service_auth=managed`, a matching `sub=service:<azp>`, the correct audience, and the requested scope. Legacy environment-secret service tokens are rejected at this boundary.

Trade registration is idempotent for an already-registered registration-number/TIN pair. A replay that changes the legal identity conflicts instead of silently rewriting a business. Agency messages are idempotent per authenticated agency and external message ID; reusing the same ID with different content returns a conflict.

Agency identity is derived from the authenticated service client rather than accepted from request JSON. For example, `rsl-simulator` is bound to the RSL simulator agency and cannot submit a message claiming to be another agency.

Local development can exercise the same endpoints with the explicit `X-BDA-Dev-Service` simulator identity header. That shortcut is disabled in production. Runnable helpers are provided:

```bash
# With local Docker Compose running, no Ithute service secret is needed.
python simulators/trade_simulator.py \
  --registration REG-001 \
  --tin 200000001 \
  --legal-name "Example Holdings" \
  --owner-name "Business Owner" \
  --owner-email owner@example.com \
  --preferred-channel email

python simulators/rsl_simulator.py \
  --tin 200000001 \
  --subject "Official tax communication" \
  --body "Please sign in to your official business inbox."
```

For a non-local environment, set `BDA_BASE_URL`, `ITHUTE_AUTH_URL`, and `ITHUTE_SERVICE_CLIENT_SECRET`; each simulator then obtains its own scoped Ithute service token instead of using the development header.

## Technology

- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Alembic
- **Database:** PostgreSQL 16
- **Frontend:** Next.js 15 / React / TypeScript
- **Authentication:** Ithute Auth (OIDC/JWT boundary)
- **Mail provisioning:** Ithute Mail Provisioning API
- **Deployment:** Docker Compose with immutable SHA-tagged application images

## Repository layout

```text
backend/       FastAPI API, domain model, migrations and Ithute clients
frontend/      Business portal and secure Ithute Auth BFF
simulators/    Trade and RSL integration test clients
infrastructure/ product-owned edge routing
.github/       CI and guarded manual production deployment
```

## Local development

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8100`
- API docs: `http://localhost:8100/docs`

## Runtime addressing configuration

`GET /api/v1/platform/config` returns the non-secret active portal/email addressing values. `PATCH /api/v1/platform/config` requires an Ithute access token carrying `is_platform_admin=true`.

The initial migration seeds:

```text
portal_base_url       https://business.ithute.co.ls
official_email_domain ithute.co.ls
```

Changing `official_email_domain` affects newly generated official addresses. Existing addresses remain unchanged so an administrative edit cannot unexpectedly invalidate addresses that have already been distributed externally.

## Current foundation scope

The application has the business/TIN/address model, working business portal, secure Ithute OIDC/PKCE browser integration, official inbox storage, external-email verification controls, guarded production topology, Ithute platform integration boundaries, and scope-protected Trade/RSL machine integration endpoints.

The current Ithute Auth callback target is `https://business.ithute.co.ls/api/auth/callback`.

Real Trade/RSL production use still requires the corresponding managed Ithute service clients to be granted the `business-digital-address` audience and their least-privilege scopes. Real mailbox provisioning remains disabled until the temporary `ithute.co.ls` mail-domain grant is constrained safely for Business Digital Address addresses.

## Security rules

1. No business owner password is stored in this repository.
2. TIN and registration number are unique business identifiers, not login credentials.
3. Service secrets are never committed to Git.
4. Official messages are retained before any external forwarding attempt.
5. External forwarding addresses must be verified before use.
6. A failed forwarding copy must not mark the official inbox delivery as failed.
7. Government/agency integrations use authenticated, auditable, scope-limited service identities.
8. Notification/Push/SMS remain optional; official email/inbox delivery is the source of truth.
9. Portal/email domain changes are auditable configuration changes; existing official addresses are not silently rewritten.
10. Development simulator identities are rejected in production; production integrations require managed Ithute service JWTs.
