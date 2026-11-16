# Bounded exact-status integration and continued production recovery

The usage interruption is over. This same worker reconciled actual process and
database state before repeating any work: no production actor or native service
was running, the old two segments remained stopped, and the actual 950-coin bid
was already RECONCILED by the explicitly authorized operator-loss procedure.
Current queue and local reservations were both zero. That operator outcome is
not retroactively labelled native proof. No completed withdrawal, confirmation,
bid, probe window or previous owner was replayed.

The unfinished repair was preserved and completed. `known_status.observe` first
validates the original fresh watched response against its native adapter. If the
exact trade is absent, it issues exactly one serialized, paced `status` read
using the retained trade/item/version and current full fences. A conflicting
full row never authorizes this fallback. Empty, changed physical identity,
explicitly different version, stale or unavailable results remain unresolved.
Expiry or watched absence alone never becomes LOST.

Both `Bidder.cycle` and startup reconciliation now invoke that path. A genuine
fresh closed/outbid status can settle the original intent without replay. The
lite endpoint may omit version 0/null: a copied interpretation uses the existing
scoped journal identity, records `native_version_observed=false`, and leaves the
captured native response unchanged. The account/context/fence checks and physical
identity match still apply. An unsuccessful lookup retains the commitment and
enters the existing controlled-stop/gating path.

An active leading status permits HOLD and independent reconciliation. Lite data
alone grants no new bid authority: rebidding still requires a fresh full watched
observation under the write lock, normal native minimum tick, stored cap, fresh
funds and all admission guards. PENDING is not WON; terminal current bid and
independent full owned physical item/actual paid-cost proof remain mandatory.
Resale's full fresh write preconditions remain in force. No pricing, reserve,
capacity, listing-duration, maintenance, pacing or production-lifetime rule was
relaxed.

All affected runtime processes and the old read-only service had exited before
source changes. `pre-repair.json` records that check; `backup.json` records five
consistent SQLite backups. Git remained at the published operator resolution
`6cd9160` during offline work. The six older dirty 003-02 receipt files were
preserved separately and excluded from this repair.

Nine focused behavioral regressions exercise the actual actor/startup integration
with native doubles: terminal loss with one exact read and no replay, fresh
startup reconciliation, leading HOLD, conservative status-only outbid handling,
empty/wrong-item/wrong-version/stale rejection, no expiry-only inference, full-row
conflict rejection, and owned physical/paid-cost requirements. These are offline
tests and contribute no live time or native case coverage.

The first full run is retained in `checks/`: 910 tests, five errors. The generic
actor fixture did not model the newly exercised status operation, returning an
invalid success that stranded its synthetic transport claim. The fixture now
models the bridge's explicit `known_identity_unavailable` local rejection with
zero native requests. The positive fallback double supplies its own valid native
status response. No production invariant or pre-existing assertion was weakened.

The final full discovery passed **910 tests, zero failures/errors**, in 340.012
seconds (see actual log for the exact measured test duration and runner receipt).
`checks-final/result.json` retains argv, exit, test count and completion time;
`checks-final/stderr.txt` retains the complete log. All **27 Node suites** passed
in the separately retained first batch. Production runtime code was unchanged
between that Node batch and the final Python run. Source, test, instruction and
configuration digests are not acceptance gates.

Browser recovery reread AGENTS.md and verified this worker's own Edge foreground
and intended official tab. A fresh Web App document was loaded so the published
selector-retention page implementation can be injected, instead of reusing the
old frozen closure. The ordinary login flow required repeated Login/Next steps.
The public EA ID was rejected by an email-only form; the worker then selected the
single designated zzorniss option through Edge's normal saved-account autofill
UI and used normal Next/Sign In controls. It read/copied no credential field
values, exported no auth/session material and bypassed no CAPTCHA/2FA/security
challenge. At 01:17:50 UTC on November 16 the application Home control was visible.
Browser attachment, authenticated persona and actual market/native-read success
will be verified separately before enabling new production work.

This repair and a resolved blocker do not complete 003-04. After publication,
fresh independent reconciliation must precede a new owner and healthy segment.
The same canonical context/journal/cache/control/native databases remain in use.
Prior native-proof gaps, stopped elapsed time and counters stay intact. Four
consecutive healthy monitored hours on the final runtime revision and every
required genuine live case still need evidence. Missing natural events remain
LIVE-UNVERIFIED and require continued supervised operation, never manufacture or
blockage solely for absence of an event. Persistent watchdog and periodic export
ownership must accompany any continued run.


## Fresh continued production segment

Publication of actor revision `3153be359145d71f72fcbe90340904a3a6309716`
was independently verified against remote main before new account reads. The
fresh read-only probe used three new IDs at epoch 73, all native GET 200, with
62,827 coins, five complete physical Transfer List identities matching the prior
independent probe, and zero unresolved commitments. It started no actors or
mutations. Normal saved-login UI boolean outputs were retained from original
orchestrator events 495460/495487/495499/495509 without any credential values.

The read-only service exited before the journal-backed service started. The
actual prelaunch process scan contained no production controller. The new run
`9bdb55697d3658b11f01f99a495b94f6` opened at 01:25:56 UTC, attached under epoch
75 and reached READY after independent reconciliation at 01:26:03 UTC. The
canonical journal, cache and control/native stores were preserved. Actual
strategy bids and a maintenance bulk relist have native results and separate
readbacks. The watchdog supervises all three actors, the executor and supervisor.
The exporter persistently captures local status each minute and five consistent
SQLite stores each five minutes. No account-lifetime cap or scheduled shutdown
was introduced.

The mutable current index and matrix now select this run. Frozen earlier episode
indexes, captures, counters and incidents remain unchanged. A separate resolved
incident document points to the user's explicit operator-loss authority and
new restart reconciliation. It continues to say that the old950 terminal outcome
has no historical native proof and no refund is inferred. Acceptance checks join
the actual immutable operator audit row, retired command and slot; a prose
resolution cannot substitute for them.

Auditor changes support the real normal UI login and its independent authenticated
readbacks, bind diagnostic commands to their actual historical runs, check the
new prelaunch scan, and retain native terminal reconciliation as independent bid
proof. The minimum-bid case accepts an independently observed subsequent outbid
of the same physical identity; it does not require catching an earlier highest
state before another bidder acts. A post-bid selector case requires an actual
native bid, an omitted exact identity in a distinct watched read, and a successful
native exact-status branch. An unrelated generic GET cannot satisfy it.

A separate local-only review watcher consumes new sealed exports, checks structural
findings against unexpired capture boundaries or proven unsent read cancellation,
updates the current matrix using case-specific native predicates and retains
immutable numbered acceptance/coverage receipts. It makes no EA calls, controls
no actor and never stops for absent events or four hours. Six audit regressions
include negative saved-login/operator/native identity cases and prove that the
watcher keeps running both while events are missing and after a four-hour PASS;
only a real sealed runtime stop or owner change ends it. The focused final batch
passed 47 tests (27 acceptance, 6 continued evidence, 9 fallback, 5 exporter).

At the 01:31:18 native capture, 315.18 monitored healthy seconds were retained;
subsequent local monitoring continued without incidents. This is not four hours.
The full acceptance check still exits 1 for required elapsed time and unobserved
natural cases. Production remains active; no missing event is labelled a human
blocker or manufactured to produce PASS.
