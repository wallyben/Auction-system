# Current system audit

## Working
- FastAPI app, owner dashboard, health endpoints
- PostgreSQL models + Alembic `20260823_0002`
- Decimal margin engine (preserved) wrapped by landed-cost
- Identity / condition / valuation / tax / opportunity engines
- Source registry with honest LIVE vs BLOCKED
- Scryfall + ECB live HTTP
- CSV/manual ingest
- Scan CLI, scheduler, production-proof artifacts

## Partial
- eBay Browse adapter (needs owner keys)
- RSS adapter (needs `RSS_URLS`)
- Outcome learning (tables exist; no production sales yet)
- Job-lot breakup (parser present, not primary path)

## Mock / not claimed
- None labelled LIVE without a real fetch

## Missing / blocked
- Irish realised sold comps
- DoneDeal, Adverts.ie, Wilsons, John Pye, BidSpotter, i-bidder, CeX: BLOCKED_POLICY
- Reverb from this host: BLOCKED_TECHNICAL (403)
- Computer vision / OCR

## Commercial risks
- Dealer/asking evidence can be mistaken for sold if an operator ignores confidence caps
- Low-value items look like disasters after postage (correct, but noisy)

## Security
- `.env` gitignored; no tracked secrets found
- Dashboard token optional

## Reusable
- `app/margin_engine` deterministic max-bid kernel
- Adapter contract + HealthProof
