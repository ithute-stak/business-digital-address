# Production deployment

Business Digital Address deploys as its own isolated Compose project at `/opt/business-digital-address`. It does not share a database or application network with Ithute, LoanHub, or other products.

## Public endpoint

- Web and browser BFF: `https://business.ls`
- Readiness: `https://business.ls/api/health/ready`
- Ithute Auth callback: `https://business.ls/api/auth/callback`

The public Caddy proxy reaches only the frontend through the generic `public-edge` transport network. PostgreSQL and the FastAPI backend do not publish host ports.

## Runtime topology

`frontend -> backend -> PostgreSQL`

The frontend connects to the private app network and to `public-edge`. The backend connects to the private app and database networks plus a dedicated product `egress` network so it can make outbound HTTPS calls to Ithute Auth, identity-invitation and Mail Platform APIs without joining another product's application network. PostgreSQL is database-network only. Human access requires Ithute Auth in production; `BDA_DEV_AUTH_BYPASS` is hard-coded off in the production Compose topology.

## First deployment prerequisites

1. The Ithute Auth interactive client `business-digital-address` must be registered with the exact production callback.
2. DNS for `business.ls` must point at the VPS public edge before the final public readiness check can pass.
3. `/opt/business-digital-address/.env.production` must already exist on the VPS. Start from `.env.production.example` and replace every placeholder with real production values. Keep the file mode at `0600`.
4. The GitHub `production` environment must expose `VPS_HOST`, `VPS_USER`, and `VPS_SSH_KEY`; `VPS_SSH_PASSPHRASE` is optional.
5. The VPS public Caddy configuration must support `import /data/product-routes/*.caddy` and the generic `public-edge` Docker network.

## Deployment behaviour

The deployment workflow is deliberately manual-only for the first production phase. It first requires a successful `Business Digital Address CI` push run for the exact `main` commit SHA being deployed. It then builds backend and frontend images from that SHA, transfers those immutable images to the VPS, reuses the persistent PostgreSQL volume, takes a PostgreSQL backup before Alembic migrations, checks backend/frontend health, validates and reloads the product-owned Caddy route, then verifies the public readiness endpoint.

A deployment refuses to continue if the exact release has not passed CI, the production environment file is missing, the app directory differs from `/opt/business-digital-address`, production Auth is not required, the development Auth bypass is enabled, or the production Compose file publishes direct host ports.

## Machine identity and real mail

`BDA_ITHUTE_SERVICE_CLIENT_SECRET` is the plaintext secret issued by Ithute Auth for the managed machine identity `business-digital-address`. Never commit it. `BDA_ENABLE_REAL_MAIL_PROVISIONING` should remain `false` until the Ithute Mail Platform API is ready and that service identity has the required scopes. The application can otherwise run with official inbox data while mail provisioning remains deferred.
