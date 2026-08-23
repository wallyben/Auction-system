# Owner runbook

1. Copy `.env.example` to `.env`. Set `DATABASE_URL`.
2. `make install && make migrate && make dev`
3. Open the dashboard. ARIE scans on a schedule if `SCAN_ENABLED=true`.
4. Optional: `make ebay-check` after adding eBay keys (no code change). If Production OAuth returns `401 invalid_client`, that is `PRODUCTION_KEYSET_DISABLED_COMPLIANCE` — follow `docs/ebay/ACCOUNT_DELETION_COMPLIANCE.md` rather than regenerating keys.
5. Import owner sales CSV on Performance (required columns: `product,sale_price,sale_date`).
6. Use Scan all / source / category / search, or Value this item / URL.
7. Open a row. Read gates, comps, exits, costs. If and only if `BUY_READY`, consider acting inside SAFE_START limits.
8. Mark purchased. Track inventory. Mark sold. ARIE records prediction error.
9. `make test`, `make test-live`, `make production-proof`, `make backtest`, `make source-health`.

Backup: `pg_dump` the `arie` database. Restore: `psql` + `make migrate`. Rotate secrets by editing `.env` only.
