# Objective 001B research scope and benchmark preregistration — T1

T1 establishes the evidence baseline, reusable contracts and measurement plan.
It performs no browser experiment, provider retrieval or account mutation. The
benchmark is **PREREGISTERED_NOT_RUN**; actual UTC start/end, latency and yield
are unknown. Completion of T1 does not claim completion of Objective 001B.

The [review ledger](001b/review-ledger.json) records completion of all five
required document reads before implementation or experiments. The machine-readable
[protocol](001b/protocol.json) is normative for subsequent collectors; the
[preservation inventory](001b/preservation.json) pins the existing evidence and
contracts. Run `python tests/test_001b_scope.py` from the workspace to check them.
These checks use local artifacts and synthetic negative cases; they send no
commands to EA, the browser or providers.

## Evidence reviewed and located

| Required document | Finding carried into this research |
| --- | --- |
| [final-report.md](final-report.md) | Objective 001 is BOUNDED_VALIDATION_DEMONSTRATED, with conditional GO for implementation. Production readiness and current attachment do not follow from the historical audit. |
| [market-strategy.md](market-strategy.md) | Native exact PC asks work historically; bulk manifest/catalog were denied with 403. Caps, full increments and actual tax rounding remain unverified. Hypothetical-cap replays returned -210 and -57 modeled coins. |
| [confirmed-capabilities.md](confirmed-capabilities.md) | Edge produced 14 authenticated network reads; direct HTTP produced zero. Exact definition, club and league filters worked; nation/rarity/position, cache hits and TTL remain unverified. |
| [execution-architecture.md](execution-architecture.md) | Preserve exact identities, UTC times, integer coins, unknown/null semantics and independent freshness. Future execution interfaces and recovery are specifications, not a delivered bot. |
| [obj002-handoff.md](obj002-handoff.md) | Reuse the pure pricing implementation; future execution modules and bridge are separate. S1–S6 and new live release evidence belong to Objective 002. |

| Reusable source or sample | Existing contract and boundary |
| --- | --- |
| [pricing.py](../../fc_access/pricing.py) | `MarketKey`, `Observation`, `Band`, `Rules`, `Policy`, `Estimate`, `evaluate`, `profit`. Pure integer/Fraction computation; full `definition_id`, platform and game must match. `DEFAULT_BANDS` is hypothetical; supplied caps do not become verified by passing tests. |
| [harness.py](../../fc_access/harness.py) | `Transport.read(operation, params, evidence_key)`, `command`, `validate_result`, item/auction projections. Read-only operations: coins, club, unassigned, purchased, transfer_list, search. Schema acceptance is distinct from empirically verified filter support. |
| [transaction.py](../../fc_access/transaction.py) | `command`, `fresh`, `TransactionTransport`, single-shot `Experiment`. Historical buy/move/list contracts are reference evidence only. Do not invoke the experiment or widen its bounds. |
| [transaction_server.py](../../fc_access/transaction_server.py) | `127.0.0.1:8768`, protocol 3; strict Host/extension Origin, bounded schema, one in-flight command, single delivery, late/duplicate result rejection. `/health` is attachment only. |
| [worker.js](../../browser/transaction-bridge/worker.js) | `chrome.alarms` period 0.5 minutes, serial `poll`, selected official HTTPS EA tab, POST `/next` with `bridge_version:3`, POST `/result`. End-to-end waiting includes local delivery delay. |
| [read-page.js](../../browser/transaction-bridge/read-page.js) and [page.js](../../browser/transaction-bridge/page.js) | Read envelope `id`, `evidence_key`, `operation`, `params`; allowlisted projections, page-side validation and per-run identity maps. Preserve the existing research bridge bytes. |
| [native identity mapping](capabilities/native-item-mappings.json) and [native read source shapes](capabilities/native-source-shapes.json) | Wire `resourceId` becomes native `definitionId`; physical `itemData.id` and auction `tradeId` remain different. Purchased/unassigned share a queue; separate purchased method was unavailable. |
| [native attempts](capabilities/attempts.json) and [verification](capabilities/verification.json) | Timestamped filter/page/expiry examples, native request/result fields and independent assessment. Page count can be 21 because of lookahead; offset pages move and are not BIN sorted. |
| [market availability](market/availability.json) and [offline proof](market/offline-proof.json) | Three retained searches: 233731 pages 1/2 (42 rows, 41 auctions), 278230 page 1 (10 rows). These historical samples support replay only, not current benchmark yield. |
| [purchase journal](transaction/live.json), [independent assessment](transaction/verification.json), [narrative](purchase-to-list.md) | Exactly one definition 278230 purchase at 200 coins, exact owned item and 200 debit, move, active listing bid 200/BIN 250 for 3600 seconds, fresh 3570-second countdown and later status. No settled sale or relist proof. |
| [cache contract](transaction/native-cache-contract.json) and [tradability contract](transaction/native-tradability-contract.json) | Cached 304 snapshots failed purchase proof; fresh reconciliation resolved the same buy without another mutation. Native success alone is insufficient. |

## Preservation and current-access boundary

The original [Objective 001](../../objectives/001-fc27-api-research.md),
[Objective 001B](../../objectives/001b-market-discovery-benchmark.md), all five
research documents, static evidence, final manifest and existing bridge/Python
contracts remain unchanged. The historical manifest is not regenerated to absorb
new research files. New captures must use a new run directory under
`experiments/market_discovery/runs/<run_id>/`; never overwrite Objective 001 paths.

At entry, `browser-access/live-v2.json` already contained additional observer
rows beyond its committed checkpoint. T1 preserves that entire existing prefix
and permits only subsequent append-only observations with a nondecreasing receive
time. Those rows are outside this benchmark and cannot be counted as its traffic
or attributed to this worker. No observer/server is stopped or restarted here.

Current browser attachment is **NOT_CHECKED**, and current authenticated FC27 PC
access is **NOT_CHECKED**. The historical VERIFIED assessments are not a current
health probe, login assertion, numeric rate limit or permission to trade. Before
a later live run, use the existing attachment-only prerequisite check, then a
fresh read-only authenticated search with current game/platform and matching
network GET. Account for that preflight separately. A badge or HTTP 200 alone
does not pass. Missing attachment/login makes that live run BLOCKED/PARTIAL;
normal reattachment or login may require the operator. This does not block T1.

## Preregistered comparison

Freeze the protocol bytes and SHA-256 in the future run header **before the first
new EA observation**. Record any amendment as a new revision before a new run;
never tune thresholds, filters or window order after seeing results. Historical
samples informed this design and must be labeled historical, separate from the
prospective observation set. No results have been collected for this protocol.

Nine five-minute windows run in the fixed order **A B C / B C A / C A B**. Each
strategy occurs once in each block position, giving 15 minutes per strategy and
45 minutes overall. Windows are half-open UTC intervals relative to an actual
start recorded after preflight. Each window has at most eight foreground EA
network requests: six discovery/reference reads and two reserved read-only
revalidations, with the same allowance for A, B and C. Total maximum: 72 reads,
24 per strategy. These are research request limits, not capital/spend policies.

Submit at offsets 0, 30, 60, 90, 120, 150, 180 and 210 seconds only if the prior
command has completed and the last actual submission was at least 30 seconds
ago. One command is in flight. Skip missed slots; never catch up, transfer unused
slots, silently replace windows or add retries outside the budget. Allow the
remaining 90 seconds for completion/cooldown. Command deadline is 60 seconds;
native observable timeout is 15 seconds. A late read cannot count in the next
window. Aggregate request counters include native side effects; if they exceed
the window allowance, invalidate the window and stop further dispatch.

Count actual foreground EA GETs, errors and safe retries against the allowance,
not localhost polls. A cache-only response consumes a command slot but contributes
zero authenticated fresh observations and zero EA GETs. Report command count,
actual foreground EA count and passive background Web App EA count separately.
Background traffic is not controllable by this protocol; record it and mark
comparisons confounded if its measurement is absent or its per-minute rate differs
by more than 25% between strategies (all-zero rates are comparable). Compare
matched complete blocks with equal actual foreground budgets; incomplete or
unequal-budget windows remain descriptive PARTIAL results. Do not invent reads
to fill a budget. Report every attempted window, including failures.

Each discovery pair is page 1 `fresh=true`, page 2 `fresh=false`, `count=21`,
native player type. Keep identical criteria across the pair and invalidate only
before page 1. Retain returned/lookahead/visible counts and overlaps; never infer
exhaustive coverage or a BIN-sorted market. The normative JSON defines the pairs:

| Strategy | Three discovery pairs, in order |
| --- | --- |
| A: targeted | Definition 233731, max_buy 7000; definition 278230, max_buy 4000; definition 233731, max_buy 6500. Ceilings are fixed coverage bands, not verified profitable thresholds. |
| B: broad filtered | Club 9, min_buy 150/max_buy 7000; league 13, same band; league 13, min_buy 150/max_buy 1000. Score by each returned exact version; unrelated versions need independent comparables. |
| C: adaptive hybrid | League 13, min_buy 150/max_buy 7000 exploration; targeted top ranked watchlist version, max_buy 7000; targeted second ranked watchlist version, max_buy 7000. |

All strategies use the same provider snapshot frozen at block start and the same
EA-reference ledger, freshness policy, estimator and X scenarios. Snapshot network
retrieval occurs outside EA windows and is reported separately. If no legitimate
fresh FC27 PC exact-version feed is available, explicitly mark it UNAVAILABLE.
A then uses the fixed EA-native watchlist; C ranks that watchlist using only the
preceding completed block's fresh EA observations by valid distinct-auction count
descending, then definition ID ascending. Initial/no-fresh-data fallback is
233731 then 278230. With a usable external snapshot, C ranks ascending exact-PC
indicative ask, then definition ID, within the same two-version watchlist. No
current-window outcomes influence its two targets. This is a bounded hybrid
fallback, not demonstrated whole-catalog discovery or external-feed success.

Two reserved slots revalidate one candidate with a fresh exact-definition page
1/2 pair at unchanged search ceiling. Choose the highest modeled profit at X=100,
then lexical auction pseudonym. If no evaluable candidate exists, choose the
lowest positive BIN from that window, then auction pseudonym, for diagnostic
identity/BIN/expiry measurement; do not call it an opportunity. If no valid row
exists, leave the slots unused. Neither mode dispatches a write. Read-only intents
are permitted only after fresh comparables and rules pass; otherwise emit an
explicit NOT_READY reason rather than inventing caps or profitable candidates.

## Timing, metrics and analysis rules

Persist timezone-aware UTC start/end, scheduled/submitted/delivered/native-start/
native-end/result-received/evaluated/revalidation-complete/intent-prepared times
when observable. Use monotonic durations for elapsed/deadline measurements. Missing
instrumentation remains null: the baseline cannot isolate EA server latency from
native-service time. End-to-end duration includes the 30-second alarm wait.
Report queue/delivery, native-service, result-return and Python compute separately;
never subtract an assumed 30 seconds or label a local failure EA latency.

Record per request: run/protocol hash, block/window/strategy/slot, command ID,
criteria/page/fresh flag, game/platform, submitted/completed UTC, elapsed duration,
HTTP/native status, fixed error code, response/visible counts, cache invalidation,
network freshness/time, expiry, exact definition, allowlisted item/auction fields,
and per-run pseudonyms. Exclude headers, cookies, tokens, raw IDs, query strings,
account identifiers, raw errors and stacks. Keep comparable and candidate lineage
within the same capture key; do not join pseudonyms across historical runs.

Primary metrics use both requests and elapsed wall minutes as denominators:
unique auctions and exact versions per EA request/minute; returned rows, duplicate
and conflicting-identity fractions; coverage by filter/page/version; observation
age and expiry distribution; errors/cache-only/empty counts; and candidate yield
for **X=100,250,500,1000**. Cross-window first-seen auctions count once per strategy
and once overall; report overlap rather than adding per-window unique counts.
Opportunity arrivals/hour = 3600 * distinct first-qualified auctions / observed
strategy seconds, with sample size and time-of-day/coverage bias. Forty-five
minutes is a small observation, not a daily or whole-market throughput guarantee.

Pricing preserves `target - target // 20 - acquisition`, equality at X, five
comparables after excluding the candidate's auction AND physical item, outlier
filtering, no cross-platform/version blending and legal tick/cap validation.
Use sample age <=120 seconds, rules age <=300, candidate age <=30 at intent, and
age-decayed remaining lifetime >60 seconds. Recompute from the fresh revalidation
pair. Wrong identity, changed BIN, lost/expired candidate, stale data or changed
price dropping profit below X are revalidation failures, with reason counts.
False-positive fraction = failed qualifying revalidations / completed qualifying
revalidations; no completed denominator gives null, never zero. Record diagnostic
revalidation separately. Missing verified caps/ticks yields unknown executable
yield; hypothetical-rule results are SIMULATED/MODELED only. Actual live absence
of candidates is zero only when observable prerequisites passed. No experiment
means null metrics. Asking prices and modeled tax do not prove sales or profit.

Latency analysis will compare the preserved baseline with a separately reviewed
read-only request-driven/long-poll adapter. The alternative is currently
PROPOSED_UNVALIDATED, not benchmarked. Reuse the same search shapes and serialized
EA pacing/budgets; a faster localhost transport grants no higher EA allowance.
Record time-to-first-result and search→evaluate→fresh-revalidate→prepared DRY-RUN
intent. Report median with sample count; nearest-rank p95 only with at least 20
valid samples per group, otherwise null. Compare matched strategy/filter/page
groups and disclose ordering effects; no forced load or new live writes.

## Stop conditions and research-only boundary

Hard stop on 401/auth loss, challenge/CAPTCHA, EA restriction, unexpected mutation,
credential-bearing output, identity/platform/schema mismatch, detached bridge or
budget overrun. Suspend on 429 and honor Retry-After; absent Retry-After use
30/60/120/240/300-second backoff. A longer Retry-After is never capped downward.
On 5xx/timeout apply the same backoff, consume the attempted slot, and never replay
an ambiguous command automatically. If the delay cannot fit, mark the window
PARTIAL. Third-party 403 disables that source until legitimate access is restored;
it does not prove EA failure. Never probe a rate threshold. Terminate normally
after nine windows; interrupted runs retain actual intervals and reasons.

No purchases, bids, moves, listings, relists, cancellations, sold cleanup or other
account mutations are authorized. No production bot, unattended write loop,
Objective 002 implementation, credential/cookie/token exports, paid subscriptions,
paid account registration, access-control bypasses, CAPTCHA solvers, proxy/fingerprint
evasion, unrelated repository cloning or third-party executable installation.
Only existing reviewed local sources are needed for T1. Any later source reuse
must respect its reviewed license; no license implies no copying. Normal provider
access and ordinary EA login/reattachment are the only access recovery routes.

The locked future P0 and configurable X remain unchanged. T1 adds no per-trade
approval, portfolio limit or spend policy. Future research may emit labeled DRY-RUN
buy/list intent documents; historical Objective 001 mutation proof remains
historical. T1 leaves all new live outcomes unobserved and hands the frozen
protocol to later provider, adapter and benchmark tasks.
