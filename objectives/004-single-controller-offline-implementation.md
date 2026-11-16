# Objective 004 — Encapsulated single controller, offline implementation

## Outcome and execution boundary

Implement a new continuous FC27 PC controller with exactly two operational
phases, **ACQUIRING** and **MANAGING**, replacing the two concurrently running
Acquirer/Bidder processes for this new mode. Reuse and import proven production
infrastructure where its contracts fit. Keep the new orchestration, state and
policy encapsulated, preferably in `fc_access/controller_v1/`.

The orchestrator must implement the controller, repair implementation defects,
run complete offline verification, document the result, and commit/push to
`main`. **Then stop. Live E2E testing, production cutover and subsequent live
adjustments belong to the user and the hands-on assistant.**

This objective authorizes **no EA request, including read-only requests**, no
interaction with Edge/login/extensions, no production service deployment,
and no real-account controller/actor/maintenance execution. Tests may start
isolated fixture processes and loopback services with synthetic account data.
Do not use production ports/databases/session owners as test fixtures. The
existing browser-recovery authorization does not expand this offline scope.

Keep Objective 003 (`obj-da182a175410`, task `003-04`) paused. Do not resume,
recheck, complete, replace or otherwise edit its orchestration records. Preserve
Objective 002's historical verdicts and all prior runs, incidents, budgets and
evidence. This is a new implementation contract; older objectives retain their
original policies and historical meanings. Do not implement deferred changes to
the orchestrator itself.

Workspace: `C:/hustle/fc-hustle`; branch: `main`.

## Read before implementation

- [AGENTS.md](../AGENTS.md).
- [Objective 002](002-two-actor-competitive-bidding.md) and
  [Objective 003](003-production-actor-soak.md), for reusable mechanisms and
  historical context; the explicit policy replacements below govern this mode.
- [Production pricing/Foundation handoff](../docs/research/001d/001d-07/REPORT.md).
- [Bid receipt repair and live proof](../docs/research/003/003-04/bid-receipt-repair-01/REPORT.md).
- [Missing-wire balance incident](../docs/research/003/003-04/production-06/REPORT.md).
- [Later unconfirmed rebid and recovery](../docs/research/003/003-04/production-07/REPORT.md).
- [Verified bulk transfer operations](../docs/research/002-bulk-transfer-operations/REPORT.md).
- Existing `production_v1`, `actors_v1`, `bidding_v1`, and `continuous_v1`
  contracts, transport, pricing, journal, ownership, receipt and resale code.

Inspect the current Git/process/database state rather than assuming these
historical reports describe the present. Establish that no competing production
worker is active. Preserve unrelated changes. Back up the working tree and any
existing state needed for compatibility work before changes; never mutate live
state to test or migrate this implementation. No credentials, authentication
headers, cookies, tokens or EA session identifiers may be read or retained.

## Architecture and reuse boundary

- One controller owns the account lifecycle. Operational phase transitions,
  command delivery and native account actions are sequential. No separate
  Acquirer, Bidder or maintenance worker processes are started by this mode.
  Lifecycle controls such as paused/stopped are distinct from the two phases.
- Reuse the exact-version pricing/cache implementation, native card limits and
  increment helpers, official native methods, safe identity projections,
  authentication/context fences, durable command IDs and evidence utilities.
  Reuse ownership and persistence primitives where suitable.
- Build new phase orchestration and policy rather than subclassing the old actor
  loops. Avoid copying their trading engine into a second collection of nearly
  identical files. Document imports, necessary shared changes and their callers.
- Existing Foundation/journal/broker/page code embeds legacy policy: per-bid
  fresh credits, global unresolved-command gates, page poisoning and supervisor
  stops. Separate those policies from reusable mechanisms. Do not silently
  inherit them, add fake successful results, or disable validation globally.
- Use an explicit new-mode dispatch/admission contract with server-side durable
  authority. An arbitrary request flag must not enable account writes. Retain
  legacy behavior for legacy entry points and historical evidence readers.
- Persist controller phase, batch identity, selected candidates, stored quotes/
  caps, attempted commands, results, confirmed management membership, deadlines
  and phase transitions. A crash or lost reply must not turn an old command into
  replay work. Keep SQLite transactions short; no write transaction or broad
  account lock may be held across awaited network operations.
- One account owner and one serialized native executor remain. Keep request
  pacing centrally configurable, initially the existing two-second spacing,
  without claiming this is a proven EA-required interval. Local helpers that
  issue no EA request do not consume an EA network slot. Parallel EA requests
  and changes to the pricing strategy are outside this objective.

## Agreed policy

| Setting | New-mode default/requirement |
|---|---|
| Acquisition entry balance | Strictly greater than configurable `40000` coins |
| Credit reads | One before each acquisition batch; none during its bid burst or MANAGING |
| Discovery | One page-1 GET, count 21, PC players, `maxBid=1000`, `minBuy=11000` |
| Initial auction lookahead | More than 60 seconds remaining at candidate selection |
| Batch size | At most 10 distinct initial-bid attempts |
| Management membership | Only independently confirmed participation; at most 10 per batch |
| Initial/rebid amount | Smallest native legal amount, never above stored profitable cap |
| Management cycle | Five-second target; sequential, with no overlapping/catch-up cycles |
| Next acquisition | After the managed batch settles; empty/rejected batches retry immediately |
| Ambiguous operation | Persist, abandon the uncertain command, continue; no global write gate |
| Pricing | Existing exact-version two-search minimum-valid-BIN algorithm; completed cache TTL 86400s |
| Profitability | Existing 5% tax calculation, `X=500`, native legal floored cap |
| Resale | Stored BIN; starting bid one native tick below; duration 3600s |
| Maintenance | Existing verified sold clear; expired relist every 3660s, unchanged prices/3600s |

These replace the legacy ten-minute acquisition timer, one-bid-per-cycle exit,
25-second monitoring target, 50-auction actor queue limit, sticky 5000-coin
DRAINING policy, repeated credits-based bid admission and global stop on an
uncertain action **for this new mode**. Do not add a sum-of-caps funding test,
per-auction budget allocator, a larger lookahead, acquisition retry timers, or a
requirement to resolve every ambiguity before making another write.

The balance threshold is an entry rule, **not** proof that every possible rebid
is affordable. EA can reject a later bid for insufficient funds. Record that as
an operation outcome and keep running under the defined rules.

Ten is the per-batch attempt/confirmed-management limit. An uncertain discarded
submission may nevertheless have registered with EA. Consequently this policy
does **not** guarantee ten actual account participations across successive
batches. Expose that uncertainty honestly; do not restore a hidden global
reservation gate that defeats the user's non-blocking rule.

## ACQUIRING

1. Start/recover a durable acquisition batch. Obtain one genuine native credits
   observation for this batch. Proceed only when credits are strictly greater
   than the configured threshold. At or below the threshold, halt the controller
   with a durable, operator-visible reason; do not begin bids or fabricate a
   balance. A failed read supplies no admission authority; handle it as a logged
   operation failure, without claiming the threshold passed.
2. Obtain one discovery page using the filters above. There is no automatic
   three-page discovery inherited from the legacy actor. Record its observation
   time, exact identities and all returned bid/BIN/expiry fields.
3. Establish eligibility and price each distinct exact version through the
   existing pricing service. Completed cache hits require zero pricing searches.
   Uncached versions retain the existing first-page search, exclusions, early
   rejection and second `maxb=first_min` search, at most two. Preserve the default
   600/10000 template exclusions and diagnostic-only `last_sale_price`. No
   alternative estimator, progressive probing, sorting, undercut or third search.
4. Select up to ten distinct eligible auctions. Require the native minimum next
   bid within the stored profitable cap, an active tradeable exact item/version,
   no existing confirmed management membership or duplicate attempted action,
   and more than 60 seconds remaining after subtracting elapsed observation age
   at selection. For an unbid auction use its legal starting bid; otherwise use
   the absolute native next increment. Retain the other applicable identity,
   legality, ownership and complete known inventory/capacity checks.
5. Preserve the physical Transfer List limit and known combined pipeline limit
   of 50, including manual/sold/expired items and known pending wins. A complete
   inventory observation can be shared across the batch under its documented
   validity contract. Unknown inventory cannot be treated as empty. This does
   not silently turn discarded uncertain actions into global blockers.
6. Persist the selected batch and an individual durable intent **before each**
   initial bid. Submit the selected bids sequentially, once per intended action.
   Use the retained native identity mapping and explicit batch authority. Do not
   repeat market search, credits and inventory GETs per candidate as the old
   actor did. Do not enforce the old per-bid credits-read freshness contract by
   issuing extra credits GETs. Record the actual age of batch observations;
   never relabel old observations as fresh. Skip a locally known expired or
   otherwise invalid action. Changed server price/availability can produce an
   ordinary rejection; do not silently raise the bid or retry the mutation.
7. Confirm the submitted auction identities through the exact-target batch
   status API below. An HTTP 200 or input-derived service `itemIds` is not
   independent participation proof. Confirmed highest **or outbid** participation
   can enter MANAGING. Handle independently established terminal results
   truthfully, including ownership/paid-cost verification for possible wins.
8. Hand off only confirmed participation to normal management. Persist discarded
   uncertain/rejected actions separately. If no managed work remains, stay in
   ACQUIRING and start another batch immediately, with its own initial credits
   read. No ten-minute/empty-batch backoff timer; existing request pacing still
   applies. Suppress duplicate uncertain-command replay across these batches.

One minute remains the eligibility window; do not extend it to avoid recording
rejections or misses. Record actual acquisition/burst/handoff durations and
expiry misses for later hands-on assessment. Offline completion must not claim
that this window eliminates expiry risk.

## Exact-target batch status and request attribution

The captured native client accepts an array:
`services.Item.transfersDao.getAuctionData([nativeItemA, nativeItemB, ...])`,
constructing one GET to `/ut/game/fc27/trade/status/lite` with comma-separated
`tradeIds`. Implement an explicit adapter operation for **only the requested
auction set**, up to ten here, with genuine one-native-invocation/one-GET
behavior. Do not repeat the filtered market search as confirmation.

Resolve native selectors privately from retained current-document mappings.
Never reverse pseudonyms, guess IDs, or reuse a lost browser epoch's mapping.
Validate each returned trade/item pair, duplicates, unexpected identities,
missing rows, malformed data and exact requested wire IDs. Native lite version
0/null may be interpreted using retained full-version evidence; record that the
version was unobserved and preserve the original response unchanged. Extending
read-only lite observations into new-mode bid authority needs an explicit tested
link to the retained full item/version and current native DTO, not a global
relaxation of legacy status contracts.

Test the captured/source-backed contract offline. **Actual multi-ID server
behavior, response completeness and practical limits remain LIVE-UNVERIFIED
until the later hands-on E2E.** No live probe is authorized by this objective.

Repair the attribution defect that lets unrelated manual UI/background traffic
contaminate the active command's captured request count. Identify owned requests
at the appropriate native/request boundary. Keep unrelated traffic as sanitized
diagnostics; it must not manufacture a failed command or successful owned
request. An actual missing/mismatched owned request remains unconfirmed.
Do not simply ignore every extra request or count arbitrary HTTP 200 traffic as
the command. Preserve exact write-target/body binding, receipt validation,
authentication, context/epoch checks and observation timestamps. Temporary hooks
must restore on success, rejection, timeout, interruption and late callbacks.

## MANAGING

1. Refresh only the managed exact auction set with a batch status GET. Target
   one cycle every five seconds; report elapsed time and missed targets. A slow
   cycle must not spawn a second cycle or replay a mutation to catch up.
2. Evaluate each auction, prioritizing the closest actionable deadline. Highest
   means HOLD. Outbid means consider the smallest legal increment, respecting
   the stored profitable cap and native legality. Cap-exhausted active auctions
   remain observed until a genuine terminal result. Do not revalue the chosen
   resale policy merely because monitoring continues.
3. Send eligible rebids sequentially through the same durable native authority.
   No credits GETs during this phase. Confirm submitted target IDs with batch
   status readbacks; every auction/result is independently correlated even when
   several share one response. Missing/ambiguous actions follow the non-blocking
   policy below. Do not substitute acknowledgements for confirmed participation.
4. Process verified LOST and possible WON. WON still requires exact physical
   ownership and paid-cost proof, then existing one-hour move/list/readback logic.
   Perform necessary resale and verified bulk maintenance as sequential work of
   this controller, behind urgent auction management. No extra actor/cron process.
5. Once the managed auctions have genuinely settled and required known win
   handling is accounted for, transition to ACQUIRING. Waiting for a long final
   auction is accepted. A missing row or elapsed timer alone does not prove loss.

## Non-blocking uncertainty and restart semantics

- Missing/malformed/ambiguous operation results are durable diagnostic outcomes,
  not global controller blockers. Abandon the uncertain action; do not halt the
  controller, poison its entire bridge, or forbid unrelated later writes solely
  because that action is unresolved. A failed rebid does not erase the auction's
  previously confirmed membership. Later fresh observations can support a new,
  distinct decision, without replaying the uncertain command.
- Never automatically replay a claimed/possibly sent command, including after
  restart, reconnect, late response or another empty acquisition batch. Persist
  tombstones/correlation sufficient to prevent disguising the same uncertain
  action as a new command. Continue with other eligible work.
- Retain native acceptance receipts and positive independent confirmations.
  Uncertainty is neither REJECTED nor LOST, and grants no refund/ownership claim.
  Preserve a queryable audit of potentially untracked account effects. Do not
  keep uncertain actions in an invisible queue that blocks future phases/writes.
- Keep authentication/identity checks, account ownership, endpoint/body checks,
  input schemas and durable-intent requirements. Missing valid admission data
  does not authorize a fabricated decision. Failed durable intent storage cannot
  authorize an unjournaled mutation. Security challenges still require the user.
- Recover phase/batch progress and existing commands conservatively. Old submitted
  commands are audit/recovery inputs, not dispatch work. Preserve scope across
  restart and reacquire native mappings before new operations after reconnect.
- Persist sufficient sanitized diagnostics: phase/batch/command IDs, exact public
  identity tuple, amount/cap/decision, snapshot source/age, elapsed expiry,
  dispatch/return times, HTTP status, allowlisted error codes, native/wire item
  counts, receipt/stale/state fields, requested/returned/missing target sets,
  subsequent observations, exception category and relevant queue/helper timings.
  Attribute background activity without storing credentials, headers, raw native
  IDs, arbitrary native exception strings or unrelated response bodies.

## Ordered implementation and acceptance

### 004-01 — Establish baseline and reusable contract boundaries

Inspect/back up the current workspace and preserve paused legacy state. Map
reusable modules and identify inherited policy gates that conflict with this
objective. Write a concise implementation/verification plan and additive state
compatibility design. No production data migration is executed.

Acceptance: preserved baseline; clear new ownership/state/configuration/API
boundaries; explicit reuse imports and legacy compatibility; every agreed policy
and the offline-only stop boundary covered by the plan.

### 004-02 — Implement new-mode native contracts and attribution

Implement the exact-target batch status operation and request correlation.
Provide explicit durable batch/write authority and non-blocking outcome delivery
for the new mode, without weakening legacy entry points or pretending a receipt
is an independent confirmation. Remove inherited global uncertainty gates only
for the explicit new policy.

Acceptance: behavioral Python/Node tests execute actual adapter/page/transport
code with synthetic native observables/XHR. Verify ten requested identities in
one GET, exact selector binding, partial/duplicate/wrong-item/version results,
native lite omissions, manual traffic interleaving, zero captured owned request,
late response/timeout cleanup, authenticated scope and exactly-once dispatch.

### 004-03 — Implement the encapsulated two-phase controller

Implement the phase loop, batch journal, configurable entry threshold, single-page
discovery, imported pricing, ten-attempt acquisition burst, batch handoff and
five-second management. Preserve legal minimum bids and stored caps; no hidden
legacy timer, balance checks, DRAINING or one-bid break. No overlapping phases,
actor processes or catch-up cycles.

Acceptance: deterministic complete controller tests acquire multiple auctions in
one batch and manage them to synthetic terminal outcomes. Verify exact credit/
discovery/pricing/status/bid request counts, threshold equality/below/above,
cached/uncached valuation and version reuse, >60-second selection boundaries,
expired/changed-price candidates, ten-attempt limit, confirmed highest/outbid,
mixed/empty/entirely rejected/uncertain batches, immediate paced reacquisition,
cap HOLD, deadline ordering and non-blocking later writes after uncertainty.

### 004-04 — Integrate lifecycle, resale, maintenance and recovery

Provide explicit run/status/pause/stop controls for the new controller, with no
import-time execution and no production cutover during this objective. Reuse
verified ownership, resale and bulk behavior through the new authority. Keep
state and logs restart-readable, and preserve legacy evidence/contracts.

Acceptance: offline fault/process tests cover interruption before/after durable
intent, dispatch claim, lost reply, confirmation and phase transition; restart
does not duplicate writes or lose confirmed membership. Test stale owners,
reconnect mapping loss, low entry balance, known capacity, owned/paid win proof,
one-hour stored-price listing, relist/clear readbacks, ambiguous maintenance and
pause/stop quiescence. Commands default to no account activity unless explicitly
started; fixture tests cannot attach to the production account/service/state.

### 004-05 — Verify offline and hand back for live E2E

Run the entire Python suite, all relevant JavaScript/Node suites, new-mode
independent validators and applicable existing offline production validators.
Investigate and repair actual failures. Keep historical receipts immutable;
where tests improperly compare sealed historical suite inventories to the current
test tree, separate historical catalogs from current discovery. No source/test/
instruction/configuration hash assertions, forged expected results, skipped
failures or deletion of tests to manufacture a green suite.

Deliver `docs/research/004/REPORT.md` with architecture/reuse map, implemented
policy, exact commands/counts/results, encountered failures/fixes, persistence
and compatibility behavior, timings measured offline, remaining risks and a
concise hands-on E2E checklist. Include exact future CLI instructions, but do
not execute the live commands. Distinguish fixture/offline proof from historical
and future live evidence.

Acceptance: zero failures/errors in required offline checks; meaningful validators
cover every task acceptance criterion; source/report committed and pushed to
`main`; final verdict **OFFLINE IMPLEMENTATION COMPLETE — LIVE E2E PENDING**.
The final report must leave the new controller undeployed and all production
controllers/actors stopped. No four-hour soak, live account outcome, live batch
API test or post-live tuning is required or authorized. Do not resume Objective
003, submit another objective, launch continuous trading, or keep making live
adjustments after this handoff.
