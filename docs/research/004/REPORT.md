# Objective 004 implementation handoff

IMPLEMENTATION COMPLETE — FULL CONTROLLER E2E PENDING

Required offline verification passed with zero failures/errors/skips. Full
controller E2E remains deferred. Publication details are recorded below.

## Architecture and reuse

`fc_access/controller_v1/` encapsulates the new mode. `controller.py` owns finite,
sequential acquisition/management steps; `config.py` validates policy;
`journal.py` records policy progress; `store.py` owns durable dispatch authority;
`protocol.py`, `adapter.py` and `executor.py` provide fenced, serialized delivery;
`work.py` handles wins and maintenance after urgent auction work. `server.py`
serves local transport/control, and `__main__.py` is the explicit operator entry.
Imports and construction start no account worker. A new lifecycle is STOPPED.
ACQUIRING and MANAGING are the only operational phases; RUNNING, PAUSED, STOPPED
and HALTED are separate lifecycle states. No actor or maintenance subprocess is
started by this mode.

Actual reuse and shared callers:

| Mechanism | Imported implementation and current callers |
| --- | --- |
| Exact-version pricing | `production_v1.pricing.PricingService`, `price_cache.QuoteCache`, `prices.PriceService`/`CardKey`, `contracts.Search`; used by the controller through its shared serialized native reader. Existing Foundation/actor pricing callers retain their policies. |
| Native legality | Existing native caps, above/below helpers and minimum-bid rules; the controller prices once per exact version and preserves stored quotes/caps. |
| Safe contracts/receipts | `production_v1.contracts` parsing, scope/field/time helpers and `bid_receipt` shape/validation; schema 4 adds explicit batch/status/bid authority instead of relaxing legacy schema 2. |
| Loopback and ownership | `production_v1.executor.EdgeExecutor`, `production_v1.server.Handler`, `actors_v1.locking.process_lock`, `foundation.scope_for`; canonical account/native guards match `continuous_v1.runtime.account_locks`. No legacy runtime loop is invoked. |
| Physical move/list effects | Extracted pure `production_v1.resale.assess_effect`, called by both `Resale.reconcile` and `controller_v1.work.Work.reconcile`. Legacy actor acquisition/bidder win handling and `continuous_v1.recovery` still call `Resale`. |
| Bulk effects | Existing `production_v1.bulk.classify`/`parameters` and extracted pure `assess_effect`, called by `BulkTransfer.reconcile` and `Work.reconcile`. Existing `Foundation.bulk`, actor sold/relist, bulk recovery and continuous recovery callers retain their admission/reconciliation rules. |
| Reviewed extension | `browser/production-v1/worker.js` loads `controller.js` before `page.js`, routes schema 4 explicitly, and selects the narrow new-mode schema 2 read seam only for the controller service. Legacy page/worker/bulk callers retain schema 2 admission, receipt and uncertainty behavior. |

The shared Python changes extract effect assessors without changing their
business predicates. The shared page adds a private controller factory and a
controller-only lite-null projection; it does not expose native selectors.
Queue-object ownership follows the actual official request through send/XHR;
unrelated UI traffic remains sanitized diagnostics and cannot replace a missing
owned request. Endpoint, body, identity, authentication, context and document
fences remain mandatory. Timeout/rejection/interruption/late callback tests
exercise hook restoration and no replay. New-mode read failures quarantine their
own work; legacy page poisoning and unresolved-command gates remain unchanged.

## Implemented policy

One genuine credits observation admits each acquisition batch only above the
configurable default 40000 coins. At/below threshold durably HALTs; failure is no
admission. There are no credits reads in the initial bid burst or MANAGING. The
single discovery page uses PC players, page 1/count 21, maxBid=1000/minBuy=11000.
Selection requires more than 60 seconds after subtracting genuine observation
age. At most ten distinct initial attempts and ten independently confirmed
members belong to a batch. Native minimum legal amounts must remain within the
stored profitable cap. No sum-of-caps funding allocator is added; later EA funds
rejections are ordinary operation outcomes.

Imported pricing retains its two-search exact-version minimum valid BIN method,
600/10000 exclusions, second maxb=first_min search, 86400-second completed-cache
TTL, diagnostic-only comparable last_sale_price, 5% tax and X=500. Completed cache
hits issue zero pricing searches. Physical Transfer List and known combined
pipeline capacity remain 50, including manual/sold/expired entries and known
pending wins. Unknown/incomplete inventory supplies no capacity authority. A
complete inventory may be shared within the same scope/document for at most 30
seconds and is invalidated by known mutation or established external change.

Status confirmation uses exactly the requested retained set (one to ten native
DTOs in one official status/lite GET), not another market search. HTTP success
and input-derived itemIds are insufficient. Independent highest/outbid evidence
admits management. Missing rows/countdown expiry alone never prove loss. Original
lite 0/null remains unchanged; a separate full-read/current-DTO link can support
new-mode authority. Conflicting identities, duplicates, unexpected rows, lost
mappings and stale fences fail closed.

MANAGING targets five seconds, orders actionable rebids by deadline and performs
all requests sequentially. Slow cycles record missed targets without overlap or
catch-up. Highest/cap-exhausted auctions remain observed. Verified terminal wins
require physical ownership and paid-cost proof before move/list. Listing uses
the stored BIN, one native tick below it, duration 3600. Sold clear and the
3660-second expired-relist tick reuse independently verified effects; relist
retains prices and one-hour duration. Empty/rejected batches immediately allow
another acquisition with its own credits read and central pacing. There is no
legacy ten-minute timer, DRAINING phase or one-bid exit. Request spacing defaults
to two seconds; this is a configurable policy, not a proven EA minimum. Local
price helpers consume no EA request slot.

## Persistence and compatibility

Controller state uses a separate SQLite WAL database with synchronous FULL.
Legacy-shaped databases are rejected; no live migration or mutation of legacy
state was performed. Selected identities, quote/cap, original observation times,
deadlines, decisions, intent, claim tombstones, results, membership, transitions,
work and metrics persist. Trusted Python admission APIs are absent from HTTP;
request flags cannot enable writes. The standalone transport CLI is read-only.
Transactions commit intent and permanent consumption before network I/O; no broad
account/data lock or write transaction spans a native call.

Ambiguous commands remain queryable UNKNOWN outcomes and are abandoned, never
silently relabeled REJECTED/LOST. Restart/reconnect cannot replay them, even under
a new batch/decision ID. Confirmed membership survives an uncertain rebid. Fresh
independent observations may support distinct later actions. Reconnection needs
new current-document full mappings and increasing owner fences. Pending physical
wins and ambiguous resale remain accounted work; unrelated urgent decisions can
continue. Pause/stop persist withdrawal, invalidate queued work, drain the one
in-flight call, exit the run process and release guards. Saved status reads use
SQLite read-only mode and do not construct a live controller.

The pre-task working tree backup is recorded in `004-05/preservation.json`.
Its integrity inventory covers 2415 pre-existing research captures/receipts/logs;
source, tests, instructions, SQL design and editable Markdown are excluded from
hash enforcement. Existing sealed capture validators remain active. Historical
Objective 002 BLOCKED/PARTIAL and Objective 003 PAUSED / task 003-04 RECONCILING
under its paused parent are checked through read-only application projections.
Their orchestration records and evidence were not edited.

## Verification commands, counts and results

| Group | Tests (Python) / commands (others) | Result | Wall seconds |
| --- | ---: | --- | ---: |
| python | 1049 | PASS | 460.347 |
| node | 33 | PASS | 12.761 |
| independent | 9 | PASS | 11.015 |
| targeted | 4 | PASS | 10.056 |

The full discovery executed 1049 tests (1032 unique IDs; existing imported test
classes account for 17 repeated executions). unittest measured 459.700s; the
recorder measured 460.347s including process startup/teardown. All passed without
skips. The targeted group ran 13 Python methods plus the design artifact check
across four commands after final gate improvements; these are additional
regressions, not extra unique whole-suite coverage. Every receipt stores exact
argv, exit code, elapsed seconds and stdout/stderr. `{python}` denotes the Python
interpreter running the recorder.

```powershell
python tests/record_00405.py python docs/research/004/004-05/python-02
python tests/record_00405.py node docs/research/004/004-05/node-01
python tests/record_00405.py independent docs/research/004/004-05/independent-02
python tests/record_00405.py targeted docs/research/004/004-05/targeted-01
python tests/check_00405.py
python tests/test_00405_handoff.py
```

Recorder output directories are exclusive: use a new suffix for a future run;
never overwrite these historical receipts. The Python command is the entire
`python -m unittest discover -s tests -v` suite. Node discovery runs every current
`tests/*checks.cjs`, including all three controller suites. The exact 33 argv and
their outputs are in `004-05/node-01/results.json`.

Independent commands (all read-only/offline):

```powershell
python tests/check_00401_artifacts.py
python tests/check_00402_artifacts.py
python tests/validate_00203_gate.py --attempt 20261114-adapter-repair-gate-06
python tests/validate_00203_stop.py --attempt 20261114-adapter-repair-gate-06
python tests/validate_adapter_repair.py
python tests/check_bulk_blocker_recovery.py
python tests/check_00301_baseline.py
python tests/check_00302_production.py --prepublication
python tests/validate_bulk_transfer_evidence.py
```

Production evidence readers intentionally retain older incomplete live verdicts;
the deferred 003 soak/004 full lifecycle is not required to pass historical live
acceptance. The offline tests verify that those readers continue rejecting
unfulfilled live claims. Full current discovery is separate from historical
receipt catalogs. `check_00405.py` matches every actual passed Python method to
current unittest discovery, rejects omissions/skips/failures, verifies the current
Node/independent command inventory, genuine sealed ten-ID evidence, preservation,
report/contracts, stopped activity, tracked main commits and remote ancestry.

Behavior includes illegal/stale/wrong identity and authority, failed persistence,
claimed/unknown/late/restart no-replay, rejected/funds-limited bids, incomplete
capacity, expiry/price changes, missing terminal rows, bad physical cost/listing
readbacks, native request attribution/hooks, one-at-a-time execution and lifecycle
withdrawal. The process suite exercises 38 actual abrupt-interruption windows
against isolated synthetic side-effect ledgers. New handoff negatives reject
missing/extra historical suites, skipped/failed current suites, invented live
PASS, absent limitations/evidence/risk/CLI text, active jobs/listeners/workers,
dirty/non-main/unpushed publication, and failed pushes. All nine task criteria
have named checks and negative cases in `004-05/handoff.json`.

## Failures and fixes

The retained first full run (`004-05/python-01`) executed 1043 tests in 463.060
wall seconds and failed with one ConnectionAbortedError in the market-discovery
transport security fixture. The server correctly denied headers before reading
the request body; Python's separate header/body sends raced with the HTTP/1.0
close on Windows. `tests/http_fixture.py` now sends the unchanged finite request
in one write. The test still asserts the actual denial status/body and retains
every hostile-origin/host/route/schema case. A separate negative proves one send,
exact duplicate-key JSON/body/headers, and propagation of a transport error.
No retry, assertion suppression or fake response was introduced. The targeted
four-test transport suite passed after this fix.

The first independent run (`004-05/independent-01`) failed the old 003-02 checker
because its sealed 27-suite Node receipt was compared with today's expanded
directory. `historical_00302_suites.py` now records that reviewed historical
inventory; `record_00405.py` still discovers all 33 current suites. Negative cases
reject missing/extra/failed historical commands. The final nine independent
commands pass. No historical receipt, command log or verdict was rewritten.

Earlier implementation repairs and their original evidence remain in the
004-02/03/04 reports: persona alias assumptions, independent lite/full native DTO
linking, cheapest legal same-version representative, preserved HALTED reason,
terminal owned-item authority, and scoped read timeout cleanup. This final task
made no new native wire-contract change and found no outstanding essential
implementation defect. Initial handoff-validator development also exposed a
reused mock HTTP client state and shell-pipe Unicode conversion; the negative
test now constructs a fresh connection and the manifest uses explicit UTF-8.

## Timings

Wall-clock suite/command times are in each receipt, not inferred from test counts.
Node: 33 suites, 12.761s total. Independent: nine commands, 11.015s total.
`004-05/synthetic-trace.json`, freshly recomputed by
`python tests/record_00403_offline.py docs/research/004/004-05/synthetic-trace.json`,
is explicitly SYNTHETIC_OFFLINE_ONLY: ten acquired, ten rebid, ten independently
settled LOST, then threshold-equal HALT. It records two credits, three searches
(one discovery/two pricing), one caps, one watched, three Transfer List, twenty
bids and four status_batch requests. Maximum parallel requests is one.
Synthetic acquisition/burst/handoff are 34.01/20/2 seconds with zero expiry misses
in that trace. Management cycles are 26 seconds/five missed targets and four
seconds/zero missed targets. These virtual-clock measurements are reproducible
policy evidence, not claims about current EA latency or full E2E performance.
Expiry-miss negatives run separately.

## Probe review, evidence classes and cleanup

004-05 budgets: zero EA requests, zero account mutations, zero new live windows.
No browser login/refresh, extension attachment or temporary account service was
needed for the offline catalog/fixture repairs. Prior checkpoints were reused
only as read-only evidence. No consumed operation/window was reset or replayed.

The genuine new-mode live contract evidence was captured in 004-02, not this
final verification task. Each window reserved its budget durably before delivery;
`status-array-06/checkpoint.jsonl` and its read-only transport DB independently
support the selected result. One fresh watched GET retained 19 full rows, one
exact-target status/lite GET requested/returned ten real closed/outbid pairs with
zero omissions, and a second forced watched GET independently agreed. HTTP 200
alone is not the proof: exact request/response identities, timestamps and genuine
personal states are compared. Original lite definition 0 is preserved with
separate full-version/current-DTO links.

| Prior window | Reserved / actual EA GETs | Precise outcome |
| --- | --- | --- |
| status-array-01 | 0 / 0 | External attachment/login limitation; no successful market check. |
| status-array-02 | 1 / 0 | Persona-display-name guard implementation defect; repaired later. Its original EXTERNAL_LIMITATION label is retained as historical evidence, not promoted to PASS. |
| status-array-03 | 1 / 0 | Case-normalizing the same invalid alias assumption did not fix it; repaired later. Original historical label retained; no successful check. |
| status-array-04 | 3 / 3 | Genuine ten-target one-GET proof after repair. |
| status-array-05 | 3 / 3 | Distinct bounded authentication/admission retest. |
| status-array-06 | 3 / 3 | Distinct bounded final native DTO-link retest. |
| Total | 11 / 9 | Zero mutations across all six windows. |

Individual current contract classifications (details and exact paths/checks in
`004-05/handoff.json`):

| Contract | Classification and genuine evidence | Live limit / decision |
| --- | --- | --- |
| status_batch | LIVE_VERIFIED_WITH_ACTUAL_LIMIT: selected 004-02 ten-ID window, independently revalidated offline. | Ten closed/outbid targets, one GET, no omissions; live active/null/error branches not induced. |
| attribution | OFFLINE_VERIFIED_LIVE_LIMITATION: shipped queue/XHR ownership code and negative interleaving tests; bound genuine status GET. | Deliberate manual/background interleaving and timeout remain offline-only; no new attribution boundary changed. |
| inventory | NOT_NEEDED_UNCHANGED_CONTRACT: strict complete-list native/parser/classifier behavior and historical genuine inventory. | No fresh 004-05 inventory claim; current authority/capacity integration is offline evidence. |
| initial_bid | NOT_NEEDED_UNCHANGED_CONTRACT: historical 003 bid-receipt repair and reviewed native method/receipt, current authority tests. | No new-mode live bid effect; server admission/no-replay composition and full lifecycle are not live-certified. |
| rebid | NOT_NEEDED_UNCHANGED_CONTRACT: same reviewed native bid API/amount plus fresh lite/full link and independent readback tests. | No active new-mode live rebid; competitors/rejections/uncertainty were not manufactured. |
| move | NOT_NEEDED_UNCHANGED_CONTRACT: genuine 002 resale/series evidence; exact native method/arguments and shared effect assessor. | New-mode physical authority/scheduling verified offline, not a new live win/move. |
| list | NOT_NEEDED_UNCHANGED_CONTRACT: same historical resale/series proof, stored BIN/tick/hour and independent readback. | New-mode complete lifecycle not live-certified; no artificial win/sale. |
| clear_sold | NOT_NEEDED_UNCHANGED_CONTRACT: verified five-item historical bulk window and consumed ledger. | Zero-argument official API unchanged; do not replay that consumed operation. |
| relist_all | NOT_NEEDED_UNCHANGED_CONTRACT: verified four-item historical bulk window, unchanged prices/new auctions/3600s and ledger. | Zero-argument official API unchanged; every future operation needs fresh exact inventory/readback. |

The optional changed-contract windows planned in 004-01 were not automatically
triggered. Offline execution covers the local authority/composition changes, and
native invocation contracts were reused unchanged. No extra live contract retest
was necessary for the two final test/catalog defects. Historical native mutation
proof, synthetic controller lifecycle proof, genuine 004-02 read-only proof and
pending integrated full E2E are separate evidence classes.

All prior live windows record stopped helper threads, zero waiting/claimed work,
disabled mutations, restored hooks and stopped controllers. Final local cleanup
is independently recorded in `004-05/final-state.json` and checked again by the
final validator using Windows CIM, TCP listeners and scheduled tasks. No relevant
production process/listener on 8783/8784, enabled FC scheduled mutation job, or
temporary write-enabled probe service may remain. No account mutation cleanup
or guessed rollback is claimed.

## Hands-on full-E2E checklist and exact future CLI

These commands are for the later user/hands-on session. They were not executed
as live controller commands during implementation. From `C:\hustle\fc-hustle`,
prepare `private-captures/controller-v1/public-context.json` using the reviewed
public account/persona/identity_namespace labels plus game=fc27/platform=pc.
Use no credentials, cookies, headers, tokens or native session material. Retain
the same isolated controller database/cache across restart. The shipped reviewed
extension is pinned to port 8784; another CLI port alone does not retarget it.

```powershell
python -m fc_access.controller_v1 run --database private-captures/controller-v1/controller.sqlite --cache private-captures/controller-v1/quotes.sqlite --context private-captures/controller-v1/public-context.json --port 8784
python -m fc_access.controller_v1 status --port 8784
python -m fc_access.controller_v1 pause --port 8784
python -m fc_access.controller_v1 status --database private-captures/controller-v1/controller.sqlite
python -m fc_access.controller_v1 stop --port 8784
```

Pause/stop exit the serving run process after draining finite work. Use saved
`status --database` after either. To exercise stop over HTTP after a pause, first
explicitly start the same `run` command again and reattach its new owner/document;
the old HTTP endpoint is gone. Run is the only CLI action arming the lifecycle.
There is no HTTP resume/start route. The public Python API has explicit resume;
it only arms subsequent steps. No default account/database/cache/run port exists.

1. Reread AGENTS.md, retain Objective 003's pause, inspect saved uncertainty and
   known wins, verify no competing account/native owner, service or scheduled job.
   Create a distinct hands-on evidence directory and agree the finite session
   scope/budget before any real operation; never reuse consumed probe windows.
2. Verify the intended foreground official EA Web App in Edge, selected zzorniss
   saved account and PC persona. Use normal saved-login UI; leave CAPTCHA/2FA or
   missing credentials to the user. Load/reload the reviewed production extension,
   use a new official document, and attach during the launcher's 45-second wait.
   Distinguish local attachment/persona binding from authenticated EA GET success.
3. Observe actual entry balance, one-page discovery/pricing/cache counts, original
   observation ages, selected deadlines, up-to-ten sequential initial attempts,
   per-target independent status and visible discarded uncertainty. Record actual
   burst/handoff timing and expiry misses, not just HTTP success.
4. Follow the confirmed batch through highest/outbid/cap exhaustion/ordinary funds
   rejection and genuine terminal results. Verify five-second target/missed-cycle
   metrics, no overlap/catch-up, no management credits and no uncertain-command
   replay. Do not manufacture a competitor or misclassify a missing row as loss.
5. For natural wins, inspect physical paid-cost/ownership, move/readback,
   stored-BIN tick-below one-hour listing/readback and known-win accounting. Check
   natural sold/expired bulk work against exact fresh complete inventory and
   unchanged prices; do not force a four-hour soak or bulk lifecycle just to fill
   a checklist. Record unavailable natural cases as limitations.
6. Exercise explicit pause/stop and saved status, then an explicitly requested
   restart with new fences/mappings. Verify membership/quote persistence and
   no replay. End with stopped workers/services/jobs and documented account
   effects/unknowns. Production cutover, soak and any tuning require that later
   session's decision; they are not implied by this handoff.

## Limitations and risks

The 60-second window retains expiry risk. Pricing, two-second spacing and a
ten-bid burst can consume much of it; the window was not enlarged. The five-second
management target can be missed by sequential native work, as the synthetic
timings demonstrate. These are exposed policy tradeoffs, not eliminated risks.
Also, discarded uncertainty may create untracked participation. Ten bounds one
batch's attempts/confirmed management membership, not all actual account
participations after ambiguous submissions across successive batches. Status
explicitly reports potentially_untracked_effects and no global-ten guarantee.

Entry credits are not a guarantee of future rebid affordability. Complete known
inventory cannot bound unknown external changes or discarded effects. Missing
native mappings grant no authority; unresolved physical resale can remain pending
without blocking unrelated auction work. Current live market availability and
full integrated account lifecycle/performance are not established by offline
tests or older native proofs. No new live active rebid, full batch lifecycle,
four-hour soak, autonomous production cutover or full-E2E tuning was performed.

## Publication and stopping boundary

Implementation/report commit: `9d53f7716fe8007d88baac1991b10fd418b46ae7` on main.
At 2026-11-16T19:24:11.381248+00:00, `git push origin main` exited 0
and an independent `git ls-remote origin refs/heads/main` returned that exact
commit. The actual push output was:

```text
To https://github.com/zrsoo/fc-hustle.git
   8981096..9d53f77  main -> main
```

The push and remote verification took 3.574 seconds including the remote read.
`004-05/publication.json` retains the exact argv, commit, exit code, output,
timestamp and remote result. This subsequent documentation/evidence commit
records the confirmed implementation publication without a self-referential
hash; the final independent validator checks that current HEAD is clean on
main, contains the implementation commit, and is present in origin/main.
The complete offline and prepublication gates passed before the implementation
commit; publication does not qualify the pending full controller E2E.

Stop after this handoff. No autonomous trading, production cutover, scheduled job,
full-batch lifecycle E2E, four-hour soak, E2E tuning, another objective or deferred
orchestrator implementation is part of this task.
