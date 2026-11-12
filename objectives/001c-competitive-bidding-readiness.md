# Objective 001C — Competitive Bidding Capability & Live E2E Readiness

**Status:** New objective; prerequisites for Objective 002. **Do not execute Objective 002's autonomous actor loops here.**

**Repository:** `zrsoo/fc-hustle` / `C:\hustle\fc-hustle` on Windows, with the existing authenticated official FC27 PC Ultimate Team Web App in Microsoft Edge.

## Outcome / definition of done

Independently prove **on the live FC27 PC transfer market** that the Bid Acquirer and Bidder specified in [Objective 002](002-two-actor-competitive-bidding.md) can perform every necessary native operation, and implement any **missing reusable infrastructure** required to make those operations callable, observable and recoverable. Deliver tested, versioned adapter contracts, an actual bounded end-to-end competitive-auction test, a detailed evidence-based capability matrix, and a precise Objective 002 engineering handoff.

**Source code, fixtures and HTTP 200 responses without authoritative independent readbacks are not live proof.** Classify each feature as LIVE_VERIFIED, SOURCE_CONFIRMED_ONLY, OFFLINE_VALIDATED, BLOCKED or UNVERIFIED. Any outcome dependent on genuine competitor activity remains unverified until witnessed. Do not invent outbids, wins, refunds or auction timer resets.

Objective 001C is a **foundation/release-gate objective**: implement missing bridge/protocol, bidding and bulk-status primitives; test their real behavior. It must **not** build the 10-minute Acquirer loop, continuous 25-second Bidder loop, automatic mass enrollment, or an unattended production trading system. Objective 002 will integrate the actors.

## Locked strategy being enabled

Objective 002 supersedes the earlier Buy Now-centric execution plan. Its initial defaults are:

| Setting | Initial configurable value |
| --- | --- |
| Acquirer discovery cadence | 600 seconds (10 minutes) |
| Market search | Maximum bid 1,000 coins; minimum Buy Now 10,500 coins |
| Acquirer enrollment | Lowest legal initial bid, for as many profitable auctions as feasible |
| Auction queue | Maximum **50 unresolved enrolled auctions** |
| New-entry reserve | **5,000 spendable coins** |
| Draining | If reserve reached/prevents entry, stop all new enrollment until **all** enrolled auctions have confirmed terminal outcomes, even if balance temporarily recovers |
| Bidder monitoring | **Target** one entire-queue refresh every 25 seconds |
| Bidder decision | If leading, **HOLD**; if outbid, bid only the **smallest legal amount to regain lead**, and never above per-auction profitable cap |
| Resale valuation | At least **five independent exact-version PC comparable BIN asks**, robust outlier rejection, conservative target, configurable profit threshold X (initially 500), projected EA sale tax 5% |
| Winning | Confirm owned item and actual price, then move/list at valid estimated target; verify readbacks |
| Diagnostics | Durable per-auction chronological event log, including reasons for bids, holds, skips, losses, wins and unknown outcomes |

Maximum profitable bid, before legal downward rounding:
`max_bid = estimated_target_sale - floor(estimated_target_sale / 20) - X`.
Do not mistake market **search** `maxBid=1000` for an eventual per-player bid ceiling: an enrolled auction might be bid up to its independently calculated profit cap. Never bid higher solely because the cap permits it.

## Baseline already available: reuse, don't re-research

1. Objective 001 confirmed live authenticated PC market searches; observed auction identifiers, exact card definition IDs, current/starting bids, BIN, expiry, trade/bid states; coin reads; owned/unassigned and transfer-list reads; and one real **Buy Now → move → listing** operation with independent readbacks. Competitive incremental bidding, watched-auction refresh and terminal competitive-auction outcomes **were not** proved.
2. `fc_access/pricing.py` already implements exact-card comparable selection, deduplication, candidate exclusion, robust outlier filtering, tax/profit computation and conservative resale price. Its generic price bands and caller-supplied card caps are **hypotheses**, not live-verified.
3. Commit `b17647c` and `experiments/market_discovery_followup_v1/` confirmed the corrected uppercase `"PC"` persona mapping, working native authenticated market GET and low-latency *local* long-poll delivery. Do not regress this.
4. The Objective 001B nine-window A/B/C discovery study is **partial**: the latest retained live run completed only A's first 300-second window before `bridge_not_attached` in the next window. Fix long-lived attachment reliability instead of assuming the extension is production-ready. A new benchmarking campaign is not the principal objective here.
5. `docs/research/execution-architecture.md`, `docs/research/obj002-handoff.md`, `docs/research/001b-obj002-addendum.md`, `fc_access/transaction.py`, `browser/transaction-bridge/` and existing validators document reusable identity/reconciliation principles; their previous generic Buy Now acquisition strategies are superseded where incompatible with Objective 002.
6. External FC27 source reference: `liusihang/fc27-copilot`, `extension/content/page-inject.js`, supplies `placeBid()` via `services.Item.bid(item, bidAmount)` and `getWatchlist()` via `services.Item.requestWatchedItems()`. This supports a potential **single bulk request** for an auction array but is **not live FC27 proof on our account**. Historical `futjs/fut-api` uses one `getWatchlist()` API call and a separate `getPilesize()`; `sauravhiremath/fut-25-market` uses trade-status reads. Earlier-game endpoints/caps must not be treated as confirmed FC27.
7. Objective 002 already requires persistent diagnostic events; 001C must supply **reusable primitive/journal infrastructure** and test evidence so 002 can implement the full persistent two-actor lifecycle.

Before coding, examine repository state, relevant source/tests, the existing live evidence and the objective's dependency; write a concise gap map showing REUSE / ADAPT / IMPLEMENT / PROVE.

## Workstream A — Native API contracts and exact search filters

Implement and independently validate, using the official active Edge Web App:

- Extend the latest verified search bridge with `max_bid` → native `UTSearchCriteriaDTO.maxBid` and `min_buy` → `minBuy`, preserving current PC, identity, paging and sanitization guarantees. Confirm both criteria appear in an actual authenticated EA request, with the correct response semantics (starting bid vs current bid, min BIN). Do not substitute max BIN / min bid.
- Execute a fresh real search with `maxBid=1000`, `minBuy=10500`. Verify the actual listing objects and filtering behavior. Handle zero results as legitimate; no hypothetical auction is created.
- Document paging/coverage, duplicate/lookahead rows, ordering, expiring/changed auctions, and whether source supports enough candidates for repeated enrollment. Correctly detect an unavailable candidate before bidding.
- Verify exact card/version and platform identity, item/trade identifiers, and actual native price caps and bidding/listing increments applicable to sampled cards; distinguish globally documented increments from card-specific caps. Any unsupported constraint must remain unverified, not guessed.
- Validate fresh five-comparable price lookup using existing code; separate reference estimates from realized sale prices. Compute and log an actual candidate's projected cap and explain when lack of fresh comparables or caps prevents a rational bid.

Deliver a tested read/query adapter contract and real sanitized request/response evidence.

## Workstream B — Bulk watchlist and scalable Bidder status

**Primary hypothesis to test:** one native `services.Item.requestWatchedItems()` call returns an array covering the user's active watched/bid auctions and their current leading/outbid/expiry state. Do not architect 50 per-auction GETs without evidence.

1. Inspect current loaded FC27 Web App implementation and the FC27 source reference. Call `services.Item.requestWatchedItems()` through the authenticated Edge bridge (read-only). Record precise native method, actual HTTP network request count/routes, status, elapsed time, payload size and allowlisted schema: trade_id, item_id, exact definition_id, current bid, starting bid, BIN, bidState, tradeState, expiry, last network time.
2. Establish whether **one request** returns the **complete** account watchlist, whether it has server-side pagination/caps, and whether an empty response means a verified empty watchlist rather than cache/attachment failure. Compare with the visible Web App Transfer Targets and, when possible, independently refreshed known enrolled auctions.
3. Examine reported watchlist/Transfer Targets **capacity**, if accessible via a native pile-size API or known observed account state; distinguish the configured **50** maximum from a potentially smaller game/account cap. No need to place 50 real bids merely to test parsing or client scaling.
4. Measure how fresh the returned current-bid/leading/outbid/expiry fields are; determine whether the native call reaches the network vs a cache snapshot. Check which statuses are reliable for *active*, *outbid*, *won*, *lost*, *expired*, *unknown* and removed entries.
5. If the bulk watchlist response is incomplete or cannot disambiguate terminal states, examine an additional **bulk trade/status** or pagination mechanism supported by the *current FC27 Web App*. Validate only genuine observed contracts. Model incomplete coverage as UNKNOWN, not LOST.
6. Use local fixtures containing **50 simultaneous enrolled auctions** to test ingestion, deduplication, reconciliation, deadline ordering and status-processing speed. Make a clear statement of expected **EA requests per refresh**, observed request duration and feasibility of 25-second whole-queue refresh for 50 auctions.
7. Investigate the reported “auction countdown extends/resets to ~30 seconds after a bid” empirically when ordinary bid traffic occurs. Record pre/post expiry timestamps. Do not assume every bid or every auction behaves that way.

**Acceptance:** Demonstrate at least one authentic bulk watched-auction response, instrumented network request count and a defensible coverage/limit assessment. If the live account has few/no watched auctions, report exactly what can and cannot be proven; establish remaining cases via bounded live enrollment where possible and 50-auction fixture tests.

## Workstream C — Ordinary bid, outbid, outcomes and coins: genuine live E2E

Implement narrowly scoped **one-shot native competitive-bid commands** for validation, not a continuous trading loop. The ordinary bid endpoint/method must not be conflated with the previously verified Buy Now action. Use strict parameters and exact trade/card identity, fresh eligibility, appropriate legal minimum next bid and maximum profitable cap.

Run a **bounded, real-account E2E** using eligible low-value live auctions, with fully recorded actual account effects:

**E2E A — Bid Acquirer path**

`real filtered search → card/version match → >=5 fresh comparable asks → outlier-resistant target → X/tax/max bid → legal minimum initial bid → authoritative watched/leading readback → current spendable coin readback`.

If no candidate meets the requirements, distinguish *integration operability* from *strategy opportunity availability*. Do not manufacture a profitable candidate merely to check a box. A minimal separately identified integration test may bid on a cheap allowed card using explicitly labeled test economics without reporting it as a profitable trade.

**E2E B — Bidder path**

`bulk watched-auction refresh → leading? HOLD without additional bid → actual outbid? compute legal minimum next bid → compare to stored max cap and spendable balance → bid only if eligible → independently verify new state`.

Demonstrate a **real ordinary opening bid**. Attempt to observe a genuine competing bid and, if it occurs, verify the rebid path. If there is no genuine outbid during the finite test, mark *live outbid/rebid* UNVERIFIED, while supplying deterministic fixture tests for HOLD, conditional REBID, over-cap STOP_COMPETING, missing state and no duplicate bids. Do not orchestrate fabricated opponent trades or pretend fixture state transitions are live observations.

**E2E C — Resolution and resale handoff**

Observe auction terminal state from fresh watchlist/trade-status and account readbacks. Distinguish a verified **WON** from a verified **LOST** and from missing/incomplete status; reconcile returned/held coins and actual paid acquisition cost. If a card is conclusively WON, verify exact owned physical item, transfer-list movement and valid resale listing by fresh readbacks, leveraging Objective 001 primitives. Do not use an ambiguous status to move/list, or infer completed sale/realized profit without settlement evidence. If no terminal outcome is reached in the finite window, report it explicitly.

**E2E D — Timing and interruption**

Instrument watchlist bulk refreshes, pending bid dispatch, independent reads and timing across active observed auctions. Verify or clearly delimit 25-second monitoring viability with observed timings and requested cycle semantics. Test tab idle/extension suspension, server restart, reattachment, command ownership, ambiguous timeout and restart reconciliation. Simulate failures where necessary; require some genuine browser lifecycle validation, not just offline mocks.

Always preserve an account-correct journal of live test intent, actual bid amounts, fresh independent before/after states and outcomes. Do not allow uncontrolled loops or repeated writes after uncertain acknowledgments.

**Live evidence policy:** If a conditional market event (natural outbid, auction win, timer extension, sale) is not witnessed within a finite run, record UNVERIFIED and exactly what live continuation would establish it; this alone must not be mislabeled a success. A finished objective needs a truthfully scoped result; critical unverified dependencies imply CONDITIONAL GO/BLOCKED, not fictional FULL GO.

## Workstream D — Build the missing reusable infrastructure for Objective 002

Implement only underlying capabilities that do not exist yet, with clear contracts and test coverage:

- **Search adapter:** validated `maxBid`/ `minBuy` criteria, current PC persona handling, fresh network snapshots and full card/version identities.
- **Bid adapter:** ordinary opening/incremental bids with price legality, bounded one-shot invocation, durable intent-before-send, strict result schema and explicit UNKNOWN/reconcile behavior. No blind retry of a mutation.
- **Bulk-watchlist/status adapter:** single native watched-items refresh where supported, comprehensive cover-state metadata, correct treatment of missing/expired results, optional supplemental native bulk status if proven necessary, and integration with balance/held-bid reads.
- **Native rules provider:** available current caps, legal bid increments and expected listing tick contract, with verifiable provenance and rejection of unsupported values.
- **Bridge lifecycle:** ensure a long-running Edge connection can survive normal idle periods; diagnose the recorded `bridge_not_attached` failure. Maintain reattachment/session-epoch/scope checks and command ownership across Python/Edge processes; do not extract credentials, store auth material or bypass normal challenges.
- **Command scheduler primitive:** separate *local long-poll latency* from actual EA native request cadence, priority, concurrency and real response times. Do not encode the previously proposed **30-second gap as an EA requirement**: it was our own arbitrary engineering default and is configurable/removable. Measure observed behavior, select an evidence-based implementation, and report restrictions only if encountered in real integration or actual service response. Test competing read/write priority, bursts, stale work and skipped calls without inventing provider limits. Never claim a request cadence immunizes against EA account restrictions.
- **Durable test-level event journal:** versioned persistent auction/command correlation IDs, UTC state transitions and reason-coded bid/HOLD/SKIP decisions, pricing inputs/caps, requested/acknowledged/verified operations, balance changes, lifecycle errors, latency, and crash/restart reconciliation. Use transactional storage or equivalent reliable append-only persistence. Expose CLI/queryable sanitized per-auction chronological trace. This foundation must be directly reusable by Objective 002's complete persistent diagnostics.
- **Core test seam:** typed account-balance, auction-status, identity and intent records, fixture/fake adapters and injected clocks. Test 50 entries, 5,000-coin sticky DRAINING admission policy, 50-slot queue, leadership HOLD and minimum legal rebid, cap boundary, multiple pending auctions, eventual win/loss handoff and absence of duplicate writes **without implementing actor service loops**.

Keep new code isolated/versioned where practical; preserve historical 001/001B artifacts and existing verified read/write bridge behavior. Do not turn research-only source into an unfenced production trading loop.

## Workstream E — Independent validation, evidence and Objective 002 handoff

Produce:

1. `docs/research/001c-capability-matrix.md` — **per operation**: current implementation, source contract, live account request evidence, independent result/side-effect proof, status classification and unresolved issue. Explicitly include *search filters, legal bid ticks, opening bid, current bid/leading, outbid/rebid, bulk watchlist completeness/capacity, win/loss, held coins/refunds, won-item transfer/list, auction extension and bridge resilience*.
2. `docs/research/001c-e2e-report.md` — actual live test timestamps, exact commands, bid amounts, pre/post state, auction identities using stable sanitized local correlation, EA HTTP/native statuses, durations, and what **really occurred**; distinguish genuine auctions and actual mutations from fixtures. Any spent coins and unsold/won test card must remain accounted for.
3. `docs/research/001c-architecture-handoff.md` — importable/native method contracts, module locations, watched-status refresh budget (especially **one bulk request vs 50 individual requests**), measured timing, account cap, local command scheduling and recovery behavior. Specify exactly what 002 should reuse, what needs integration, and what remains blocked or conditional.
4. Bounded live test harness and versioned sanitized outputs, with an **independent validator** that detects fabricated claims, missing independent readbacks, duplicate bid writes, test outcomes labeled live without live network evidence, or historical evidence being relabeled as current.
5. Offline automated tests covering adapter validation, state model, bid-price increments, comparables, queue 50, sticky DRAINING, 25-second cycle model/priority behavior, 50-row bulk statuses, unknown outcomes, durability and crash/replay. Run existing relevant suites and document exact passing/failing commands.
6. A **GO / CONDITIONAL GO / BLOCKED** decision on whether both actors have all required primitive operations and credible live evidence. Include concise next steps for Objective 002 and a discrepancy list for current Objective 002 design, without silently revising strategy choices.

### Required live acceptance matrix

| Requirement | Required level |
| --- | --- |
| MaxBid=1000 + MinBuy=10500 search combination | Real authenticated FC27 PC request and validated response semantics |
| Minimum 5 exact-PC comparable pricing / max bid | Real fresh listings plus deterministic correct, reason-coded estimate |
| Native ordinary opening bid | **Real successful bid** with authoritative watched/account readback |
| Already-leading HOLD | Verified in live bid state, plus no additional bid write |
| Native watched-auctions bulk refresh | **Real authenticated call**, quantified native request count and coverage |
| Up-to-50 queue/status processing | Deterministic 50-auction tests; real account capacity and complete coverage if accessible |
| Outbid + minimal rebid within cap | Live evidence if real outbid occurs; otherwise must remain marked live-UNVERIFIED, fixture-tested |
| Lost and won terminal classifications | Independently demonstrated for any outcomes witnessed; other branches marked UNVERIFIED |
| Coin escrow/return/available balance | Genuine pre/post coin measurements and clearly separated uncertain cases |
| Won physical item → transfer/list | Real proof if a legitimate auction win is observed; previous Buy Now proof is reuse-only |
| Bid extension and 25-second monitored refresh | Measure from actual active auctions; disclose non-observed timing behavior |
| Connection/restart, no duplicate bid, diagnostic timeline | Live browser integration plus deterministic fault tests and persisted journal |

**Never replace missing genuine evidence with test fixtures.** If live conditions make a required competitive event impossible to observe in a finite test, report that dependency as outstanding rather than asserting Objective 002 is FULL GO.

## Work plan, boundaries and delivery

Suggested orchestrator DAG: (1) source/contract audit; (2) adapters and test seams; (3) bulk watchlist/limits live check; (4) bidding/rules/economics live check; (5) browser durability and durable journal; (6) bounded complete E2E where genuinely possible; (7) independent test/evidence audit and handoff. Parallelize independent offline research/coding; serialize real account mutations and browser operations.

Use actual signed-in Edge and only the official Web App's normal authentication. Never export credentials/session headers/cookies, never bypass challenge or access denial, never fabricate proof of account state or profit. Real bidding is permitted **only in deliberately bounded, evidence-recorded integration tests**; do not enroll a large live queue, run an unattended bidding actor, place repeated speculative transactions or automatically relist without a conclusive actual win. No third-party subscription spending. Treat EA account restrictions as a genuine platform risk; do not assert a ban-safe rate.

Publish final code, tests, docs, sanitized evidence and exact reproduction commands on `main` through normal Git workflow, without altering or rewriting sealed 001/001B artifacts or hiding pre-existing validation failures. If operator interaction is needed for Edge attachment/login, state the exact minimal action and resume only through normal access.

**Success = reusable, demonstrably functional native bidding + bulk auction-monitoring infrastructure for BOTH Objective 002 actors, independently tested on live FC27 PC auctions with all real and missing evidence correctly classified; no full autonomous actor implementation yet.**
