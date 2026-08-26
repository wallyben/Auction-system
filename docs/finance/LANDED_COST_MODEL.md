# Landed cost model

All-in acquisition =

purchase (FX-converted) + FX spread + buyer premium + inbound shipping + inbound payment + duty + import VAT (cash) + refurb + auction fee/VAT where applicable.

Net resale comes from the chosen exit quote, not a hard-coded 12.9% + €9.50 stack (those remain the eBay IE / fallback defaults).

Inbound shipping uses corridor bands or the seller's listed postage. Outbound uses category/weight bands (An Post / courier assumptions).

The existing Decimal `margin_engine` still prices auction max hammer.

Invariants: `all_in >= purchase`, `net <= gross`, higher fees cannot raise max buy, higher purchase cannot raise expected profit.
