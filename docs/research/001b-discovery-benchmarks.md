# Objective 001B discovery benchmarks — T6

The live A/B/C comparison is **BLOCKED / NOT STARTED**. T4's attempted access
period was 2026-11-11T22:00:49.736773+00:00 through
2026-11-11T22:04:49.887092+00:00 (240.150319 seconds), with **zero authenticated
observation seconds**, zero completed windows and zero matched blocks. A
four-minute access attempt is not a four-minute market observation. The
30-minute authenticated target remains unmet. T6 makes no new EA requests;
current authentication is NOT_RECHECKED_T6.

The [T4 report and input hashes](../../experiments/market_discovery/runs/t4-live-20261111T220200Z/report.json)
retain two separate preflight commands: the alternative returned
`schema_unrecognized` before native execution; the baseline sent one EA search
and received HTTP 401. No auctions were returned. Neither preflight consumes
an A/B/C window. Attachment health true did not establish authentication.
These are historical access outcomes, not a fresh probe of today's session.

## Reproducible comparison and budgets

The frozen [protocol](001b/protocol.json) is authoritative. Run nine 300-second
windows in order A/B/C/B/C/A/C/A/B with slots at 0/30/60/90/120/150/180/210
seconds. Each strategy has three windows (900 planned seconds); stop after the
last response, so nominal window allocation and actual elapsed observation are
reported separately. At most one command is in flight, minimum submission gap
30 seconds, deadline 60 seconds, native timeout 15 seconds. Skip missed slots;
no catch-up or budget transfer. Count all foreground EA network requests,
including errors and native side effects. Local transport polls cost no EA
requests. Two preflight arms have a separate cap of one EA request each.

<!-- evidence:budgets -->
| Strategy | Planned windows | Discovery requests | Revalidation requests | Maximum requests | Actual windows / requests / authenticated seconds |
| --- | --- | --- | --- | --- | --- |
| A | 3 | 18 | 6 | 24 | 0 / 0 / 0 |
| B | 3 | 18 | 6 | 24 | 0 / 0 / 0 |
| C | 3 | 18 | 6 | 24 | 0 / 0 / 0 |
<!-- /evidence:budgets -->

The total planned cap is 72 requests: 54 discovery and 18 diagnostic/fresh
revalidation requests. Equal planned caps alone cannot establish equal actual
work or comparable throughput. Match completed three-strategy blocks; record
passive background load separately. Missing background counts confound the
comparison; unequal actual budgets support descriptive results only.

| Arm | Three discovery query pairs, each page 1 then page 2 |
| --- | --- |
| A: targeted | Exact definition 233731, max BIN 7000; exact 278230, max BIN 4000; exact 233731, max BIN 6500 |
| B: broad filtered | Club 9, BIN 150–7000; league 13, BIN 150–7000; league 13, BIN 150–1000 |
| C: adaptive hybrid | League 13, BIN 150–7000; rank 1 exact version, max BIN 7000; rank 2 exact version, max BIN 7000 |

All queries request 21 rows (20 visible plus lookahead); page 1 requests native
cache reset, page 2 uses the same criteria without another reset. C ranks only
the preceding completed block: verified fresh exact-PC external indicative asks
ascending if available, else fresh distinct native-auction counts descending,
then definition ID. Initial fallback is [233731, 278230]. No current-block
lookahead influences the ranking. Frozen benchmark ceilings are experimental
filters, not proven profitable acquisition thresholds.

To repeat **offline** from the workspace (new output paths are required):

```text
python -m experiments.market_discovery replay --output private-captures/t6-historical.json
python -m experiments.market_discovery.t5_pricing --output private-captures/t6-pricing.json
python -m experiments.market_discovery.t6_analysis --output private-captures/t6-analysis.json
python tests/test_t6_discovery_recommendation.py
```

For a future authorized read-only run, follow [the separate extension setup](../../experiments/market_discovery/README.md).
Normal EA login and FC27 PC selection must produce a fresh authenticated HTTP
200 transfermarket GET first. If normal persona selection still fails, review
and test a minimal read-only platform projection; do not force the guard. Pin
protocol/source hashes before observations; use a new output directory. The
bounded command is `python -m experiments.market_discovery live --windows 9
--output private-captures/new-live/observations.json`. It is **not run by T6**.
No buy, bid, move, list or relist is authorized by this benchmark.

## Actual coverage, yield and revalidation

There are no A/B/C live observations. Zero returned identities does not measure
zero market supply, zero demand or a zero arrival rate. Every per-request and
per-minute denominator below is absent; unknown is encoded as JSON null in the
[T6 analysis](../../experiments/market_discovery/runs/t6-analysis/report.json).

<!-- evidence:live_coverage -->
| Strategy | Auctions / versions | Auctions/request | Versions/request | Auctions/minute | Versions/minute | Candidate yield | False positives |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 0 / 0 | unknown | unknown | unknown | unknown | unknown | unknown |
| B | 0 / 0 | unknown | unknown | unknown | unknown | unknown | unknown |
| C | 0 / 0 | unknown | unknown | unknown | unknown | unknown | unknown |
<!-- /evidence:live_coverage -->

Historical context is limited to the three retained Objective 001 searches at
2026-11-11T19:10:03.139863+00:00 through
2026-11-11T19:11:15.334878+00:00, **72.195015 seconds**. The
[historical replay](../../experiments/market_discovery/runs/t3-harness/historical.json)
contains actual asks, not newly collected samples. It is unmatched targeted
evidence and must not be attributed to A/B/C windows.

<!-- evidence:historical -->
| Evidence | EA requests | Rows | Unique auctions | Unique versions | Auctions/request | Versions/request | Auctions/minute | Versions/minute |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Historical only | 3 | 52 | 51 | 2 | 17.000000 | 0.666667 | 42.385198 | 1.662165 |
<!-- /evidence:historical -->

Definition 233731 contributes 42 rows, 41 auctions across pages 1/2; definition
278230 contributes 10 rows/auctions on page 1. One overlapping lookahead is
deduplicated: 52 rows / 51 unique auctions, duplicate fraction 1/52. Rates in
the table are descriptive coverage over that short capture span, including
collection delays; they are not steady-state supply or opportunity arrivals.
No fresh profitable candidate was revalidated in T4: 0 attempts, 0 completed
qualifying revalidations, 0 observed failures. False-positive fraction is
**unknown (0/0)**, not 0%. Diagnostic lowest-BIN checks are not qualifying
opportunity checks. A future run must retain changed BIN, identity mismatch,
expiry, stale data, not observed and profit-below-X outcomes separately.
Define the fraction as `failed_qualifying_revalidations /
completed_qualifying_revalidations`; require a completed qualifying denominator
and report unresolved/timeouts separately. A missing bounded-page row is a
failed confirmation, not proof of a completed sale or a market-wide absence.

## X scenarios and estimation limits

<!-- evidence:scenarios -->
| X coins | Live candidates observed | Live opportunities/hour | Historical modeled candidates | Synthetic candidates | Synthetic opportunities/hour |
| --- | --- | --- | --- | --- | --- |
| 100 | 0 | unknown | 0 | 2 | unknown |
| 250 | 0 | unknown | 0 | 2 | unknown |
| 500 | 0 | unknown | 0 | 2 | unknown |
| 1000 | 0 | unknown | 0 | 1 | unknown |
<!-- /evidence:scenarios -->

Live opportunities/hour is **UNOBSERVED at X=100, 250, 500 and 1000**. No
observation interval supports estimation or an upper confidence bound. When
valid data exists, use `3600 * distinct_first_qualified_auctions /
observed_strategy_seconds` within matched windows, deduplicating repeated
auctions across windows and reporting qualifying revalidation failures
separately. Discovery counts and revalidated counts need distinct labels.
Neither 51 historical auctions nor repeated synthetic flow successes supply
the numerator or live time denominator for that estimate.

The [T5 pricing report](../../experiments/market_discovery/runs/t5-pricing/report.json)
replays all historical candidates, with zero qualifying modeled candidates at
every X above even under hypothetical rules. Its two reference examples give
targets/profit 6200/-210 for acquisition 6100 (39 independent comparables) and
150/-57 for acquisition 200 (5 comparables). Without supplied caps both return
`MISSING_CAPS`. These counts differ from Objective 001's 40/6 because T5 uses
a stricter >60-second remaining-lifetime margin. Robust median/mean would
give 6500/75 and 200/-10 respectively; none reaches X=100.

Synthetic success is separate: two fixture candidates model 1300 and 700 coins;
counts 2/2/2/1 do not represent arrivals. All four scenario runs select the same
1300-coin fixture, so four prepared intents are not four independent auctions.
There is no synthetic opportunities/hour estimate. **Projected profit is not
completed-sale evidence.** Sale probability, sell-through time, actual net
proceeds and tax rounding remain unmeasured; the retained real listing was
active evidence, not attributable settlement.

## Coverage bias and extrapolation limits

Expiry-ordered offset pages are not cheapest-BIN order or a random sample.
Twenty visible rows plus a lookahead do not cover a version's whole supply;
page drift can duplicate or omit auctions. Even a short page does not prove
market exhaustion. Club/league filters and low BIN bands favor narrow, cheap
supply; two exact versions cannot represent all FC27 PC cards. Broad cheap
rows may be illiquid noise. Caps, full legal increments, completed-sale
liquidity and market-wide denominators remain missing. Price-ceiling bias can
lower the reference distribution, while concentrated asks can defeat robust
statistics. Missing passive background counts confound request-load analysis.

The 72-request **SIMULATED** T3 demo only tests budgets, pages and state logic.
Its per-strategy elapsed aggregates span interleaved windows, including other
arms' time; do not reinterpret those values as active scan throughput. T6 does
not rank strategies from that fixture. No whole-market, hourly profit, daily
yield or subsecond-sniping extrapolation follows from these captures. The
selected targeted strategy is an implementation choice based on demonstrated
exact-version access, not an empirically proven yield winner. See the final
[one-page decision](001b-discovery-decision.md).
