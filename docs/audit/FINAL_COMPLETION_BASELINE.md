# ARIE final-completion baseline

Recorded 2026-08-23 before behaviour changes for the real-money completion programme.

## Git

- Branch: `cursor/arie-production-engine-7e8a`
- HEAD: `4df83e9aaced47ef59dd93512eb5194d1b2202f7`
- Message: `Build a fail-closed Irish resale decision engine with honest live sources.`
- Dirty: local `.env` only (ignored). No uncommitted source changes at baseline.
- PR: https://github.com/wallyben/Auction-system/pull/2

## Tests before change

Command: `python3 -m pytest tests -m "not live" --tb=short -q`

Result: **24 passed**.

Live tests were not re-run at this snapshot; the previous programme recorded 3 live proofs (ECB, Scryfall, Reverb 403-as-blocked).

## What already works (do not throw away)

- FastAPI app, owner dashboard, health endpoints (`/health` must stay `{"status":"ok"}`).
- PostgreSQL models + Alembic `20260223_0001` + `20260823_0002`.
- Deterministic Decimal margin engine (`app/margin_engine`) wrapped by landed-cost.
- Identity / condition / valuation (weighted median + MAD) / Irish tax / liquidity / risk / opportunity engines.
- Source registry with honest LIVE vs BLOCKED. No mock labelled LIVE.
- Scryfall official JSON (Cardmarket EUR = dealer/market, not Irish realised).
- ECB FX official XML.
- CSV / manual ingest.
- eBay Browse adapter (OAuth client-credentials) awaiting keys.
- Reverb adapter (datacentre 403 = BLOCKED_TECHNICAL, no proxy circumvention).
- APScheduler continuous scan (skipped under pytest).
- BUY/WATCH/IGNORE/REVIEW fail-closed scoring.
- Production-proof artifacts from the previous programme.

## Known commercial deficiencies at baseline (the job of this programme)

1. Engine `BUY` is not a money-ready instruction. No `BUY_READY` overlay or hard real-money gates.
2. No first-class realised-sale providers. Asking/dealer evidence can still be the only price input.
3. No owner historical-sales ingest with high evidence weight.
4. No Irish realised-price panel.
5. Single implicit Irish exit; generic 12.9% + €9.50 postage baked into landed cost.
6. Identity is one generic parser (GM vs GM II, 4080 vs SUPER, MacBook generation are weak).
7. No canonical catalogue, weak comp rejection, no calibration, no paper trade, no inventory lifecycle UI.
8. Default scan queries concentrate on cheap cards (postage traps), not Tier-1 €100–€2,500 goods.
9. Dashboard ranks engine score, not money-ready economics.
10. Certification levels 0–5 and category/exit certification do not exist.
11. `make ebay-check` / `make backtest` / `make source-health` do not exist.

## Safety posture that must be preserved

- Asking ≠ sold. Dealer/Cardmarket ≠ Irish realised.
- No invented Ireland premium.
- Cheap listings raise risk, not score.
- Fail closed. One source failure must not crash a global scan.
- Never bypass CAPTCHA, auth, anti-bot, contracts, or rate limits.
- Do not claim LEVEL 4/5 or `ARIE_REAL_MONEY_READY` without empirical evidence.
