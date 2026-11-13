# 001d-04: deterministic completed quotes

The production API is `fc_access/production_v1/pricing.py:PricingService.quote`.
`fc_access/pricing.py` re-exports `PricingService`, `Quote` and `QuoteCache`;
its old `evaluate` implementation is historical experiment/replay code only.
Production never calls that five-sample, MAD, quartile or automatic-undercut
estimator. Shared exact identity, integer tax and historical legality helpers
remain available. Original 001C captures are unchanged.

`fc_access/production_v1/price_cache.py:QuoteCache` stores completed observations
in SQLite table `completed_quotes_v1`. The default workspace-relative database
path is `private-captures/production-v1/completed-quotes.sqlite3` (ignored private
runtime data); an explicit path may be injected. Its primary key is account,
game, platform, exact definition ID. `observed_at` is the first network sample's
time. Validity is exactly `0 <= age < 86400` seconds: the boundary expires, a
backward clock is a miss, and a hit does not renew age. WAL plus synchronous FULL
commits survive process restart. Cache entries also fence evidence source and
identity namespace so fixture results or unrecognizable pseudonyms cannot
silently become native evidence. Owner/document epochs are deliberately not
cache keys. The preceding protocol supports FC27 PC only; other game/platform
inputs fail explicitly rather than sharing this market's cache.

Construction is explicit and starts no work:

```python
from secrets import token_hex
from fc_access.production_v1.pricing import PricingService
from fc_access.production_v1.price_cache import QuoteCache

cache = QuoteCache()  # or an explicit durable workspace path
service = PricingService(adapter, lambda: token_hex(16), cache)
quote = service.quote(candidate_auction_row, native_prices, X=500)
# ... consume quote.resale_price / quote.max_affordable_bid / quote.evidence
cache.close()
```

The adapter is the existing attached `fc_access/production_v1/adapter.py:NativeAdapter`;
native_prices comes from `fc_access/production_v1/prices.py:PriceService.load`.
The injected optional `fetch(command_id, Search)` has exactly the same response
contract as `adapter.search`. Every response is revalidated against the requested
command, full account/persona/fences, authenticated actual route, exact wire
criteria, freshness and cache invalidation in
`fc_access/production_v1/contracts.py:parse_response`. The pricing-only
`pricing_rows=True` mode permits per-row exclusion with reasons; default parsing
and other operations keep strict row validation. Row deferral changes no network
or envelope validation. The production transport store applies that same pricing
mode before retention, replacing unsafe rows with null exclusion markers; their
unknown fields and values are never persisted. Unrecognized/unsafe rows are
excluded, never persisted as comparables. Fetch exceptions are recorded as fixed incomplete reason codes;
arbitrary native exception text is not retained.

On a miss, request one is exact definition, page=1, count=21, fresh=True with no
discovery filters. The minimum is over all valid independent observed BINs,
without assuming any BIN order. Exclusions include the paired startingBid=600 /
buyNowPrice=10000 template, invalid data/ticks, expired/inactive/nontradeable
offers, wrong versions, repeated or conflicting trade/item identities and the
candidate auction/item itself. A genuine cheap offer, including 1500 or 1700,
is retained regardless of its distance from the other offers. A genuine 10000
BIN with another starting bid and a genuine 600 BIN are retained too.

The economic cap is native legal rounding DOWN of
`resale_price - floor(resale_price/20) - X`, with initial X=500. It is not bounded
below by the card's listing minimum. `last_sale_price` is diagnostic only.
The candidate's minimum uses the native absolute next price when currentBid>0,
or its legal startingBid when currentBid=0. A minimum exceeding the first cap
returns REJECT after one search. Equality qualifies for the second request.
An empty/invalid first sample is INCOMPLETE after one request.

Otherwise request two is exactly page=1/count=21/exact definition with inclusive
`max_buy=first_min` (wire `maxb`). There is no pagination, retry or third probe.
The final resale price is the minimum valid BIN across both samples. A successful
empty/equal second sample retains first_min; a lower offer lowers it. Failed,
stale, unauthenticated, mismatched or ambiguous second requests are INCOMPLETE
and cannot enter the completed cache. A final cap may reject the candidate
while the successful two-search quote remains completed and reusable.

Only a successful two-search observation set is committed. Rejection-only
evidence is never promoted to a completed price. Hits perform zero price searches
and recompute the cap with current X and native legality. Comparable IDs remain
separate from the current candidate; if it appeared in cached samples its own
row is removed, and a cache with no remaining independent observation returns
INCOMPLETE without searching. Current native caps/helper checks can still run on
a hit: zero *price searches* does not mean zero local helper evaluations.

`Quote.status` is COMPLETE, REJECT or INCOMPLETE; `Quote.completed` describes
whether both pricing samples succeeded, independently of candidate eligibility.
Evidence includes sample params, network times and ages, returned/per-sample
valid/combined-unique counts, bounded coverage, exclusions, reasons, candidate
identity/last sale diagnostic and accepted independent comparables. Its claim is
only OBSERVED_MINIMUM_ONLY, never global cheapest, realized sale or liquidity.
Twenty-four-hour cached observations may be stale in the real market; that is
the specified reuse policy, not a market completeness guarantee.
Each sample's row validity is checked at its read time; evidence ages continue
to advance while the second read completes. A successful empty second response
preserves the initially valid first observation even if the second read is slow.

The former `fc_access/bidding_v1/rules.py:estimate_cap` and
`fc_access/bidding_v1/adapter.py:bid_once` observation-estimator coupling now
requires a completed Quote, matching account/game/platform/version/source and
TTL, then recomputes the native cap. Legacy observation arrays fail explicitly.
The bounded harness forwards the quote. Existing durable intent, minimum bid,
balance, fresh status and native-source write gates remain. Neither the pricing
API nor cache calls those bid paths, attaches a browser, or starts an actor loop.
No live searches, bids or listings were needed for this implementation.
`migration.json` extends the prior authorized source-change chain for historical
audit readers; no sealed 001C or 001d-01/02/03 evidence was rewritten. Runtime
pricing does not load audit manifests or use file hashes as authorization.

Independent acceptance validator: `python tests/test_001d04_pricing.py`.
It consumes the retained 261855 first page (minimum 1500), tests empty/equal/lower
second samples, row exclusions, one/two/zero request budgets, failed/ambiguous
responses, exact TTL boundary, a separate-interpreter restart, cache isolation,
last-sale independence, evidence and real production adapter integration.
Regression validators: `python tests/test_001d03_native_prices.py`,
`python tests/test_001d02_contract.py`, `python tests/test_bidding_v1.py`,
`python tests/test_durability_v1.py`, `python tests/test_market_pricing.py`.
The unrelated legacy watched-bulk HTTP fixture needs the existing
`tests/run_offline_suite.py` request-coalescing runner on this Windows host;
its direct WinError 10053 result is retained in `validation-08-direct.txt`,
alongside the passing wrapped check. The runner changes no assertions and
does not retry requests. `validation.json` records both invocations.
