# Objective 002 — FC27 Two-Actor Competitive-Bidding Bot

**Status:** 001D foundation/final remediation completed and [FC27 bulk-transfer research](../docs/research/002-bulk-transfer-operations/REPORT.md) live-verified; **12 ordered work items**, with item 12 the final integrated real E2E run. No autonomous actors or recurring maintenance jobs have been launched by this specification.

**Repository:** `zrsoo/fc-hustle` (`C:\hustle\fc-hustle`).

## Purpose

Build an autonomous FC27 Ultimate Team **competitive-auction bidding** strategy with **two cooperating actors**, not the earlier generic Buy Now sniping loop:

1. **Bid Acquirer** periodically finds attractive auctions and places the *smallest legal initial bid* to enroll in them.
2. **Bidder** continuously manages already-enrolled auctions, rebidding **only if outbid**, never bidding up to the price cap merely because it is affordable.

A shared durable auction registry, coin/account state and serialized native EA execution queue coordinate the two actors. **Acquire via competitive auction bids only, never acquisition Buy Now.** On confirmed WON, list the exact owned physical card with **Buy Now = stored `resale_price`** and **starting bid = one native legal price increment below `resale_price`**. The same stored resale BIN defines the projected 5%-tax profitability cap.

Objective 001C is already complete: it verified genuine first auction participation, leading HOLD, eventual LOST and available-coin debit/return, but not active personal rebids, competitive wins or sustained actor operation. **001D** owns the pre-actor fixes and read-only investigations; **002** owns the independent Python actors and their naturally occurring live outcomes. Older Buy Now-first acquisition strategies are superseded.

## Initial configurable settings

```yaml
acquirer:
  search_interval_seconds: 600     # Every ~10 minutes; target cadence
  max_search_bid: 1000             # Search filter, not per-auction maximum spend
  min_search_buy_now: 11000        # Search filter, not expected resale value
  min_available_coins: 5000        # Coin-reserve / drain threshold
  max_enrolled_auctions: 50        # Maximum unresolved auctions in shared queue

bidder:
  target_check_interval_seconds: 25
  rebid_only_when_outbid: true
  bid_smallest_legal_increment: true

strategy:
  min_profit_coins: 500            # X; initial default, configurable
  estimated_sale_tax_rate: 0.05
  pricing_method: two_search_minimum_valid_bin
  comparable_page_size: 21
  comparable_extra_searches: 1
  price_cache_ttl_seconds: 86400   # 24h per exact card version + platform

resale:
  buy_now_price: stored_resale_price
  starting_bid: one_native_increment_below_resale_price
  duration_seconds: 3600
  max_transfer_list_occupied: 50
  max_total_pipeline_slots: 50
  bulk_relist_interval_seconds: 3660
  bulk_relist_preserve_prices: true
  bulk_relist_duration_seconds: 3600
  clear_sold_on_detection: true
```

Established numeric settings are configurable with these locked defaults; listing duration and expired/sold handling are no longer TBD. Search filters select candidate auctions, **not** their final bid cap. The 001C experimental 1,000 per-bid limit is not a production constraint. Also enforce the separate 50-slot combined occupied/pending/unresolved capacity rule above, in addition to reserve, queue, profitability and eligibility.

## 002 updated scope — 12 ordered tasks (authoritative, 2026-11-13)

Objective 001D's [final remediation](../docs/research/001d/final-remediation/REPORT.md) is complete (467 Python tests, 15 Node suites, verified read-only live pricing, fresh admission, and status after reconnect). [FC27 bulk-transfer research](../docs/research/002-bulk-transfer-operations/REPORT.md) subsequently verified **one native bulk Clear Sold** (`services.Item.clearSoldItems()` → `DELETE /ut/game/fc27/trade/sold`, five sold removed) and **one native Relist All** (`services.Item.relistExpiredAuctions()` → `PUT /ut/game/fc27/auctionhouse/relist`, four expired relisted at unchanged prices for 3600s). These consumed live research windows are complete and **must not be repeated simply to satisfy item 9**. The original acquisition/price/bidding rules below remain in force **except where expressly updated here**. Items 1–11 are implementation/targeted verification. **Item 12 is the final comprehensive live E2E run**, only after the preceding tasks succeed.

1. **Replace the last EA source-hash gate:** Remove hardcoded `STATUS_SOURCE` / SHA-256 checking of `getAuctionData` function bytes in `browser/production-v1/page.js`; instead validate native function availability, actual authenticated `/trade/status/lite` GET, allowed response schema, exact retained trade/item identity, source freshness, and reconnect behavior. Preserve EA response/log hashes and legitimate runtime identity digests; use behavioral unit tests.
2. **Optimize uncached pricing:** Profile actual EA RTT, queue wait, browser bridge, repeated native price helper calls, SQLite and logging separately; batch `price_helpers` operations (existing up to 32 probes per call), deduplicate BIN values and memoize repeated above/below ticks. Do not alter the agreed **at most two** page-1 exact-version pricing searches, filters, 24h cache, X/tax or native legality checks.
3. **HARD <30-second live gate — STOP ON FAILURE:** After the above optimization, verify a **real, previously uncached** two-search valuation through the actual production Foundation through a **fresh `BID/ELIGIBLE` admission decision (decision only; no bid)** in **strictly less than 30.000 seconds monotonic elapsed** from uncached valuation start to fresh final decision, **including** the actual two EA pricing GETs, helper work, serialized transport, ordinary diagnostic writes, and any necessary fresh auction/credits rechecks. Require genuine cache miss, exact defId/page 1/count 21 and actual `maxb=first_min`; no warmed cache, fixture, skipped freshness, stale HOLD or simulated eligible candidate. **If >=30s, no real eligible case, stale/unknown decision or any failure: report FAILURE/BLOCKED with timing breakdown and STOP ALL FURTHER CODE FIXES AND ITEMS 4–12 until the user instructs otherwise. Do not automatically apply more fixes or rerun this failed acceptance gate.** Profile/optimize offline before that one bounded gate run.
4. **Implement both actual independent Python actors and native-work priority:** Acquirer ~600s and Bidder target ~25s use one durable scoped journal/registry and globally serialized prioritized native executor; yield pricing/maintenance between native commands so urgent watched/rebid/status checks take precedence. Preserve minimum legal rebid, stored profit cap, no blind retry, restart/reconnect and genuine timing measurements.
5. **Enforce strict Transfer List occupancy <=50:** Count **all** Transfer List entries (active, expired unsold, sold uncleared, inactive, pre-existing/manual) from a complete fresh `requestTransferItems()` read. Unknown/truncated/stale/conflicting count means **pause Acquirer**, never optimistic allocation; existing over-cap occupancy is reported, not silently deleted.
6. **Implement atomic combined capacity reservations:** Enforce **`transfer_list_occupied + pending_resale + unresolved_auctions <= 50`** before every new enrollment **in addition** to the separate `unresolved_auctions <=50` queue limit. One unresolved auction (including UNKNOWN or pending intent) reserves one possible win; on confirmed WON atomically move that one reservation to pending resale then occupied on proven transfer-list presence, on LOST release it, and never double count or temporarily unreserve it. Preserve across restarts; 40 occupied + 10 pending/unresolved blocks an eleventh.
7. **Implement Acquirer capacity pause/resume:** Pause new enrollment when combined budget reaches 50 or is unknown; Bidder, resale/relist/clear and reconciliation continue. Resume only after actual confirmed capacity returns (e.g. auction LOST releasing reservation, or sold card **cleared and verified absent**), also respecting existing sticky **5,000-coin DRAINING** which retains precedence. Sale alone doesn't free a Transfer List slot while sold card remains uncleared.
8. **Implement one-hour post-WON sale listing:** After independently verified exact WON physical item and actual paid cost, durably move/list via native APIs for **`duration=3600`**, **`Buy Now=stored resale_price`**, **starting bid = exactly one legal `getIncrementBelowVal(resale_price)` tick**. Validate current card caps, read back exact owned/listed item and new trade identity, never silently undercut/change prices or retry ambiguous writes.
9. **Integrate the ALREADY LIVE-VERIFIED FC27 bulk APIs into the shared production executor:** Reuse [the finished bulk-transfer report and finite harness](../docs/research/002-bulk-transfer-operations/REPORT.md): `services.Item.clearSoldItems()` → `DELETE /ut/game/fc27/trade/sold` and `services.Item.relistExpiredAuctions()` → `PUT /ut/game/fc27/auctionhouse/relist`; each invokes one native bulk mutation and requires independent Transfer List readback. The completed live proof shows five sold removed without touching four expired/three active, and four expired relisted with stable physical identity, unchanged BIN/start, observed 3600s duration and three active untouched. **Do not replay consumed windows or require fresh eligible sold/expired items to rediscover those proven APIs.** Integrate strict context/epoch fences, fresh complete inventory, account-wide/manual-item effects, durable intent-before-dispatch, the single prioritized native executor, independent post-mutation reconciliation, UNKNOWN/no-blind-retry and actual duration checks using behavioral tests. **Relist has no duration request parameter; 3600s is a live-observed server default that MUST be verified on readback for every execution.** No silent per-item fallback. Actual recurring jobs and integrated live verification remain for items 10–12; changed or incompatible future native semantics must fail closed.
10. **Automate bulk relist every 61 minutes:** On each **3660s** maintenance tick, use a fresh complete Transfer List read; if expired unsold cards exist, invoke **one verified native relist-all operation**, re-list **all expired eligible cards at their prior BIN and starting bid for 3600 seconds**, and independently reconcile each new trade/item after durable intent. No eligible items -> logged no-op. Relist does NOT free occupied capacity, and ambiguous result is not blindly retried.
11. **Automatically bulk clear sold on detection:** When a fresh Transfer List observation contains sold items, invoke **one verified native sold-only bulk clear**, then read back that sold entries disappeared and no unsold/expired items were removed; only confirmed freed slots allow Acquirer resumption. Journal and reconcile uncertain results; no per-item fallback.
12. **FINAL integrated LIVE E2E run testing EVERYTHING across Acquirer, Bidder and resale/clearing/relisting:** Only after items 1–11 pass, run **both real Python actors concurrently** against authenticated official FC27 PC, with actual production extension/native executor, durable state, correct request priorities and full regression suite. Verify real discovery, fresh price/cache/coin/capacity admission, initial minimum auction bid, leading HOLD, actual outbid/rebid/cap stop where naturally encountered, terminal WON/LOST, exact physical ownership/paid price, one-hour listing with fixed stored BIN/native previous tick, **expired entry -> actual one-call bulk relist**, **sold entry -> actual one-call bulk clear**, combined 50-slot cap and pause/resume, sticky coin DRAINING, 25s monitoring behavior, restart/reconnect, and realized-profit settlement. **Full E2E PASS requires independent actual native evidence of all named transaction and maintenance branches** (plus offline tests); HTTP 200, fixture tests or an event not witnessed in bounded real trading is **PARTIAL/NOT FULL PASS**, with exact missing proof. Do not manufacture wins, sales, expirations or 50 simultaneous bids to claim completeness.

### Locked 002 resale/capacity behavior

- Every newly won physical card is listed for **3600s**, with BIN **exactly stored `resale_price`** and starting bid **exactly one native legal tick below**. No more `TBD` listing duration or unsold policy.
- Every **3660s** relist **all expired unsold items** at their existing starting bid and BIN for another **3600s**, using **one native bulk write** *if and only if* that exact FC27 behavior has been verified. Account-wide native bulk operations may also affect manually listed cards.
- Whenever sold items appear, clear **all sold entries only** with one FC27 native bulk operation, then independently refresh Transfer List. Sold cards occupy space until actually removed; no per-item fallback when bulk unsupported.
- Combined capacity: **occupied Transfer List (all states, including manual/sold/expired) + pending won-not-listed + unresolved auction reservations <=50**, checked as a prospective post-enrollment count. Also preserve the separate 50-unresolved-auction limit. Unknown capacity fails closed, and moves between buckets are atomic. **A full cap pauses new Acquirer bidding, never Bidder management or selling maintenance.** A verified loss or cleared sold item can release a slot; sticky coin DRAINING remains independent and takes precedence.
- Existing one-hour resale and 61-minute relisting do **not** revalue or adjust the previously chosen `resale_price`. Verify current EA listing legality and readback for each mutation. All bulk writes are guarded by durable intent, single global executor, no blind retry and actual live FC27 capability evidence.
- **The item 3 <30s gate is a hard stop**: if it fails, Codex must report failure and stop *all further code fixes*, not iterate on its own. **Item 12 is always the last, actual full-system E2E test**, including Acquirer, Bidder and selling/relisting/clearing; unobserved outcomes cannot be claimed as PASS.

## Actor 1 — Bid Acquirer

**Ownership:** discovering new auctions, estimating value, determining the maximum profitable acquisition bid and enrolling new auctions.

On its next scheduled acquisition cycle (initially every 600 seconds):

1. Search the authenticated **FC27 PC player transfer market** with `maxBid=1000` and `minBuy=11000` (in EA native criteria terms). Fetch as many qualifying auction candidates as practical, handling bounded pagination, duplicates and search-result ordering. Verify the actual live filter semantics: “maximum bid” and “minimum Buy Now” must not be confused with current bid, starting bid or max BIN.
2. Ignore auctions already enrolled, conclusively resolved, unavailable, ineligible, or without trustworthy pricing; verify the complete fresh Transfer List and combined pipeline capacity before new enrollment.
3. **Pricing lookup through 001D's implemented pricing API and cache (not a second estimator), once per uncached exact card version and platform:** Read a completed price-cache entry if its age is <24 hours (86,400 seconds); reuse it across auctions of that version. Otherwise, issue **one native exact-version PC market search requesting up to 21 rows, page 1 only**, with no sort. Exclude stale, expired, unavailable, duplicate, mismatched-card, invalid and recognizable default 600-starting-bid / 10,000-BIN listings. Compute `first_min = min(valid BIN prices)`; if none exist, skip enrollment. Capture all returned `lastSalePrice` fields as `last_sale_price` for diagnostics **only**, with zero influence on resale target or bid ceiling. There is no minimum sample count, MAD, median, quartile, outlier-based trimming or automatic undercut. **Early reject each auction** if its minimum required legal bid already exceeds the profit cap implied by `first_min`; a lower subsequent BIN cannot make that auction profitable. For a still-eligible auction, issue **exactly one more native search** for the same exact version and PC, **page 1, count 21, `maxBuy=first_min` (inclusive)**, also excluding default templates and other invalid listings. Set `estimated_target_sale = min(first_min, min(valid BIN prices from second search))`, falling back to `first_min` when the second returns no valid offers. **Stop: no additional pages, price sorting or progressive probes.** Persist a completed cache entry for 24 hours keyed by account/game/platform and exact version, storing the final resale price, timestamp, raw/sample count, and observed-min evidence. Early-rejected first-page-only observations must **not** be misrepresented as fully evaluated cache entries (they may be stored as a rejection-only upper bound). One completed cache hit requires zero valuation searches; an early rejection requires at most one; an uncached eligible version requires at most two. Cache hits still require fresh auction identity/leading status and actual spendable funds before bidding. Treat the cached price as the chosen 24h pricing policy even though the market may have moved; never pretend it is a fresh market-wide minimum.
4. Calculate the auction's maximum acceptable final bid (coin integer):

   `max_affordable_bid = estimated_target_sale - floor(estimated_target_sale / 20) - X`

   Round **down** to the applicable legal bid increment (not universally hundreds; the 001C 750→800 example uses a 50-coin step) and respect exact-card price restrictions as verified by Objective 001C. Require a viable bid above the current/starting auction requirement. Treat expected profit as **projected**, never realized.
5. If admissible **and one pipeline slot has been atomically reserved**, place **only the minimum legal first participation auction bid**: native `startingBid` when current bid is zero, otherwise the absolute next price from `UTCurrencyInputControl.getIncrementAboveVal(currentBid)` (do not add the current bid again). Do not jump to the calculated cap. Freshly verify actual auction identity, price, expiry, funds and legal price before calling `services.Item.bid(item, amount)`; independently reconcile the result. No acquisition Buy Now purchase.
6. Add the auction to the shared registry upon confirmed enrollment, storing exact card version, auction identity, current bid, our bid, max cap, estimated target resale, X, timestamps and unresolved status. Prevent duplicate enrollment or write retries on ambiguous outcomes.
7. Continue through candidates, yielding to the higher-priority Bidder when API work conflicts, until no eligible opportunities remain or an admission limit is reached. The 10-minute cadence is a **cycle scheduling target**, not a promise that a potentially long acquisition batch completes within ten minutes.

### Admission limits and draining

- **Queue cap:** A maximum of **50 unresolved enrolled auctions** by default. Leading, outbid, cap-exhausted and outcome-unknown auctions all occupy slots until their **win/loss is confirmed**. At capacity, pause new enrollment; slots reopening can be used on a subsequent eligible acquisition cycle.
- **Coin floor:** Default **5,000 spendable coins**. Do not enroll if an initial bid would violate the admission reserve, and never treat coin escrow or pending bid returns as freely available funds without verified account semantics. Once the available balance reaches the threshold (or the reserve prevents further enrollment), enter **DRAINING**.
- **DRAINING is sticky:** While draining, the Acquirer creates **no new auction enrollments**, even if the coin balance temporarily increases or queue slots open. Let the entire enrolled queue resolve **WON or LOST** first. Then exit draining; admission resumes only on a future acquisition cycle **if the reserve test passes**. If coins remain too low, stay paused.
- The coin floor governs **new enrollment only**. It does **not** stop the Bidder from managing existing auctions; the Bidder still obeys each auction's profit cap and actual spendable-balance constraints.
- If the queue cap, combined selling-capacity limit and coin threshold coincide, **coin DRAINING takes precedence**; capacity pause separately resumes only after confirmed free space.

### Valuation validation requirement

The acquisition discovery filter (`maxBid=1000`, `minBuy=11000`) **does not apply to comparable pricing searches**. Reuse 001D's exact two-search pricing API; 002 must not add further queries. Pricing always uses the exact-version PC `maxBuy` filter only on its second search; both searches are fixed to page 1 and at most 21 returned rows each. The second `maxBuy=first_min` is intentionally **inclusive**; if the returned page contains only listings priced at `first_min`, the result remains `first_min`. Do not assume EA sorts by BIN or that two pages cover the entire market. The accepted risk is that a cheaper listing may exist outside both samples or the cache may become stale during its 24-hour TTL.

Validate on the retained 001C version-261855 first-page fixture: the cheapest valid BIN was 1,500 even though the old estimator returned 2,800. With an empty/equally priced second search, the result must remain 1,500; a genuinely cheaper second-search BIN lowers it. Validate first-page early rejection, equivalent-card cache reuse, TTL expiry, no valid comparables, excluded 600/10,000 defaults, partial rejection-only evidence, unsorted pages and second-request exactly-once behavior. `last_sale_price` must be recorded but must not affect either calculation. The production two-search estimator and completed 24-hour cache were delivered by 001D and live read-only verified in final remediation; Objective 002 must reuse, not reimplement, them. Preserve safe identity, legal-price/tax helpers and historical 001C evidence.

## Actor 2 — Bidder

**Ownership:** monitoring and competing on auctions already enrolled. Target refreshing the *shared enrolled-auction queue* every **25 seconds**, subject to actual verified EA APIs, elapsed time, request pacing and auction count. It is **not** permission to issue 50 requests every 25 seconds.

For each unresolved auction, prioritize those approaching expiration:

1. Obtain an authoritative fresh auction/bid-state observation (including our leading/outbid status, current bid, required next bid and remaining time). Reconcile ambiguous bid acknowledgments before taking further action.
2. **If we are leading:** do nothing. Never increase our own bid just because we can afford a higher price or time is running out.
3. **If outbid:** determine the **smallest legal next bid** required to regain the lead. Bid *only* if it is at or below the auction's stored maximum profitable cap, the auction is still active, and we have sufficient actually spendable coins.
4. **If the next legal bid exceeds the cap:** stop competing. Continue to track this auction to a confirmed terminal result; don't free its queue slot prematurely.
5. **If lost:** record the terminal loss, reconcile any returned funds, then release the queue slot.
6. **If won:** prove exact acquired physical item and actual price via fresh reads; release auction queue slot only on confirmed terminal result and atomically transfer its pipeline reservation to pending resale before the one-hour listing workflow.
7. When an auction is uncertain due to timeout, lost connectivity, restart, stale data or conflicting identity, mark it **UNKNOWN / RECONCILING**. Do not repeat a potentially successful bid blindly.

**Illustrative invariant:** If our current leading bid is 3,000 coins and the computed cap is 6,000, **do nothing**. If outbid at 3,100, offer only the minimum legal amount needed to lead again; if the required bid would be 6,100, do not bid.

The alleged 30-second near-expiry reset remains LIVE-UNVERIFIED. A sustained 25-second whole-queue Bidder was not demonstrated by 001C. **002**, with actors running, must measure natural expiry changes and true independent polling intervals; these are not 001D prerequisites or guaranteed EA behavior.

## Shared components and invariants

- **Single source of truth:** durable shared auction registry keyed by account/game/platform and actual auction identity. Prevent the two actors from racing, double-enrolling or duplicating bids. Preserve exact player-version/auction/physical-item separation and stable identity across restarts.
- **Serialized EA request execution:** One Edge-native bridge and one globally prioritized executor: Bidder watched/rebid/urgent reconciliation always outranks acquisition pricing, transfer-list maintenance and relist/clear. Yield between pricing native requests so valuation cannot monopolize the targeted 25s Bidder cycle; preserve durable intent and no blind retry.
- **Bid price cap:** Persist 001D's cached `resale_price`, projected 5% tax and X at admission. Use EA-native card caps and tick helpers, **not** the static artifact-hash RulesProvider. Revaluation may lower an enrolled cap, never raise it (including on competitor bids); downward legal rounding must not increase it.
- **Coin accounting:** track spendable balance, the economics of held bids, refund/outbid behavior and unresolved bid intents using live verified semantics; do not double-count committed or returned funds. New enrollment uses the 5,000-coin admission reserve; existing bids may continue within available funds and their caps.
- **Auction outcomes and resale:** On independently confirmed competitive WON, prove physical item/paid cost, move if needed and list via `services.Item.list(item, startingBid, stored_resale_price, 3600)` with startingBid exactly `getIncrementBelowVal(stored_resale_price)` and legal card limits; independently read back each mutation/new listing. An invalid pair is UNLISTABLE, not a reason to alter prices. Auto-clear sold items on detection and relist all expired every 3660s at original prices/3600s using **live-verified single native bulk calls** only; LOST never lists.
- **Recovery:** intent-before-dispatch, timestamps, epochs, duplicate suppression, unknown-vs-lost-vs-won distinction, restart reconciliation and account/session scope checking. An absent auction in a limited search page alone does not prove a loss or win.
- **Evidence and ownership:** Native EA card caps, 750→800 accepted first bid, fresh INBOX-dirty watched GET, `/user/credits`, leading HOLD and terminal LOST were witnessed in 001C. **001D** integrates the reusable production rules and read APIs; **002** validates active personal rebid, competitive WON/ownership/listing, arbitrary enrolled-trade status, sustained 25-second/50-slot coverage and settled sales. All remain LIVE-UNVERIFIED until naturally witnessed. FC27 exact-version PC BIN asks remain the valuation baseline; external price providers are not required.
- **Account/service restrictions:** automated trading may violate EA rules and lead to account sanctions; no safe EA request frequency has been established. Preserve failure/backoff and ordinary authentication behavior. Do not attempt detection circumvention or access-control bypass.

## Persistent per-auction diagnostic logging (mandatory)

The durable auction registry is the **current state**; separately maintain an **append-only, queryable event history** so each auction can be reconstructed from discovery to terminal outcome across restarts. Logging is part of the execution contract, not optional debug console output.

- **Persistence:** Use a transactional SQLite event journal (or equivalently durable append-only store), with ordered event IDs, UTC timestamps, process/session epoch, actor name, correlation/auction ID, command/intent ID, event type, state before/after and outcome. Make critical bid-intent and state writes atomic or transactionally linked, fsync/durable before dispatch; retain events through restarts, crashes and reconciliation. Never silently overwrite earlier events. If required intent/journal persistence fails, block new bid writes rather than executing untraceable actions.
- **Discovery and admission:** Record search criteria and freshness, observed auction/bid/BIN/expiry and exact card version; raw comparable prices and `last_sale_price`, fixed one-/two-request search count, cache key/age/hit/miss, first/second sample count, exclusions/invalid reasons, observed minimum BIN, early-rejection reason, resale estimate, calculated 5% tax and X, rounded bid cap, queue occupancy, spendable coins and reserve state. Record a **reason code for every relevant action or skip** (e.g., insufficient comparables, price-cap exceeded, leading already, low balance, queue full, DRAINING, expired, ineligible or stale).
- **Every bidding decision:** Log leading/outbid status and its source/time, current highest/our last bid, required minimum next bid, configured maximum, expiry remaining, actual available balance and whether the decision was **BID, HOLD, STOP_COMPETING or RECONCILE**. A leading 3,000 bid with a 6,000 cap should leave an explicit HOLD event, not an unexplained absence of a bid.
- **Every native operation:** Persist the exact intended operation and sanitized request parameters before it is dispatched; record dispatch time, response status and allowlisted EA error code, result timing, callback uncertainty and independent fresh readback. Correlate events through retries/reconnects/late responses so duplicate bids and lost acknowledgements can be diagnosed. An HTTP 200/callback is **not** proof of a successful bid, win or settlement.
- **Lifecycle and economics:** Journal the three combined capacity counters, reservation transfers, capacity pause/resume and coin DRAINING; every bid, outcome, owned card/actual cost, one-hour listing, sold bulk clear and every-61-minute expired bulk relist with exact affected items/readbacks; log realized profit only from actual settled proceeds, not projections.
- **Operator diagnostics:** Provide CLI/query commands to view one auction's complete timeline, all decisions in a time window, current unresolved auctions and the reasons for blocked bidding; export a sanitized machine-readable trace suitable for postmortems. Logs must never contain EA session tokens, raw credentials, cookies or arbitrary native response bodies. Maintain stable local correlation across process restart, with account scope checking. Keep retention configurable but never prune unresolved intents or evidence needed for settlement/recovery.

**Acceptance examples:** Replaying the event journal must explain (1) why auction A was enrolled, (2) why a leading bid was held without raising, (3) why an outbid triggered the minimum-increment rebid or exceeded the cap, (4) why the Acquirer entered DRAINING, and (5) why an auction ended WON/LOST/UNKNOWN and how that was verified. Simulate a crash between intent persistence and EA response; the recovered timeline must preserve the unresolved intent and show reconciliation without another blind bid.

## Intended actor coordination

```text
Acquirer (every ~600 sec):
    get fresh complete Transfer List and durable pending/unresolved reservations
    if coin DRAINING or unresolved >= 50 or combined occupied+pending+unresolved >= 50
       or capacity UNKNOWN: pause new enrollment
    else: discover maxBid=1000, minBuy=11000
          price using cached or two-search uncached valuation with Bidder priority
          atomically reserve one potential win, bid smallest legal first bid,
          independently reconcile, no duplicate/ambiguous retries

Bidder (independent target ~25 sec):
    fresh bulk watched status for unresolved enrolled auctions
    leading => HOLD; outbid => smallest legal next bid if <= stored cap and spendable
    LOST => release unresolved reservation
    WON => prove exact owned card and paid cost; atomically move reservation
           unresolved -> pending resale -> Transfer List occupied upon readback
    UNKNOWN => reconcile, no blind retry

Transfer List maintenance (same prioritized native executor):
    detected sold => one verified sold-only bulk clear, then fresh slot readback
    every 3660s => one verified bulk relist of all expired items at existing prices,
                  with new 3600s duration, then fresh item/trade readback

Sticky coin DRAINING does not clear when capacity returns; only after all
unresolved auctions end WON/LOST and funds permit at a subsequent cycle.
```

## Relationship to completed 001C and new 001D

- **001:** A successful native Buy Now acquisition → transfer-list move → listing, but not a competitive win.
- **001B:** Native PC persona, market search and local long-poll research; old Buy Now-first strategy superseded.
- **001C:** Completed with CONDITIONAL GO for foundation reuse. Real 800 minimum participation, leading/HOLD, and eventual LOST with spendable-coin return were proved; natural active outbid→rebid, competitive WON, sale, timer extension, sustained 25-second actor processing and 50-live-auction completeness were NOT observed. See [001C capability matrix](../docs/research/001c-capability-matrix.md) and [architecture handoff](../docs/research/001c-architecture-handoff.md). Ignore its obsolete five/MAD pricing, 10500 discovery threshold, static artifact gate and experimental per-bid ceiling in production.
- **[001D](001d-pre-actor-integration-readiness.md):** Pre-actor fixes: unify native adapter/route semantics including current `/user/credits`, native caps/increment helpers instead of static reviewed-hash RulesProvider, two-query minimum-valid-BIN price service and 24-hour completed cache, fresh dirty watched/owned reads, reusable one-shot journal/scheduler, bounded read-only known-trade status investigation and listing-price tick validation. **No live trading or actor loops**.
- **002:** Implement standalone Python Acquirer/Bidder with shared serialized prioritized native execution and durable account state; handle actual bidding, winning, moving, listing and actor-dependent live validation. An unwitnessed naturally occurring event stays LIVE-UNVERIFIED, not a reason to re-open 001D.

## Actor-dependent investigations and exact validation paths (002 only)

1. **Personal active outbid→rebid:** In the real Bidder use `repositories.Item.setDirty(ItemPile.INBOX)` then `services.Item.requestWatchedItems()`; for an actual enrolled active/outbid trade, use native absolute `getIncrementAboveVal(currentBid)`, stored profitable cap and actual spendable coins, call `services.Item.bid(item, amount)`, independently read back watched and `/user/credits`. 001C verified opening/HOLD, not a real rebid.
2. **Competitive WON→owned→move/list:** Treat closed/highest/native `isWon()` as a candidate; prove the exact physical card with fresh PURCHASED-dirty `requestUnassignedItems()`/owned pile plus auction-paid amount/coin evidence before move/list. Use the historically verified native `Item.move`/`Item.list` operation types and TRANSFER-dirty `requestTransferItems()` for listing confirmation. Competitive win settlement is not yet live-proven.
3. **Known auction status when watched coverage is missing:** Use 001D's scoped investigation of `services.Item.transfersDao.getAuctionData` / `/trade/status/lite`, previously exercised for one historical ID; validate support for real 002 enrolled trade IDs. Lite `definition_id=0` means omitted, not conflicting. Missing/inconclusive status stays UNKNOWN.
4. **25-second refresh and capacity:** Run the actual independent Python Bidder under concurrent Acquirer activity; measure start-to-start intervals, EA request fanout, fresh bulk watched coverage, deadline misses/reconnect and queue growth. 001C tested 50-row fixtures, but only empty/one-item native reads; do not fabricate 50 actual bids to claim coverage.
5. **Expiry/funds:** Instrument natural near-expiry pre/post timestamps and actual spendable credits; no established 30-second reset or complete transient escrow/refund timing.
6. **Settlement/unsold cards:** Observe attributable card sales/coin proceeds before claiming realized profit; **duration=3600s, every-3660s relist-all expired at original prices for 3600s, and sold-only bulk clear on detection are locked**. The exact FC27 single-operation bulk semantics have been live-verified in [the bulk-transfer report](../docs/research/002-bulk-transfer-operations/REPORT.md); item 9 integrates these established contracts into the production executor rather than repeating consumed experiments.

Every remaining investigation must identify its exact API and needed real event; missing natural events are reported LIVE-UNVERIFIED, not fictional success or open-ended research prerequisites.

## Objective 002 deliverables, when executed later

1. Working configurable **Bid Acquirer** and **Bidder** actors running concurrently through a single prioritized EA command queue.
2. Durable registry for up to the configurable queue limit, exact bid caps, auction state, operation intents, spendable funds/coin reserve and draining mode across restart/reconnect.
3. Reuse 001D's production bridge, runtime native legal prices, two-query min-BIN valuation/24h cache, fresh balance/watch/status and conditional bid APIs; never recreate MAD/five-comparable valuation or static signed-rule gates.
4. Verified outcome lifecycle: first auction bid → leading/outbid → optional minimum-increment rebids → confirmed won/lost → exact won-card move/list with **Buy Now = stored resale_price, starting bid = previous native legal tick**, and no unnecessary bids while leading.
5. Operator configuration, current queue/coins/actor status, **persistent per-auction event journal** and structured execution/profit records, with queryable human-readable timelines and sanitized trace export.
6. Deterministic test coverage for two-request minimum-BIN valuation (default 600/10,000 listings, high ask clusters, genuine low BIN listings, first-page early rejection, no valid samples, empty/equal/cheaper second result, strict max-two-page-1 searches, inclusive `maxBuy`, 24-hour exact-version PC cache hit/expiry, unsorted paging, `last_sale_price` logged but never used), cap equality/rounding, winning-at-low-bid behavior, outbid competitions, losing over cap, 50-slot unresolved auction queue saturation, independent 50-slot occupied+pending+unresolved capacity, atomic reservation transitions, sold-only clear and 61-minute bulk relist with 3600s duration, 5,000-coin DRAINING stickiness, balance changes, simultaneous actor requests, stale status, restart/unknown responses, chronological reason-coded bid decisions, crash-safe event replay/reconciliation, and won-item handoff.
7. Targeted actor-dependent live validation followed by **item 12's final comprehensive real E2E run** across both actors and transfer-list listing, relist and clearing; never infer success from an HTTP acknowledgement alone, and record projected profit separately from realized settled profit.

**Acceptance:** Items 1–11 pass (item 3 must meet real strict <30s uncached valuation-to-fresh-eligible-decision or STOP further fixes), separate auction queue <=50 and combined occupied+pending+unresolved <=50, sticky coin DRAINING preserved, single-operation FC27 bulk clear/relist verified, one-hour fixed-price listing enforced. **Item 12 must be the final comprehensive actual-live E2E run across Acquirer, Bidder and resale/relisting/clearing**; unobserved required events mean PARTIAL, not FULL PASS.

## Out of scope / decisions deferred

No additional trading strategies, bid sniping variants, portfolio allocation optimization, third-party subscriptions or unapproved per-item fallback for bulk operations. **001D is complete**; 002 implements the 12 ordered tasks above. **One-hour listing, every-61-minute bulk relist at existing prices, sold-only bulk clearing and combined 50-slot capacity are decided**; FC27 native bulk clear/relist support is verified by the linked report, while production integration, scheduled jobs and final concurrent-actor E2E remain items 9–12. **Committing this file starts no actors and executes no trades.**
