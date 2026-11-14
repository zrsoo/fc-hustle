# Sixth live attempt: PASS

**READY TO RESUME ITEM 4.** Genuine uncached exact version **278046** completed
two real pricing GETs and fresh `BID/ELIGIBLE` admission in **12.069805600 seconds**.
No bid or other account mutation was dispatched.

The first page returned 21 auctions with minimum valid BIN **5200**. The second
page-1/count-21 request emitted actual `maxb=5200`, returned 20 auctions and
produced final resale **4900**. Fresh exact auction, credits **62127** and native
card limits **700–11000** supported minimum bid **700** and legal cap **4100**.
The first completed-cache lookup missed; final admission reused the completed
24-hour quote. The normal durable decision was independently readable afterward.

This exclusive checkpoint consumes a new, explicitly authorized attempt. All five
earlier checkpoints remain unchanged and `FAILURE/BLOCKED`; none is reinterpreted.

See the [full remediation report](../../adapter-repair/20261114-01/REPORT.md),
[authorization](authorization.json), [checkpoint](gate.json),
[wire evidence](wire-summary.json), [transport diagnostics](transport.json) and
[independent local restart readback](restart-readback.json).

Repeatable offline validation, with no EA requests:

```text
python tests/validate_00203_gate.py --attempt 20261114-adapter-repair-gate-06
python tests/validate_00203_stop.py --attempt 20261114-adapter-repair-gate-06
python tests/validate_adapter_repair.py
```

Do not rerun this consumed live attempt. The orchestrator should validate retained
evidence and resume its existing objective from item 4 after recheck admission.
