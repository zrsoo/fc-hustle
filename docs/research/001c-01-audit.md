# Objective 001C entry audit and bounded validation plan — 001c-01

Audit complete; **Objective 002 remains gated on Objective 001C**. This task
delivers an audit and plan, not native adapters or a live readiness claim. No EA
requests, browser recovery or account mutations were performed. Current browser
attachment, authentication and account state are **NOT_CHECKED**. All twelve
current 001C live rows remain **UNVERIFIED**. Historical observations retain their
original dates and classifications.

The [review ledger](001c/001c-01/review-ledger.json) records inspected inputs and
their hashes. The [machine-readable gap map](001c/001c-01/gap-map.json) and
[finite plan](001c/001c-01/validation-plan.json) are the contracts for subsequent
work. Scope was frozen before any production implementation; only audit artifacts
and offline artifact checks were added. [001C](../../objectives/001c-competitive-bidding-readiness.md)
and [002](../../objectives/002-two-actor-competitive-bidding.md) take precedence
over the older Buy Now-first handoffs.

## Entry state, preservation and actual baseline

Entry branch: `main`, tracking `origin/main`, HEAD
`c64be86ebdf07acfe18dcdb51db2ed7a7150f61c`. The initial tracked tree and index were
clean; `AGENTS.md` was the only untracked user file. The later recorder snapshot
also includes the newly authored audit recorder. Neither observation implies
that the user's file should be staged or edited. Python **3.13.17**, Node
**v26.13.0**. See [entry.json](001c/001c-01/entry.json).

The [preservation inventory](001c/001c-01/preservation.json) hashes every entry
tracked file and the user's `AGENTS.md`, with separate Git blob IDs so Windows
checkout line endings are not mistaken for edits. Keep all those bytes unchanged
for this audit. In later implementation, use new versioned code rather than
widening sealed research commands. Particularly preserve:

- Objective 001 [final seal](final/manifest.json), browser observations and
  capability captures, [native mappings](capabilities/native-item-mappings.json),
  [market sample](market/availability.json), and [transaction journal](transaction/live.json).
- Objective 001B [entry lock](001b/preservation.json), [T7 seal](001b/t7/manifest.json),
  frozen [protocol](001b/protocol.json), provider evidence and all experiment runs.
- Follow-up [source review](../../experiments/market_discovery_followup_v1/source-review.json),
  [preserved seals](../../experiments/market_discovery_followup_v1/runs/20261111T230544Z/preserved-seals.json),
  successful search capture, and partial live benchmark/checkpoints. No historical
  source pin, timestamp, observer prefix or result is rewritten to clear a check.

These commands actually ran from the workspace before the new acceptance tests
were written. Full output, timestamps, exit codes and hashes are retained in
[baseline.json](001c/001c-01/baseline.json). `{python}` means the active Python.

| Actual command | Result / implication |
| --- | --- |
| `{python} -m unittest discover -s tests -p test_*.py` | 196 tests; 195 passed, one pre-existing failure: `test_browser_access.BrowserAccessTests.test_criterion_0_inspection_is_current_and_does_not_assume_cdp`, line 112, retained inspection age 98,692.887 seconds exceeds 86,400. Do not refresh historical evidence to pass it. |
| `{python} tests/validate_001b.py --precommit` | PASS: retained artifact audit. |
| `{python} tests/validate_001b.py` | FAIL: `missing_scoped_commit_or_unrelated_changes`, `preexisting_unrelated_change_committed:docs/research/browser-access/live-v2.json`. Historical commit gate. |
| `{python} tests/validate_final.py` | FAIL: manifest/deliverable-set and old commit assertions (`artifact manifest differs from retained files`, missing deliverable commit/HEAD, unrelated files, Git verification). Predates later research. |
| `{python} -m experiments.market_discovery_followup_v1 validate --input experiments/market_discovery_followup_v1/runs/20261112T062256Z/search.json` | PASS: historical search integrity, not fresh access. |
| `{python} -m experiments.market_discovery_live_v1.validate --run-dir experiments/market_discovery_live_v1/runs/20261112T064306Z` | Nonzero: integrity PASS, benchmark completion BLOCKED; 1/9 windows, A=8/B=0/C=0 EA calls. Expected incomplete experiment, not an audit blocker. |

The new artifact checks do not depend on a live login, the age of a historical
inspection, a new commit, or external network availability. They check actual
retained outputs and preservation rather than declaring the whole repository
green. They include in-memory deletion, tampering and unsafe-plan counterexamples.

After recovery on 2026-11-13, **18/18 audit checks passed**. The final full run
executed **214 tests, with 212 passing and two historical age failures**; see
[verification.json](001c/001c-01/verification.json) and its hashed logs. In
addition to the entry inspection-age failure, the unchanged browser trace crossed
its 24-hour cutoff during the interruption, causing
`test_review_matches_executed_bridge_sources_and_retained_metadata` at line 91 to
report `stale_live_evidence` and its downstream missing-current-observation
errors. The audit checks independently replay that trace at both recorded run
times: valid at the entry baseline, stale at the final run. This is elapsed-time
behavior of existing tests, not a new account observation or altered artifact.

## Inspected implementations and dependency findings

**Identity and PC.** Reuse `MarketKey`, `Observation`, `Rules`, `Policy`, `Estimate`,
`evaluate`, `profit` and legal downward rounding from
[pricing.py](../../fc_access/pricing.py). Full definition/version, physical item
and trade ID are distinct. Preserve the follow-up
[persona.js](../../experiments/market_discovery_followup_v1/browser/persona.js)
guard: uppercase `PC` requires `isPC === true` and matching `GamePlatform.PC`.
Console/conflicting/throwing values fail closed. Do not regress to the old
lowercase-only assumption. Per-run pseudonyms/maps are insufficient for durable
cross-restart ownership: add stable local scope, epoch and correlation identity.

**Search and pricing.** The latest
[page](../../experiments/market_discovery_followup_v1/browser/page.js) and
[worker](../../experiments/market_discovery_followup_v1/browser/worker.js) support
`min_buy → minBuy`, `max_buy → maxBuy`, exact definition, club/league, 21 rows and
pages 1/2. `max_bid` is absent throughout the schema chain. Preserve cache
invalidation, bounded paging and duplicate/lookahead handling. The retained
06:22:57 UTC search returned 21 exact-version PC rows (definition 233731), with
native duration 136.6 ms and Python 172.421 ms. One sample proves no sustained
throughput or p95. The robust calculator already deduplicates, excludes candidate
trade/item, rejects mismatches/stale rows/outliers, requires five survivors and
uses a lower-quartile undercut. Its acquisition field is BIN cost; ordinary
bidding needs explicit bid-cost adaptation. `DEFAULT_BANDS` and caller-supplied
caps are hypotheses. Fresh native rules and profitable-cap provenance are gaps.

**Transactions and ownership.**
[transaction.py](../../fc_access/transaction.py) persists/fsyncs intent before
dispatch, uses an OS lock, and independently reads coins, owned items and transfer
pile. Its verified historical 200-coin Buy Now of definition 278230 subsequently
moved and listed the exact item at bid 200/BIN 250 for 3600 seconds (3570 observed).
Cached-read failure and fresh restart readbacks are retained. This proves neither
ordinary bids, escrow/refunds, auction wins, settled tax nor realized profit.
Buy is restricted to 200–500; listing <=1000 in 50-coin steps: experiment limits,
not native rules. Do not rerun its completed one-shot experiment.

The [transaction server](../../fc_access/transaction_server.py) has a volatile
single-pending slot, delivery flag, 60-second wait and late-result rejection;
extension Origin is shape-checked, not pinned to one ID. The search queue pins
Origin, rejects concurrent polls/work and uses a bounded 20-second long poll.
Neither is a durable shared registry, session-epoch protocol or crash-safe
per-auction journal. Preserve their strict schemas/privacy and at-most-one local
delivery concepts; add durable operation ownership and reconciliation separately.
An acknowledgement never releases a pending intent without authoritative reads.

**Attachment failure.** The retained
[benchmark](../../experiments/market_discovery_live_v1/runs/20261112T064306Z/REPORT.md)
ran A's first 300-second window (8/72 budgeted requests), then B's first command
returned `bridge_not_attached` with no EA network rows. Passive observation was
unavailable. The follow-up worker's poll loop exits to WAIT on error and has no
alarm/startup revival; the server's health expires after 45 seconds without a
poll. That is a plausible failure mechanism, **not a proven root cause**. Later
work should collect bounded idle/restart/reattachment evidence and separate
attachment, persona validity, authentication and actual market-service success.
The A=16/B=24/C=24 remaining discovery budgets belong to the old frozen campaign;
this audit does not resume it, repeat completed windows or reset budgets.

**002 dependencies.**
[execution architecture](execution-architecture.md), [handoff](obj002-handoff.md)
and [001B addendum](001b-obj002-addendum.md) provide identity, durability,
reconciliation and settlement design. Their `fc_execution/*` paths are planned,
not delivered. Preserve S1 store/models/identity → S2 bridge/session → S3 verified
rules/pricing → S4 scheduler/reconciliation/offline faults → bounded 001C live
proof → independent handoff. S6 actor operation stays outside 001C. Historical
L1–L8 guide evidence discipline; their Buy Now/two-cycle acceptance does not
replace 001C's twelve competitive rows. Source/fixture/HTTP acknowledgement alone
is insufficient; critical unproved primitives preclude FULL GO for 002.

## Current source reference, separate from live proof

On 2026-11-12, public GitHub `main` still resolved to
`fa0fdde132715b2c09a4cff1e51736a1794d635e`, the retained transaction pin.
[Source review](001c/001c-01/source-review.json) records the API URL, raw SHA-256,
line ranges, range hashes and four short excerpts. No upstream runtime was run.
The reviewed source supports these findings:

- `placeBid` delegates to `Item.bid` (1624–1633). Its lookup filters max BIN by
  offered bid (1243–1259), which can exclude the intended high-BIN candidate.
- `getWatchlist` invokes `requestWatchedItems` once (1723–1727). Native network
  fanout, freshness, completeness, pagination and account capacity remain unknown.
- Auction projection merges bid/trade status, and unrecognized result shapes can
  become empty arrays (303–321). Preserve distinct states and UNKNOWN coverage.
- Search exposes BIN bounds (1596–1609). The whole-file selected-symbol scan found
  no max-bid mapping, native range/tick provider, pile-size or bulk-status helper.
  This limits the finding to this file; it establishes no native API absence.

These are SOURCE_CONFIRMED_ONLY clues, with rules UNVERIFIED, from the
[pinned FC27 reference](https://github.com/liusihang/fc27-copilot/blob/fa0fdde132715b2c09a4cff1e51736a1794d635e/extension/content/page-inject.js).
Historical futjs/fut-api or FC25 status/cap endpoints are questions only. Obtain
current native rules/status provenance in a later bounded read phase. Review
licenses before copying upstream code.

## REUSE / ADAPT / IMPLEMENT / PROVE gap map

The following twelve rows correspond exactly, in order, to the required 001C
live acceptance matrix. A = Bid Acquirer; B = Bidder; both share a single
serialized bridge. Each row's full paths, gaps and independent proof obligations
are in [gap-map.json](001c/001c-01/gap-map.json). Current live status is UNVERIFIED
for every row; REUSE describes implementation/historical evidence only.

| Row / required operation | Actors / disposition | Gap and bounded proof |
| --- | --- | --- |
| search_filters — maxBid/minBuy | A: ADAPT / IMPLEMENT / PROVE | Add max_bid through all schemas; authenticated 1000/10500 request semantics, identity/paging and fresh candidate recheck. |
| pricing_cap — five PC comparables / cap | A+B: REUSE / ADAPT / IMPLEMENT / PROVE | Estimator survives; adapt bid cost, add verified rules; fresh five independent survivors, target/tax/X and rounded cap. |
| opening_bid — ordinary opening | A: ADAPT / IMPLEMENT / PROVE | One-shot minimum legal bid, durable intent; watched leadership and coin readbacks independent of acknowledgement. |
| leading_hold — already leading | B: IMPLEMENT / PROVE | Fresh highest-state decision yields journaled HOLD; command/network ledger shows zero extra bid. |
| bulk_watchlist — watched refresh | B: IMPLEMENT / PROVE | Native bulk adapter, separate states and coverage; real call count/bytes/routes/duration versus Transfer Targets. |
| queue_50 — queue/status capacity | A+B: IMPLEMENT / PROVE | 50-row fixtures, no 51st slot, sticky 5000-coin DRAINING; account cap if accessible, never mass live enrollment. |
| outbid_rebid — minimal rebid | B: IMPLEMENT / PROVE | Natural outbid only; min legal amount, immutable cap, actual funds, STOP_COMPETING; otherwise fixture-tested, live UNVERIFIED. |
| terminal_outcomes — lost/won | B: ADAPT / IMPLEMENT / PROVE | Fresh terminal plus independent ownership/account proof; missing/incomplete means UNKNOWN and retains queue slot. |
| coins — escrow/return/spendable | A+B: REUSE / ADAPT / IMPLEMENT / PROVE | Currency reads plus attributable holds/refunds/cost, nullable uncertain values; no assumed spendable refunds. |
| won_transfer_list — won item resale handoff | B: REUSE / ADAPT / PROVE | Conclusive actual win and cost before exact item movement/listing; historical Buy Now is reuse-only. |
| extension_timing — expiry / 25 seconds | B: ADAPT / IMPLEMENT / PROVE | Pre/post expiry timestamps and measured whole-queue network budget; no assumed 30-second reset or 50 individual requests. |
| lifecycle_journal — recovery / diagnostics | A+B: ADAPT / IMPLEMENT / PROVE | Stable scope/epochs, durable append-only trace and ownership; real idle/restart/reattach plus crash/no-duplicate fixtures. |

The shared foundation also requires typed account/auction/intent records, injected
clocks and fake adapters; command priority (urgent reconciliation/Bidder before
new entry, without starving recovery or listing); and transactional event history
with ordered UTC events and CLI queries. The 50-slot queue includes leading,
outbid, cap-exhausted and UNKNOWN auctions until confirmed terminal resolution.
DRAINING is sticky until **all** enrolled auctions resolve; reserve applies to
new enrollment, while existing bids obey actual funds and stored cap. Test those
policies as pure seams; do not implement actor service loops.

## Finite future live protocol, frozen before writes

This task's limits are **zero requests / zero mutations**. The following is a
later 001C integration plan, not execution performed or readiness inferred here.
Adapters, fault tests, independent assessor, durable intent, single command owner,
same-account epoch, native rules and fresh account/economic evidence must all
pass before any live write. Recovery follows the existing `AGENTS.md`; workers
must verify their own desktop control. Challenges/missing credentials require
normal user completion. Do not expose authentication values.

| Window | Maximum wall seconds | Maximum foreground native requests | Maximum mutation attempts |
| --- | ---: | ---: | ---: |
| R0 readiness / account/rules/coverage | 180 | 6 | 0 |
| R1 filtered discovery / comparables | 300 | 10 | 0 |
| R2 one idle interval + one local restart/reattach | 600 | 8 | 0 |
| E2E one auction / conditional outcomes | 900 | 60 | 4 |
| R3 read-only accounting closeout | 180 | 10 | 0 |
| Total, with no automatic extension | 2160 (36 minutes) | 94 | 4 |

Count every service-induced network request and every failed attempt; native
fanout consumes the same foreground budget. Cap aggregate EA traffic at **120**,
including passively observed background activity. Unmeasurable aggregate traffic
blocks writes; recording it as zero is forbidden. Windows expire on wall time,
including waits/recovery; deadlines and consumed budgets survive restart. No
catch-up, retry campaign, extra window or reset on reattachment. These ceilings
may end observation before all branches occur.

Enroll at most **one** auction. At most **one opening bid + one conditional
rebid + one won-item move + one won-item listing = four mutation attempts**.
Persisting an intent consumes its attempt budget even if dispatch/ack is unknown.
No Buy Now, relist, cancel, sold cleanup or watchlist mass enrollment. **Maximum
500 coins per bid**, **1000 coins cumulative gross attempted bid exposure**;
refunds never replenish that budget. Same-auction simultaneous liability is at
most 500. The effective bid ceiling is the minimum of 500, the verified legal
profitable cap and actual spendable funds, while the amount is always the minimum
legal opening/next bid. New entry must leave at least 5000 spendable coins; the
reserve never authorizes exceeding a cap on existing bids.

Strategic pricing uses >=5 fresh independent exact-version PC BIN asks, X=500,
projected tax `target // 20`, and profitable cap
`target - target // 20 - X`, rounded **down** using verified rules. Search
maxBid=1000 is not that cap. No eligible candidate is a legitimate outcome. A
separate later **INTEGRATION_ONLY** cheap-card test may use the same bounds and
verified rules if strategy opportunity is absent, but must label its test
economics explicitly; no automatic threshold relaxation or profitable-trade
claim. Source/fixture rules cannot authorize either path.

Stop new writes immediately on any time/request/mutation/coin ceiling; attachment,
tab/persona/scope conflict; 401/login/challenge; access restriction; 429; 5xx;
timeout/unknown acknowledgement; stale/conflicting identities; incomplete state;
missing rules/comparables; unavailable candidate; external account activity;
journal failure or duplicate intent. Preserve UNKNOWN and reconcile read-only
within the remaining healthy window. Honor Retry-After even past its end. Never
blindly redispatch a possibly successful mutation. Closing failures leave explicit
unresolved obligations, not invented settlement.

Observe HOLD, a natural outbid/rebid, win/loss, expiry extension and any sale only
if genuine events occur. Unwitnessed branches remain UNVERIFIED, with exact future
continuation needed. Do not fabricate competitors or force terminal outcomes.
Use fixtures for all conditional decisions, 50-auction ingestion, cap boundaries,
priority, DRAINING, partial coverage, ambiguous timeout, late/wrong-epoch response
and crash/replay. Live browser lifecycle evidence is still necessary. The target
is one **whole-queue** refresh per 25 seconds if observed behavior supports it;
one native watchlist invocation does not prove one EA request. Record measured
fanout/latency before assessing feasibility. The old 30-second guard is a local
arbitrary engineering default, **not an EA requirement**; leave sealed experiments
unchanged and test configurable pacing in new code. No ban-safe cadence claim.

For every attempt, persist stable local account/auction/item/command correlation,
UTC/monotonic times and epochs, actor/reason/state, pricing inputs/rejections,
target/tax/X/cap, intended amount before dispatch, acknowledgement and separate
fresh watched/owned/coins/transfer readbacks. Record network count, generic route,
status, payload size, freshness, coverage and timing. Keep held/refunded/spendable
coins, actual cost, projected profit and attributable realized proceeds distinct;
unknown values stay null. End with balances, consumed budgets, outstanding holds
and intents, exact owned/unsold cards and active listings. No auction absence or
balance increase alone establishes a win, loss, refund or sale. Retain unresolved
records across restart; subsequent accounting is read-only until safely resolved.
All evidence is allowlisted and sanitized; no credentials, cookies, tokens or
authentication headers are retained.

## Implementation exclusions and verification

Exclude **autonomous actor loops**, **mass enrollment**, **fabricated competition**
and **third-party subscription spending**. Do not build the 600-second Acquirer
or continuous 25-second Bidder services here. No provider purchase or entitlement
is needed. Native asks remain authoritative; the 001B comparison is partial and
no external production PC feed is validated. Do not clone unrelated repositories,
extract saved credentials, bypass restrictions or replay completed discovery.

Run independently from the workspace:

```text
{python} tests/test_001c01_audit.py
```

The validator covers all six 001c-01 criteria: entry/baseline/preservation; exact
twelve-row and both-actor gap coverage; evidence-backed implementation audit;
pinned current-source findings separated from live claims; finite windows,
budgets/stops/accounting; and exclusions. Its negative tests remove required
rows/actors/reads, alter historical bytes in memory, hide baseline failures,
promote source to live, remove stops/accounting and enable forbidden scope. It
does not replay a live collector or require human intervention. This audit can
pass while the full historical regression suite and old commit gates retain
their documented failures. Later tasks must deliver and independently assess
the actual adapters/live evidence before changing Objective 002 readiness.
