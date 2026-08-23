# ARIE

**Automated Reseller Intelligence Engine** for an Irish reseller.

ARIE answers: *what can I buy, from where, for how much, and what is it realistically worth after every cost if I resell from Ireland?*

It is not a toy dashboard. It is a decision engine that fails closed when evidence is weak.

## What is live today

| Capability | Status |
|---|---|
| Scan / identify / value / cost / decide pipeline | Working |
| Owner dashboard | Working |
| Continuous APScheduler scans | Working when `SCAN_ENABLED=true` |
| Scryfall + ECB FX | **LIVE** (real HTTP in this environment) |
| Reverb public listings | **BLOCKED_TECHNICAL** (HTTP 403 from this host) |
| eBay Browse | **BLOCKED_CREDENTIALS** until you add app keys |
| DoneDeal, Adverts.ie, auction houses, CeX | **BLOCKED_POLICY** — no scraping |
| CSV / manual capture | LIVE fallback |
| Asking prices labelled as realised Irish sales | Never |

## Quick start

```bash
cp .env.example .env   # then set DATABASE_URL
make install
make migrate
make dev               # http://127.0.0.1:8000
```

```bash
make test              # unit + contract (no network)
make test-live         # ECB / Scryfall / Reverb
make scan
make scan-source SOURCE=scryfall
make validate
make production-proof
make ebay-check
make source-health
make backtest
```

Dashboard: open `/`. Scan, value a URL/item, inspect gates, mark purchased. `BUY_READY` is not engine `BUY`.

## Owner knobs

All ordinary configuration is in `.env`. You do not edit Python to change thresholds, sources, or queries.

## Honest limits

- Irish *realised* sold comps are not available from a public API in this programme.
- Asking prices are haircut and capped at 0.48 confidence.
- Tax figures are operational estimates. An accountant must confirm VAT/margin-scheme treatment.
- Do not trust ARIE with real money until you have recorded actual buys and sales in the outcome loop.
- Current honest status: software complete; empirical validation required. SAFE_START stays on.
