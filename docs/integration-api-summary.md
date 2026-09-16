# Integration API summary

- `POST /api/v1/integrations/trade/businesses` — scope `business.register`
- `POST /api/v1/integrations/agencies/messages` — scope `official-message.send`

Both production routes require Ithute-managed RS256 service JWTs for audience `business-digital-address`. The Trade route is idempotent by the registered business identity and the agency route is idempotent by authenticated agency plus external message ID.
