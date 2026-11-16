# Bid registration receipt repair

Status: **OFFLINE PASS; live verification has not started**.
This repair does not complete Objective 003 or reinterpret any old bid as accepted.

The backup in `backup.json` preserves six consistent SQLite databases and the
pre-existing working tree. `checkpoint.json` and `RESUME.md` describe the pending
work and the single authorized live budget. Starting main was `148d9a4`.

The reproduced defect is in the bridge/adapter acceptance contract. FC27's DAO
can retain HTTP success with zero generated auction items and mark its input
stale. The Item service can still return success and an itemIds array derived
from its input. The old page accepted those flags; Python converted them to
ACKNOWLEDGED. The captured historical wire bodies were not retained, so this is
an executable false-positive path, not a reconstruction of Alvarez/Doue's exact
server responses. The earlier diagnosis and synthetic reproduction are in
`../production-03/ack-diagnosis-01/`.

The repaired page still invokes `services.Item.bid(raw, amount)`. It observes the
existing `transfersDao.bid` subscription, keeps the same observable and callback
ownership, and restores its temporary hooks in finally/timeout paths. It binds
the private URL trade selector and the sole `{bid: amount}` body before send;
wrong target, amount, extra body keys and duplicate sends are blocked. The input
DTO's current identity/state must still match the retained fresh read.

Only safe evidence leaves the page: pseudonymized identities, numeric amount,
HTTP status, wire/native item counts, numeric error code, a reviewed public error
enum name, input stale marker and a matching auction projection. No credentials,
headers, auth delegates, session values or raw response bodies are retained.

`result.bid_receipt` schema 1 separates ACCEPTED, REJECTED and UNCONFIRMED.
ACCEPTED requires one actual matching returned auction and account participation,
not service itemIds. A prior outbid row cannot acknowledge a rejected rebid.
Empty HTTP 200, stale, none, unknown errors, missing receipt or contradictory
success/error remain unconfirmed. REJECTED requires a matching authenticated
4xx wire response and matching reviewed native error, with no accepted item.
Numeric EA error codes are resolved against the loaded public enum, not guessed.
A zero-EA capability check rejects an older injected page before a bid intent.

Active Store, broker, scheduler and adapter boundaries require the receipt;
archival parsing remains compatible with sealed old envelopes. Safe receipts
are stored in an append-only journal table. Native acceptance still needs an
independent fresh readback before reconciliation. A proven rejection also waits
for independent fresh exact status and funds. A rejected opening releases its
tentative slot without inventing LOST; a rejected rebid retains prior verified
participation/capacity. The broker/watchdog permit that validated ordinary
rejection. Unknown results still stop. The Bidder does not dispatch another bid
in the cycle that reconciles a rejection.

The operator non-registration seam appends the user's new assertion, separately
from native evidence. It refuses conflicting verified participation, ownership,
resale or inventory. It preserves the prior Doue operator-loss audit. It claims
neither an EA rejection nor a refund, and grants no replay authority. No such
amendment has been applied yet.

The finite `fc_access.actors_v1.verify_bid_receipt` harness runs one real
Acquirer cycle through Foundation, then independently reads watched/status and
credits and reconciles the exact command. It permits at most one bid, 16 actual
EA requests including metadata, and 64 local helper commands, and forbids other
mutations. Claims/budgets are fsynced before dispatch; exclusive attempt creation,
reserved interrupted operations and duplicate-command checks prohibit replay.
Its synthetic E2E test reports OFFLINE_PASS, never a live PASS.

The first full discovery is retained in `offline-01`: **916 tests, 3 failures,
9 errors**. `offline-01/failures.json` names every failing test/setup class and its
root cause. The adapter fixture supplied a superseded generic ACK; it now models
the receipt and local capability honestly. All other failures came from archived
suite inventories being compared to today's file glob. The 002-11 validator now
uses its reviewed historical command catalog; the 003-01 baseline uses the test
filenames at its recorded Git boundary. Neither enforces implementation bytes.
The sealed reports/results were not regenerated. New test runners still execute
the current complete inventory. All **28 Node suites** passed in that first batch.

Earlier focused runs found an invalid rebid fixture that called new-enrollment
admission again, invalidating the old cap object; it now follows the production
rebid path. Two finite-harness negative assertions expected a raw guard error
through a scheduler which deliberately wraps delivery failures as TimeoutError;
they now test the actual bounded guard directly while retaining the complete
actor/Foundation E2E test. One initial misspelled test selection ran zero tests
(exit 1); the corrected Foundation command ran all 16 tests successfully.
Final focused receipt coverage passed 11 tests, finite harness 3, and the broker/
watchdog ordinary-rejection test 1 before final discovery.

No new actors, recurring jobs, strategy changes or historical command replay are
part of this repair. The existing six dirty 003-02 receipt files and review.lock
are excluded from this remediation's commits.

Final full-suite results, publication, production amendments and the uniquely
identified live attempt will be appended after they actually occur. Until then
the live claim remains **NOT VERIFIED** and no orchestrator recheck is authorized
by a test fixture or an HTTP-only acknowledgement.

The second full run (`offline-02`) ran **937 tests with three failures and zero
errors**. All 28 Node suites and all five independent validators passed. The
three exact failures are in `offline-02/failures.json`: two operation-inventory
assertions omitted the new zero-EA capability helper, and the dependency test
caught the experiment runner inside the primitives layer. Tests now assert that
the helper makes zero requests and occurs only at the permitted bid; the finite
runner moved to `fc_access.actors_v1.verify_bid_receipt`. All three affected tests
and the three harness tests passed before full discovery was rerun.

Both local operator amendments have now been applied under stopped-account,
supervisor, executor and bid locks. The native mailbox had no WAITING/CLAIMED
work. The exact identity/amount checks passed for both historical commands. Each
amendment returned RESOLVED / NOT_REGISTERED / native_outcome_verified=false.
`operator-ff4174653771149736e63b1ac12630f9.json` retains the prior-loss clarification;
`operator-6b3faed8a418890da8147b59eae039fc.json` retires the unregistered opening's
local commitment. All previous journal/proof records remain. Neither command was
sent again; no refund, EA rejection or native terminal loss was asserted. There
are no unresolved journal bid commands after the two amendments.

Final offline run `offline-03` passed **937 Python tests, zero failures/errors**
in 347.066 seconds. Command: `python -m unittest discover -s tests -v`.
All **28** current `tests/*checks.cjs` suites passed via `node <suite>`.
The five independent commands also passed:

- `python tests/validate_00203_gate.py --attempt 20261114-adapter-repair-gate-06`
- `python tests/validate_00203_stop.py --attempt 20261114-adapter-repair-gate-06`
- `python tests/validate_adapter_repair.py`
- `python tests/check_bulk_blocker_recovery.py`
- `python tests/check_00301_baseline.py`

`offline-03/results.json` records every exact argv, exit and elapsed time; paired
numbered stdout/stderr files retain complete output. `git diff --check` passed.
The repair is ready for its single authorized live verification. Neither old
command was replayed. No new EA operation has occurred during this repair so far.
The code/report are published before the reviewed bridge is deployed live.
