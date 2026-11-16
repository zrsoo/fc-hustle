# 004-04 implementation and verification

Lifecycle, verified resale, sequential bulk maintenance and conservative recovery
are implemented through ControllerStore authority. New state starts STOPPED;
imports start nothing. The explicit CLI and Python API are documented in
`fc_access/controller_v1/README.md`. No full account controller lifecycle,
legacy actors or recurring production job was launched for this task.

Controller dispatch now checks durable lifecycle before queueing, claiming and
after pacing. Pause/stop withdraw queued work and drain the serialized executor;
stale owners cannot dispatch or control a successor. Run acquires the existing
canonical account/native/port process guards and the isolated controller guard.
The local service supplies status/pause/stop and cannot start lifecycle activity
or create trusted intent. Saved status uses a read-only SQLite connection and
survives service shutdown. Run is always explicit, including after pause.

`work.py` composes native pricing, the existing schema 2 move/list/bulk commands,
the production bulk classifier/parameter constructor and extracted pure production
resale/bulk effect assessors. Legacy actor loops and their global uncertainty gates
are not imported. The assessors remain callers of the legacy resale/bulk paths;
their negative and process-crash regressions pass. The reviewed page's controller
entry now admits those four existing operations under current preconditions and
one-shot native queue cleanup, preserving ordinary legacy entry behavior.
ControllerStore separately requires exact durable work intent before dispatch;
an HTTP flag or a schema 2 mutation alone supplies no authority. Schema 2 bidding
remains forbidden on this service.

Wins require closed/highest, expired terminal proof, exact physical item/version,
tradeability, actual owned last-sale cost and a matching dispatched bid. The
controller rechecks a fresh full watched win, ownership, complete capacity,
current native caps and reciprocal native ticks before move/list intent and claim.
Stored BIN, one native tick below and 3600 seconds are immutable command policy.
An acknowledgement never accounts for a win. Independent exact item/new trade,
unchanged prices and dispatch-anchored expiry prove listing. Pending ambiguous
wins remain visible and retain membership; unrelated urgent management continues.

Urgent exact status/rebids/readbacks precede resale and maintenance. Every managed
cycle obtains a complete maintenance scan; acquisition and resale also provide
inventory observations. Verified sold clearing runs on detection. The durable
3660-second relist deadline advances before I/O and never catches up in a burst.
Verified clearing precedes relisting when both are needed. Bulk readback requires
all affected manual items, unchanged unaffected entries, and unchanged prior
prices with observed 3600-second duration. Unknown/incompatible generations
remain consumed, with sticky incompatible evidence. Disjoint later work can run;
adding targets to a bulk set cannot disguise replay of consumed generations.

Recovery preserves batch candidates, quotes, confirmed members, all command
tombstones, work intents/effects and relist deadline. Unfinished intents and
unconfirmed acknowledgements become explicit UNKNOWN audit records. No saved
command is executable recovery work. Submitted bulk/resale records support only
independent readbacks. Reconnect loses native mappings and requires new full
watched evidence plus exact linked status. A missing row, elapsed final auction
timer, full/unknown inventory or missing paid ownership cannot establish loss,
free capacity or authorize a write.

The new behavior suite covers each acceptance criterion with positive/negative
cases. Actual OS workers terminate at before/after intent, dispatch claim, native
effect, lost reply, readback, confirmation and phase transition boundaries for
bidding, move/list and sold clearing. A separate synthetic server ledger survives
the controller process, so write counts and membership are checked independently.
Native VM tests execute the shipped page/worker. Fixtures use temporary databases,
unique owners, synthetic public scope and prohibited network sockets. IPC tests
bind port 0 and reject every destination except their allocated loopback port;
they cannot attach production service, state or persona. Captured exception
canaries do not enter restart-readable diagnostics.

`live-contract-review.json` records the finite live-evidence decision. Native
bid/rebid methods, write arguments, move/list operations and zero-argument bulk
APIs are unchanged, so no additional account probe is required by this local
authority/persistence change. Existing genuine ten-ID read-only controller proof
and consumed historical bulk windows are independently revalidated. New authority
resale/bulk composition is verified offline, not promoted to new live transaction
proof. Historical active-rebid/new-authority limits remain explicit; the full
integrated lifecycle and continuous cutover remain deferred to the hands-on user.
No external challenge/market limitation was encountered because no new live
window was opened. Budgets were not reset and no sealed evidence was changed.

Acceptance mapping is in `acceptance.json`. Supervisor validators run independently
from the workspace and never hash mutable source, tests, instructions or config.
The historical evidence readers retain sealed response/log integrity checks.

Final verification: nine independent commands passed, covering 106 Python test methods plus their native VM checks and 38 actual process-interruption windows. `verification.json` records argv, exit codes, durations and retained output. `final-cleanup.json` records the final local observation: no FC production workers and no listeners on 8783/8784. No new live window or full lifecycle was started.
