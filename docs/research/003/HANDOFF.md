# Objective 003 submission handoff

The user authorizes continuous production operation with monitoring and an
automatic stop–fix–test–restart loop. Artificial experiment time/request/cycle/
new-enrollment ceilings are removed for this new objective. Strategy safeguards
remain. Realized-profit tracking is deferred. The minimum stability target is
four consecutive healthy monitored hours after the last runtime fix; this is not
a shutdown timer or a claim that every possible unknown bug can be witnessed.

Specification: [003-production-actor-soak.md](../../../objectives/003-production-actor-soak.md).

Existing Objective 002 (`obj-29bea3b74eb3`) remains BLOCKED. Its old live segments,
consumed budgets, failures and PARTIAL assessment are historical inputs, not
windows to reopen. Do not recheck it while Objective 003 owns operation.

The submission turn only prepares/publishes the specification and submits it to
the existing orchestrator. It does not directly launch a second actor stack.
The orchestrator must review the current baseline, reconcile fresh state, implement
the continuous monitor/lifecycle and pass checks before enabling live operation.

Before writing the specification, the workspace and runtime were backed up to
`private-captures/003-handoff/20261115T151935Z/`:

- Git bundle at initial HEAD `84a1e083573ba8ceefdbbd8845ce7b4772b9814e`;
- binary diff of pending tracked changes;
- archive of 44 untracked baseline files;
- consistent journal, cache, native mailbox, transport and orchestrator DB backups,
  all with SQLite integrity result `ok`.

Pending Objective 002 source/evidence changes belong to the previous worker's
latest continuation, including review-05 (744 Python tests and 27 Node suites
reported). They are intentionally preserved outside this specification commit.
Task 003-01 must independently review/verify and commit that baseline rather than
discarding it or treating an old report as current runtime proof.

No browser recovery, EA request or account mutation is performed by the
specification/submission step. Subsequent production trading is authorized by
the new objective under its retained strategy, identity, pacing and recovery rules.
