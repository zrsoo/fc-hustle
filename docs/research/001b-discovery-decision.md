# Discovery architecture decision — CONDITIONAL GO

**Scope:** proceed with offline Objective 002 architecture implementation and
bounded read-only validation. Live discovery throughput is BLOCKED / UNOBSERVED;
this is not a production readiness or profitability GO. T6 completes the
analysis of retained evidence without new EA requests or account mutations.

**Best source:** EA native exact `(fc27, pc, definition_id)` asking prices are
the only demonstrated production market observations in this research, from
Objective 001's historical reads. No third-party production feed is selected.
DataFluxor has the most explicit documented commercial exact-PC contract and
is the first conditional feed candidate, but production returned 401 and its
accessible sandbox is fixed console data. FUT-DB also requires entitlement;
FUT.GG's single retest returned 403 with automation permission unresolved.
No sandbox, provider description or repository contract establishes working
current PC prices. [Source evidence](001b-price-providers.md).

**Search choice:** start with A, the exact-version watchlist [233731, 278230],
and propose a bounded C hybrid with club/league exploration and ranking from
the preceding completed block. This minimizes unsupported identity assumptions;
it is not a measured yield winner. B's expiry-ordered, price-filtered pages
have unknown whole-market coverage. All A/B/C windows remain unrun; compare
them under the frozen 24-request-per-arm cap before claiming superiority.
[Budgets and coverage](001b-discovery-benchmarks.md).

**Defensible opportunities/hour:** unknown for X=100/250/500/1000; no numeric
estimate is supported. T4 retained zero authenticated observation seconds,
zero auctions and zero qualifying revalidations. Its 240.150319-second access
attempt is not an observation denominator. The historical 51-auction capture
spans only 72.195015 seconds; modeled examples are negative under hypothetical
rules. Synthetic counts 2/2/2/1 prove the dry-run flow only. Projected profit
is not completed-sale evidence; no sell-through or realized-profit estimate
follows. [Scenarios and extrapolation limits](001b-discovery-benchmarks.md).

**Latency:** the controlled local alarm queue median is 24888.920100 ms (n=3),
versus 0.037200 ms for long poll (n=3). Queue delivery is the demonstrated local
bottleneck. Native EA service time and the live bottleneck remain unknown;
one baseline 401 and one pre-native alternative failure are not a matched
speed comparison. Select bounded long polling as the proposed delivery design,
pending successful Edge/MV3 and lifecycle validation. Keep the >=30-second EA
submission gap; all p95 claims are withheld below n=20. [Timing evidence](001b-latency.md).

**Exact unverified prerequisites:** (1) normal EA sign-in/challenge completion,
FC27 PC selection and a fresh authenticated HTTP 200 search; (2) reviewed
read-only persona projection if normal selection still fails the schema guard;
(3) matched A/B/C observation, at least 30 authenticated minutes, background
traffic accounting, fresh qualifying revalidation and adequate timing samples;
(4) exact-card native caps and relevant legal increments with provenance and
<=300-second age; (5) successful long-poll search, MV3 suspend/tab/reconnect
behavior and handoff pairing/epoch/durable-identity protections; (6) legitimate
production entitlement, mapping, timestamps, PC payload and terms validation
before any external feed is enabled. Third-party access is optional for the
initial native watchlist. Real sale settlement, odd-boundary tax rounding and
liquidity remain unverified prerequisites for realized-profit claims; existing
Objective 002 execution/lifecycle release conditions remain in force.

**Exit:** implement S1–S4 offline using the [delta addendum](001b-obj002-addendum.md),
then satisfy the existing S5 live evidence conditions. Do not represent this
conditional architecture recommendation as a completed throughput benchmark.
