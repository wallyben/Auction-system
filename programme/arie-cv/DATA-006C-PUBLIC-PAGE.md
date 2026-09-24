# DATA-006C — public search-page harvest

Recorded 24 September 2026. Native v2 thresholds were not changed. CV-019 cohort 001 was not replayed.

## DATA-006B conclusion

`AUTONOMOUS_INDEX_APPROACH_INSUFFICIENT`. Brave remains URL discovery and diagnostics only. It is not the valuation observation source.

## What ran

Chromium via Playwright opened public search pages from a worker-equivalent container. No stealth, proxy, or challenge bypass. DoneDeal and CarsIreland returned HTTP 403 `BLOCKED_CHALLENGE` and that source stopped. Carzone commercial search pages rendered listing cards. Observations are `PUBLIC_PAGE_CURRENT_UNLICENSED`, technical status `EXPERIMENTAL_PUBLIC_BROWSER`, rights status `UNLICENSED_PUBLIC_WEB`. DoneDeal and Carzone stay `BLOCKED_POLICY` for any licensed feed.

Stage A, Carzone commercials, pages already fetched, year within six of the subject:

| Vehicle | Raw cards | Unique ROI | Mileage known | VAT known | Confidence | Decision usable |
| --- | --- | --- | --- | --- | --- | --- |
| 2018 Transit Custom | 71 | 33 | 33 | 0 | LOW | no |
| 2019 Transit Connect | 54 | 23 | 22 | 0 | LOW | no |
| 2021 Transit | 66 | 45 | 32 | 2 | INSUFFICIENT | no |
| 2023 Partner | 53 | 46 | 34 | 3 | LOW | no |
| 2020 Combo | 8 | 2 | 2 | 0 | LOW | no |

Combo stopped early because a later Carzone page was a challenge. VAT wording is too rare for Native v2 to issue a conservative resale. That is a valuation-evidence limit, not a card-extraction failure.

T426 coverage replay 002 used the frozen pre-bid file `artifacts/runtime/cv019/T426_CV019_INPUT_2026-09-23.txt` (SHA-256 `0501091f9fdcc3268686a4a926d00dc0566638d9e9407b473fb52c6df5036636`). No max-safe hammer was issued. Lot 3 (CAT S) and lot 45 (non-runner) rejected. Crew and tipper lots were not given a panel hammer.
