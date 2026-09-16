# Integration activation status

Code-level Trade/RSL integration support is present in this repository, but production activation remains deliberately separate.

Current code supports:

- Trade business/TIN registration through a scoped service endpoint.
- Optional owner invitation through the Business Digital Address managed Ithute identity.
- RSL/agency official-message delivery by TIN.
- Retained official-inbox delivery before optional external forwarding.
- Idempotent retries and conflict detection.

Production activation still requires:

1. `trade-simulator` to be allowed audience `business-digital-address` and scope `business.register` in Ithute Auth.
2. `rsl-simulator` to be allowed audience `business-digital-address` and scope `official-message.send` in Ithute Auth.
3. Each simulator/client to receive its own rotated managed credential outside source control.
4. Business Digital Address to remain configured with production authentication enabled.

The localhost development header is never a substitute for these production grants and is rejected when `BDA_ENVIRONMENT=production`.
