# New incident: actual 950-coin bid needs independent native outcome proof

**BLOCKED on a new prerequisite.** The original 700-coin, never-dispatched
reservation was independently verified withdrawn before any further work. The
worker then continued actual supervised production. This incident concerns a
different, genuinely dispatched **950-coin bid**, not that repaired admission.

| Field | Actual retained evidence |
| --- | --- |
| Run / owner epoch | `956a2d483cf70c2d440709ed20a312fe` / 69 |
| Runtime revision | `dbc580c56cc5a37768ed41f0c6718369ee78dd57` |
| Bid command | `ff4174653771149736e63b1ac12630f9` |
| Trade | `trade:86f34fb6234c8c320dceeede` |
| Physical item / exact version | `item:6a39764a61664629878abd4a` / 271421 |
| Bid / stored legal cap | 950 / 3900 |
| Native bid network time | 2026-11-15T22:20:58.092Z |
| Callback / HTTP | success / 200; effect remains unproven |
| Watched read | `804caa79bbb16c7b5f99ba837bb50253`, 22:21:19.353Z |
| Independent exact-status diagnostic | `b92923c8c69cd549332835ba7e7bb495` |
| Diagnostic result | `known_identity_unavailable`, zero EA requests |

The native bid was dispatched exactly once. Its journal remains ACKNOWLEDGED,
with a conservative unresolved reservation/capacity slot. The fresh watched
response returned three other auctions, omitted this trade, and explicitly
reported incomplete coverage. Fresh aggregate credits were 62,827. Neither that
balance, the omission, nor HTTP 200 establishes whether this bid was accepted,
outbid, won, lost, or had no effect. The actual auction state remains UNKNOWN.
No account effect was inferred from those observations and no bid was replayed.

The monitor's primary incident is control sequence **4849**:
`ACTOR_INVARIANT_MISSING_OR_STALE_IDENTITY`, followed by stop sequence 4850 and
the monitor exception at 4851. The maintenance read
`e84dcddef494468d3e12a2766ccd6fba` was queued afterward; dispatch was already gated.
It timed out before dispatch, with no start timestamp, native dispatch claim or
transport command. Its later maintenance exception/stop at 5185/5186 was a
consequence of the controlled stop, not evidence of scheduler starvation.

All five owned children have exit records. RUN_STOPPED sequence **5193** confirms
all exits verified, no remaining processes and the segment sealed. The persistent
exporter took its final five-database capture and exited. Observed healthy time
for the stopped segment is **651.545921 seconds**; it is retained, not combined
with another segment or represented as four hours. The final capture is
`private-captures/continuous-evidence/00304-production02-periodic/20261115T222151Z-7db25231/`.

## Diagnosis and narrow repair

The reason EA's watched response omitted this auction is unknown. A separate
local defect prevented the intended exact independent diagnostic: before bidding,
`page.js` deleted the `known` entry to consume the write observation. That also
discarded the only retained native status selector. The same-epoch exact-status
diagnostic therefore failed before it could issue an EA GET.

After every affected controller/executor/monitor child and the mutation-capable
service exited, the page implementation was repaired. A separate read-only
selector retains the exact trade/item/version mapping after bidding consumes its
write observation. Status still requires exact identity and an actual fresh
native GET with the matching private wire selector. The selector grants no new
bid or owned-item authority, contains no raw DTO/read-observation authorization,
and is cleared on every complete fence change. No authentication data or raw
native identifier is exported. Old consumed command/read guards are preserved.

Behavioral regressions execute the actual page and retained native DAO in a VM:
successful bid, subsequent empty watched response, independent exact closed/outbid
status, incorrect item/version rejection, inability to claim ownership, refusal
to replay the consumed bid, and existing fence/reconnect invalidation. This is
offline regression evidence, not a live resolution of the consumed 950 bid.

The runtime patch passed **887 Python tests**, zero failures/errors, in 340.807
seconds, and **all 27 Node suites**. Actual argv/results and stdout/stderr are
retained in `checks/results.json`. The repair was committed and pushed as
`cca90b85f9904426b71812821a1175669495fa4d` before any restart. Additional focused
acceptance checks passed **27 tests**; exporter checks passed **5 tests** after
the new incident assessment support was added.

The patch cannot recreate a selector that was already deleted in the old loaded
page, or retroactively prove an account effect. It has **not** been represented
as live recovery of this bid. No actor restart, command replay, actual-bid
withdrawal or fresh empty journal was attempted.

## Safe state and exact remaining prerequisite

The mutation-capable service was stopped with exit verified and replaced with
the reviewed read-only service. Ordinary verified Edge UI reattachment followed
a fresh AGENTS.md read. It required no login and accessed no credentials, cookies,
authentication headers, tokens or EA session values. `readonly-health.json`
records attached=true, mutations_enabled=false and intent_journal=null. The
complete owned-runtime exit proof is in `process-stop.json` and the sealed control
records. Only the read-only service remains; no unmonitored mutation actor runs.

Provide independently verifiable official native outcome evidence for the exact
trade/item/version in the table before reconciling the ACKNOWLEDGED journal entry
or restarting production. The approved bridge currently cannot resolve that
consumed identity. Missing watched membership cannot be converted to LOST/no
effect, and the certified never-dispatched withdrawal must not be applied to a
real bid. Do not guess native IDs, replay the bid, discard the reservation, reset
budgets or bypass startup reconciliation. This is an actual uncertain-result
prerequisite, not blockage for an unwitnessed natural coverage event.

`incident.json` records the unique incident, command/read IDs, known/unknown
effects, diagnosis, committed fix, regressions, safe state and NOT_RESTARTED
reconciliation disposition. `diagnostics.json` preserves primary/secondary
control records, native command rows and journal state. The exact-status result
is independently joined to a sealed transport copy. `evidence-integrity.json`
checks only captured observations and the evidence database, never mutable
implementation, tests, instructions or configuration.

The new case `post_bid_selector_reconciliation` joins the matrix as LIVE-FAILED.
The 12 earlier genuine branch observations remain scoped to this stopped segment;
the other cases remain LIVE-UNVERIFIED. There are now 25 required cases. No failed
callback or offline repair was promoted to a successful live outcome. Four
consecutive healthy hours on the final runtime revision and full genuine live
coverage remain unfulfilled. Realized profit remains DEFERRED.

Full task validation remains separate from this prerequisite:

```text
python tests/check_00304_live.py
python tests/test_00304_live.py
python tests/test_00304_exporter.py
node tests/production_inventory_checks.cjs
```

The first evaluates all ten original acceptance criteria and exits 1 / INCOMPLETE.
It is not a human prerequisite-only blocker check. The stopped index is retained
at `../stopped-evidence-index.json`; current ownership/evidence selection remains
in the root `evidence-index.json`. Resolve this actual bid independently, then
recover under a fresh fence with the same durable state and a new healthy segment.
Preserve both earlier stopped segments, counters, incidents and all original
acceptance criteria.
