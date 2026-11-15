# Independent evidence assessment for Objective 003

This procedure is prepared before launch. Its result is separate from the
collector, actor registry and runtime's self-reported counters. The assessor
reads retained evidence without sending EA requests or dispatching commands.
An operator collecting evidence must not approve their own unsupported summary.
A separate reviewing session/operator records the reviewer identity, timestamp,
run, revision, exact references, checks, failures and bounded conclusion.

1. Run `python -m fc_access.continuous_v1.evidence assess <snapshot-directory>`.
   Preserve its output as a new assessment artifact. It checks sealed capture
   integrity, protocol correlation, context/fences, native versus fixture source,
   missing/failed callbacks, unsettled commands and independently reconstructs
   adjacent healthy sample intervals per run. A STRUCTURALLY_VALID result means
   the evidence can be inspected; it leaves live coverage LIVE-UNVERIFIED.
2. Resolve the capture's source paths, capture interval, selected run and revision
   from its manifest and the operator's launch/revision record. Each copied DB is
   individually SQLite-consistent. They are not a cross-database transaction.
   Join records by command ID, read ID, exact context and fenced epoch, never row
   position or wall-clock proximity. A boundary race requires another snapshot or
   remains unverified. Retain table/primary-key references for every join.
3. Compare `native.sqlite3 work.command/response` and `native_events` with the
   independently retained transport `commands.body/result` and `events`, including
   recovery commands in `control.sqlite3 records/RECOVERY_INTENT/RECOVERY_READ`.
   Check the exact command ID, operation, parameters, response command/read IDs,
   context/account/persona/game/platform/identity_namespace and owner/epoch/host/
   worker/document fences. Readbacks must be distinct commands, fresh after the
   effect and complete where required. Native network method/path/query/status,
   source, timing and fanout must match the operation, not merely HTTP 200.
   Missing or inconsistent replicas remain a finding; never repair the evidence.
4. Open the captured canonical journal and quote cache read-only. Join commands,
   journal `events`, `registry_events_v1`, `resale_writes_v1`, `bulk_writes_v1`
   and their retained lifecycle records to the referenced native reads. Preserve
   the native trade/physical-item/definition mapping, public identity namespace,
   original acquisition versus new resale trade, actual paid cost and stored
   quote. Verify bid ceiling/minimum tick/reserve and the three separate capacity
   bounds. No missing watched row, account balance delta, callback or actor event
   alone establishes WON/LOST, ownership, sale, listing or released capacity.
5. Apply every case-specific requirement in `live-coverage-matrix.json`.
   For listing/relist/clear, reuse the independently tested `listing_proof` and
   `bulk_proof` helpers in `fc_access.actors_v1.final_assessment` when applicable,
   with the case's captured native inputs and exact time anchors. Check all
   manual-item effects and unchanged survivors, exact new trade mappings, stored
   prices, actual hour duration and distinct complete readbacks. Legacy failed
   callbacks remain failures even when later reads prove an effect. Record
   `effect_reconciled` separately; no old callback counts as new execution.
6. Review each `INCIDENT`, `SUPERVISION_GAP`, stop/exit and unresolved intent.
   An incident record names its unique ID, trigger command/readbacks, known and
   unknown effects, root cause, fix revision, regression receipt, old child exits
   and restart reconciliation references. Missing diagnosis or ambiguity keeps
   the affected cases unverified and mutations gated. Retain failed segments.
7. Recompute healthy time from adjacent successful SNAPSHOT ticks after READY,
   no more than 10 seconds apart, without crossing a gap, stop, run or runtime
   fix. Check snapshot identities, heartbeat leases and process/queue/freshness/
   capacity/intent health. Cross-check runtime healthy counters and incident
   boundaries. Four consecutive hours on the final revision is a later live-run
   milestone, not a launch preparation claim, cumulative-window sum or stop timer.
8. Record a per-case independent decision with run/revision, reviewer identity,
   command IDs, distinct readback IDs, native response references, DB table/keys,
   exact item/trade mappings, incident IDs and healthy segment ID. Promote to
   LIVE-VERIFIED only the fully witnessed case on that run/revision. Use
   LIVE-FAILED for a witnessed failure and LIVE-UNVERIFIED for absent/incomplete
   evidence. A repair requires new current-revision checks and new live proof;
   never overwrite historical failures or copy prior proof into current-run proof.

Realized-profit accounting is DEFERRED and excluded from acceptance. Preserve
all transaction/cost/ownership records, gross sale observations and diagnostics.
Projected tax-adjusted return and aggregate credits are not realized profit.
Do not request net receipts or a settlement dashboard as a preparation/run gate.

Every newly discovered case joins the matrix with an incident, explicit evidence
requirements, negative regression and independent reassessment in the repair
loop. This finite matrix does not exhaust every possible unknown edge case.
Ordinary no-candidate, rejection, HOLD, cap stop, loss, capacity/reserve pause or
empty maintenance is normal behavior unless an invariant or contract fails.
