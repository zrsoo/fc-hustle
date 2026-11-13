# Objective 002 task 002-03

The explicit one-shot runner is `python -m fc_access.production_v1.gate_00203`.
It exclusively creates `gate.json` before live work; existing RUNNING, PASS and
FAILURE/BLOCKED checkpoints prevent all automatic re-entry. A crash consumes the
window. There is no repair/resume/retry flag. Items 4â€“12 must call `require_pass`
before dependent work; that checks retained evidence as well as the verdict.

The finite budget is seven EA GETs and at most 64 local helper batches: one
discovery, initial caps, two exact pricing requests, fresh discovery and credits,
then the Foundation admission's fresh caps. Each local batch remains <=32 probes.
Pricing is permitted only in the single UNCACHED_VALUATION stage, at most twice.
The service must have mutations disabled and the executor rejects all writes.

The monotonic nanosecond timer begins before initial caps, helpers, cache lookup,
and the first pricing request. No cap/helper/price warmup occurs before it. The
ordinary Foundation journal/diagnostic writes and sanitized checkpoint writes
run inside the timer. After the uncached quote completes, the runner refreshes
the exact discovery auction and actual credits and calls production
`Foundation.admit`. That admission reuses the just-completed quote inside this
same timer and writes its normal durable decision before returning. This reuse
does not substitute for the initial uncached valuation: both actual cache reads
and the two initial EA requests are retained and assessed separately.

The stopwatch ends after the final Foundation decision and checkpoint writes; report assembly,
read-only independent assessment, and sealing occur afterward. Every delivery
and checkpoint checks the strict deadline; >=30.000 seconds, unavailable auction,
missing quote, stale/unknown/noneligible decision, native/transport error, or any
other failure stops the attempt. Only failure evidence/reporting and already
prepared offline validators may run afterward. No code fixes, another candidate,
another attempt, or items 4â€“12 are authorized after failure without a subsequent
explicit user instruction. No bid is ever dispatched by this runner.

`tests/test_00203_gate.py` exercises the real Foundation with an explicitly offline
page double and temporary state. It tests cache miss and timed reuse, both actual
wire queries, native price legality, fresh admission, persisted diagnostics,
deadline equality and overrun, missing candidate, transport failure, stale hold,
unknown decision, evidence corruption, no dispatch after stop, crash fencing,
finite budgets and dependency rejection. These fixtures never create live proof.
`tests/validate_00203_gate.py` independently reads the retained live capture and
fails until a genuine evidenced PASS exists; it never sends live requests.
`tests/validate_00203_stop.py` verifies the sealed terminal verdict, exclusive
checkpoint consumption, and failure rejection or evidenced-PASS admission of
dependent work, independently of whether the live performance gate succeeds.
Only captured response/experiment evidence has integrity hashes. Mutable source
and configuration are not pinned.

During offline test development, a mocked top-level runner test exposed a bound
default-path isolation bug and created `offline-isolation-failure.json` in this
directory. That file is preserved as test-development evidence: its mocked
health call raised AssertionError, with zero operations, zero cache reads and
no valuation timer or browser requests. It is not a live gate attempt. The
runtime path now resolves after mocking, and that test uses a temporary path.

## Actual single live command outcome — FAILURE/BLOCKED

On 2026-11-13 the explicit live command failed during its desktop preflight,
before `run`, Foundation construction, candidate discovery, or valuation start.
Python's subprocess reader selected cp1252 and encountered an undefined 0x81 byte
in the ordinary UI inspection output, raising UnicodeDecodeError; stdout was
then None and the preflight raised AttributeError. No credential value was read.

The terminal `gate.json` records this actual failure, consumes the window, and
blocks re-entry and items 4–12. There were **zero EA pricing GETs, no live gate
valuation, no final eligible decision, and zero bid dispatches**. Valuation
elapsed time is unavailable; it is not claimed as zero or as a <30s PASS.
No code fixes, automatic repair, second candidate or rerun followed this failure.
A subsequent explicit user instruction is required before further gate work.
This is a runner failure, not a request for CAPTCHA, login or missing credentials.

Before this command, all 523 discovered offline tests passed in 68.109s; the
final focused suite passed seven tests. Those results prove behavioral contracts,
not the missing live acceptance. The retained-live validator must remain nonzero;
the hard-stop validator and offline behavioral tests are separately repeatable.
