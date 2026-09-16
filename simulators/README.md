# Integration simulators

These scripts exercise the same scoped Trade/RSL integration endpoints used by machine clients.

For local development (`BDA_BASE_URL` omitted or pointing to localhost), they use the explicit development-only simulator identity header. Production rejects that header.

For any non-local environment, set:

```bash
export BDA_BASE_URL=https://business.example
export ITHUTE_AUTH_URL=https://auth.ithute.co.ls
export ITHUTE_SERVICE_CLIENT_SECRET='<secret for the simulator identity>'
```

The script then exchanges that secret for a short-lived managed Ithute service token with audience `business-digital-address` and only the required scope.

Run from the `simulators` directory or invoke the files directly from the repository root.
