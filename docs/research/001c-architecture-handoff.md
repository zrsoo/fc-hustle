# Objective 001C architecture handoff to Objective 002

**Release: CONDITIONAL GO for foundation reuse and bounded prerequisite work. Objective 002 actor execution remains gated.**
The independently checked [matrix](001c-capability-matrix.md), [account report](001c-e2e-report.md) and
[release record](001c/001c-07/release.json) scope every claim. This audit issued zero EA operations.
All live statements refer to retained observations from 2026-11-13, not a current account refresh.
The release validator is independent of the execution adapters and earlier evidence auditors.
No autonomous actor loops are included.

The ordinary 800 first-participation bid, leading HOLD, eventual LOST and available-coin return were witnessed.
Active outbid/rebid, auction extension, competitive WON ownership/move/list, sale/profit and the 25-second
whole-queue live cycle remain **live-UNVERIFIED**. Missing coverage remains UNKNOWN.
No unattended actor execution is authorized by this conditional decision.

## Reusable contracts and integration boundaries

| Module / native API | Contract to reuse | Required Objective 002 integration |
|---|---|---|
| [contracts.py](../../fc_access/bidding_v1/contracts.py) | Frozen Identity, Search, AuctionStatus, Balance, Freshness, Coverage, Snapshot, BidIntent, BidResult. Schema 1; trade/item/version/platform remain separate. | Add durable account/game/platform registry ownership. Local owner/epoch/evidence IDs are correlations, never EA authentication material. Keep live and fixture stores separate. |
| [adapter.py](../../fc_access/bidding_v1/adapter.py) | NativeAdapter(executor,journal,provider,scope,owner,evidence_key,now); search(command_id,Search), watched(command_id), balance(command_id), bid_once(intent,status,balance,rules,observations,X), reconcile(command_id,status,balance). PageExecutor.attach/execute/reconciled is injected. | Supply one reviewed current transport; do not mix protocols from experimental servers. Preserve native freshness, actual route and positive projections. No actor starts on import. |
| [rules.py](../../fc_access/bidding_v1/rules.py) | RulesProvider(reviewed_hashes,allow_offline=False,max_age=300); load/validate NativeRules; minimum_bid and estimate_cap. Fresh exact-card caps plus continuous valid increment bands required. | BLOCKED until a reviewed LIVE_VERIFIED rules artifact satisfies the strict provider. Never use allow_offline/fixture mode to authorize native writes. One sampled accepted price is insufficient for a whole schedule. |
| [pricing.py](../../fc_access/pricing.py) | Exact MarketKey, independent trade/physical-item asks, candidate exclusion, freshness/outlier rejection, conservative target, integer tax and downward cap rounding. | Obtain >=5 exact-version PC samples, preserve target/tax/X/cap and inputs in events. Ask estimates are projected. Seller independence cannot be proved from unavailable seller IDs. |
| [core.py](../../fc_access/bidding_v1/core.py) | decide returns HOLD/BID/STOP_COMPETING/RECONCILE; AuctionQueue.admit/refresh/deadlines models 50 slots and sticky 5000 admission reserve. | Share ownership across both actors; every UNKNOWN and cap-exhausted auction occupies a slot until confirmed terminal. Coin floor limits new entry, not existing auction management. Replay queue/drain state transactionally. |
| [journal.py](../../fc_access/bidding_v1/journal.py) | SQLite WAL/FULL synchronization; intend before dispatch, one-use dispatch claim, append-only event triggers, ownership epoch, independent status/balance reconciliation; read-only trace CLI. | Link shared registry and full per-auction event transitions atomically; retain unknown intents across process changes. Store reasons, comparisons, balance/pricing provenance, timestamps and timings. Never prune unresolved evidence. |
| [scheduler.py](../../fc_access/bidding_v1/scheduler.py) | Injected monotonic clock; Work deadlines, priority, capacity, configurable native interval/concurrency, delivery vs service metrics, skipped stale work. | One global EA executor with concurrency=1. Urgent Bidder/reconciliation before acquisition, without starving recovery or verified resale. Rebuild decisions from fresh state after restart; never replay a serialized work queue. |
| [durability store](../../fc_access/durability_v1/store.py) / [adapter](../../fc_access/durability_v1/adapter.py) | Explicit ownership, process/document/worker fences, durable finite deadline/read/mutation/exposure counters, uncertainty stop; observed credits-route adaptation. | Keep account authentication, browser attachment, PC persona and native service success as independent gates. The transport poll is local and does not imply EA activity. |
| [live page](../../browser/e2e-live-v2/page.js) / [policy](../../fc_access/e2e_live_v2/policy.py) | Isolated bounded empirical search/caps/balance/watched/bid seam; numeric bid body projection, exact physical identity, independent readback. | Adapt proven route/cache/next-price details into the reusable protocol with new tests. This experiment is not a production replacement for the stricter adapter. |
| [resolution page](../../browser/e2e-resolution-v2/page.js) | Current native bulk status-lite plus independent full-version watched read. | Lite definition_id=0 is omitted data. Supplement with exact full-version read; missing results are UNKNOWN, never an inferred loss/win. |
| [transaction.py](../../fc_access/transaction.py) | Historical exact physical-item move/list, intent-before-write and independent readback principles. | Historical Objective 001 Buy Now proof does not establish competitive WON settlement. Require fresh native WON, physical ownership and actual paid cost before moving/listing. Relist/sale settlement need their own proof. |

The native contract is `services.Item.searchTransferMarket(criteria,page)` with `max_bid -> maxBid`,
`min_buy -> minBuy`, exact `defId`, count 21 and bounded paging. Actual query fields were `macr=1000`
and `minb=10500`. Search maxBid is an eligibility filter, never the stored profitable bid ceiling.
Lookahead rows, duplicates, disappearance and changed bids were observed; no exhaustive market coverage or server ordering guarantee exists.

`services.Item.requestWatchedItems()` yields a bulk array. The current native implementation can return cached data;
the observed dirty-inbox invalidation must precede an authoritative refresh. The original adapter's cache/route assumptions
must be harmonized with these current sources. Observed routes include `/watchlist`, `/user/credits`,
`/marketdata/pricelimits`, `/trade/status/lite` and `/trade/:trade/bid` under `/ut/game/fc27`.
Do not rewrite actual evidence to the older `/user/currencies` spelling. The durable parser adapts that route internally
while retaining the original response path for audit. Every operation must fail closed on unrecognized or cache-only responses.

`services.Item.bid(item,amount)` is an ordinary bid, with exact native physical-item identity.
The native currency helper `getIncrementAboveVal` returns the next absolute price: at 750 it returned 800.
Adding currentBid again was corrected in the isolated version. The strict reusable provider still requires verified bands;
client source and one accepted price do not prove all server bid/list increments or tax rounding.

## Request budget, timing and capacity

One fresh watched refresh was **one bulk GET**, not 50 per-auction GETs. Empty and single-entry live responses are proved.
The loaded inbox and server setting reported **50**, with platform split disabled. This is observed reported capacity,
not a saturation test, proof of server maximum or proof that 50 simultaneous active auctions cannot be truncated.
Use the lower independently established limit when smaller than configured 50. No 50-bid capacity experiment is needed for parsing tests.

At a nominal 25-second target, one bulk status call is 2.4 watched requests/minute, independent of client queue length
if live coverage is eventually proved. A balance read each cycle would make 4.8 reads/minute before extras.
Rebids, balance, fresh availability, card caps, comparables, supplemental status and post-write readbacks are **additional** calls.
For k rebids, a conservative example is one status + k bid writes + 2k independent status/balance readbacks,
plus required fresh eligibility/economics: at least 1+3k calls before those extra prerequisites.
This is a planning example, not an established provider limit. Count actual network fanout and cached zero-request calls separately.
Never allocate 50 individual status calls merely because the queue has 50 entries.

Resume 02 watched native durations were **76.000, 93.800, 91.800, 106.600, 97.600 ms**.
The 800 bid measured **343.700 ms native**, **377.398 ms host**, **4.393 ms claim-to-native-start**;
the first independent watched response finished **158.000 ms after bid response**.
Actual active refresh starts were **58.326, 48.736, 41.391 seconds** apart.
The intended 25-second pair was interrupted. These measurements do not prove sustained 25-second whole-queue monitoring.
The 50-row offline model uses a synthetic 200 ms service and finite 25-second checkpoints; a 51-second service misses its deadline
and skips stale work. Its simulated concurrency peak 2 is not a native production setting.

Durability work retained eight authenticated read successes at **62.300-178.000 ms**, ten deliveries and two uncertain/failed outcomes.
Local transport latency is distinct from native EA duration. The historical 30-second gap was an engineering default,
not an EA requirement; the new scheduler defaults to zero interval and configurable concurrency. No ban-safe cadence is claimed.

## Lifecycle, recovery and diagnostics

Observed idle lasted **319.945 seconds**, exceeding the earlier 300-second detachment boundary, with zero EA calls while idle.
Controlled host restart reattached under a new fence in **14.081 seconds**, preserving original counters/deadline;
extension reload, page refresh and ownership changes were followed by genuine native GETs. These finite observations
are LIVE_VERIFIED only for their sampled read-only lifecycle behavior, not for unattended reliability or live crash-during-write safety.
Offline tests cover actual child-process termination around simulated dispatch and durable unknown/reconciliation behavior.

Every delivered command remains consumed even if its result is missing. Never blindly retry a mutation.
After an ambiguous write, stop new writes; reacquire fresh exact status, balance and identity under the current owner/epoch,
then record reconciled state or UNKNOWN. Recovery cannot reset deadlines, charged budgets or old command IDs.
Resume 02 expired during an outage; recovery sealed it with **zero native requests after deadline**.
Terminal observation used a separate four-read window. Closed/outbid at 1200 was observed after the outage, not an active outbid event inside it.

When browser recovery is needed, reread AGENTS.md, verify this worker's actual desktop access, intended Edge official tab and foreground,
then use normal saved sign-in UI, reviewed extension attachment and required localhost service. CAPTCHA/2FA/missing credentials need user action.
Never extract credentials/session material. Attachment alone is not persona validation, authentication or EA market-service success.
This audit needed no browser recovery; earlier recovery permissions do not authorize another live test here.

The read-only diagnostic seam is:

```text
python -m fc_access.bidding_v1.journal path/to/events.sqlite --scope <local-32-hex-scope> --trade-id trade:<local-24-hex-id>
python -m fc_access.release_audit_v1
python tests/test_release_audit.py
python tests/check_release_publication.py
```

Keep acquisition/decision/outcome events ordered and reason-coded, with actor, epoch, intent/read IDs, pre/post state,
target/tax/X/cap, required amount, available balance, HOLD/SKIP/STOP_COMPETING/RECONCILE reason, dispatch/native duration,
unknown acknowledgments and independent settlement evidence. The registry's latest state is not a replacement for append-only history.

## Locked-strategy discrepancies and release gates

The locked source is [Objective 002](../../objectives/002-two-actor-competitive-bidding.md).
It remains byte-identical. Earlier Buy Now-first handoffs are superseded. No strategy change is silently introduced.

| Locked requirement | Evidence / discrepancy | Required continuation |
|---|---|---|
| 600-second acquisition cadence | No actor/cadence implemented in 001C. | Integrate later after prerequisites; yield to Bidder, no unbounded mass enrollment. |
| maxBid=1000, minBuy=10500; >=5 exact asks, X=500, 5% projected tax | Current observed filters and 12-ask estimate support this boundary. | Keep ask economics distinct from realized profit; refresh after stale/changed cards. |
| Minimum opening/rebid; legal downward cap | 750 -> 800 ordinary first participation proved. Objective prose says “hundreds”; current client tick at this price is 50. | Do not hard-code 100-coin steps. Prove supported bands and integrate reviewed rules. Search 1000 is not an eventual bid cap; the experiment's 1000 ceiling is a finite-test limit only. |
| 50 unresolved queue; 5000 sticky DRAINING | Fixture behavior is OFFLINE_VALIDATED; account reports capacity 50. | Shared durable registry must enforce lower known account capacity and retain UNKNOWN until terminal. Balance recovery cannot end draining until every enrolled auction resolves. |
| Whole queue each 25 seconds | Small live reads fast; manual intervals exceed target and sample interrupted. | Prove coverage and actual cycle timing including bursts; use target semantics and deadline skips, never a guarantee. |
| Natural active outbid -> minimum rebid | Only eventual closed/outbid LOST witnessed. | Authoritative active outbid, fresh eligibility/balance, minimum <= stored cap and independent new state. |
| WON -> owned physical card -> move/list | No competitive WON; zero new cards and zero move/list writes. | Independently prove ownership, actual paid acquisition price, legal listing and readbacks. Historical Buy Now proof cannot fill this gate. |
| Held funds/refunds and terminal slots | 800 available debit/return and exact LOST witnessed; direct held field and transient refund timing absent. | Use observed spendable, keep pending holds unknown, avoid double counting; retain conditional semantics. |
| Bridge/durable journal/global queue | Finite read-only lifecycle and crash fixtures pass; adapter protocols still differ. | Integrate current native contracts, one executor and atomic shared diagnostics without bypassing rules validation. |
| Timer reset / realized profit | Both live-UNVERIFIED. | Observe natural near-expiry traffic and independently settled sales before making either claim. |

Critical missing prerequisites therefore prevent a full GO: strict rules/current adapter integration, natural active outbid/rebid,
conclusive competitive WON/resale handoff, and whole-queue coverage/timing. CONDITIONAL GO permits reuse and bounded validation preparation;
it does not release the two autonomous actors. Reassess the decision after each independently verified gate.

## Precise finite continuation

There is nothing to replay for either historical bid. At the last retained reads: zero paid cost, zero unresolved active bids,
zero new owned/unsold cards, spendable restored to 16268. Leave the expired outbid target unless cleanup is separately authorized.

A separate recorded continuation, if authorized, has **one new auction, at most 900 seconds, 40 reads, two bid writes,
four mutations total, gross exposure 2000, individual bid ceiling 1000 and reserve 5000**.
All counters must persist; refunds do not replenish the gross test budget. Select an eligible auction expected to expire within remaining time.
Obtain fresh PC search, full physical identity, >=5 comparables and native caps/ticks. Reserve intent durably before the minimum first bid;
independently verify watched state and spendable balance. HOLD when leading. Only after a natural active outbid may one eligible minimum rebid occur.
Record naturally occurring near-expiry pre/post timestamps to test extensions; never fabricate an opponent.
On conclusive WON, require exact owned physical item plus actual paid cost before at most one move and one legal listing with separate readbacks.
Stop at ambiguity, access challenge or any time/request/coin/mutation ceiling; unwitnessed events remain live-UNVERIFIED.
This specification is a handoff, not a command to start another auction or actor loop.

## Verification and publication

[checks.json](001c/001c-07/checks.json) retains exact test argv, timestamps, output hashes and actual exit codes.
Eighteen targeted checks passed; historical original E2E acceptance exits 1. Full discovery ran 361 tests with two known freshness failures
in historical browser-access checks. Sealed timestamps were not rewritten to suppress them. New release rejection tests cover false live claims,
missing authoritative readbacks, duplicate writes, fixtures relabeled live and historical evidence relabeled current.
The [staged Git whitespace checks](001c/001c-07/git-checks.json) also retain an actual exit 2 for preserved research log whitespace;
the scoped source/tests/release documents pass. No sealed log was normalized to suppress this failure.
The [payload manifest](001c/001c-07/payload-manifest.json) and independent publication validator verify committed sanitized artifacts on main,
baseline ancestry and actual remote main. No history rewrite, credentials, mutable SQLite transport files or actor loops are included.
All 645 pre-existing file hashes remain intact; unrelated AGENTS.md stays untracked. `.orchestrator/` and `private-captures/` remain ignored.
