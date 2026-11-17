# Next repair stage: scheduler-owned runtime contract

This is an implementation plan, not operational proof. Original Objective 005
requirements, strategy and 14,400-second acceptance remain authoritative.

1. Retain validated `/diagnostic` records with command/peer correlation. Reuse the
   shared typed diagnostics schema; reject unknown keys or arbitrary exception
   text. Bound record counts, preserve rejected-result diagnostics safely, and
   distinguish primary wire status, native error code, service status and local
   delivery status. Add adversarial correlation/sensitive-canary tests.
   Also cover repeated failed local `price_helpers`: successful helpers must not
   renew native freshness, but persistent helper failures must not be silently
   treated as ordinary empty discovery when caps/read calls still succeed.
   Current stage01 semantic policy deliberately ignores helper events for native
   freshness and has no separate helper failure counter yet. Verify and repair
   that gap before production launch; do not claim stage01 is complete health
   coverage.
2. Extend verified Edge foreground recovery with a bounded temporary
   `AttachThreadInput` fallback. Select and privately allowlist the intended
   official tab before any input, restore/detach in finally, and verify foreground
   again immediately before input. Test ambiguity/failure behavior and inspect
   actual desktop access again. Reload the reviewed extension and app as needed;
   normal saved sign-in remains authorized, challenges remain for the user.
3. Extend the existing watchdog with an optional owned runtime interface rather
   than a second trading loop. Preserve one spawned sequential controller, its
   canonical account/native/port/database guards, durable intents and leases.
   The parent obtains an additional exclusive service lock before creating a
   unique generation or child. Existing records never authorize a replay.
4. Persist a small atomic, fsynced state manifest plus append-only events under
   `private-captures/controller-v1/operational/`, with public scope, generation,
   parent and child identity/creation times, task key, launch intent, real start
   monotonic time, progress state, semantic snapshot and exact stop reason.
   Lock ownership and process creation identity must prevent stale/PID-reuse
   acceptance. Generation boundaries retain previous events and evidence.
5. Provide workspace scripts for scheduler `service`, `monitor.check` and
   `monitor.stop`. Launch persistent service only through the scheduler-owned
   service handoff; do not spawn it as an ordinary tool child or create another
   scheduler. The manifest survives provider/quota cleanup and supports inspection
   without a browser request. Do not edit orchestrator lifecycle SQL.
6. Check: bounded, deterministic, zero account writes or EA requests; stdout
   exactly `{status,generation,diagnostic,evidence}` JSON, exit0. Read actual
   generation/ownership, controller lifecycle, work-boundary freshness, real
   semantic success/failure counters and last native success. Expose STARTING,
   ACQUIRING/MANAGING, RECOVERING and STOPPED truthfully. Only a genuine new launch
   permits STARTING within90 seconds, also bounded by scheduler-owned grace.
   No callback heartbeat or local helper extends native freshness. Poll at30s.
7. Stop: generation/owner-bound durable local request consumed by the parent;
   withdraw leases before further native claims, drain one existing request,
   join only its own child, retain uncertain intents and acknowledge actual exit.
   Use a bounded timeout compatible with the existing30s transport/35s grace
   (scheduler stop timeout can be60s). Repeated stop is harmless. A stale request
   cannot stop a later generation or another owner's service. Never terminate
   an arbitrary PID or replay an ambiguous control/mutation.
8. Add isolated process tests: duplicate launch and lost lease, parent crash,
   stale owner/PID, stop twice, late stop against a new generation, service
   startup timeout, malformed/missing/stale semantic evidence, repeated failed
   native operations, recovery boundaries and genuine semantic progress. Keep
   fixtures off production ports/DBs and prohibit EA access in offline tests.
9. Make a new finite live write experiment after diagnostics are retained.
   Record reservation/intent before each irreversible action, use the agreed
   filters/pricing/minimum legal bid/cap/account scope and independent fresh
   account/status readback. Investigate a denial using actual layered evidence;
   neither alter pricing to manufacture a win nor retry an uncertain bid.
   Historical expired mappings do not block safely isolated new work.
10. Reconcile actual current account state and launch the corrected runtime
    through this task's scheduler service handoff. Persist concrete resumable
    next actions before handing off. Return monitoring for quota-free checks;
    any defect/stop/restart/monitored gap resets the final interval.
11. Implement a separate strict acceptance audit over retained genuine command,
    wire/service, independent status/member, win/paid ownership, move/list and
    eligible maintenance evidence. Bind evidence to the final generation and
    the scheduler's complete monotonic sample interval/epoch. Reject fixtures,
    prior generations, ACK-only ownership, idle/failed-read coverage, missing
    branches, gaps and durations below14400s. Verify running owned service and
    committed/pushed changes. Cover acceptance indexes0 and1 with independently
    runnable argv validators, including negative tests of the audit itself.

Do not replay read-01/read-02 or historical bids. Stage01 introduced semantic
stops but did not establish write success or launch a persistent runtime.
