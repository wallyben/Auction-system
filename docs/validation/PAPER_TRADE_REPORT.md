# Paper trade report

Paper trades open only on `BUY_READY`. No fabricated dispositions.

At completion, live scans produced no `BUY_READY` rows, so the paper book is empty or contains only later owner-triggered rows.

`python3 -m app.cli paper-trade` writes `artifacts/paper_trade_results.json`.
