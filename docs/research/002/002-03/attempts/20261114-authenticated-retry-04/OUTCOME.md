# Fourth attempt: authenticated, discovery blocked

**BLOCKED — USER INSTRUCTION REQUIRED.**

The verified official Web App window was brought into focus and refreshed. Home
and Transfer controls were visible; no normal login or security-challenge prompt
was present. No credential values were read or exported.

Authentication was then proved by an actual native EA request:

```text
GET https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/user/credits
Query: empty
HTTP: 200
Native authentication header present: true (value never exported)
Command: 5bef03a3ca10eff135ea08c6ef73502c
Transport: RESERVED → DELIVERED → ACKNOWLEDGED
EA RTT: 239.40000000596046 ms
Native service time: 270.5 ms
```

The following broad discovery command still received no accepted result:

```text
Parameters: page=1, count=21, fresh=true, maxBid=1000, minBuy=11000
Definition selector: omitted, for discovery across card versions
Transport: RESERVED → DELIVERED → TIMEOUT_NO_RETRY
Final state: UNKNOWN; result absent
Discovery command start to stopped checkpoint: 22044.3497 ms
```

There is no retained EA search status or auction count. This outcome does not
establish an empty market or the browser-side cause. The successful preceding
credits read establishes authentication at that time, narrowing the remaining
investigation to the native market-search/result path, including possible result
rejection or lost delivery. It does not prove market-service success.

No auction was selected. **Valuation never started**, and the strict 30-second
valuation/admission gate remains unmeasured. There were no pricing searches,
account mutations, retries or items 4–12 work after failure.

The attempt ran from 2026-11-14T01:24:55.816640+00:00 to
2026-11-14T01:25:26.923317+00:00. Overall preparation/transport wall time must not be
substituted for the absent monotonic valuation measurement.

Before live execution, **542 Python tests and 18 Node scripts passed**, including
25 focused gate/preflight/discovery tests. All three earlier failed checkpoints
remain unchanged. Independent retained-evidence and stop checks matched their
expected results.

See the [report](REPORT.md), [checkpoint](gate.json),
[transport journal extract](transport-diagnostic.json),
[authorization](authorization.json) and
[offline test receipts](offline-checks/results.json).
