# 001c-05 bridge durability and bounded readiness

Actual Edge lifecycle checks passed. The closed campaign retained eight successful
authenticated native GETs (seven watched-auction reads and one balance read),
charged ten command reservations out of twelve, and permitted **zero mutations**.
The two failed delivered reads remain charged and are never replayed. Two other
readiness probes were rejected before queueing and consumed no command budget.
No earlier campaign was restarted or reset. Historical files and sources covered
by entry.json remain byte-for-byte unchanged.

## Diagnosis and genuine lifecycle observations

The retained 001B campaign's last record is bridge_not_attached with an empty
network array, before an EA operation. The historical capture cannot identify
which browser or local-network event originally stopped the worker. Source review
establishes a failure mechanism: the old worker exits its polling loop on one
exception and has no alarm/startup recovery. This is an inference about the retained
trigger, not a fabricated browser trace. The new isolated transport adds a local
alarm watchdog and current-document injection, with no automatic native operation.

The signed-in official EA Web App was controlled through this worker's own Windows
UI Automation, with verified Edge/tab/foreground selection. It required no login
or challenge. The read-only extension is pinned to **dgcldmlgghjmcikfmgghgpjjjilgadma**
on **127.0.0.1:8779**. Attachment, accepted public PC persona, authenticated network
presence, and native success are recorded as separate observations.

* Normal idle lasted **319.945 seconds**, beyond the retained 300-second
  boundary. Budget remained one before the post-idle read; that read made one GET.
* A real page Refresh changed the document fence. Alarm reinjection restored the
  page bridge and a new successful native read followed.
* Python was actually stopped and the port was observed unavailable. A first
  post-start probe was too early and returned 409 with no delivery. In a separately
  controlled restart, with no browser action during recovery, the new process
  epoch reattached automatically in **14.081 seconds**. Its
  process generation changed; deadline, consumption and page document were retained.
* A genuine extension Reload exposed an orphan-long-poll race in the first version:
  the old /next handler could claim work after its worker had disappeared. The
  resulting 504 is retained as extension-reload.json and stays UNKNOWN. The fix
  adds a public worker-generation fence, invalidates the orphan on a new hello,
  and prevents its finally block from clearing the replacement poll. A deterministic
  HTTP test reproduces the race. A second actual Reload, normal action reattachment,
  changed worker generation, preserved epoch/budget and completed a fresh native read
  (extension-reload-verified.json). The old command was not retried.
* Real host-side wrong scope/owner/epoch/Origin submissions and an old owner after
  takeover were rejected without reservation. The actual Edge page independently
  exercised wrong scope/owner/stale-epoch and bid-disabled guards, all with zero
  native requests; these flags are retained in health.page_checks. Changing owner
  with a higher epoch restored watched reads under the new fence.

The first balance probe exposed an outdated adapter contract: it accepted only
/user/currencies and payload credits. Retained verified read-bridge code already
established /user/credits and numeric user.coins.amount after requestCurrencies.
The new version adapts that route and wallet projection; prior sources were not
changed. balance-verified.json proves the actual authenticated GET and numeric
spendable coins. An early post-refresh final probe also correctly failed persona
readiness before queueing; its checkpoint is preserved. Neither failure was used
as a fresh write precondition.

Local scope, owner, command, process, worker and document values are generated
correlation/fencing values, not EA authentication session identifiers. The extension
never reads saved sign-in values, cookies, tokens or header values for retention;
its XHR wrapper notes only the presence of the session header. No raw native item
or trade IDs leave the page.

## Durable bounds, fault behavior and ownership

Store commits each reservation and each delivery with SQLite WAL / synchronous FULL.
A delivered command is never put back on the queue. On restart, queued/delivered
commands become UNKNOWN; mutation uncertainty stops its window. Result correlation
requires current process, scope, owner, epoch, page document and worker. Host and
page fences reject stale work even when the other side is still running.

BoundedHarness takes an explicit adapter and explicit independent readback functions;
importing or constructing it launches no actor. Default mutation allowance is zero.
Explicit windows allow at most **3 mutations**, **10,000 gross coin exposure**, and
**900 seconds**; deployments can choose smaller limits. Existing database deadlines,
limits, spent reservations and uncertainty stops survive reopen and cannot be enlarged
by new constructor arguments. All actions reserve before sending. Exposure is gross,
not an inferred refund. Missing/cached/stale balance, status, identity, legal minimum,
current ownership, reviewed rules or five fresh exact-version comparables cannot
produce a bid. UNKNOWN acknowledgments end the window, even if fresh data later
becomes available. Successful native ACKs still require separate status and balance
read IDs and journal reconciliation. No previous command is ever redelivered.

Tests inject lost ACKs, invalid replies, exceptions, process termination before/after
send, stale epochs, owner takeover, restart reconciliation and reopened reservations.
They count actual simulated sends independently of journal state and require a single
send after a crash. Page cache/timeout and the extension orphan race are also tested.
These are deterministic fault proofs, not claims of real EA bid idempotency.

Won-item transfer/list actions require a fresh WON status, matching physical owned
item and actual paid amount, a separate fresh ownership proof, tradeability and current
command ownership. The final ownership check and synchronous send share the journal
write lock. Listing additionally requires reviewed current price rules and a legal
price. Each action requires an independent fresh readback and reserves mutation budget.
Closed/highest alone remains PENDING. Native live win/transfer/list outcomes were not
created in this task.

The actual lifecycle EdgeReadExecutor and extension are explicitly read-only. The
mutation harness is policy/fixture verified and takes the reviewed mutation executor
seam from bidding_v1; a live mutation campaign still requires conclusively verified
ordinary bid/listing server rules and fresh native preconditions. The observed client
increment schedule from 001c-04 is not promoted to LIVE_VERIFIED server legality.
This task does not declare Objective 002 FULL GO or launch continuous Acquirer/Bidder
services. No live bid/write throughput, real outbid, coin escrow settlement or win
was inferred from these tests.

## Measured service behavior and the 25-second model

Across eight retained successful native reads, native service time ranged from
**62.300 to 178.000 ms**. measurements.json
contains each value; capture files separately retain host end-to-end time. Idle
long polls and page guard probes generated no native operation. The failed extension
command's native outcome is unknown; the failed balance version captured no matching
route. Their unobserved requests are not counted as zero EA traffic. Delivery budgets
remain conservative. The sample does not establish EA capacity or a safe request rate.

scheduler.json is explicitly DETERMINISTIC_SIMULATION: writes precede ordinary reads,
an urgent read can preempt a write, a two-slot burst respects concurrency and cadence,
stale work is skipped, and a cache hit records zero network requests. Fifty HOLD
entries require zero bid submissions. Three synthetic 50-row bulk refreshes each
cost one GET in the model. A 51-second service delay misses a whole 25-second cycle
and expires the next refresh; the scheduler skips it instead of generating catch-up
traffic. Pricing, balance, rebids and reconciliation add calls; 50 rows are not 50
independent network status calls. The measured small live watchlist and fixture
50-row processing cannot establish a 25-second whole-queue guarantee. Write timings
and bursts remain live-UNVERIFIED.

## Reproduction and preserved failures

Run independently from the workspace (no browser or account access):

```
python tests/test_durability_v1.py
python tests/test_durability_artifacts.py
python tests/test_readiness_regressions.py
```

The regression command runs each documented offline suite in its own process, with
no retry or reinterpretation of failures. It includes 50-row bulk ingestion, durable
journal/queue faults, pricing, search, scheduler, native JavaScript, historical
transaction reconciliation and the new lifecycle tests. checks.json and check-N.txt
record exact commands and outputs; checks-first.json and first-check-N.txt retain
the initial results. One initial combined watched-bulk rejection test and an earlier
standalone search rejection test reported Windows socket error 10053. They were not
reported as HTTP success. Broader discovery also exposes two pre-existing Objective
001 tests whose retained browser evidence is older than 24 hours; those evidence
bytes were preserved. The final check logs record all remaining failures explicitly.

The live window was closed explicitly (/close); live-final.sqlite is an independent
SQLite backup after closure. Acceptance validators only inspect retained evidence and
run offline code. They do not restart this consumed window or request any EA operation.

Final verification: **21** new behavior/fault checks, **8** independent artifact
checks, and **126** relevant tests across **12** isolated suites pass. The
relevant runner uses tests/run_offline_suite.py to coalesce byte-body requests
with their headers; every original response assertion executes, with no retry,
exception suppression or fabricated HTTP response. This removes the legacy
Windows split-write rejection race in the offline fixture. The new server
consumes bounded bodies before rejecting and independently passes a real
split-header/body socket test without that shim. Prior plain-client failures
remain retained; legacy server sources were preserved. Final broad discovery
ran **298** tests: **296 passed**, with exactly the two retained Objective 001
BrowserAccessTests freshness failures named in checks.json. git diff --check
passed. Final command logs are final-behavior.txt, final-artifacts.txt and
final-regressions.txt, with each exact argv recorded in checks.json.
