# Business Digital Address

Business Digital Address is a standalone product for registering and managing the official digital communication address of a business. It is designed to integrate with the Ithute platform without putting business, TIN, official-message, or government-agency data inside the Ithute database.

## Product boundary

**This repository owns:**

- businesses and registration numbers
- TIN mapping
- business memberships and authorised users
- official `@business.ls` digital addresses
- verified custom business email destinations
- official inbox messages and delivery history
- government/agency integration records
- future optional business mail archive metadata

**Ithute owns:**

- central human identity and authentication
- password/passkey/MFA/recovery
- managed machine identities and scoped service tokens
- trusted identity invitations
- mail infrastructure and mailbox provisioning
- DNS infrastructure
- Push/Realtime and future Notification Gateway

The Business Digital Address application never stores a user's Ithute password.

## First usable flow

```text
Business registration / Trade simulator
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
                    b<registration>@business.ls
                                 |
                   +-------------+-------------+
                   |                           |
                   v                           v
             Official inbox            verified custom email
                                          forwarding copy
```

The official `@business.ls` address is the canonical government/business communication destination. A verified external company email is an additional delivery destination; forwarding must never remove the official copy.

## Technology

- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Alembic
- **Database:** PostgreSQL 16
- **Frontend:** Next.js 15 / React / TypeScript
- **Authentication:** Ithute Auth (OIDC/JWT boundary)
- **Mail provisioning:** Ithute Mail Provisioning API
- **Deployment:** Docker Compose, immutable app images later in CI/CD

## Repository layout

```text
backend/       FastAPI API, domain model, migrations and Ithute clients
frontend/      Business portal shell
infra/         deployment/runtime configuration
.github/       CI
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

## Current foundation scope

The first implementation establishes the business/TIN/address data model and safe Ithute integration boundaries. It intentionally does not pretend that `business.ls` is already registered or delegated. `BDA_OFFICIAL_DOMAIN=business.ls` is a product configuration target; real production provisioning must only be enabled after the domain is legitimately controlled and its DNS/mail records are delegated to the production infrastructure.

The current Ithute Auth platform still needs the Business Digital Address interactive OIDC client to be registered before end-user login is activated in production. The backend therefore contains the verification boundary now, while production credentials/client registration remain deployment configuration rather than source-code secrets.

## Security rules

1. No business owner password is stored in this repository.
2. TIN and registration number are unique business identifiers, not login credentials.
3. Service secrets are never committed to Git.
4. Official messages are retained before any external forwarding attempt.
5. External forwarding addresses must be verified before use.
6. A failed forwarding copy must not mark the official inbox delivery as failed.
7. Government/agency integrations must use authenticated, auditable service identities when activated.
8. Notification/Push/SMS remain optional; official email/inbox delivery is the source of truth.

## Status

This repository was initialized as a clean standalone product after the Ithute platform foundation was separated from business-specific RSL/Trade logic.
