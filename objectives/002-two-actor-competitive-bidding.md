# Objective 002 — FC27 Two-Actor Competitive-Bidding Bot

**Status:** Strategy specified (v0); not submitted for execution. Implement after Objective 001C capability validation and prerequisite infrastructure work.

**Repository:** `zrsoo/fc-hustle` (`C:\hustle\fc-hustle`).

## Purpose

Build an autonomous FC27 Ultimate Team **competitive-auction bidding** strategy with **two cooperating actors**, not the earlier generic Buy Now sniping loop:

1. **Bid Acquirer** periodically finds attractive auctions and places the *smallest legal initial bid* to enroll in them.
2. **Bidder** continuously manages already-enrolled auctions, rebidding **only if outbid**, never bidding up to the price cap merely because it is affordable.

A shared durable auction registry, coin/account state and serialized native EA execution queue coordinate the two actors. Won players are handed off for verified transfer-list placement and resale. Net projected profit is evaluated using the existing 5%-tax pricing model.

This objective fixes the initial product behavior. **Do not build or run Objective 002 before Objective 001C** validates currently missing FC27 live capabilities, and implements any required integration prerequisites. Objective 001C will be written separately; its scope/results may refine this strategy before implementation. Older Objective 001/001B execution handoffs document reusable infrastructure but their Buy Now-first strategy is **superseded** by this objective.

## Initial configurable settings

```yaml
acquirer:
  search_interval_seconds: 600     # Every ~10 minutes; target cadence
  max_search_bid: 1000             # Search filter, not per-auction maximum spend
  min_search_buy_now: 10500        # Search filter, not expected resale value
  min_available_coins: 5000        # Coin-reserve / drain threshold
  max_enrolled_auctions: 50        # Maximum unresolved auctions in shared queue

bidder:
  target_check_interval_seconds: 25
  rebid_only_when_outbid: true
  bid_smallest_legal_increment: true

strategy:
  min_profit_coins: 500            # X; initial default, configurable
  estimated_sale_tax_rate: 0.05
  min_independent_comparables: 5
```

All numeric settings are configurable, with these defaults. Search filters select candidate auctions, **not** their final acceptable bid price. Do not introduce extra arbitrary limits on enrollment other than the configured coin reserve, queue capacity, profitability and availability of qualifying auctions.

## Actor 1 — Bid Acquirer

**Ownership:** discovering new auctions, estimating value, determining the maximum profitable acquisition bid and enrolling new auctions.

On its next scheduled acquisition cycle (initially every 600 seconds):

1. Search the authenticated **FC27 PC player transfer market** with `maxBid=1000` and `minBuy=10500` (in EA native criteria terms). Fetch as many qualifying auction candidates as practical, handling bounded pagination, duplicates and search-result ordering. Verify the actual live filter semantics: “maximum bid” and “minimum Buy Now” must not be confused with current bid, starting bid or max BIN.
2. Ignore auctions already enrolled, conclusively resolved, unavailable, ineligible, or without trustworthy pricing.
3. For each distinct **exact player card/version** on PC, obtain at least **five independent comparable active BIN listings**. Reuse `fc_access/pricing.py` and the existing independent-sample/outlier protections: deduplicate, exclude the candidate auction and physical item, reject stale/invalid/mismatched observations, apply the conservative resale estimator and legal price rounding. Do **not** average five unrelated players. External prices may aid discovery but cannot silently substitute for comparable live PC listings.
4. Calculate the auction's maximum acceptable final bid (coin integer):

   `max_affordable_bid = estimated_target_sale - floor(estimated_target_sale / 20) - X`

   Round **down** to a legal bid increment (hundreds) and respect exact-card price restrictions as verified by Objective 001C. Require a viable bid above the current/starting auction requirement. Treat expected profit as **projected**, never realized.
5. If admissible, place **only the minimum legal initial bid**; do not jump directly to `max_affordable_bid`. Freshly verify auction identity, current price, time remaining and account capacity before a bid, then independently reconcile the bid result.
6. Add the auction to the shared registry upon confirmed enrollment, storing exact card version, auction identity, current bid, our bid, max cap, estimated target resale, X, timestamps and unresolved status. Prevent duplicate enrollment or write retries on ambiguous outcomes.
7. Continue through candidates, yielding to the higher-priority Bidder when API work conflicts, until no eligible opportunities remain or an admission limit is reached. The 10-minute cadence is a **cycle scheduling target**, not a promise that a potentially long acquisition batch completes within ten minutes.

### Admission limits and draining

- **Queue cap:** A maximum of **50 unresolved enrolled auctions** by default. Leading, outbid, cap-exhausted and outcome-unknown auctions all occupy slots until their **win/loss is confirmed**. At capacity, pause new enrollment; slots reopening can be used on a subsequent eligible acquisition cycle.
- **Coin floor:** Default **5,000 spendable coins**. Do not enroll if an initial bid would violate the admission reserve, and never treat coin escrow or pending bid returns as freely available funds without verified account semantics. Once the available balance reaches the threshold (or the reserve prevents further enrollment), enter **DRAINING**.
- **DRAINING is sticky:** While draining, the Acquirer creates **no new auction enrollments**, even if the coin balance temporarily increases or queue slots open. Let the entire enrolled queue resolve **WON or LOST** first. Then exit draining; admission resumes only on a future acquisition cycle **if the reserve test passes**. If coins remain too low, stay paused.
- The coin floor governs **new enrollment only**. It does **not** stop the Bidder from managing existing auctions; the Bidder still obeys each auction's profit cap and actual spendable-balance constraints.
- If both the queue cap and coin threshold apply, **DRAINING takes precedence**.

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

The reported “30-second countdown resets when a bid is placed” and the desired 25-second monitoring schedule are **assumptions to test in Objective 001C**, not established API facts. Verify how auction expiry changes and whether status can be observed efficiently; do not claim deadline protection or a ban-safe cadence from an untested polling target.

## Shared components and invariants

- **Single source of truth:** durable shared auction registry keyed by account/game/platform and actual auction identity. Prevent the two actors from racing, double-enrolling or duplicating bids. Preserve exact player-version/auction/physical-item separation and stable identity across restarts.
- **Serialized EA request execution:** one reviewed local Edge-native bridge and global prioritized command scheduler. Active-auction reconciliation and urgent Bidder operations take precedence over new acquisitions; do not starve recovery or post-win listing. Local long polling may deliver immediately, but EA request scheduling is independent.
- **Bid price cap:** Preserve the target, tax and configured X used to authorize acquisition. Revalidate pricing when necessary; never raise an existing auction's maximum profitable bid merely because competitors bid higher. Rounding must never increase the cap.
- **Coin accounting:** track spendable balance, the economics of held bids, refund/outbid behavior and unresolved bid intents using live verified semantics; do not double-count committed or returned funds. New enrollment uses the 5,000-coin admission reserve; existing bids may continue within available funds and their caps.
- **Auction outcomes and resale:** a confirmed win transitions to owned-item verification, movement to transfer list and listing at the estimated legal target; independently verify each mutation. A lost auction never produces a resale action. Handle relisting of unsold items only after separately verified eligibility.
- **Recovery:** intent-before-dispatch, timestamps, epochs, duplicate suppression, unknown-vs-lost-vs-won distinction, restart reconciliation and account/session scope checking. An absent auction in a limited search page alone does not prove a loss or win.
- **External source caveat:** DataFluxor/FUT-DB remain unverified for production PC prices; FC27 native comparable asks are the working baseline. Missing price caps, legal bid increments, watched-trade status and settlement behavior must be validated rather than fabricated.
- **Account/service restrictions:** automated trading may violate EA rules and lead to account sanctions; no safe EA request frequency has been established. Preserve failure/backoff and ordinary authentication behavior. Do not attempt detection circumvention or access-control bypass.

## Intended actor coordination

```text
Acquirer (every ~10 min):
    if DRAINING or enrolled_count >= max_enrolled_auctions:
        do not enroll
    else:
        search maxBid=1000, minBuy=10500
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

## Relationship to Objectives 001, 001B and upcoming 001C

- **Objective 001** verified native read access and one **Buy Now** acquisition → transfer-list → listing; it did **not** verify competitive incremental bidding, repeated outbids, holding funds or settled auction wins.
- **Objective 001B** provided exact-version PC pricing research, search/budget experiments and dry-run opportunity evaluation. Its live benchmark is **partial**, not a demonstrated winning discovery strategy.
- **Follow-up `b17647c`** verified uppercase `"PC"` persona handling and the authenticated long-poll search path.
- **Latest research on main** has a partial A-only benchmark; its subsequent browser detachment makes long-running attachment/reconnection a prerequisite, not a solved feature.
- **Objective 001C (to be scoped separately):** investigate and, where missing, implement/validate the exact bid-price/BIN filters, ordinary bid operation and bid-status API, outbid/won/lost/coin-hold semantics, minimum legal increments, auction extension timing, queue monitoring under real request limits, cap/range lookup, browser lifecycle and other prerequisites. Complete this before Objective 002 execution. Do not automatically treat research-only tools as a production execution adapter.
- Existing `docs/research/obj002-handoff.md`, `docs/research/execution-architecture.md`, `docs/research/001b-obj002-addendum.md` are architectural references. Where they describe the older **Buy Now-first** loop, this objective's **two-actor bidding flow takes precedence**. Reuse their durability, identity, transport, reconciliation, listing and settlement lessons as applicable; revise module boundaries after 001C.

## Objective 002 deliverables, when executed later

1. Working configurable **Bid Acquirer** and **Bidder** actors running concurrently through a single prioritized EA command queue.
2. Durable registry for up to the configurable queue limit, exact bid caps, auction state, operation intents, spendable funds/coin reserve and draining mode across restart/reconnect.
3. Native search-filter integration, reliable comparable pricing, legal bid computation, bid-state observations and conditional bid placement.
4. Verified outcome lifecycle: initial bid → leading/outbid → optional minimum-increment rebids → confirmed won/lost → won-item move/list workflow, with no unnecessary bids while leading.
5. Operator configuration, current queue/coins/actor status and structured execution/profit records.
6. Deterministic test coverage for cap equality/rounding, winning-at-low-bid behavior, outbid competitions, losing over cap, 50-slot queue saturation, 5,000-coin DRAINING stickiness, balance changes, simultaneous actor requests, stale status, restart/unknown responses, and won-item handoff.
7. Bounded independently assessed live validation **after 001C prerequisites**; do not infer bid/win/list success from an HTTP acknowledgement alone. Record projected profit separately from realized settled profit.

**Acceptance:** demonstrate both actors following these invariants without duplicate bids or unverified state transitions; at full capacity no 51st enrollment; at coin reserve no new enrollment until queue drain is complete; when leading at 3,000 with a 6,000 cap, do not rebid; when outbid, advance by the smallest legal step only if within cap. Explicitly report any live prerequisite not yet verified. Don't claim sustained 25-second monitoring, safe EA pacing, successful profit or fully autonomous production readiness without evidence.

## Out of scope / decisions deferred

No additional trading strategies, bid sniping variants, portfolio allocation optimization or third-party subscription purchase in this initial version. Exact auction-status collection contract, fast-path timing, native caps/increments and any needed interface or cadence refinements belong to Objective 001C and later iteration. **This file records the agreed v0 strategy; it does not authorize immediate execution of trades.**
