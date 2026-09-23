# Native Irish market engine

Version `arie-native-v1`. Asking-to-achievable model `asking-haircut-v1`.

This is the estimator ARIE uses for routine commercial-van valuation. Cartell, Brego, MotorCheck, and MTP are not called. A paid figure can be stored later with `compare_valuations` for calibration. Those rows are not training data.

## Source

Autoza search, `GET https://autoza.ie/api/v1/vehicles`, OpenAPI retrieved 2026-09-23. No API key for basic search. The worker sends `body_type=van` plus make and model. It does not fetch HTML.

The query plan takes vans already on the candidate board first, then rotates through the common van families, four searches per refresh. Pages pause for two seconds. At most two pages of 50 are read per search. A partial or failed refresh does not mark missing listings as disappeared, and disappearance is never stored as a sale.

Registration, VIN, VAT, wheelbase, and generation are stored only when the payload contains them. The current summary schema does not include registration or VAT, so those stay unknown. Unknown VAT caps confidence at 0.55, below the shadow-candidate floor.

`CV_AUTOZA=0` turns the refresh off.

## Estimator

1. Keep the latest fresh observation per listing.
2. Reject a different family, passenger or crew title, salvage, non-runner, generation mismatch, body mismatch, fuel mismatch, wheelbase mismatch, a year gap over six, or a mileage ratio outside 0.45 to 2.2.
3. Count one registration once. Count one named dealer plus year, mileage, and price once. The same specification without a registration or dealer name is not collapsed.
4. Put prices on one VAT basis. A single basis is left as stated. Mixed exclusive and inclusive prices are converted to VAT-inclusive euro at 23%. Unknown-VAT rows are left out of that central estimate.
5. Drop modified-z outliers above 3.5 when there is a non-zero median absolute deviation.
6. Take the score-weighted median, and the 20th and 80th percentiles.
7. When the percentile gap is under €200, amounts stay in cents. Wider books round to €100, and books wider than €2,000 round to €250.
8. Subtract the asking haircut. The base is 15% while realised Irish sales are fewer than three. It can widen to 30% when listings are old or repeatedly cut. The haircut is an estimate.
9. Conservative resale is the lower of the achievable value and the lower quartile of haircut prices. Quick sale takes a further liquidity haircut. It is not the lowest asking price. Trade downside is the 10th percentile of those haircut prices.
10. Withhold every resale figure when the book is older than 14 days, or when fewer than five comps remain and fewer than three of them are close.

Liquidity labels stay `DEEP`, `ADEQUATE`, `THIN`, `ILLIQUID`, and `UNKNOWN`, from active supply and median listing age. A shadow candidate still needs adequate or deep liquidity, eight eligible comps, five close comps, and confidence of at least 0.60.

## Not in this model

Revenue OMSP is not fetched and is not a resale price. Machine-learning models are not fitted. There is no measured sold-price error yet, so certification stays `NOT_STARTED`.
