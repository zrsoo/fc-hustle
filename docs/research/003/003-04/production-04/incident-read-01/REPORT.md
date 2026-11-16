# Failed watched read: preserve absent HTTP status and controlled stop

Run `e593e1be9debe924c2f9be3ba555e9a2` stopped on November16 at 08:13:24 UTC,
after 2548.49 healthy monitored seconds. Its fourteen genuinely witnessed cases,
counters and final exporter capture remain separate from any future segment.
All five child exits were awaited; RUN_STOPPED is control sequence29015. The
supervisor, exporter and independent reviewer subsequently exited. The
journal-backed service exited before read-only recovery, and that read-only
service also exited before source changes.

Primary command `2f2909de513d3229cc6a8e293449c872` was a read-only watched GET.
It was dispatched once. The page reported `service_failed` with no valid HTTP
status. The host rejected its result as `invalid_network_status`, retained the
bounded diagnostics, and eventually recorded delivery UNKNOWN. The raw invalid
status/body was not retained and has not been reconstructed. The secondary
bidder/maintenance timeouts followed the closed dispatch gate. Maintenance read
`57a7d48bfd6ac5712d7cf9b6cc6698f8` has no start, claim or transport command and
was not an executed account operation.

The page's numeric conversion can represent native XHR0 as network status0,
although zero is not an HTTP response status. Executing the actual page with
explicit offline XHR/native doubles reproduces that representational defect.
The captured metadata is consistent with this path; it does not identify why
the original native request failed. Abort, connectivity, CORS, rate limiting or
authentication causes are not asserted from the missing status.

The corrected page records XHR0 as absent HTTP status null and emits only a
typed `xhr_zero_status` boolean in positive-allowlist diagnostics. The Python
diagnostic boundary accepts that boolean and rejects non-boolean values and
unknown credential-like keys. The native failure, null freshness, one attempted
request and controlled stop remain. Literal network status0 is still rejected
by the protocol. No HTTP200, successful read, personal outcome or automatic
retry is manufactured. A failed envelope can now be retained by the host and
broker immediately instead of being lost to result rejection and later timeout.

At the stop, accepted bid `663b8845906ad81b8b9cde2af179674a`, amount1000,
was awaiting independent verification. Its actual accepted receipt and prior
bid history were preserved. Three **new**, genuine native read-only GETs under
epoch85 independently reconciled it. `fresh-reads/native.jsonl` and the distinct
before/after database copies retain that proof. The failed watched command,
accepted bid and cancelled maintenance read were never replayed. Credits were
62,827; the complete inventory held five physical items and the existing
potential-win commitment remained reserved. No refund was inferred.

The auditor's narrowly documented-read exception allows inspection of this
sealed failed GET only when the actual host rejection and page-failure records
exist. It cannot waive an unknown mutation, promote the failed callback to live
success, count a stopped segment as healthy, or authorize replay. Offline
negative tests cover those constraints. Historical raw failure evidence stays
unchanged.

Five focused Python tests exercise actual page output, host retention, broker
controlled stop/no retry, the genuine independent recovery, and refusal to waive
an uncertain mutation. The new Node suite verifies the real page/diagnostic
implementation using offline doubles. Final full discovery passed **948 Python
tests**, zero failures/errors; all **29 Node suites** passed. Exact argv,
completion times, stdout and stderr are retained in `offline-01/`. These tests
are not live case coverage or elapsed production time.

No human prerequisite is currently known: fresh native reconciliation passed
without a credential/security challenge. Publication and a fresh document/owner
must precede production restart. The next healthy segment must independently
reconcile again; the earlier 42 minutes cannot contribute to its four-hour
requirement. Missing natural cases remain LIVE-UNVERIFIED. Four hours will not
trigger a scheduled shutdown.
