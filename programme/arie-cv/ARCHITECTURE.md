# ARIE-CV architecture

## What production is today

ARIE on `main` is a FastAPI application and a separate worker.

- Web process: HTTP only. `/health` does not run the pipeline.
- Worker: APScheduler plus a Postgres job queue (`scan`, `revalue`, `sold-revalidate`, `sold-refresh`). One heavy job at a time.
- Decision path for cameras: ingest, camera identity firewall, sold comps, valuation, landed cost, `BUY` / `WATCH` / `IGNORE` / `REVIEW`, then stricter `BUY_READY` gates.
- Persistence: PostgreSQL, Alembic through `20260922_0011` on this branch (`20260901_0010` was the previous head).

## Camera decisions

| Area | Decision | Reason |
|---|---|---|
| `app/sold/cameras.py`, identity firewall, eBay sold refresh | KEEP, isolated | Working camera certification path. Van logic does not import it |
| `app/decision/gates.py` safe-start camera cap | KEEP | Capital control for camera bodies. Vans use `app/domains/vehicles/gates.py` |
| `app/margin_engine` | KEEP | Camera and legacy auction kernel. Van bids use `max_bid.py` because premium bands and import VAT are piecewise |
| `app/core/money.py` | KEEP, shared | Decimal money. No floats |
| `app/jobs` worker queue | KEEP, not extended | No van poller until a permitted source exists |
| `app/sources` DoneDeal / Wilsons / Adverts blocks | KEEP | Policy still applies. CV register repeats it and does not fetch |
| `app/tax/irish.py` | KEEP | Camera/general corridor estimates. Van VRT is a separate versioned module |
| Scryfall, Reverb, camera catalogue | KEEP | Unrelated to vans. Not on the van path |
| Root dashboard `/` | KEEP | Switching it would hide the camera floor. Vans are at `/cv` |

## Van path

```
manual case
  → parse or accept canonical identity
  → provenance ledger
  → history checks (unchecked stays unchecked)
  → homologation and VRT / NOx / duty / import VAT
  → auction fee schedule
  → Irish market book observations at or before as_of
  → scored comps
  → asking / achievable / conservative / quick-sale
  → repair reserve
  → landed stack
  → maximum hammer by search
  → gates
  → shadow report
```

No step calls an LLM. No step places a bid.

## Boundaries

- Vehicle identity (`VehicleIdentity.vehicle_key`) is VIN, else registration. Listing identity is `source_id:external_id`.
- The same vehicle key on two listing keys is a reappearance.
- Market rows are insert-only. A price change is a new observation id.
- Tax amounts used in a bid must be `PROVEN` or an explicit `ESTIMATED` duty rate. `UNKNOWN` blocks the stack.
- €200 VRT is computed only from homologation (CoC / NSSTA / IVA), seat count, fuel, and the weight ratio. The model name is not an input to that rule.
- Registration-format signals do not set provenance.
- Auction country does not set provenance.
- Asking price is not OMSP and is not achievable value.
- Disappearance is not a realised sale.

## Freshness

- Market observations older than 14 days are outside the current valuation.
- Tax rules older than 120 days fail `DATA_FRESHNESS_PASS`. Retrieval timestamp is 2026-09-22.
- Non-EUR bids need an FX rate no older than 3 days. A missing rate does not drop the bid on the floor.

## UI

`/cv` lists shadow candidates. The in-process board is written through to `cv_evaluations` when `DATABASE_URL` is set, and that table is what a restarted web process reads. A buy candidate older than 14 days, or past its auction close, is shown as needing manual evidence. The frozen shadow snapshot is not rewritten into a pass.

## Real-money control

There is no bid client, payment client, or contract client on this path. Certification cannot be turned on by a configuration flag. `purchasing_recommendation` returns false.
