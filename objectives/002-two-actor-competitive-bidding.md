# Objective 002 — FC27 Two-Actor Competitive-Bidding Bot

**Status:** Strategy locked (v0), not submitted for execution. Objective 001C finished with CONDITIONAL GO for foundation reuse. Implement the autonomous actors after [Objective 001D](001d-pre-actor-integration-readiness.md) delivers the integrated pre-actor foundation; actor-dependent live validation belongs to 002.

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
  duration_seconds: TBD             # Select before live resale
  unsold_handling: TBD              # Select before unattended relisting
```

Established numeric settings are configurable, with these defaults; TBD fields remain undecided. Search filters select candidate auctions, **not** their final bid cap. The 001C experimental 1,000 per-bid limit is not a production constraint. Do not introduce extra arbitrary limits on enrollment other than the configured coin reserve, queue capacity, profitability and availability of qualifying auctions.

## Actor 1 — Bid Acquirer

**Ownership:** discovering new auctions, estimating value, determining the maximum profitable acquisition bid and enrolling new auctions.

On its next scheduled acquisition cycle (initially every 600 seconds):

1. Search the authenticated **FC27 PC player transfer market** with `maxBid=1000` and `minBuy=11000` (in EA native criteria terms). Fetch as many qualifying auction candidates as practical, handling bounded pagination, duplicates and search-result ordering. Verify the actual live filter semantics: “maximum bid” and “minimum Buy Now” must not be confused with current bid, starting bid or max BIN.
2. Ignore auctions already enrolled, conclusively resolved, unavailable, ineligible, or without trustworthy pricing.
3. **Pricing lookup through 001D's implemented pricing API and cache (not a second estimator), once per uncached exact card version and platform:** Read a completed price-cache entry if its age is <24 hours (86,400 seconds); reuse it across auctions of that version. Otherwise, issue **one native exact-version PC market search requesting up to 21 rows, page 1 only**, with no sort. Exclude stale, expired, unavailable, duplicate, mismatched-card, invalid and recognizable default 600-starting-bid / 10,000-BIN listings. Compute `first_min = min(valid BIN prices)`; if none exist, skip enrollment. Capture all returned `lastSalePrice` fields as `last_sale_price` for diagnostics **only**, with zero influence on resale target or bid ceiling. There is no minimum sample count, MAD, median, quartile, outlier-based trimming or automatic undercut. **Early reject each auction** if its minimum required legal bid already exceeds the profit cap implied by `first_min`; a lower subsequent BIN cannot make that auction profitable. For a still-eligible auction, issue **exactly one more native search** for the same exact version and PC, **page 1, count 21, `maxBuy=first_min` (inclusive)**, also excluding default templates and other invalid listings. Set `estimated_target_sale = min(first_min, min(valid BIN prices from second search))`, falling back to `first_min` when the second returns no valid offers. **Stop: no additional pages, price sorting or progressive probes.** Persist a completed cache entry for 24 hours keyed by account/game/platform and exact version, storing the final resale price, timestamp, raw/sample count, and observed-min evidence. Early-rejected first-page-only observations must **not** be misrepresented as fully evaluated cache entries (they may be stored as a rejection-only upper bound). One completed cache hit requires zero valuation searches; an early rejection requires at most one; an uncached eligible version requires at most two. Cache hits still require fresh auction identity/leading status and actual spendable funds before bidding. Treat the cached price as the chosen 24h pricing policy even though the market may have moved; never pretend it is a fresh market-wide minimum.
4. Calculate the auction's maximum acceptable final bid (coin integer):

   `max_affordable_bid = estimated_target_sale - floor(estimated_target_sale / 20) - X`

   Round **down** to the applicable legal bid increment (not universally hundreds; the 001C 750→800 example uses a 50-coin step) and respect exact-card price restrictions as verified by Objective 001C. Require a viable bid above the current/starting auction requirement. Treat expected profit as **projected**, never realized.
5. If admissible, place **only the minimum legal first participation auction bid**: native `startingBid` when current bid is zero, otherwise the absolute next price from `UTCurrencyInputControl.getIncrementAboveVal(currentBid)` (do not add the current bid again). Do not jump to the calculated cap. Freshly verify actual auction identity, price, expiry, funds and legal price before calling `services.Item.bid(item, amount)`; independently reconcile the result. No acquisition Buy Now purchase.
6. Add the auction to the shared registry upon confirmed enrollment, storing exact card version, auction identity, current bid, our bid, max cap, estimated target resale, X, timestamps and unresolved status. Prevent duplicate enrollment or write retries on ambiguous outcomes.
7. Continue through candidates, yielding to the higher-priority Bidder when API work conflicts, until no eligible opportunities remain or an admission limit is reached. The 10-minute cadence is a **cycle scheduling target**, not a promise that a potentially long acquisition batch completes within ten minutes.

### Admission limits and draining

- **Queue cap:** A maximum of **50 unresolved enrolled auctions** by default. Leading, outbid, cap-exhausted and outcome-unknown auctions all occupy slots until their **win/loss is confirmed**. At capacity, pause new enrollment; slots reopening can be used on a subsequent eligible acquisition cycle.
- **Coin floor:** Default **5,000 spendable coins**. Do not enroll if an initial bid would violate the admission reserve, and never treat coin escrow or pending bid returns as freely available funds without verified account semantics. Once the available balance reaches the threshold (or the reserve prevents further enrollment), enter **DRAINING**.
- **DRAINING is sticky:** While draining, the Acquirer creates **no new auction enrollments**, even if the coin balance temporarily increases or queue slots open. Let the entire enrolled queue resolve **WON or LOST** first. Then exit draining; admission resumes only on a future acquisition cycle **if the reserve test passes**. If coins remain too low, stay paused.
- The coin floor governs **new enrollment only**. It does **not** stop the Bidder from managing existing auctions; the Bidder still obeys each auction's profit cap and actual spendable-balance constraints.
- If both the queue cap and coin threshold apply, **DRAINING takes precedence**.

### Valuation validation requirement

The acquisition discovery filter (`maxBid=1000`, `minBuy=11000`) **does not apply to comparable pricing searches**. Reuse 001D's exact two-search pricing API; 002 must not add further queries. Pricing always uses the exact-version PC `maxBuy` filter only on its second search; both searches are fixed to page 1 and at most 21 returned rows each. The second `maxBuy=first_min` is intentionally **inclusive**; if the returned page contains only listings priced at `first_min`, the result remains `first_min`. Do not assume EA sorts by BIN or that two pages cover the entire market. The accepted risk is that a cheaper listing may exist outside both samples or the cache may become stale during its 24-hour TTL.

Validate on the retained 001C version-261855 first-page fixture: the cheapest valid BIN was 1,500 even though the old estimator returned 2,800. With an empty/equally priced second search, the result must remain 1,500; a genuinely cheaper second-search BIN lowers it. Validate first-page early rejection, equivalent-card cache reuse, TTL expiry, no valid comparables, excluded 600/10,000 defaults, partial rejection-only evidence, unsorted pages and second-request exactly-once behavior. `last_sale_price` must be recorded but must not affect either calculation. The algorithm replaces, rather than calls, the legacy MAD estimator in `fc_access/pricing.py`; preserve safe identity, legal-price and tax helpers. Do not rewrite the historic 001C evidence or claim the production estimator has already been updated.

## Actor 2 — Bidder

**Ownership:** monitoring and competing on auctions already enrolled. Target refreshing the *shared enrolled-auction queue* every **25 seconds**, subject to actual verified EA APIs, elapsed time, request pacing and auction count. It is **not** permission to issue 50 requests every 25 seconds.

For each unresolved auction, prioritize those approaching expiration:

1. Obtain an authoritative fresh auction/bid-state observation (including our leading/outbid status, current bid, required next bid and remaining time). Reconcile ambiguous bid acknowledgments before taking further action.
2. **If we are leading:** do nothing. Never increase our own bid just because we can afford a higher price or time is running out.
3. **If outbid:** determine the **smallest legal next bid** required to regain the lead. Bid *only* if it is at or below the auction's stored maximum profitable cap, the auction is still active, and we have sufficient actually spendable coins.
4. **If the next legal bid exceeds the cap:** stop competing. Continue to track this auction to a confirmed terminal result; don't free its queue slot prematurely.
5. **If lost:** record the terminal loss, reconcile any returned funds, then release the queue slot.
6. **If won:** prove the acquired physical item and final actual acquisition price through fresh account/auction readbacks. Release the queue slot only once the terminal result is confirmed; hand the item to the resale workflow.
7. When an auction is uncertain due to timeout, lost connectivity, restart, stale data or conflicting identity, mark it **UNKNOWN / RECONCILING**. Do not repeat a potentially successful bid blindly.

**Illustrative invariant:** If our current leading bid is 3,000 coins and the computed cap is 6,000, **do nothing**. If outbid at 3,100, offer only the minimum legal amount needed to lead again; if the required bid would be 6,100, do not bid.

The alleged 30-second near-expiry reset remains LIVE-UNVERIFIED. A sustained 25-second whole-queue Bidder was not demonstrated by 001C. **002**, with actors running, must measure natural expiry changes and true independent polling intervals; these are not 001D prerequisites or guaranteed EA behavior.

## Shared components and invariants

- **Single source of truth:** durable shared auction registry keyed by account/game/platform and actual auction identity. Prevent the two actors from racing, double-enrolling or duplicating bids. Preserve exact player-version/auction/physical-item separation and stable identity across restarts.
- **Serialized EA request execution:** one reviewed local Edge-native bridge and global prioritized command scheduler. Active-auction reconciliation and urgent Bidder operations take precedence over new acquisitions; do not starve recovery or post-win listing. Local long polling may deliver immediately, but EA request scheduling is independent.
- **Bid price cap:** Persist 001D's cached `resale_price`, projected 5% tax and X at admission. Use EA-native card caps and tick helpers, **not** the static artifact-hash RulesProvider. Revaluation may lower an enrolled cap, never raise it (including on competitor bids); downward legal rounding must not increase it.
- **Coin accounting:** track spendable balance, the economics of held bids, refund/outbid behavior and unresolved bid intents using live verified semantics; do not double-count committed or returned funds. New enrollment uses the 5,000-coin admission reserve; existing bids may continue within available funds and their caps.
- **Auction outcomes and resale:** After confirmed competitive WON, verify exact owned physical `item_id` and final paid price from fresh watched/status, unassigned/owned and balance evidence. Move via `services.Item.move([item], ItemPile.TRANSFER, false)` when required and list via `services.Item.list(item, startingBid, buyNowPrice, duration)` with **`buyNowPrice = stored resale_price` and `startingBid = UTCurrencyInputControl.getIncrementBelowVal(stored resale_price)`**. Verify both prices against current card-specific EA min/max, starting bid strictly below BIN, and read back the resulting listing with fresh `requestTransferItems()`. If the exact pair is illegal, journal UNLISTABLE/NEEDS_OPERATOR_DECISION rather than silently choosing new prices. A LOST auction is never listed. Duration and unsold-listing automation remain TBD product decisions.
- **Recovery:** intent-before-dispatch, timestamps, epochs, duplicate suppression, unknown-vs-lost-vs-won distinction, restart reconciliation and account/session scope checking. An absent auction in a limited search page alone does not prove a loss or win.
- **Evidence and ownership:** Native EA card caps, 750→800 accepted first bid, fresh INBOX-dirty watched GET, `/user/credits`, leading HOLD and terminal LOST were witnessed in 001C. **001D** integrates the reusable production rules and read APIs; **002** validates active personal rebid, competitive WON/ownership/listing, arbitrary enrolled-trade status, sustained 25-second/50-slot coverage and settled sales. All remain LIVE-UNVERIFIED until naturally witnessed. FC27 exact-version PC BIN asks remain the valuation baseline; external price providers are not required.
- **Account/service restrictions:** automated trading may violate EA rules and lead to account sanctions; no safe EA request frequency has been established. Preserve failure/backoff and ordinary authentication behavior. Do not attempt detection circumvention or access-control bypass.

## Persistent per-auction diagnostic logging (mandatory)

The durable auction registry is the **current state**; separately maintain an **append-only, queryable event history** so each auction can be reconstructed from discovery to terminal outcome across restarts. Logging is part of the execution contract, not optional debug console output.

- **Persistence:** Use a transactional SQLite event journal (or equivalently durable append-only store), with ordered event IDs, UTC timestamps, process/session epoch, actor name, correlation/auction ID, command/intent ID, event type, state before/after and outcome. Make critical bid-intent and state writes atomic or transactionally linked, fsync/durable before dispatch; retain events through restarts, crashes and reconciliation. Never silently overwrite earlier events. If required intent/journal persistence fails, block new bid writes rather than executing untraceable actions.
- **Discovery and admission:** Record search criteria and freshness, observed auction/bid/BIN/expiry and exact card version; raw comparable prices and `last_sale_price`, fixed one-/two-request search count, cache key/age/hit/miss, first/second sample count, exclusions/invalid reasons, observed minimum BIN, early-rejection reason, resale estimate, calculated 5% tax and X, rounded bid cap, queue occupancy, spendable coins and reserve state. Record a **reason code for every relevant action or skip** (e.g., insufficient comparables, price-cap exceeded, leading already, low balance, queue full, DRAINING, expired, ineligible or stale).
- **Every bidding decision:** Log leading/outbid status and its source/time, current highest/our last bid, required minimum next bid, configured maximum, expiry remaining, actual available balance and whether the decision was **BID, HOLD, STOP_COMPETING or RECONCILE**. A leading 3,000 bid with a 6,000 cap should leave an explicit HOLD event, not an unexplained absence of a bid.
- **Every native operation:** Persist the exact intended operation and sanitized request parameters before it is dispatched; record dispatch time, response status and allowlisted EA error code, result timing, callback uncertainty and independent fresh readback. Correlate events through retries/reconnects/late responses so duplicate bids and lost acknowledgements can be diagnosed. An HTTP 200/callback is **not** proof of a successful bid, win or settlement.
- **Lifecycle and economics:** Record enrollment, queue/drain state changes, bid extensions if observed, outbid transitions, confirmed lost/won outcomes, bid holds/refunds and spendable balance changes, purchase price, ownership proof, transfer/listing state and eventual attributable sale proceeds. Keep modeled profit separate from realized profit; unknown events remain UNKNOWN and produce explicit reconciliation records.
- **Operator diagnostics:** Provide CLI/query commands to view one auction's complete timeline, all decisions in a time window, current unresolved auctions and the reasons for blocked bidding; export a sanitized machine-readable trace suitable for postmortems. Logs must never contain EA session tokens, raw credentials, cookies or arbitrary native response bodies. Maintain stable local correlation across process restart, with account scope checking. Keep retention configurable but never prune unresolved intents or evidence needed for settlement/recovery.

**Acceptance examples:** Replaying the event journal must explain (1) why auction A was enrolled, (2) why a leading bid was held without raising, (3) why an outbid triggered the minimum-increment rebid or exceeded the cap, (4) why the Acquirer entered DRAINING, and (5) why an auction ended WON/LOST/UNKNOWN and how that was verified. Simulate a crash between intent persistence and EA response; the recovered timeline must preserve the unresolved intent and show reconciliation without another blind bid.

## Intended actor coordination

```text
Acquirer (every ~10 min):
    if DRAINING or enrolled_count >= max_enrolled_auctions:
        do not enroll
    else:
        search maxBid=1000, minBuy=11000
        for each new eligible auction:
            if reserve admission would fail:
                enter DRAINING; break
            estimate resale and maximum bid
            submit minimum legal first bid; reconcile outcome
            enroll confirmed auction
            if enrolled_count reaches cap: stop

Bidder (queue refresh target ~25 sec, prioritized):
    for each unresolved enrolled auction, nearest expiry first:
        refresh authoritative bid status
        if leading: no bid
        elif outbid and next_legal_bid <= cap and spendable:
            submit next_legal_bid; reconcile
        elif outbid and next_legal_bid > cap:
            stop competing, continue tracking
        if terminal won: verify owned item; hand off to resale
        if terminal lost: reconcile funds; release slot

Acquirer DRAINING:
    no new bids until ALL enrolled auctions are confirmed resolved
    after queue empty: resume only on future eligible cycle if balance permits
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
6. **Settlement/unsold cards:** Observe attributable card sale/coin proceeds before claiming realized profit. Require a product decision for listing duration before live resale and for relisting behavior before unattended unsold-item automation.

Every remaining investigation must identify its exact API and needed real event; missing natural events are reported LIVE-UNVERIFIED, not fictional success or open-ended research prerequisites.

## Objective 002 deliverables, when executed later

1. Working configurable **Bid Acquirer** and **Bidder** actors running concurrently through a single prioritized EA command queue.
2. Durable registry for up to the configurable queue limit, exact bid caps, auction state, operation intents, spendable funds/coin reserve and draining mode across restart/reconnect.
3. Reuse 001D's production bridge, runtime native legal prices, two-query min-BIN valuation/24h cache, fresh balance/watch/status and conditional bid APIs; never recreate MAD/five-comparable valuation or static signed-rule gates.
4. Verified outcome lifecycle: first auction bid → leading/outbid → optional minimum-increment rebids → confirmed won/lost → exact won-card move/list with **Buy Now = stored resale_price, starting bid = previous native legal tick**, and no unnecessary bids while leading.
5. Operator configuration, current queue/coins/actor status, **persistent per-auction event journal** and structured execution/profit records, with queryable human-readable timelines and sanitized trace export.
6. Deterministic test coverage for two-request minimum-BIN valuation (default 600/10,000 listings, high ask clusters, genuine low BIN listings, first-page early rejection, no valid samples, empty/equal/cheaper second result, strict max-two-page-1 searches, inclusive `maxBuy`, 24-hour exact-version PC cache hit/expiry, unsorted paging, `last_sale_price` logged but never used), cap equality/rounding, winning-at-low-bid behavior, outbid competitions, losing over cap, 50-slot queue saturation, 5,000-coin DRAINING stickiness, balance changes, simultaneous actor requests, stale status, restart/unknown responses, chronological reason-coded bid decisions, crash-safe event replay/reconciliation, and won-item handoff.
7. Bounded independently assessed actor-dependent live validation **after 001D foundation handoff**; do not infer bid/win/list success from an HTTP acknowledgement alone. Record projected profit separately from realized settled profit.

**Acceptance:** demonstrate both independently running Python actors following these invariants without duplicate bids or unverified state transitions; at full capacity no 51st enrollment; at coin reserve no new enrollment until queue drain is complete; when leading at 3,000 with a 6,000 cap, do not rebid; when outbid, advance by the smallest legal step only if within cap. Test that when `resale_price=1500`, live listing intent has Buy Now 1500 and a native one-tick-below starting bid 1400 (assuming card caps allow both). Explicitly report any actor-dependent natural event not actually observed. Don't claim sustained 25-second monitoring, safe EA pacing, successful profit or fully autonomous production readiness without evidence.

## Out of scope / decisions deferred

No additional trading strategies, bid sniping variants, portfolio allocation optimization or third-party subscriptions. **001D** fixes pre-actor bridge/status, native caps/tick and pricing/cache contracts; **002** implements real actors and verifies dependent outcomes. Listing duration and unsold handling remain **TBD product decisions**, not arbitrary defaults. **Committing this file does not start actors or authorize immediate account trading.**
