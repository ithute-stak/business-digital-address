# Integration security boundary

Production machine endpoints accept only database-managed Ithute service JWTs. Tokens from the legacy environment-secret compatibility path are rejected because they do not carry `service_auth=managed`.

The API verifies issuer, audience, RS256 signature, expiry/not-before, `token_use=service`, `service_auth=managed`, matching `sub`/`azp`, and the route-specific scope. Agency identity is derived from the authenticated client binding rather than request content.
