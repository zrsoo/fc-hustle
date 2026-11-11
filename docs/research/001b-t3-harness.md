# T3 implementation and transport review

The [isolated harness](../../experiments/market_discovery/README.md) implements
bounded targeted, broad filtered and adaptive hybrid plans with common budgets,
observations, freshness, response/error, duplicate and coverage accounting.
The frozen T1 protocol and original Objective 001 bridges/evidence are preserved.
This completes T3's implementation work. A live discovery benchmark remains
**PARTIAL / unavailable**: the new bridge's one attachment attempt stopped with
`bridge_unavailable`, zero EA requests. No current authenticated search or new
account mutation is claimed.

The [historical replay](../../experiments/market_discovery/runs/t3-harness/historical.json)
reproduces the real targeted sample: two overlapping pages return 42 rows and
41 distinct auctions, plus the second version's ten rows. Page 1's lookahead
reappears on page 2. Expiry order is measured separately from BIN order; these
bounded pages cannot establish exhaustive coverage or opportunity arrival rates.
Historical end-to-end waiting does not identify EA-only latency.

The [synthetic A/B/C run](../../experiments/market_discovery/runs/t3-harness/demo.json)
exercises nine alternating windows, with 24 simulated requests per strategy,
including diagnostic revalidation. Shared metrics explicitly withhold live
candidate yield, background load and market denominators. The separate
[synthetic flow](../../experiments/market_discovery/runs/t3-harness/flow.json)
measures search, evaluation, a second fresh search and prepared dry-run intent.
Its hypothetical caps and profitable fixture are not evidence of a live
opportunity or verified listing rules.

The [local transport run](../../experiments/market_discovery/runs/t3-harness/local-latency.json)
uses actual 30-second baseline polls and bounded long polling against a Python
extension simulator, three requests per arm, zero EA reads. Median queue
delivery was about **24,889 ms** for the baseline and **0.037 ms** for the local
long-poll arm. Controlled simulated-native time was about 11 ms in each arm and
is labeled separately; it is not EA response time. n=3 does not support p95.
These are local queue measurements, not a measured Edge speedup. The new browser
worker's two modes and page timing are exercised in Node with native fixtures;
current MV3/tab lifecycle behavior remains unvalidated.

The original transaction worker retains its 30-second alarm, verified by its
preregistered digest. The separate alternative binds only loopback, pins the
extension origin, rejects unknown fields and unsupported filters at independent
boundaries, permits only search, bounds payloads/deadlines, delivers once, rejects
late/duplicate results, sanitizes IDs and errors in the page, and never reads
credential values. Local HTTP header spoofing by hostile local software remains
outside its protection. Long polling reduces command notification delay without
changing the 30-second EA observation cadence. No buy/bid/move/list/relist path,
transaction bridge delegation or production executor exists in this harness.

The [source review](../../experiments/market_discovery/source-review.json) pins
local reused sources and previous upstream license reviews. Competitor source
reuse is empty. MIT notice obligations and the exclusion of repositories with
no reviewed license grant remain explicit; provider data rights are separate.

Validation runs independently from repository root:

```powershell
python tests/test_market_discovery_harness.py
python tests/test_market_discovery_transport.py
python tests/test_market_discovery_artifacts.py
```

These checks execute the strategies, replay the actual source, validate sanitized
schema/artifacts, exercise a complete synthetic fresh revalidation flow, execute
the browser code with mutation traps and private-value canaries, test real HTTP
security, long-poll wake-up, single delivery, mismatched IDs and deadline expiry,
recompute retained local timing aggregates, and verify preservation digests.
