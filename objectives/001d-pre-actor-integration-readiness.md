# Objective 001D — Pre-Actor Integration Fixes and Readiness

**Status:** Scoped for execution after Objective 001C; **do not implement the autonomous actors here**.

**Repository:** `zrsoo/fc-hustle` (`C:\hustle\fc-hustle`). Parent strategy: [Objective 002](002-two-actor-competitive-bidding.md). Evidence: [001C capability matrix](../docs/research/001c-capability-matrix.md), [001C architecture handoff](../docs/research/001c-architecture-handoff.md), and [001C completion report](../docs/research/001c/001c-06-complete/REPORT.md).

## Purpose and boundaries

Turn 001C's proven one-shot native capabilities and offline-tested components into **one coherent, tested, reusable pre-actor foundation** for Objective 002. Fix known integration defects; perform only narrowly identified investigations feasible **without** an autonomous Bid Acquirer or Bidder. Produce an explicit handoff separating IMPLEMENTED/OFFLINE_VALIDATED, LIVE_VERIFIED (with exact scope), and INVESTIGATION REQUIRED / LIVE-UNVERIFIED.

**Not authorized in 001D:** recurring 600-second discovery, a 25-second Bidder loop, autonomous auction enrollment, persistent unattended trading, new competitive bids, Buy Now purchases, card moves, or listings on the live account. Live access in this objective is **bounded and read-only** for the specific probes below, using the normal logged-in official FC27 PC Web App in Edge; if unavailable, use offline tests and report the precise missing validation. Do not expand scope to force a live result, invent an auction, fabricate server outcomes, bypass account challenges, or rewrite sealed 001/001B/001C evidence.

Before making changes, read `AGENTS.md`, inventory the named modules and tests, and publish a concise **REUSE / REPLACE / IMPLEMENT / INVESTIGATE / DEFER-TO-002** gap map. Prefer adapting existing working primitives over creating a third incompatible implementation.

## Locked behavioral decisions: do not re-open

- **Acquisition is competitive auction bidding, never Buy Now sniping.** The Acquirer selects auctions using `maxBid=1000`, `minBuy=11000` as *discovery filters*. That `maxBid` is **not** a production per-bid ceiling; per-auction maximum comes solely from profitability.
- **Pricing is one page + at most one bounded cheaper-price probe per exact card version on PC**, not an arbitrary minimum of five comparable listings, median/MAD estimator, or page-sorting scheme. First search: exact version, page 1, `count=21`, take the minimum valid Buy Now after excluding the recognizable default starting-bid-600/BIN-10000 template and otherwise invalid/stale/mismatched/duplicate results. If no valid price exists, skip. Check each candidate's minimum legal required bid against the maximum profitable bid derived from that first minimum; reject the candidate early if already over cap.
- **Only if still potentially profitable**, second exact-version search: page 1, `count=21`, `maxBuy=first_min` **inclusive**. Use the minimum valid BIN across both samples; if the second succeeds but contains no valid listings, use `first_min`. **No third search, pagination or progressive probing.** A failed/ambiguous second request is NOT an empty successful response and must not silently be converted to a valid completed quote.
- Store a **completed** price in a 24-hour (`86400` second) TTL cache keyed by account/game/platform/exact definition ID, reusable by all auctions of that version. Incomplete first-page-only early-rejection evidence is not a completed price cache entry (optional separate rejection bound). Record age/coverage/sample counts and acknowledge that this is the minimum **observed**, not the guaranteed global minimum.
- `lastSalePrice` / `last_sale_price` must be captured for diagnostics, **never used** to estimate resale value, tax, profitability or the bid cap.
- **Resale is at the fixed sampled `resale_price` as Buy Now**. The resale listing's starting bid is **exactly one EA-native legal increment below `resale_price`**. These are not strategy parameters to optimize or silently revise; if either price is invalid under current card limits, return an explicit unlistable/needs-reconciliation result. The completed move/list lifecycle itself belongs to Objective 002.
- Projected tax is 5%: `max_affordable_bid = resale_price - floor(resale_price/20) - X`, initially `X=500`, rounded **down** to a legal bid price. Native legal ticks are price-tier dependent. Current `maxBid=1000` discovery filter and previous 001C **test-only** bid ceilings must not constrain the future production profitability cap.
- For bidding, when already leading do nothing; when outbid use **only** the smallest legal new bid if under the stored profitable cap. No actor or new live bidding is implemented under this objective.

## Deliverables and fix checklist

Every task below must cite the **specific production implementation path**, the available implementation/evidence, and an **offline test and/or bounded read-only live verification**. Do not mark an unsupported behavior LIVE_VERIFIED.

### D1. Consolidate the production native bridge and contracts — IMPLEMENT

- Reconcile `browser/e2e-live-v2/page.js`, `browser/bidding-v1/page.js`, `fc_access/bidding_v1/adapter.py`, `fc_access/bidding_v1/contracts.py`, `fc_access/durability_v1/adapter.py`, and the current durability executor/transport. Choose and document **one** authoritative production command/response schema and native execution route rather than indefinitely maintaining parallel experimental dialects.
- Preserve native `trade_id` vs physical `item_id` vs exact `definition_id`, FC27/PC persona and account scope, command IDs, host/worker epochs, request-source freshness, field allowlists, and actual native route evidence. No auth/session secrets in Python logs; do not infer a stable native identity from a per-run pseudonym across unrelated session keys.
- Fix the known reusable-adapter route discrepancy: current authenticated balance GET is `/ut/game/fc27/user/credits` (native `services.User.requestCurrencies()`), while the original bidding adapter expected `/user/currencies`. Preserve the **actual observed route** in audit data; remove or adapt the legacy expectation without lying about the wire request.
- Retain `UTSearchCriteriaDTO` exact `defId`, `count=21`, page 1, `maxBid`, `minBuy`, `maxBuy` semantics. Pricing and discovery must have separate request criteria. Verify the second pricing request really emits the maximum-BIN criterion (native `maxBuy`; observed wire `maxb`) rather than an unrelated bid constraint; do not infer server sort.
- Retain error/timeout/ambiguous-result semantics, authentication/persona checks, a single browser/native command owner, and correlation of independent readback results. Remove stale test-only `bid <=1000`, `minBuy=10500`, finite test-window and hardcoded player/auction restrictions **from the production path only**; do not mutate historical test harnesses or archived evidence.

**Acceptance:** fixture/mocked-native protocol tests demonstrate correct current routes, persona, fresh source, exact version, operation routing, malformed/timeout handling and no old experimental production ceiling. Existing historical tests remain intact or are explicitly migrated if they test superseded production contracts.

### D2. Replace the artifact-driven rules gate with EA-native runtime price checks — IMPLEMENT

- Remove the production dependency on `fc_access/bidding_v1/rules.py:RulesProvider`'s preapproved JSON artifact hashes, `LIVE_VERIFIED` classification gate, arbitrary 300-second artifact freshness and full price-band certification. No operator-generated rules artifact or reviewed SHA is required for a new card version.
- Obtain exact-card listing caps with `services.Item.transfersDao.getItemMarketDataByDefId([definitionId])`; the returned `minimum`/`maximum` are **EA-allowed listing bounds, not the current cheapest market BIN**.
- Use EA's loaded client helpers `UTCurrencyInputControl.getIncrementAboveVal(value)` and `getIncrementBelowVal(value)` for minimum rebids, rounding/validation and the **one-increment-below-resale** future listing start. The former returns the **next absolute bid amount**, not an additive increment. Reuse observed client tiers only where needed; no manually certified whole-market schedule.
- Expose small versioned, testable native-cap/tick service functions to Python. Verify integer legal rounding **down** for the profitability cap; verify opening bid = startingBid when currentBid=0, otherwise next native tick above currentBid; validate actual card limits and list BIN/start values. Fail explicitly when native service/helper/caps/identity is unavailable or disagrees. Preserve durable intent, actual spendable balance and cap checks on writes; eliminating a static provenance gate must **not** disable these basic checks.
- Read-only acceptance may inspect/get current card caps and native helper values; **no new bid/list writes**. Existing 001C evidence includes an accepted 750→800 bid and live card-specific caps, not blanket validation of all bands.

**Acceptance:** bid and listing-price computations operate without static rule files; deterministic boundary fixtures exercise 750→800 and 1500→1400 where applicable, edge-of-cap cases, no legal lower starting bid, price ticks across tier boundaries, mismatched card, and unavailable native helper/caps.

### D3. Implement the exact two-search pricing service and 24-hour cache — IMPLEMENT

- Replace the **production** path through `fc_access/pricing.py` (and the former `fc_access/bidding_v1/rules.py:estimate_cap` / `fc_access/bidding_v1/adapter.py:bid_once` coupling) that currently demands five samples, symmetric MAD, lower quartile and automatic undercut. Keep useful exact-identity, 5%-tax, valid-price and dedup helpers; historical experiments need not be rewritten.
- Provide a callable, deterministic **one-shot** pricing API usable later by the Acquirer; it should accept exact-version native fetch functions, persist/reuse a 24h complete result, record `last_sale_price` diagnostics, and output `resale_price`, rounded `max_affordable_bid` and evidence/reasons. It must not dispatch bids or start a discovery/monitoring loop.
- Implement first-page early rejection *per candidate*: if `minimum_legal_bid > first_page_profit_cap`, return REJECT without the second call; otherwise perform **exactly one** second query `maxBuy=first_min`, inclusive, then recalculate the final cap. A candidate rejected after first-page calculation never qualifies by finding a still-lower BIN.
- Do not reuse a rejection-only entry as a completed 24-hour price. Cache only the successful two-search result, with account/game/platform/version key and `observed_at`; cache hits issue **zero** price searches. Handle invalid responses and failed/ambiguous second requests distinctly from successful empty ones.
- Keep the candidate auction itself separate from independent market comparables and do not assume a page's first item is the cheapest. Do not price another card version or platform from this cache. Record exclusion reasons including default 600/10000 templates; genuine cheap offers (e.g. 1500, 1700) must **not** be dropped as outliers.

**Acceptance:** retained 001C version-261855 fixture's first minimum is 1,500 (not old estimator's 2,800); second sample equal/empty/lower changes the result only as specified; one-page rejection uses one request; other uncached eligible candidates use two; completed cache hits zero within TTL and expire at 24h; process restart retains durable completed cache if persistence is used; `last_sale_price` changes never alter cap or sale BIN.

### D4. Integrate fresh watched, balance, unassigned, transfer-list and status primitives — IMPLEMENT + BOUNDED INVESTIGATION

- Implement the already observed cache invalidation on read: `repositories.Item.setDirty(ItemPile.INBOX)` then `services.Item.requestWatchedItems()` for a fresh bulk watched GET; use `ItemPile.PURCHASED` + `requestUnassignedItems()` and `ItemPile.TRANSFER` + `requestTransferItems()` for fresh read-only inventory/list evidence. Check corresponding actual authenticated response routes `/watchlist`, `/purchased/items`, `/tradepile`, and `/user/credits`; fail on cache-only/unsupported response rather than claim a refresh.
- Reuse exact native watched `trade_state`, `bid_state`, `expires`, `current_bid`, and `native isWon()` projection where available. A missing watched row is **UNKNOWN**, never a loss. A closed/highest result alone is **pending independent owned-item proof**, never a confirmed win. `/trade/status/lite` can omit `definition_id` (seen as 0); do not treat zero as proof of a different card.
- **Investigation 001D-S1 (read-only):** inspect `browser/e2e-resolution-v2/page.js` / `services.Item.transfersDao.getAuctionData` and determine whether the **already validated, single-historical-trade** status technique can generalize to any *known native trade ID* with retained exact identity across current browser context and reconnect. Implement a reusable read-only lookup **only if supported** by the current client and tested without new bids. This is NOT evidence that newly enrolled or missing trades always resolve. If blocked by per-session native ID availability or no eligible known trade, document the precise gap and hand it to Objective 002 for validation on its real enrolled trades.
- **Investigation 001D-S2 (read-only):** verify native `getIncrementBelowVal(resale_price)` and card caps can produce the exact specified future listing start/BIN pair; implement standalone validation, **do not place a listing**. Document what happens when no legal lower start exists.

**Acceptance:** mocked-native tests for dirty-then-read, GET route/freshness validation, bulk row identity, missing rows → UNKNOWN, closed/highest → PENDING, and native card version omitted in lite results. If actual Edge access is available, obtain only bounded read-only samples and mark unobservable cases unresolved rather than initiating purchases.

### D5. Ready the existing durable scheduler/registry primitives, without actors — IMPLEMENT

- Reuse `fc_access/bidding_v1/journal.py`, `fc_access/bidding_v1/core.py`, `fc_access/bidding_v1/scheduler.py`, `fc_access/durability_v1/store.py` and related bridge lifecycle code. Prepare **one** production prioritized native executor, serial EA request concurrency=1, delivery vs native-request metrics, deadline-aware skip, and durable intent-before-write/no-blind-retry contracts. One-shot fixture harnesses only; no 10-minute Acquirer or 25-second Bidder loops.
- Provide shared registry/journal interfaces for Objective 002 with stable account/game/platform/auction ownership, current state plus append-only per-auction event history, queued/unresolved states, available coin reads, sample-price evidence and reason-coded HOLD/REJECT/BID/UNKNOWN transitions. The actual actor ownership, periodic ingestion and live event sequencing are implemented in 002, not here. Preserve/replay UNKNOWN bid intents after interruption; never reinterpret them as rejected/never sent merely because Python restarted.
- Remove test-only restrictions from production code without removing real account/persona, identity, legal-price, profitability and fresh-read preconditions. Do not add an arbitrary 30-second EA inter-request delay as an EA requirement. Request pacing remains configurable and observable; the 25-second target is **not** tested or started here.
- Ensure production adapter constructs and processes one-shot search/watched/credits/caps/price-quote/intent outcomes without incompatible schema migrations or an external Codex supervisor. **002**, not 001D, will run the continuously scheduled Python processes.

**Acceptance:** independent one-shot fixture integration traverses native adapter → quote → candidate admission decision → serialized scheduler → durable journal with zero real account writes. Unit/crash tests cover dropped result, duplicate intent, restart epoch, stale read and queue priority. Report if the installed browser/extension still requires a separately running local server.

## Explicit investigations deferred to Objective 002

These **depend on the autonomous actors or on a naturally occurring competitive auction outcome**; 001D must not expand into them:

- An actual *active personal outbid* and minimum-increment **rebid**; existing live proof covers first participation and HOLD, **not** an active outbid → rebid.
- A naturally **WON** competitive auction, exact owned physical item, **actual paid cost**, post-win move/list, listing readbacks, and later sale/settled proceeds. Objective 001 proved Buy Now purchase→move/list, not this competitive-win branch.
- **Sustained** independent Python Bidder polling near 25-second target with Acquirer demand and reconnects; practical 50-slot watchlist coverage, truncation, expiry handling, latency and priority under load.
- Real auction timer extension/reset behavior near expiry; transient held-funds/refund timing beyond the observed 800-coin balance debit/return.
- Any ambiguous status lookup that cannot be resolved from existing read-only historic evidence; validate with real enrolled trades created by Objective 002 rather than forcing a new trade in 001D.
- Actual relisting of unsold cards and realized profit proof, after Objective 002 defines the missing listing-duration and unsold-listing behavior. Do not invent product rules for these in 001D.

## Definition of done and handoff

1. `docs/research/001d/REPORT.md` (or equivalent) contains a **per-fix checklist**: source files changed, exact implementation, evidence source, offline tests, bounded read-only results, and status **IMPLEMENTED / VERIFIED / PARTIAL / INVESTIGATION REQUIRED / DEFERRED TO 002**. For every unsupported assumption, state the specific missing operation, not a generic "needs research".
2. A versioned production API/adapter contract, tested one-shot pricing/price legality/route/identity/status primitives, 24h cache, and an explicit Objective 002 integration call graph. No live actor process required to consume the contract.
3. Regression tests cover every changed contract and expected error path, including retained 001C pricing counterexample and no experimental 1,000-coin production bid cap. Run relevant baseline checks; report pre-existing or unrelated failures rather than silently amending sealed captures or broadly relaxing assertions.
4. If authorized read-only Edge calls are feasible, report actual route/status/freshness evidence; distinguish **client helper available**, **offline-tested**, and **live transaction verified**. A historical successful bid is not evidence of a newly successful rebid or listing.
5. No code path launched recurring actors, placed live bids, moved/listed items or altered 001C sealed histories. Publish a crisp **001D READY / PARTIAL** assessment with exact 002 dependencies. If a narrow read-only probe cannot be completed, hand off that one verification without allowing open-ended scope creep.

**Completion of 001D means the foundation is wired and testable; it does not mean competitive-auction wins, unattended monitoring, sale settlement or full production trading are proven.**
