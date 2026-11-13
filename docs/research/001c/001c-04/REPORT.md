# 001c-04 search, identity and fresh indicative economics

A pricing-qualified opportunity existed at **2026-11-13 02:11:03 UTC**, scoped
to the captured auctions. **No candidate was authorized for a bid and no account
mutation occurred.** Availability, comparable freshness and rules must be checked
again before the later bounded bid test. This report is an observation at the
recorded checkpoint, not an evergreen actionable price.

The exact PC FC27 card/version **227323**, trade
`trade:e32196e4116d4d9e0bdcc192`, physical item
`item:46c98d2eac24cf505500c3cb`, had a native opening price of **700** and BIN
**11,000**. Of 21 exact-version asks captured at 02:09:13 UTC, **12** were still
fresh with more than 30 seconds remaining at evaluation; nine were expiring or
expired. Median/MAD outlier rejection was applied after independent trade/item
deduplication and candidate exclusion. No additional price outlier was rejected
in this particular retained sample. Distinct listings do not prove distinct
sellers; the native projection does not expose seller identity.

The nearest-rank lower quartile, undercut by one native client tick, gave an
indicative target **5,900**. With default **X=500**, projected sale tax is
`floor(5900/20)=295`; the profitable cap is `5900-295-500=5105`, rounded **down to
5,100** on the observed client schedule and bounded by the exact card caps.
Projected profit at an opening 700 bid is **4,905**, conditional on an eventual
sale at that estimated target. It is not realized profit or a sale price.
The search's **maxBid=1000** is an enrollment filter; **5100** is a separate
indicative per-auction cap. A later bidder must use the minimum legal next bid,
not jump to that cap.

The reused estimator's nested `estimate.acquisition_price=11000`,
`expected_profit=-5395` and `meets_threshold=false` describe the candidate's
**BIN purchase reference**, because that estimator was originally written for
Buy Now. The bid assessment separately uses `minimum_client_bid=700` and
`projected_profit_at_minimum=4905`. Neither reference records an actual payment.
The candidate passes the pricing calculation at the checkpoint. No separately
bounded integration-only candidate is needed; `integration_test_candidate` is
null. Ordinary bid/server tick acceptance remains UNVERIFIED, and the probe
cannot dispatch any bid. Unsupported rules cannot authorize a write through the
existing RulesProvider; no LIVE_VERIFIED write-rules artifact was registered.

## Authenticated search and observed contracts

`search-1.json`, `search-2.json` and `search-3.json` contain fresh successful
authenticated PC FC27 native searches with `UTSearchCriteriaDTO.maxBid=1000`
and `minBuy=10500`. Each has an actual GET, presence-only authentication flag,
HTTP 200, safe request query numbers, timestamps, byte length and duration.
Entity projection is checked against a separate projection of the actual XHR
response body before the raw body leaves the page. The retained payload never
contains a credential, cookie, header value or raw item/trade identifier.

Observed native HTTP mapping is **maxBid -> macr**, **minBuy -> minb**,
**maxBuy -> maxb** and exact `defId -> definitionId`. The initial parser's
maxb/micr hypothesis was wrong; the original capture is preserved, and the
validator/tests now require the observed mapping. No source-only mapping is
presented as live proof. All sampled results satisfy starting bid <=1000,
current bid <=1000 and BIN >=10500. Both no-bid/current=0 and already-bid/current
positive rows were observed, so starting and current bid are independently
retained and checked. The minimum opening bid uses startingBid when currentBid
is zero; subsequent minimums use the client increment above currentBid.
This is observed response conformance, not a proof of every unseen boundary
case in EA's filtering implementation. Zero results would be a valid successful
authenticated search; deterministic native/projection tests exercise that case.

Each page requests **21** rows. Page 1 uses `start=0`, page 2 `start=20`:
20 visible rows plus a lookahead. These sequential dynamic reads returned 42
distinct auction IDs and **no overlap**, including no reappearance of page 1's
lookahead. This does not establish disjoint stable pages: 65 seconds elapsed
between the first two reads. All three samples were nondecreasing by expiry,
but server ordering is not guaranteed. `has_more` was null, and market coverage
is incomplete. No claim of market exhaustion or repeatable enrollment supply
follows from these two pages. Repeating page 1 showed four old entries absent,
four new entries and a changed current bid on one retained entry. Missing from
a bounded page cannot distinguish expiry, repricing, movement to another page,
withdrawal or sale. `report.json` enumerates the actual identities and changes.
Fresh exact-version availability reads found the candidate again and preserve
its physical-item identity. `availability-2.json` was less than 21 seconds old
at the pricing checkpoint. It ages out after 30 seconds. Absence, changed price,
changed identity, conflicting rows, expiry and cached reads fail closed.

## Exact identities and native rules

The selected persona projection is native uppercase **PC**, with `isPC=true`
and matching `GamePlatform.PC`. Wire `itemData.resourceId` is the exact card
version exposed by the loaded entity as `definitionId`; wire `assetId` is the
base card. In `search-1.json`, **50573369** is distinct from base asset **241721**.
The validator requires that full version and independently matches trade/item
pseudonyms and starting/current/BIN values. Base asset identity is never used
to combine versions. Wire tradeability is also retained separately from native
entity properties that the original projection could not recognize.

An explicitly bounded native read,
`services.Item.transfersDao.getItemMarketDataByDefId([227323])`, produced an
authenticated GET **/ut/game/fc27/marketdata/pricelimits?defId=227323**, HTTP 200.
Independent wire and native value-band projections agreed on exact-card caps
**minimum=700, maximum=11000** (`rules-and-availability.json`). The preceding
search entities had null embedded price limits; the additional native query
resolved that evidence gap. The current official compiled_2.js DAO method was
reviewed before invocation. It is a read, with no speculative older-game route.

The loaded `UTCurrencyInputControl.PRICE_TIERS` and twelve executions of its
`getIncrementAboveVal`/`getIncrementBelowVal` helpers are retained. The client
uses steps 50 below 1000, 100 below 10000, 250 below 50000, 500 below 100000,
and 1000 above that; it also has a 0-to-150 tier. Boundaries were checked, e.g.
1000 -> above 1100 / below 950 and 10000 -> above 10250 / below 9900. The native
helper returns zero below 150, which must not be conflated with an executable
card price. The same currency input is used in native listing views according
to reviewed public source. That listing usage is **SOURCE_CONFIRMED_ONLY**;
native helper executions are **observed client behavior**. Actual server
acceptance of ordinary bid increments, full listing ticks and tax settlement
is **UNVERIFIED**. No test listing or bid was placed to upgrade those claims.

## Recovery, budget, implementation and verification

AGENTS.md was explicitly read before recovery. This worker established its own
Windows UI Automation access, selected the official EA tab, verified foreground,
loaded and reattached the reviewed isolated read-only extension. The app was
already authenticated. No login, password access or security challenge was
needed. Initial folder/popup foreground checks failed conservatively; the new
UI helper was corrected to verify the modal handle and the Edge popup process.
`edge-*.txt`, `attach-*.txt` and review files retain the sanitized checks.

The final service is **127.0.0.1:8778**, pinned to extension
**coofofjomkjpjbojdkamapbfbcjkpmhn**. Earlier listeners 8776/8777 are left idle;
the same consumed budget was loaded at each transition. Attachment is separate
from persona, authentication and successful native service evidence. The
001c-03 service/budget/evidence were preserved.

Nine of twelve explicit command deliveries were consumed. Eight invoked native
searches, and one of those also read price limits: **nine actual native GETs**.
`comparables-2.json` was rejected by the page's 30-second experiment guard
(29.994-second delivery interval), consumed a delivery, and made **zero** EA
requests. It is retained as a failed capture and is not pricing evidence. The
final host adds a 31-second guard before queueing. This is a local experiment
guard, not a claim about EA rate limits. Commands are delivered once and no
ambiguous command, completed window or consumed budget was replayed/reset.
Unused budget is not permission for an unattended continuation.

`experiments/search_validation_v1/validation.py` is the updated read/query
adapter validator for the observed wire/DTO contracts. `economics.py` reuses
the exact-version estimator with native card caps/client bands; it separates
BIN reference economics from minimum bid economics and always returns
`bid_authorized=false`. The versioned browser probe has no write operation.
Its schema 1/2/3 captures are independently validated, rather than rewriting
older capture bytes after discovering a contract. Prior task files are unchanged.

Run the acceptance checks independently from this workspace:

```
python tests/test_search_validation_v1.py
python tests/test_search_validation_artifacts.py
```

The artifact validator replays freshness at the **recorded evaluation time**,
independently recomputes robust pricing and caps, checks all captured requests,
native/wire identities, read budget, preserved files and unsupported claims.
It does not make new EA calls or claim the checkpoint is still actionable.

Verification results: both task-specific commands passed (10 behavior tests and
7 artifact tests). The complete repository discovery command ran 269 tests:
267 passed; two unchanged `test_browser_access.BrowserAccessTests` checks failed
because retained Objective 001 browser inspection/live-v2 evidence is older than
24 hours (`test_criterion_0_inspection_is_current_and_does_not_assume_cdp` and
`test_review_matches_executed_bridge_sources_and_retained_metadata`). Those
historical files were preserved rather than re-dated. The new authenticated
search captures independently establish this task's own live evidence. Relevant
pricing, bidding-v1, watched-bulk and follow-up tests passed in that discovery.
`git diff --check` passed. Exact results are recorded in `checks.json`.
