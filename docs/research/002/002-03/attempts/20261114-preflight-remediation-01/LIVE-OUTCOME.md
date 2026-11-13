# Newly authorized 002-03 attempt: BLOCKED — USER INSTRUCTION REQUIRED

The encoding repair worked: the live PowerShell preflight returned valid UTF-8
JSON, and official-tab, Edge control and foreground checks all passed. The
production bridge remained on the selected FC27 PC account with mutations disabled.

Attempt `20261114-preflight-remediation-01` then stopped with
`no_real_eligible_candidate_single_discovery`. The actual authenticated EA discovery
returned HTTP 200 and **zero auctions**. This is a market-result limitation, not a
recurrence of the preflight encoding failure. No other card was tried.

The one actual EA request was:

```text
GET https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket
definitionId=261855&macr=1000&minb=11000&num=21&start=0
HTTP 200; auction rows: 0; native authentication-header presence: true
```

Parameter order above is descriptive; the retained query object in
[gate.json](gate.json) is authoritative. No authentication value was exported.
These are the unchanged discovery filters, page 1 and count 21.

| Measurement | Actual result |
| --- | --- |
| Attempt start UTC | 2026-11-13T23:03:22.849244+00:00 |
| Desktop preflight observation UTC | 2026-11-13T23:03:24.0209293Z |
| Attempt finish UTC | 2026-11-13T23:03:39.714789+00:00 |
| Discovery command monotonic start | 142204679805900 ns |
| Discovery command monotonic finish | 142204922603600 ns |
| Discovery recorded command interval | 242.7977 ms |
| EA RTT | 210.30000001192093 ms |
| Native service time, including RTT | 216.30000001192093 ms |
| Native helper time | 0 ms |
| Valuation start / final decision | Neither occurred |
| Valuation elapsed / performance verdict | Unavailable / FAILURE/BLOCKED |
| Consumed EA GETs / pricing GETs | 1 / 0 |
| Local helper batches / account mutations | 0 / 0 |

Attempt wall-clock duration includes desktop/setup, Foundation attachment and
discovery; it is not the required monotonic valuation-to-decision measurement.
The discovery command interval includes the retained command's transport and
checkpoint work. Native service time and RTT overlap and must not be added.

No pricing searches, second `maxb` query, fresh credits read, final admission caps
or `BID/ELIGIBLE` decision occurred. Those acceptance requirements remain
**unverified**. The failed attempt consumed its separate authorization and budget.

The [original checkpoint](../../gate.json) remains byte-for-byte unchanged and
FAILURE/BLOCKED. Its old encoding diagnosis remains accurate. Prepared independent
validators verified both original and new stop conditions; acceptance validators
correctly rejected both. See
[post-attempt-validation/results.json](post-attempt-validation/results.json).

Full offline verification before the attempt passed **533 Python tests and all
18 Node scripts**. The initial unrelated offline localhost connection abort is
retained separately. The [remediation report](REPORT.md) describes the exact code
changes, behavioral coverage, immutable checkpoint references and execution budget.

After the new failure, only retained-evidence validation, documentation and Git
delivery continued. No code fix, gate retry, second candidate, further EA request,
actor, maintenance job or Objective 002 item 4–12 work was performed.

**BLOCKED — USER INSTRUCTION REQUIRED.**
