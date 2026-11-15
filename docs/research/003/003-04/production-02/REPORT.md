# Production recovery after the certified withdrawal

The original blocker is resolved. The existing independent withdrawal assessor
was run first against the retained before/after captures; it passed. A separate
read-only projection of the current canonical journal confirmed the certified
withdrawal remains recorded and the 700-coin reservation/queue entry is absent.
The completed withdrawal and the consumed three-read probe were not repeated.
The published repair is `dbc580c56cc5a37768ed41f0c6718369ee78dd57`.

This worker reread AGENTS.md, checked the intended official Edge tab and its own
foreground control, verified the existing read-only service and absence of actor
controllers, and retained consistent backups of journal, cache, control, native
mailbox and transport before changing service authority. The original stopped
run and its evidence remain sealed. Historical Objective 002 remains unchanged.

The read-only service exited before the journal-backed replacement started.
Production used the supported `recover` command with the same context, journal,
cache and state directory. The reviewed extension attached in the verified
official tab. No login was needed; no credential or EA session material was
accessed. Current foreground evidence is in `browser-recovery.jsonl`.

New run: `956a2d483cf70c2d440709ed20a312fe`, owner epoch **69**, actor runtime revision
`dbc580c56cc5a37768ed41f0c6718369ee78dd57`. Startup issued three new official native
GETs under the new fences and independently reconciled zero commitments, credits
and the complete five-item Transfer List. RECONCILED is control sequence 81;
READY is sequence 82. Supervisor, watchdog, executor, Acquirer, Bidder and
maintenance then operated together. There is no artificial run/cycle/request or
new-enrollment cap and no four-hour shutdown timer.

The first strategy-led enrollment had stored resale 5100, legal cap 4300 and
minimum initial bid 800 above a competitor's 750. Genuine native watched reads
proved leading HOLD. A natural outbid led to the smallest legal 4000 rebid with
its own native response and independent leading readback. A later higher bid
caused OVER_CAP without another bid. A distinct closed/outbid read proved LOST;
the reservation was released through the ordinary reconciliation path. No auction
outcome, coin debit/refund or capacity change was manufactured for coverage.

The persisted watchdog samples include native counts, actor progress, queue and
priority data, credits/freshness, all capacity components, intents, maintenance
and supervision leases. The separate exporter was tested before starting and
published as `8be94c6`. It adds no EA polling and never replaces the watchdog or
owns actors. It exports the five databases every 300 seconds and at stop, uses
fresh output directories, and requests a controlled stop on collection failure.
Adding this previously absent read-only observer did not edit or restart any
running actor/monitor/executor process. Its launch metadata is
`exporter-launch.json`; captures/events are under
`private-captures/continuous-evidence/00304-production02-periodic/`.

An independent retained-evidence review at 22:21 UTC on November 15 verified 12
cases: discovery pagination, fresh pricing, native legality/admission, minimum
initial bid, leading HOLD, natural outbid/rebid, cap stop, LOST, occupancy and
reservations, priority/cadence, normal no-op/rejection, and identity/freshness.
The 22:19 capture contained about 513.56 healthy monitored seconds. This is a
checkpoint observation, not a claim of four hours or current total runtime.

Cached pricing, WON/ownership/listing, sold clear, expired relist, capacity
pause/resume, sticky DRAINING, successful reconnect/restart, uncertain-result
reconciliation, unrelated browser activity and lost supervision still require
their own complete live evidence at this checkpoint. They remain
LIVE-UNVERIFIED in `live-coverage-matrix.json`; missing natural cases do not stop
production. The reviewer does not promote old failed callbacks, offline doubles
or a generic successful GET into branch coverage. Realized profit stays DEFERRED.

The current evidence index selects this run and its latest completed periodic
capture. It retains separate run/revision mappings and the resolved original
incident, including certified-withdrawal proof, actual 879-test regression output,
publication provenance and independent new startup read IDs. The original
startup index/report/incident/captures are unchanged.

The acceptance assessor now understands live capture boundaries: an unexpired
WAITING/CLAIMED command may be in flight while copying databases; failed or
UNKNOWN deliveries are still rejected. Startup's process-creation grace is
excluded from fully observed actor time. A temporarily prepared journal intent
counts only when the later sealed journal independently records reconciliation;
overdue/unresolved intents still fail. Native initial bids can correctly be one
legal tick above an existing competitor bid. Behavioral tests cover each of
these distinctions and preserve all initial stopped-episode tests.

Current offline validation: 23 acceptance behavior/artifact tests and five
exporter tests pass. Full live acceptance still exits 1 / INCOMPLETE for the
four-hour requirement and remaining LIVE-UNVERIFIED cases. Reproduce with:

```text
python tests/test_00304_live.py
python tests/test_00304_exporter.py
python tests/check_00304_live.py
python tests/review_00304_cases.py
```

`review_00304_cases.py --write` explicitly updates only the mutable current-run
matrix and creates a new unique review receipt from sealed native/transport
evidence. It sends no EA request and never stops for missing events. Continue
supervised operation and inspect incidents; do not report the task complete until
all original criteria genuinely pass. Stop/status controls remain
`python -m fc_access.continuous_v1 stop` / `status`. Any later controlled stop,
runtime repair or supervision gap must retain this segment and begin a new healthy
segment after independently reconciled recovery, without replaying old commands.
