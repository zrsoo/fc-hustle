# Objective 002 handoff delta from Objective 001B — T6

Apply only these changes to [obj002-handoff.md](obj002-handoff.md). The original
handoff bytes, planned S1–S6 dependencies, L1–L8 release conditions, X-only
profit policy and durable execution/reconciliation requirements remain in force.
This addendum specifies changes; it implements no Objective 002 modules.

## Selected sources — refinement to providers

Keep EA native exact FC27 PC asks authoritative. Enable no third-party production
feed by default. DataFluxor replaces unspecified bulk-feed preference as the
first conditional commercial candidate: its documented exact-PC contract is
strongest, but production access, exact mapping, freshness and permission are
unverified. Its accessible fixed console sandbox is excluded. FUT-DB remains
an entitlement-dependent alternative with batching uncertainty; FUT.GG stays
disabled after 403 until ordinary access and automation permission are resolved.
Do not infer current availability from historical results. External quotes rank
and audit only; they never fill missing EA comparables or rules. Refer to
[the retained provider evaluation](001b-price-providers.md) for supporting evidence.

## Search approach — targeted first, bounded hybrid proposed

Retain exact watchlist [233731, 278230]. Start with A; introduce C exploration
by replacing budgeted scans, ranking only the preceding completed block. Do
not select B or C on synthetic throughput. Add the frozen A/B/C experiment as
an evidence requirement: three 300-second windows per strategy, 24 requests
per arm, 30-second minimum submission gap, matched blocks and passive background
accounting. There is no observed opportunities/hour estimate at any X and no
empirically established yield winner. Executable max BIN is legal-at-or-below
`target_sale_price - target_sale_price // 20 - X` after native target validation;
fixed benchmark ceilings are not profitable thresholds. The two-read T5 demo
starts broad and is not this proposed targeted production scheduler.

## Latency solution — proposed delivery change

Replace 30-second alarm command delivery in the planned separate execution
bridge with bounded 20-second long polling, subject to successful authenticated
Edge/MV3 and lifecycle validation. Retain >=30-second EA submission pacing.
The local simulator measured the delivery benefit; T4's alternative delivered
but failed before native search. No successful live speedup is established.
Add enqueue/delivery/native/return/compute/first-result/prepared-intent marks,
n/median and p95 only at n>=20; native service is not EA-only server latency.
Preserve the handoff's pairing, epoch, deadline and durable command semantics;
the search-only prototype is not a production write bridge.

## Exact modules/interfaces — changes to the existing module plan

All `fc_execution/*` and `browser/execution-bridge/*` paths below remain
**planned**, not delivered. Existing research modules are references/adaptation
inputs; only the existing pure pricing calculator is directly reusable.

| Planned existing handoff module | Interface delta / existing research reference |
| --- | --- |
| `fc_execution/providers.py` | Add explicit unavailable/source-lineage result and exact-PC publication/mapping checks to `CatalogPrices`; use `opportunity.external_comparison(snapshot, key, now, target)` diagnostics and `t5_pricing.source_snapshot()` retained-data shape as references, not a live feed client |
| `fc_execution/strategy.py` | Adapt `opportunity.price_candidate(rows, candidate, rules, *, now, X, external=None)`, `rank_candidates(records, rules, *, now, X, external=None)` and `revalidate(candidate, record, *, now, scan_completed)`; preserve independent candidate exclusion and post-read repricing; call `fc_access.pricing.evaluate` with `Policy(min_remaining=60)` |
| `fc_execution/rules.py` | Add provenance/verification gate outside `Rules`; caller-supplied rules and `DEFAULT_BANDS` do not establish native legal caps/ticks; retain <=300-second rule age |
| `fc_execution/scheduler.py` | Adapt `discovery.rank(previous_block, external, now)` and `plan(strategy, ranking)` for bounded exploration; replace scheduled slots rather than add requests; keep 90/300-second target cadence, shared queue and >=30-second gap; record actual network load |
| `fc_execution/models.py` | Add source lineage, pricing assumptions, revalidation time and component timing fields from T5 buy/list intents; retain handoff scope/epoch/semantic IDs/payload hashes; reject promotion of SIMULATED or DRY_RUN_ONLY intents |
| `fc_execution/transport.py`, `browser/execution-bridge/worker.js` | Adapt `SearchTransport.search(params, evidence_key)` and research `bridge_server.SearchServer`/`Handler` concepts for bounded long-poll delivery; add required pairing/durable/epoch contracts before writes; preserve separate execution protocol |
| `browser/execution-bridge/page.js` | Add reviewed PC persona projection if still needed after normal PC selection; retain fail-closed game/platform/identity validation and full timing marks; never export auth values |

Existing reference files:
[opportunity.py](../../experiments/market_discovery/opportunity.py),
[discovery.py](../../experiments/market_discovery/discovery.py),
[transport.py](../../experiments/market_discovery/transport.py),
[bridge_server.py](../../experiments/market_discovery/bridge_server.py),
[t5_pricing.py](../../experiments/market_discovery/t5_pricing.py),
[research worker](../../experiments/market_discovery/browser/worker.js).
`opportunity.run_flow(read, *, mode, rules, clock, X=100, external=None)` returns
rankings, fresh revalidation, final pricing, inert buy/list intents and stage
metrics; it is a finite research demonstration, not an execution interface.

## Dependencies — additions to S2/S3 validation

No new runtime package or paid entitlement is required for offline work. The
research uses Python 3.10+ standard library and Node 22+ for bridge checks.
S1 models/store/identity precede S2 transport/session/bridge; add authenticated
long-poll and normal lifecycle evidence to S2 validation. S3 rules/providers/
strategy depends on fresh native rule provenance and current comparables;
external entitlement remains optional. S4 scheduling/reconciliation stays
offline until these boundaries hold. The discovery comparison can be captured
read-only after access recovery; its result is required before advertising
throughput or hybrid superiority, not for S1–S4 offline implementation.

## Open blockers — evidence added by 001B

| Added evidence gap | Exact prerequisite / affected claim |
| --- | --- |
| T4 baseline EA 401, zero authenticated observation seconds | Normal Web App sign-in/challenge completion, select FC27 PC and fresh authenticated HTTP 200 market GET before any benchmark window |
| T4 alternative `schema_unrecognized` before native start | Normal PC selection/reattachment first; if persistent, reviewed read-only persona projection with tests, never bypass the guard |
| Zero completed A/B/C windows or qualifying revalidations | At least 30 authenticated observation minutes in matched bounded windows, actual/background request accounting and qualifying outcome samples before any opportunities/hour or comparative yield claim |
| Only local simulated successful alternative timing | Successful instrumented Edge searches, timing components, MV3 suspension/tab/reconnect behavior, and sufficient n before live latency or p95 claims |
| No production PC feed retrieval | Ordinary entitlement and permission, exact mapping/PC payload/publication verification before enabling the optional source |

Carry forward the existing caps/ticks, durable identity, session recovery and
natural settlement/tax blockers from the handoff; their status did not improve
in 001B. Projected profit remains distinct from settled-sale evidence. The
[one-page conditional decision](001b-discovery-decision.md) and
[analysis report](../../experiments/market_discovery/runs/t6-analysis/report.json)
are the new evidence references for these deltas.
