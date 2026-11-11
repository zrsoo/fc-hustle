# Read-only market discovery harness (T3)

This directory is an isolated research harness, not an executor. Python 3.10+ and
Node 22+ suffice; no packages, competitor binaries or browser automation installs.
Run from the repository root. Outputs must be new paths; commands never overwrite
historical evidence. The original read and transaction extensions are preserved.

```powershell
python -m experiments.market_discovery --help
python -m experiments.market_discovery demo --output experiments/market_discovery/runs/my-demo/strategies.json
python -m experiments.market_discovery replay --output experiments/market_discovery/runs/my-replay/pages.json
python -m experiments.market_discovery flow-demo --output experiments/market_discovery/runs/my-flow/intent.json
python -m experiments.market_discovery.local_latency --samples 3 --output experiments/market_discovery/runs/my-local/latency.json
python tests/test_market_discovery_harness.py
python tests/test_market_discovery_transport.py
python tests/test_market_discovery_artifacts.py
```

`demo` uses deterministic synthetic asks and logical time to exercise all nine
preregistered windows, including A/B/C order, six discovery and two diagnostic
revalidation slots per window. Its 72 requests are **simulated**, not EA reads.
`replay` analyzes actual retained Objective 001 FC27 PC observations at their
original UTC times. Historical end-to-end timing has no component breakdown.
`flow-demo` creates a deliberately profitable **SIMULATED** fixture, applies
`fc_access.pricing.evaluate`, excludes the candidate from comparables, performs a
second fresh search, and emits a **DRY_RUN_ONLY** intent. Hypothetical caps and
increments are labeled. No real intent can be promoted using these rules.

The local latency command takes about 90 seconds for three baseline samples.
It measures actual Python localhost queue delivery with a controlled extension
simulator, actual 30-second polls, simulated injection and a simulated native
observable. It measures no EA or Edge latency. Repeating it may change numbers.

## Optional finite authenticated observation

1. Load **only** `experiments/market_discovery/browser/` as a separate unpacked
   Edge extension. Obtain its ID from Edge's extension manager.
2. Start the separate search-only server, replacing the example ID with that ID:

   ```powershell
   python -m experiments.market_discovery serve --extension-id aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa --transport long_poll
   ```

3. Select the official HTTPS EA Ultimate Team Web App, sign in normally to FC27
   PC, and click this extension's action. This grants activeTab; neither Python
   nor the extension reads or exports session values. Close other research
   callers while observing. If normal login or market access is unavailable,
   preserve the failure and stop.
4. Run the bounded observation (nine windows take roughly 44 minutes):

   ```powershell
   python -m experiments.market_discovery live --windows 9 --output experiments/market_discovery/runs/my-live/observations.json
   ```

There is one command in flight and at least 30 seconds between scheduled slots.
Missed slots are skipped; no catch-up, retries or production schedule exists.
Errors, unexpected schema/platform, missing attachment, budget overrun, 401/403,
429 and 5xx stop the run. Local polls do not consume EA budget. Every delivered
search spends a slot; every captured foreground request including failures is
charged separately. Multiple native requests can cause an observed overrun; the
run then stops rather than pretending that the cap was enforced inside EA.

For the instrumented 30-second baseline arm change the single `TRANSPORT`
constant in the **new** worker to `alarm_30s`, reload it, restart the server with
`--transport alarm_30s`, and reattach. Its `/next` is nonblocking. The long-poll
arm uses bounded 20-second waits, preventing a busy idle poll loop. Keep the same
30-second EA submission pacing and request budget for both. The original
`browser/transaction-bridge/worker.js` still uses `periodInMinutes: 0.5`.
The comparison arm is an instrumented research counterpart of that baseline;
it is not a new measurement of the historical extension.

## Contracts and interpretation

- `model.py` and [observation.schema.json](observation.schema.json) define the
  sanitized boundary. Unknown response fields, raw error strings, raw auction
  or physical IDs, unsafe integers, non-PC markets and unsupported filters are
  rejected. Exact identity is `(fc27, pc, definition_id, trade_id, item_id)`;
  asset/resource IDs never substitute for the full definition. Auction/item
  hashes share a random per-run key, including across strategies and windows.
  The key travels only on localhost/page injection and is absent from artifacts.
- External availability comes from T2's [provider evidence](runs/t2-providers-20261111T212333Z/providers.json).
  No usable production FC27 PC broad feed was retrieved. Sandbox/console prices
  do not become external quotes. EA current attachment is separate from this
  historical evidence. The retained T3 attempt failed with `bridge_unavailable`
  before EA access; live latency and yield are unobserved.
- A searches exact versions. B uses historically validated club/league and
  bounded price bands. C explores a league and targets ranked versions. Ranking
  uses a verified fresh exact-PC external snapshot, else fresh native distinct
  auctions from the **preceding completed block only**, else the frozen initial
  watchlist. No current block is used to peek ahead. Revalidation is diagnostic
  only in the discovery runner because verified card rules remain unavailable.
- All strategies share accounting for actual requests, returned and visible
  rows, response bytes, duplicates/conflicts, distinct auctions/versions,
  UTC/monotonic elapsed time, freshness upper bounds, decayed expiry, native and
  HTTP errors, cache-only/empty responses, and coverage by filter/page/version.
  A page requests 21 rows: 20 visible plus lookahead. Page 2 may repeat lookahead
  or drift as auctions expire. Even a short/empty page or `has_more=false` does
  not establish exhaustive market coverage. No BIN ordering is assumed.
- Coverage denominators, passive background EA load, verified rules and live
  opportunity arrival rates remain unknown. Results are descriptive and marked
  confounded where background traffic is not measured. An equal simulated
  request budget does not establish a fair live throughput comparison.

Timing is separated into server queue/poll delivery, worker-to-native start,
native observable duration, page completion, return overhead, Python compute,
time to first result, and complete search-to-prepared-intent. The last is null
when no intent was prepared. Worker/page `performance.timeOrigin + now()`
normalizes origins; negative/invalid differences are unknown. Native duration
includes Web App/service work and is not EA server latency. Server residual
return time includes local serialization/HTTP overhead. Each aggregate includes
sample count, median, and nearest-rank p95 only when n >= 20. Historical waits
are never split by subtracting an assumed alarm delay.

The [source and transport review](source-review.json) pins reused local sources,
the untouched baseline and existing competitor/license reviews. No competitor
implementation was copied. The alternative is **prepared and locally fixture
validated**, not live Edge/MV3 validated: service-worker suspension, tab lifecycle,
fresh FC27 search and background load remain untested. Origin pinning prevents
ordinary hostile web/extension origins, not hostile local software that can forge
HTTP headers. This protocol adds no credential surface or mutation command.

## T6 offline synthesis and recommendation

The [discovery benchmark report](../../docs/research/001b-discovery-benchmarks.md),
[latency analysis](../../docs/research/001b-latency.md),
[selected flow](../../docs/research/001b-proposed-flow.md),
[Objective 002 delta](../../docs/research/001b-obj002-addendum.md) and
[one-page decision](../../docs/research/001b-discovery-decision.md) synthesize the
retained T2–T5 evidence. Their decision is CONDITIONAL GO for offline
architecture implementation. The live benchmark is blocked at the historical
T4 checkpoint; current access is not rechecked. No live opportunities/hour or
successful authenticated alternative latency is inferred from fixtures.

```text
python -m experiments.market_discovery.t6_analysis --output private-captures/new-t6-analysis.json
python tests/test_t6_discovery_recommendation.py
```

The new-path-only CLI uses no network, recomputes coverage and latency from
retained rows/samples, and pins inputs including the unchanged original handoff.
The tests compare document tables, schema examples and conclusions with those
inputs and reject fabricated yield, unsupported p95 and production-source
promotion. The report is retained in `runs/t6-analysis/report.json`.

## T7 final audit and offline reproduction

Start with the [audit and actual command outcomes](../../docs/research/001b/t7/audit.md).
It links all five required research documents, inputs, fixtures and results.
After the scoped deliverable commit, run:

```text
python -m unittest discover -s tests -p test_*.py
python tests/validate_001b.py
```

The validator checks artifact hashes, raw-evidence claim consistency, privacy,
preserved Objective 001 bytes and the scoped commit. The original
`tests/validate_final.py` belongs to Objective 001's frozen manifest and commit;
use the new validator for the additive Objective 001B deliverables.

The audit records six executable offline replay commands, using temporary new
output paths and checking their results. To repeat the recorder without changing
the sealed audit, use a fresh ignored directory:

```text
python tests/record_001b_checks.py --output private-captures/new-001b-audit
```

The optional live instructions above require normal authenticated FC27 PC access,
the separate extension's exact ID, activeTab attachment and a fresh HTTP 200
market GET. At the retained checkpoint EA returned 401 and the separate adapter
hit its persona schema guard. Resolve these normally before observation. A
successful offline replay of that failure does not restore authentication.
