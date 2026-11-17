# Single controller (Objective 004)

The final implementation and verification handoff is documented in
`docs/research/004/REPORT.md`. Full controller E2E remains deferred to hands-on
operation; the commands below are future operator instructions.
The later minimal-watchdog implementation and verification is recorded in
`docs/research/004/watchdog/REPORT.md`.

Imports and a newly constructed controller perform no account activity. New
durable lifecycle state is STOPPED. ACQUIRING and MANAGING are the only
operational phases; RUNNING, PAUSED, STOPPED and HALTED are separate lifecycle
states. The Python API exposes `run`, `status`, `pause`, `stop`, and explicit
`resume` (which only arms subsequent steps). `step` is finite and does nothing
while quiesced. No actors, maintenance subprocesses or scheduled jobs are started.

Explicit operator commands, from the workspace:

```powershell
python -m fc_access.controller_v1 run --database private-captures/controller-v1/controller.sqlite --cache private-captures/controller-v1/quotes.sqlite --context public-context.json --port 8784
python -m fc_access.controller_v1 status --port 8784
python -m fc_access.controller_v1 pause --port 8784
python -m fc_access.controller_v1 stop --port 8784
python -m fc_access.controller_v1 status --database private-captures/controller-v1/controller.sqlite
```

The run command explicitly starts account activity. Do not launch it during the
Objective 004 implementation: full lifecycle operation belongs to the later
hands-on handoff. The context file contains only the existing public
account/persona/identity_namespace/game/platform labels, never authentication
material. There is no default account, database, cache or run port. Run holds the
canonical legacy account owner/native and port guards plus a controller database
guard. The CLI parent supervises one controller worker; that worker's HTTP thread
serves local delivery while its main thread performs all policy, resale and
maintenance. The standalone `controller_v1.server` CLI remains a
read-only transport service and cannot create trusted mutation admission.

## Minimal watchdog

The same `run` command now starts the watchdog automatically. Leave its terminal
open: one refreshing line shows STARTING/RUNNING, phase, current operation and
managed count. On an incident it shows STOPPING, then **STOPPED** with the reason
after verifying worker exit. Ctrl+C requests a cooperative stop; the existing
pause/stop commands still work. There is no automatic restart. A unique local
`watchdog-runs/<UTC-random>/events.jsonl` next to the controller database retains
progress, sanitized exception stack locations, the stop reason and whether
termination was forced. Its path is printed before startup.

Stop criteria are process exit, an unhandled controller exception, an existing
HALTED/PAUSED/STOPPED lifecycle, a missing supervision lease, or a stalled work
boundary. Initial startup/attachment allows 90 seconds, one native transport
call allows 45 seconds (the underlying transport already times out at 30), and
local work allows 60 seconds without a new boundary. These are liveness limits,
not an acquisition or management-cycle budget. Long batches and the documented
26-second management cycle remain valid when individual operations progress.
The watchdog also stops if its own status output or event log fails.

The parent checks every 0.5 seconds. Leases expire after 10 seconds; policy step,
paced dispatch, server enqueue and native claim refuse work after supervision
loss. On stop it allows 35 seconds for in-flight work/cleanup, then terminates
only its own stuck worker. An already-issued EA action cannot be undone; its
result can remain unknown. After a forced termination, saved SQLite lifecycle
may still say RUNNING: the watchdog's verified process-exit record is authoritative
for that run. Existing restart recovery consumes uncertain commands as before.

Rejected bids, outbids, expiry, missing status rows and ambiguous commands do not
trip the watchdog. They retain the controller's existing non-blocking policy.
Existing admission/identity/persistence checks remain in the controller; this
watchdog does not duplicate the trading engine or detect every possible logic
error. Repeated handled operation failures can keep reporting progress and need
inspection of the normal controller journal. No GUI, desktop notifications,
additional EA polling, recovery automation or new trading policy is introduced.

Pause/stop persist lifecycle withdrawal, invalidate queued delivery and drain the
serialized in-flight call before acknowledging quiescence. They retain phase,
pricing and membership. The run process then exits and releases its service and
guards. Read saved status with `--database`; restarting the explicit run command
resumes using a new owner epoch/document and independently recovered mappings.
The HTTP `/control` route accepts pause/stop only; `/run` is a one-shot command
transport route and cannot start lifecycle activity or manufacture admission.

Known wins remain PENDING_WIN until exact physical ownership/paid-cost proof and
independent move/list readbacks establish handling. Listing uses the stored BIN,
native previous tick and duration 3600. Inventory/caps/ticks and terminal proof
are rechecked at admission and claim. A consumed ambiguous move/list is read-only
recovery work and leaves its known win pending until proved; unrelated urgent
auction management continues. A proven list and the final genuine settlement
allow ACQUIRING; timer expiry and missing rows do not establish loss.

A confirmed move can remove the claimed auction from watched. Before listing,
the controller reparses its original terminal/our-paid-bid lineage and separate
move readbacks in their original account/epoch. Those are historical evidence,
not fresh observations. The listing still needs a new complete exact physical
inventory, matching paid price, current caps/ticks and current owner fences.
Claimed auctions with this proof are excluded from subsequent status polling.
Across reconnect, native inventory can provide a bounded private item selector
for an independent item GET; that selector grants no move/list authority.

After urgent status/rebid/readback work, maintenance inspects complete inventory.
Sold clearing uses the existing native classifier, zero-argument bulk API and
independent effect assessor. Each durable relist tick advances by 3660 seconds
before I/O; it preserves prior BIN/start and checks the observed 3600-second
duration. If sold and expired items coexist at a tick, verified clear precedes
relist. A changed/unknown inventory fails closed for that operation. Ambiguous
bulk generations are consumed and visible without gating unrelated writes;
changing a bulk set cannot sneak a consumed target into a new command. New trade
generations can support a later distinct operation. Recovery never dispatches a
saved command. Current complete inventory and watched mappings must be rebuilt
after reconnect; stale fences cannot dispatch or control the new owner.

See `docs/research/004/004-04/REPORT.md` and its acceptance/live contract review
for independent validators, fault boundaries and evidence limits.

## Transport and native contracts retained from 004-02

Implemented: dialect 4 commands, exact-target `status_batch` (1â€“10 distinct
trade/item/version targets), watched/balance reads, durable batch/decision/intent
admission and one-shot bid delivery. Importing these modules starts nothing.
The phase controller and pricing/selection composition are implemented by 004-03
in `controller.py`, `config.py` and `journal.py`. Operational lifecycle controls,
resale/maintenance integration and the launcher are implemented by 004-04. Nothing starts
production actors on import. See
`docs/research/004/004-03/REPORT.md` for policy, inventory validity and limitations.

`ControllerStore` uses a new, isolated SQLite database, WAL and synchronous FULL.
Only trusted server construction enables `write_authority`. The CLI service is
read-only and provides no write-enable flag. Batch admission, immutable decisions
and intent creation are Python APIs absent from the HTTP routes. `admit_batch`
requires a server-retained authenticated entry balance and a separately parsed,
complete current-scope inventory. `decide` records the exact target/amount/cap,
read, deadline and batch. `/run` cannot create or alter that authority.

The claim transaction rechecks scope, evidence, deadline and durable decision,
then consumes a permanent action tombstone before returning a command to the
extension. Initial action keys exclude batch/decision identity; rebids bind the
originating independent observation and amount. Reopening storage abandons all
old queued/claimed commands. Unknown, expired and duplicate commands do not gate
unrelated later work. No SQLite transaction or account data lock spans network
I/O. A controller launcher must hold the canonical account/native process guards;
the bounded probe demonstrates that ownership without launching the controller.

The existing reviewed production extension serves both dialects. It loads
`controller.js` before `page.js`; a new document is required after installation.
The factory receives private current-document mappings through a closure. There
is no public selector export or pseudonym inversion. A status batch passes the
actual retained DTO array once to the official DAO. Every requested native wire
trade ID is compared privately with the sole GET query. Duplicate, unexpected,
wrong-item and conflicting-version rows fail. Omissions remain explicit and
supply no row authority. Lite 0/null is preserved in original projections; a
separate version link references the full read, its original timestamp, the
status read and a revalidated current native DTO. Server admission independently
checks that retained full evidence before using a lite row.

Only after validating the complete returned set, the bridge uses the native
`setAuctionData` setter to attach each genuine returned auction entity to its
retained full-version item DTO. This refreshes bid state and prices without
replacing the full version with lite 0/null. Tests execute a rebid from both
0-version and null-version status updates; the original safe responses stay intact.

Request ownership starts when the native invocation passes its request object
to the official queue. A temporary wrapper follows only that object's eventual
`send`; matching URLs from manual/background requests do not grant ownership.
The actual owned XHR must match the exact endpoint, query, method and body before
dispatch. An absent owned send stays unconfirmed. Per-request retry/reauth is
disabled so the finite invocation cannot silently repeat; global EA authentication
policy is unchanged. Timeout/interruption remove only the owned queued request,
abort its in-flight request, unsubscribe/remove listeners, and restore temporary
queue, request, DAO, observable and XHR hooks. Late replies are scoped evidence.

The designated account is selected using normal Edge UI. Attachment pins the
actual user and selected PC persona objects privately; every call and native send
rechecks them and every result retains full public scope/epoch fences. The public
persona display name is not an EA saved-sign-in identifier. The result's
`designated_account_verified` flag denotes this binding following explicit
operator selection; the UI selection evidence is retained separately in the probe.
That flag alone supplies neither write admission nor participation proof.

Bid receipts use the existing reviewed semantics. ACKNOWLEDGED is not independent
confirmation; unknown and late receipts remain queryable without poisoning the
page or imposing a global write gate. The legacy schema 2 execute path retains
its original admission, receipt, timeout and poisoning behavior. Shared changes
are the factory handoff, explicit worker dialect routing, and a controller-only
null-version projection option. Legacy callers still reject explicit null
versions under their original contract.

Verification: `python tests/test_00402_controller.py` executes the shipped page,
captured official DAO, actual adapter/store/HTTP transport and worker behavior.
`python tests/check_00402_artifacts.py` checks retained genuine ten-ID live evidence,
budget history, independent comparisons, original lite versions and cleanup.
Neither validator invokes EA or hashes mutable implementation files.


Pure native reads preserve only a request's already-enabled native session renewal
permission. Automatic request retry remains disabled: the original 401 is retained
as a failed read, and a separately journaled fresh read must establish recovery.
A native opt-out remains disabled. Bids and every request in move/list/bulk
mutation lineages keep both retry and renewal disabled. Native renewal does not
supply balance, participation, ownership or write authority. Its normal UTAS
completion emits only a NATIVE_RENEWAL_RESULT success boolean; no authentication
response, header, token, cookie or EA session identifier is retained. A non-UTAS
notification does not produce that diagnostic. Existing failure streaks,
freshness bounds, stop policy and challenge handling remain in force.


A coherent native bid response can report a competitor's higher price before
independent confirmation. The semantic monitor keeps that command UNKNOWN and
counts neither native success nor confirmed membership. When native/wire status,
exact identities, amount and receipt all establish this specific active outbid
race, it neither increments nor clears the write failure streak. Incoherent or
stale receipts, equal-price uncertainty and native 461/service 403 still count
as failures. Three actual consecutive write failures still stop the runtime.


Controller watched reads include native watch_list coverage: capacity from
Item.getPileSize(INBOX), matched owned-wire/callback/repository counts, and the
native isPileFull result. Closed targets still occupy slots. Initial selection
uses at most the remaining native slots in addition to the original ten-attempt
and50-item pipeline bounds; dispatch revalidates the retained same-scope read.
Missing or contradictory coverage grants no new bid authority. The native bid
boundary also preserves the UI's full-INBOX guard for unwatched targets.
This admission guard does not clear lost targets; durable cleanup remains a
separate maintenance repair required before final operational acceptance.
