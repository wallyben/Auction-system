# ARIE final architecture

ARIE is an Irish-homeed resale decision engine. It discovers candidate acquisitions, identifies them, values them against evidence, costs a landed Irish exit, and only then considers `BUY_READY`.

```
ingest (API / CSV / manual / URL)
  → identity resolvers + catalogue
  → condition (category defects)
  → sold evidence + asking comps (labelled)
  → robust valuation (weighted median, MAD, percentiles)
  → exit-channel comparison (fees + shipping)
  → tax scenarios + landed cost (existing Decimal margin kernel preserved)
  → liquidity / risk / EV / negotiation / urgency
  → engine decision (BUY/WATCH/IGNORE/REVIEW)
  → money-ready gates → BUY_READY / WATCH / REVIEW / IGNORE
  → paper trade if BUY_READY
  → owner purchase → inventory → sold outcome → calibration
```

Persistence is PostgreSQL. Workers are APScheduler (`scan-live-sources`, `daily-self-audit`). The dashboard is the owner floor.

`ENGINE_DECISION` is a model conclusion. `MONEY_READY_DECISION` is whether the owner should act. A large modelled margin cannot override failed gates.
