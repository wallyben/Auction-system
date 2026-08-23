# Architecture

ARIE is a FastAPI app with PostgreSQL, Alembic, APScheduler, and pluggable source adapters.

```
scan → ingest → normalise → identify → comps → value → land costs → score → persist → alert
```

## Packages

- `app/sources` — adapters + registry. A source is LIVE only after a real fetch.
- `app/identity` — brand/model/GTIN parsing. Ambiguity lowers level to family/unknown.
- `app/condition` — grade + refurb band.
- `app/valuation` — weighted median, MAD outliers, evidence/geography/recency weights.
- `app/costs` — wraps the existing Decimal margin engine; adds corridor shipping, FX, platform fees.
- `app/tax` — Irish acquisition posture, labelled assumption vs accountant-required.
- `app/opportunity` — transparent BUY / WATCH / IGNORE / REVIEW gates.
- `app/pipeline` — orchestration, dedupe, persistence.
- `app/jobs` — APScheduler interval scan.
- `app/web` — owner dashboard.

## Rules the code is built on

1. Asking ≠ realised.
2. Subject listing ask is not a comparable for its own resale.
3. One source failing does not abort the global scan.
4. No CAPTCHA bypass, no unofficial clients, no fake LIVE.
5. Existing `app/margin_engine` remains the auction max-bid kernel.
