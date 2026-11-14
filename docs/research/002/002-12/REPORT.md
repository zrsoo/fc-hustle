# 002-12 final integrated experiment: PARTIAL / NOT FULL PASS

The actual concurrent production run failed closed on discovery page 2. Item 12
is **unresolved**, and the failed window must not be reopened or its budget reset.
No transaction or maintenance branch is claimed complete. No human login or
security prerequisite currently blocks the work; the observed failure is a native
pagination contract mismatch.

The independent live assessor is `tests/check_final_live_00212.py`. It exits **1**
and enumerates every missing requirement. Passing artifact tests establish the
accuracy of this PARTIAL report; they do not constitute FULL E2E acceptance.

## Actual integrated run

The selected, previously consumed item-3 gate was independently validated PASS:
12.0698056 seconds, two genuine pricing GETs, fresh BID/ELIGIBLE decision, zero
bids. It was not rerun. Before starting any actor, all 40 current implementation
regression commands passed: 370 Python tests in 27 suites and 13 Node checks.
Their new recording is `regressions.json`; prior task recordings remain intact.

`live-01/supervisor.jsonl` records the actual process launches and exits. One
broker (PID 9804) owned native dispatch. Acquirer (16244), Bidder (16036) and
integrated maintenance (5560) were separate concurrent Python processes with
bounded cycle arguments. All three recorded a real CYCLE_STARTED. They shared
the existing final-remediation foundation journal, completed quote cache and
account/persona/identity namespace. The actual production extension attached
at epoch 37. None used an in-process actor double or historical research worker.

The experiment opened at 2026-11-14 08:10:58.363884 UTC. The workers launched
at approximately 08:11:21 UTC. All owned processes had exited by
08:11:33.853857 UTC: 35.489973 seconds total, approximately 12.68 seconds of
concurrent worker operation. A 7200-second external supervisor deadline,
1800-request dispatch threshold with a 200-request reserve, finite actor cycles
and a twelve-initial-enrollment bound were armed before worker launch. The first
native service failure stopped the run immediately, well before those ceilings.

Six native commands produced seven actual EA requests. The first discovery
search included one additional metadata request, which was counted as fanout.
Observed command queue waits ranged from 4.007 to 4296.115 milliseconds. There
were zero recorded deadline skips, zero completed Bidder cycles, and therefore
no measured whole-queue monitoring interval. Zero misses in this short window
does not establish the 25-second monitoring target under sustained load.

| Native observation | Actual result |
| --- | --- |
| Bidder watchlist | Authenticated GET, empty returned set; conservative incomplete coverage |
| Bidder and Acquirer credits | 62,127 available coins on both independent reads |
| Complete Transfer List | Five physical entries: two expired unsold and three active |
| Combined capacity | Five occupied + zero pending resale + one preserved unresolved reservation = six |
| Discovery page 1 | HTTP 200; actual `macr=1000`, `minb=11000`, `num=21`, `start=0`; returned rows satisfy the filters |
| Discovery page 2 | HTTP 200, but native result **success=false**, `error=schema_unrecognized` |

The failed command is `5e8c5944b2475c2695307d02f9c6d91a`. It requested logical
page 2, count 21. The captured native wire query used **start=20**; the production
page's existing protocol validation expected `(page-1)*21`, or **21**. This is
the observed contract mismatch, rather than an EA authentication failure. HTTP
200 did not override it. The broker recorded NATIVE_SERVICE_FAILURE; the
supervisor stopped and waited for every owned process. No production pagination
fix or second live attempt followed this failure.

No bid, move, listing, relist or clear was dispatched. One maintenance inventory
read remained WAITING in the mailbox and was never claimed or delivered. Its
durable state is retained; no broker remains to execute it. The old item-3
decision-only reservation was also preserved. No acquisition bid ever existed
for that historical reservation; it was missing from the real watchlist, and
was not relabeled LOST or presented as a new enrolled auction.

## Recovery before launch

This worker reread AGENTS.md, verified its own Windows input desktop, Edge
foreground and official Web App tab, and used normal browser controls. The old
injected page returned incomplete Transfer List coverage. The production
extension was reloaded and the official page refreshed. EA's ordinary sign-in
was completed through Edge's saved autofill and normal Login/NEXT controls,
including repeated normal continuation steps. No credential value, cookie,
authentication header or security challenge was read or exported.

The already-running Python service had loaded its contracts before items 5-11
were implemented. After the extension reload, its stale parser rejected the new
Transfer List coverage fields as `invalid_fields`, despite one successful native
GET returning five rows. This failed read and its diagnostics remain retained.
The existing runtime service was restarted with the current reviewed code,
preserving its database and increasing its epoch. `preflight-05.jsonl` then
captured successful fresh credits, watchlist and complete Transfer List reads,
including the native bulk predicates. Attachment, authentication, completeness
and bulk eligibility were checked separately.

The initial preflight collector also incorrectly required complete watchlist
coverage. That instrumentation requirement was corrected before the live launch:
protocol 2 intentionally uses conservative watchlist coverage, while capacity
and bulk operations require a complete Transfer List. The original failed
preflight files were preserved. These preparation steps did not replay any old
valuation gate or consumed transaction/maintenance research window.

## Missing integrated proof

`outcome.json` contains the exact per-criterion observations and missing proof.
All missing claims are **LIVE-UNVERIFIED**:

- Fresh and cached valuation admission tied to a real acquisition, spendable
  funds at bidding, minimum initial bid, leading HOLD, active outbid, minimum
  rebid, profitable-cap stop, terminal WON and LOST, exact ownership and paid cost.
- Stored-price listing for 3600 seconds, actual one-call expired bulk relist with
  unchanged prices and observed duration, actual one-call sold bulk clear, and
  the associated independent native readbacks. The two observed expired items
  were not relisted because maintenance never reached dispatch.
- Capacity saturation and pause/resume, sticky DRAINING, complete queue monitoring
  cadence, priority under acquisition pricing load, integrated restart/reconnect,
  unknown reconciliation and attributable realized-profit settlement. Current
  native APIs expose no attributable per-sale net receipt; credits deltas or
  projected five-percent tax cannot fill that gap.
- Real newly enrolled-trade status coverage and natural expiry/funds effects.
  Only unchanged 62,127-coin observations were obtained. No timer reset, sale,
  win, expiration event or sample of fifty live auctions was manufactured.

Historical component evidence and all passing offline checks remain supporting
context only. FULL E2E PASS requires every named integrated branch; the strict
validator correctly fails the overall acceptance.

## Evidence and repeatable checks

`evidence-index.json` seals fourteen captured experiment files. Hashes apply
only to captured responses/logs and stopped-state SQLite backups, never to
mutable source, tests, instructions or configuration. JSONL records are
individually chained and fsynced; run/evidence creation is exclusive. The
snapshot/export retains unresolved work, the historical reservation and native
failure diagnostics. No historical sealed evidence was edited.

After shutdown the localhost service was restored to its original read-only
mode. `shutdown.jsonl` records mutations_enabled=false and a Windows process
inventory showing zero actor or maintenance processes. No recurring maintenance
or second executor was left running.

The final behavioral suite passes fourteen tests covering exclusive capture,
evidence corruption, fixture rejection, priority, real child-process termination,
wall/request/enrollment bounds, no blind retry and consumed-state refusal.
Eleven artifact/assessment tests pass, including independent bulk readback
negative cases and the strict validator's intentional nonzero PARTIAL result.
The tracked diff passes `git diff --check`.

| Command from workspace | Purpose | Criteria |
| --- | --- | --- |
| `python tests/test_final_run_00212.py` | Offline supervisor and evidence behavior | 0, 3, 5, 6, 7 |
| `python tests/test_final_artifacts_00212.py` | Integrity and truthful retained failure assessment | 0-7 |
| `python tests/check_final_live_00212.py` | Strict full acceptance; currently exits 1 with exact missing proof | 0-7 |
| `python tests/regression_00211.py` | Current implementation regression, no live replay | 0, 5 |

Any future repair and resumed experiment must preserve this failed checkpoint,
the existing account/journal/cache and consumed budgets. This report does not
claim task completion or authorize an automatic rerun.
