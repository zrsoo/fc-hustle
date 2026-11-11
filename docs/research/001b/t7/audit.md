# T7 reproducibility and research boundary audit

T7 completes the offline audit and scoped repository delivery of Objective 001B.
It does not complete the blocked live benchmark or implement Objective 002.
The [architecture decision](../../001b-discovery-decision.md) remains CONDITIONAL
GO for offline design implementation only. Current browser access was not probed
in T7. No provider, browser or EA command was sent by this audit.

The [command record](checks-verified/validation.json) records actual UTC start/end, argv,
exit status, test count, skip detection, command-output digests and semantic
artifact checks. Python and Node versions are recorded there. The [manifest](manifest.json)
pins every scoped deliverable except itself; the final validator checks every
file, including the manifest, against committed Git bytes. The [entry inventory](entry.json)
pins the baseline revision and identifies the preexisting observer change that
is deliberately excluded from the deliverable commit.

## Deliverable and lineage index

| Required deliverable | Supporting artifacts and interpretation |
| --- | --- |
| [Price providers](../../001b-price-providers.md) | [HTTP observations](../../../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/http.json), [provider findings](../../../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/providers.json), [retention hashes](../../../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/artifacts.json). No production FC27 PC feed was retrieved. Sandbox prices are illustrative. Denial and production auth/rights gaps remain explicit. |
| [Discovery benchmarks](../../001b-discovery-benchmarks.md) | [Preregistered budgets](../protocol.json), [historical replay](../../../../experiments/market_discovery/runs/t3-harness/historical.json), [T4 raw failure](../../../../experiments/market_discovery/runs/t4-live-20261111T220200Z/baseline-preflight.json), [T4 report](../../../../experiments/market_discovery/runs/t4-live-20261111T220200Z/report.json). Historical 3 reads / 52 rows / 51 auctions / 2 versions; no new A/B/C windows and zero authenticated observation seconds. |
| [Latency](../../001b-latency.md) | [Measured localhost samples](../../../../experiments/market_discovery/runs/t3-harness/local-latency.json). Actual 30-second polls with a simulated extension/native service. n=3 per arm, p95 unknown; no successful live Edge comparison or EA server latency. T7 replays aggregates and does not rerun the timing experiment. |
| [Proposed flow](../../001b-proposed-flow.md) | [Isolated prototype and commands](../../../../experiments/market_discovery/README.md), [observation schema](../../../../experiments/market_discovery/observation.schema.json), [synthetic fixtures](../../../../experiments/market_discovery/fixtures/t5-opportunities.json), [T5 results](../../../../experiments/market_discovery/runs/t5-pricing/report.json). Fresh identity/BIN/expiry checks lead only to inert SIMULATED dry-run buy/list intents. Hypothetical rules never establish live eligibility. |
| [Objective 002 delta](../../001b-obj002-addendum.md) | [Unchanged original handoff](../../obj002-handoff.md), [T6 analysis](../../../../experiments/market_discovery/runs/t6-analysis/report.json). Planned interfaces are specifications. No production executor, scheduler or execution bridge is included. |

Provider and native inputs retain collection timestamps; synthetic fixtures retain
modeled UTC clocks and explicit lineage. T7 command times identify offline
reproduction, not new market collection. Historical/synthetic success never
contributes to live arrival rates. Live yield at X=100/250/500/1000 and the
false-positive rate (0/0) remain unknown. Four fixture intents replay one auction
under four thresholds, not four live trades. Projected after-tax profit is not
a completed sale or realized yield.

## Commands and actual outcomes

Run from the repository root with Python 3.10+ and Node 22+, standard libraries
only. Missing Node is an error. All commands below are executed as part of this
audit; actual results and versions are in the linked command record. Each replay
is checked against retained artifacts or their timing-independent semantics.
Temporary outputs are then removed. `NEW` means a previously unused filename.

```text
python -m unittest discover -s tests -p test_*.py
python -m experiments.market_discovery demo --output NEW
python -m experiments.market_discovery replay --output NEW
python -m experiments.market_discovery flow-demo --output NEW
python -m experiments.market_discovery.t4_evidence --output NEW
python -m experiments.market_discovery.t5_pricing --output NEW
python -m experiments.market_discovery.t6_analysis --output NEW
python tests/validate_001b.py
```

The initial audit ran 168 tests: 167 passed, one failed because T6 extended the
prototype README without updating its T3 source-review hash. T7 reviewed those
documentation additions, added reproduction links, and updated that single pin
with its prior value retained in [the review](../../../../experiments/market_discovery/source-review.json).
The first recorder run passed 173 tests but exposed a second reproducibility
issue: synthetic equal-expiry rows were ordered by randomly salted pseudonyms,
which changed page membership and adaptive coverage. The fixture now breaks
ties using the public exact version. A regression compares all 72 requests and
strategy metrics across two independent salts. Per-run pseudonyms and measured
Python execution times still vary intentionally. The earlier failed semantic
check remains in [its command record](checks/validation.json). No observation,
timing sample, original evidence hash or native contract changed. Final suite
and replay outcomes follow these corrections; post-commit validation checks Git
bytes too. Retained T3 simulation results describe their original run, while
fresh simulations use stable tie ordering and recompute metrics from their rows.

To record new diagnostic outcomes without overwriting the sealed audit:

```text
python tests/record_001b_checks.py --output private-captures/new-001b-audit
```

## Optional live read-only prerequisites

The [prototype instructions](../../../../experiments/market_discovery/README.md)
document the separate localhost search server, exact extension ID, normal Edge
attachment and finite `live --windows 9` command. Before starting, an operator
must sign in normally to the official HTTPS FC27 Web App, select PC, complete any
normal challenge, and obtain a fresh authenticated HTTP 200 market GET. A badge
or stale UI is insufficient. T4's baseline got EA 401; the alternative stopped
at its selected-persona schema guard. Resolve the platform projection through
reviewed read-only changes if normal PC selection still fails. Preserve the
guard and do not retry a denied session.

Keep one command in flight, minimum 30-second EA pacing, frozen equal budgets,
and matched alternating A/B/C blocks for at least 30 authenticated minutes. For
transport comparison, reload/reattach `alarm_30s` and `long_poll` separately with
identical budgets. Successful Edge/native results, MV3 lifecycle behavior,
verified caps/increments, liquidity and production-feed entitlement/mapping
remain unverified. No paid account or new transaction is needed offline.
No live command was run by T7.

## Privacy, mutation and preservation checks

The audit scans scoped artifacts and preserved Objective 001 files for concrete
credential/private-field signatures. Native schemas reject unknown fields and
raw auction/physical IDs. JSON Schema property definitions are scanned as
contract text rather than captured identifier values; negative tests verify that
literal secrets still fail. No findings is a bounded artifact audit, not proof
about unrecorded external account activity. Mutation evidence here consists of
preserved Objective 001 journal bytes, zero new mutation counters, search-only
protocol/page-adapter review, Node rejection tests and fixture-only replays.

[Preservation tests](../../../../tests/test_001b_scope.py) verify all frozen
Objective 001 source/evidence hashes and the append-only observer prefix.
Historical buy/move/list evidence belongs only to Objective 001 and was not
replayed live. Preexisting `docs/research/browser-access/live-v2.json` worktree
additions stay outside the commit. The [T7 tests](../../../../tests/test_t7_audit.py)
reject false yield/feed/latency claims, secret fields, unsafe intents, missing
commands, skipped tests, unrelated commit paths and uncommitted bytes. The
[validator](../../../../tests/validate_001b.py) requires a scoped commit after the
entry baseline and exact committed artifact equality. Objective 001's historical
final manifest and validator are preserved rather than regenerated.
