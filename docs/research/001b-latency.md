# Objective 001B latency findings — T6

The measured local bottleneck is 30-second alarm delivery. A bounded long-poll
alternative removes that local wait in a Python simulator, but its successful
authenticated Edge search path is **UNVALIDATED**. There is no defensible live
speedup, EA-only service-time estimate, or full live search-to-intent latency.
All results are retained observations; T6 makes zero network calls.

## Baseline, alternative and timing definitions

The preserved [transaction worker](../../browser/transaction-bridge/worker.js)
uses `chrome.alarms` with `periodInMinutes: 0.5`. The T3 simulator models that
30-second polling interval with real localhost HTTP and controlled timing; it
does not run that installed extension. T4's baseline preflight used the existing
read bridge, not a matched instrumented baseline. The separate
[research worker](../../experiments/market_discovery/browser/worker.js) supports
`alarm_30s` and `long_poll`; long polling waits up to 20 seconds server-side,
then renews. Both modes retain one in-flight command, strict loopback Host and
pinned extension Origin, allowlisted projections, deadline and duplicate/late
result rejection. Credential values remain inside the native page. This is a
search-only prototype, not a production write channel.

| Component | Measurement boundary |
| --- | --- |
| Queue/delivery | Server enqueue to worker delivery; includes local poll scheduling |
| Worker to native | Worker poll receipt to page native-service start; injection and dispatch overhead |
| Native service | Native observable start to completion, including Web App/service/cache work; not isolated EA server latency |
| Page total | Overlapping enclosing page interval; do not add to its native subcomponent |
| Result return | Local residual return/serialization/HTTP work; unknown if timestamps are missing |
| Python decision | Local scoring/evaluation/repricing wall time; measured separately from native traffic |
| First result | Submission to successful result; failed round trips are labeled failures |
| Prepared intent | Initial search through scoring, new exact revalidation, repricing and dry-run buy intent |

Worker/page epoch-normalized monotonic marks support cross-context timing;
negative/missing differences stay unknown. Aggregated component medians do not
sum to the median end-to-end time. Historical waits are never split by
subtracting an assumed 30 seconds.

## Local measured comparison, not EA performance

The [T3 local capture](../../experiments/market_discovery/runs/t3-harness/local-latency.json)
ran 2026-11-11T21:48:29.472910+00:00 through
2026-11-11T21:50:00.687452+00:00. There are three samples per arm, zero
errors, zero EA requests and zero account mutations. Injection/native work is
a controlled sleep fixture; only localhost scheduling/delivery is real.

<!-- evidence:local_latency -->
| Local simulator component | Alarm n | Alarm median ms | Alarm p95 ms | Long poll n | Long poll median ms | Long poll p95 ms |
| --- | --- | --- | --- | --- | --- | --- |
| end_to_end_ms | 3 | 24947.711100 | unknown | 3 | 46.323500 | unknown |
| queue_delivery_ms | 3 | 24888.920100 | unknown | 3 | 0.037200 | unknown |
| worker_poll_to_native_ms | 3 | 2.622300 | unknown | 3 | 2.580100 | unknown |
| native_service_ms | 3 | 10.792800 | unknown | 3 | 10.592400 | unknown |
| page_total_ms | 3 | 16.458400 | unknown | 3 | 12.525700 | unknown |
| result_return_ms | 3 | 12.943700 | unknown | 3 | 18.399000 | unknown |
<!-- /evidence:local_latency -->

The alarm samples deliberately use different enqueue phases: queue waits about
29.916/24.889/19.904 seconds. Their median is not an unbiased estimate of a
uniformly arriving command's expected wait. Long-poll queue median is about
0.037 ms in this local environment. The difference supports removing local
alarm scheduling as a design choice; it does not establish a live latency ratio
or justify faster EA request pacing. MV3 suspension, tab navigation, reconnect,
extension lifecycle and authenticated search still need validation.

## Actual Edge preflights and historical baseline context

The [T4 evidence](../../experiments/market_discovery/runs/t4-live-20261111T220200Z/report.json)
contains one failed sample per arm, from the access attempt documented in the
[discovery report](001b-discovery-benchmarks.md). The baseline got EA 401;
the alternative failed its PC persona schema guard before native search.

<!-- evidence:live_latency -->
| Failed live arm | Attempts | EA requests | Round trip n / median ms / p95 ms | Queue n / median ms / p95 ms | Outcome |
| --- | --- | --- | --- | --- | --- |
| alarm_30s | 1 | 1 | 1 / 10397.477900 / unknown | 0 / unknown / unknown | service_failed |
| long_poll | 1 | 0 | 1 / 18.067900 / unknown | 1 / 0.043000 / unknown | schema_unrecognized |
<!-- /evidence:live_latency -->

For both arms successful-first-result, native-service, local-result-return,
EA-server and search-to-prepared-intent latency are **unknown, n=0**. The
alternative's n=1 queue mark proves local delivery to Edge only. Its fast
failure cannot be compared to the baseline's authentication failure as a
speedup. The baseline's poll/native/return components were uninstrumented and
cannot be separated. No candidate was available for fresh revalidation.

The three successful historical searches took 12220.924/30012.495/29961.553
ms end to end, median **29961.553 ms (n=3)**. These times include alarm waiting,
native work and return; component samples are n=0. They are not a current
baseline or matched alternative comparison. Their p95 remains unknown.

## Python computation and complete-flow boundary

The [T5 retained fixture replay](../../experiments/market_discovery/runs/t5-pricing/report.json)
has four scenario runs of the same data, not four independent live opportunities.
The table aggregates recorded monotonic stage times. Its SCAN and REVALIDATE
times are local fixture loading/processing, not network search latency. Separate
modeled 50-ms record delays are not added as measured native durations.

<!-- evidence:fixture_latency -->
| Fixture stage (local Python wall time) | n | Median ms | p95 ms |
| --- | --- | --- | --- |
| SCAN | 4 | 0.306450 | unknown |
| PRICE | 4 | 4.903400 | unknown |
| EVALUATE | 4 | 0.001300 | unknown |
| REVALIDATE_READ_ONLY | 4 | 0.270750 | unknown |
| REPRICE_AND_EVALUATE | 4 | 0.446750 | unknown |
| DRY_RUN_BUY_INTENT | 4 | 0.010900 | unknown |
| PROPOSED_LISTING_INTENT | 4 | 0.003250 | unknown |
| search_to_prepared_intent_ms | 4 | 6.072450 | unknown |
<!-- /evidence:fixture_latency -->

Full live search → evaluate → fresh revalidation → prepared buy-intent remains
unknown. Fixture intent latency includes local Python work and interstage
overhead; it cannot predict competitive opportunity capture. Real listing
dispatch or settlement latency is outside this research.

Every table reports sample counts. Median is descriptive for n>0; p95 is
withheld for n<20, using nearest rank `ceil(0.95*n)` only when n>=20. No
confidence interval or population-tail claim is justified by 1/3/4 samples.

## Bottleneck and next measurement

Queue delivery dominates the controlled alarm experiment (about 24.889 seconds
of a 24.948-second median round trip); fixture Python pricing is measured in
milliseconds. This supports prioritizing transport delivery over estimator
micro-optimization. It does not establish the live bottleneck: authentication
currently prevented measurement in T4, and native-service time is unknown.
The independent 30-second EA submission gap also limits sustainable scan
capacity after delivery is improved. An extra fresh search still consumes that
budget; low delivery latency alone cannot guarantee a subsecond buy decision.

After normal login/PC selection and reviewed persona projection, compare
instrumented alarm and long-poll modes on successful read-only searches with
identical EA budgets and >=30-second pacing. Retain enqueue/delivery/native/
return/compute marks, successful first-result and full prepared-intent marks,
passive background load, and errors. Collect >=20 valid samples per reported
p95 component across normal lifecycle conditions without stress testing.
Resolve MV3 suspend/reconnect before selecting the transport for unattended use.
Keep pairing, durable identity/epochs and native command validation required
by the existing Objective 002 handoff.

Reproduce offline with `python -m experiments.market_discovery.t6_analysis
--output private-captures/new-t6-latency-analysis.json` and
`python tests/test_t6_discovery_recommendation.py`. To rerun the controlled
local experiment use `python -m experiments.market_discovery.local_latency
--samples 3 --output private-captures/new-local-latency.json`; this takes about
90 seconds and changes timings. None of these commands validates a live EA path.
