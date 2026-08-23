# Exit channel model

ARIE does not assume a single Irish resale price.

Channels compared (category-filtered): eBay IE, eBay GB, local IE, Cardmarket, Discogs, Reverb, CeX trade-in, auction, dealer.

Each quote: gross (channel haircut) − versioned fee − payment − outbound shipping − returns allowance = net. Days and a safety score are attached.

Outputs: `best_expected_exit`, `fastest_exit`, `safest_exit`, `highest_net_exit`.

Fee rules carry `source`, `effective_from`, `last_verified`, `jurisdiction`, `category_scope`. They are not invoices.
