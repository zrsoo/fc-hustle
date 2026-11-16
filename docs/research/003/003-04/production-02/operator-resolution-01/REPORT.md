# Operator-confirmed loss: resolve the 950-coin incident and resume 003-04

The user explicitly confirmed that this expired auction was **lost**, then
authorized recording that outcome, releasing its local reservations and
rechecking the existing task. This is a narrow operator resolution of the exact
bid below, not native readback evidence and not an automatic unknown-write policy.

| Field | Value |
|---|---|
| Scope | `e7fce7c176935f0b95dc3db91dd28521` |
| Command | `ff4174653771149736e63b1ac12630f9` |
| Trade | `trade:86f34fb6234c8c320dceeede` |
| Item / exact definition | `item:6a39764a61664629878abd4a` / `271421` |
| Actual dispatched amount | 950 |
| Outcome source | Operator: the user explicitly reported LOST |
| Native terminal outcome verified | **false** |
| Refund claimed | **false** |

The user's confirmation was: “we lost. what does it matter about the current bid?
it expired and we lost, this SHOULD NOT be a blocker.” The subsequent execution
instruction was: “okay, do that and then recheck. make sure the orchestrator is
safely past this and then let it run on its own.” These instructions authorize
this one exception to the earlier native-only reconciliation prerequisite.
They require no further human action for this incident. They do not authorize
inferring other auction losses from expiry, absence or unchanged balances.

## Change and actual application

`fc_access/continuous_v1/operator_loss.py` is an explicit local operator seam;
it is not an EA operation or an automatic startup rule. It requires the exact
context, command, trade/item/version, amount, expired deadline, dispatched claim,
operator attestation and execution authorization. Known native terminal evidence,
owned inventory/resale conflicts, a terminal/not-dispatched command, conflicting
unresolved bids and mismatched identities are rejected.

One transaction fences the previous owner, appends immutable `operator_losses_v1`
proof and `OPERATOR_LOST_CONFIRMED`, marks the matching command RECONCILED and
changes its capacity slot to OPERATOR_LOST. Queue replay releases its local coin
reservation, invalidates its old balance observation, and creates no pending
resale. The registry labels its terminal outcome `source=operator` with
`native_outcome_verified=false`. There is no LOST_VERIFIED event, fabricated
native response, account credit, or write replay. Sticky DRAINING and unrelated
scopes remain unchanged; duplicate application returns the original proof.

No controller/actor process was running. Account, supervisor, native executor,
journal ownership/executor and bid locks were held during actual application.
Consistent five-database backups, initial dirty-tree patch and starting commit
are recorded in [backup.json](backup.json), under
`private-captures/operator-loss/20261115T235101Z/`. Each backup passed SQLite
integrity checking. Historical reports and stopped segments were not rewritten.

[Application](application.json) independently checks that all preceding journal
and registry rows remain unchanged and only the matching command's state changed.
Zero queued commitments and zero local reserved coins remained. The after-state
capture is `private-captures/operator-loss/20261115T235101Z/after.sqlite3`.
The 950-coin local reserve release is not an assertion that EA refunded 950 coins.

The existing transport authority recognizes the durable resolution and permits
retiring that transport fence. Independent checking also verifies the old bid
itself remains unauthorized for replay. Future mutations still require new,
fresh, independently authorized intents.

## Verification

Nine new behavioral tests cover explicit authorization, exact context/identity/
amount, no expiry-only inference, native/owned conflicts, no terminal-command
reuse, immutable proof, idempotency, rollback, owner fencing, scope isolation,
sticky DRAINING, migration/restart replay, and actual Foundation startup with
the resolved trade absent from watched data.

```text
python tests/test_operator_loss.py
python -m unittest discover -s tests -v
node tests/<each *checks.cjs file>
python tests/check_00301_baseline.py
python tests/check_bidding_v1_artifacts.py
git diff --check
```

The focused nine tests pass. [checks.json](checks.json) and its stdout/stderr
files retain the full Python/Node and independent-validator execution results.
The historical baseline verifier permits the new OPERATOR_LOST projection while
continuing to preserve historical identities, events, intents and consumed work.

The first full discovery ran 900 tests with one error, a Windows 10053 loopback
connection abort in the historical follow-up server's denied-origin HTTP test.
An unchanged isolated run passed, but another isolated run reproduced the error;
both failed receipts are retained rather than discarded. The handler rejected a
POST and closed with its body unread, allowing a TCP reset before the 403 reached
the client. Its denied-origin path now discards only a size/time-bounded body,
without parsing or retaining it, and preserves the 403/authentication policy.
The added fragmented-POST behavioral regression and all ten final module tests
pass; [HTTP repair receipt](http-fixed.json) records that check. This repair is
limited to the historical diagnostic harness, not the production native server.
[Final broad-check receipts](final-checks.json) retain the subsequent discovery
run separately from the earlier failures.
The successful broad run passed **900 tests, zero failures/errors** in 334.639
seconds. Its discovery preceded addition of the fragmented-request regression;
the final HTTP-module invocation passed all **10 tests**, including that added
case. All **27 Node suites**, baseline preservation and bidding artifact checks
also passed. No test was deleted, skipped or weakened to obtain these results.

Fresh read-only production startup verification used:

```text
python tests/probe_00304_recovery.py --output docs/research/003/003-04/production-02/operator-resolution-01/live-recovery
```

It exercised the actual Foundation, canonical journal/cache, native adapter and
localhost production bridge. At fresh epoch **71**, all three authenticated EA
GETs returned 200: watched `2b1ac266f91476af8d51cb1dde0abb28` at 23:55:11.331Z,
credits `3dd154ba55a2ae8ec0301b6bb84f0201` at 23:55:13.349Z and complete Transfer
List `96a21a6dcf98125dd3a7d7b009a72b55` at 23:55:15.336Z on 2026-11-15 UTC.
The result was PASS: **62,827 credits, five occupied items, zero unresolved
commitments, zero pending resale**. Credits and inventory were fresh. The probe
made three read operations, no account mutations, and launched no actors.

[Exact sanitized native evidence](live-recovery/native.jsonl),
[probe result](live-recovery/result.json) and [independent verification](independent.json)
retain the observations. Each response was independently reparsed and joined
to its durable transport row. A separate transport capture is retained alongside
the backup. No authentication values were extracted or recorded.

## Handoff to the existing orchestrator task

**The specific 950-coin blocker is resolved by explicitly authorized operator
confirmation, and actual fresh startup reconciliation passed.** Keep the old
incident's missing native outcome proof visible; do not relabel that case as
independently native-verified. Other ambiguous writes retain normal safeguards.
Future selector retention is already committed in `cca90b8`; the original lost
selector need not be reconstructed to resolve this operator-confirmed loss.
Load the updated reviewed bridge in a fresh browser document before production
recovery; a source commit alone does not replace an already loaded page closure.

After publishing the repair and this report, recheck the same
`obj-da182a175410/003-04`. Do not create a duplicate objective or controller.
Resume with the same durable account state, a fresh owner and startup reads,
and a new healthy segment under the persistent watchdog. Preserve the two old
stopped segments, all request counters, the native-proof coverage gap and
Objective 002's BLOCKED/PARTIAL history. Four consecutive healthy hours and
genuine remaining coverage are still required; this report does not complete
the objective.

The initiating session must verify that the orchestrator gets past the resolved
bid and reaches supervised operation before leaving it to run. Runtime and
handoff observations will be retained separately from the pre-recheck evidence.
No further approval is needed for ordinary fixes/recovery authorized by Objective
003. Ordinary missing/incomplete watched observations should be investigated
through safe exact-status recovery where available; do not infer terminal states
or replay bids to manufacture evidence.

There is a concrete remaining recovery path to review before enabling writes:
`Bidder.cycle` currently emits MISSING_OR_STALE_IDENTITY on a missing watched row,
and `continuous_v1.recovery.reconcile` requires watched membership. Neither path
currently invokes the available exact-status operation as a fallback. Selector
retention by itself does not integrate that read. Investigate and repair that
ordinary integration defect autonomously within 003-04 where needed, using
bounded serialized read-only lookups, exact identity/freshness validation and
normal terminal/ownership proof. Preserve the controlled-stop behavior if the
fallback cannot resolve the outcome. This is an actionable implementation task,
not another missing human prerequisite. It does not undo this exact operator
resolution or authorize inferring any other loss.

The orchestrator process enhancement is recorded separately as
`C:/hustle/agent-orchestrator/improvements/IMP-004-autonomous-recovery-before-blocking.md`.
Its implementation remains deferred as requested; no scheduler code or global
blocking policy was changed in this repair.
