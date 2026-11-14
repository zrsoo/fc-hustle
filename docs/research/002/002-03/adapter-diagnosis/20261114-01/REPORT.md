# Adapter diagnosis: steps 1, 2 and 3

**The single instrumented broad search PASSED. The earlier failure did not
reproduce. Its underlying root cause is NOT CONFIRMED; no adapter behavior fix
is justified by this sample alone. User review remains pending.**

The user authorized offline comparison, targeted logging, and one bounded
read-only diagnostic broad search, then a report before execution of a proposed
fix. This is not a fifth performance-gate attempt. No pricing, valuation, bid,
purchase, listing, bulk mutation or actor was executed. The four previous failed
gate checkpoints remain unchanged. This report does not declare Objective 002
item 3 passed or permit item 4.

## 1. Offline comparison and inference

The historical implementation is `browser/e2e-live-v2/page.js`; the production
implementation is `browser/production-v1/page.js`. Both construct native
`UTSearchCriteriaDTO`, set type=player, count=21 and the price filters, clear the
native market cache and call `services.Item.searchTransferMarket(criteria,1)`.
Omitting the exact-version selector is the intended broad-discovery case.

The historical successful broad capture
`docs/research/001c/001c-06-resume-02/search-2.json` used maxBid=1000 and the old
minBuy=10500. Current policy is minBuy=11000; historical bytes and expectations
were not edited to match the new policy. All 21 retained native auction rows,
mapped into the current nested item representation, pass the current row
validator. That rules out a universal incompatibility in those recorded rows;
it does not prove every current native object or response envelope is compatible.
See [offline-comparison.json](offline-comparison.json).

Important migration boundaries were identified:

| Boundary | Historical primitive | Production wrapper |
| --- | --- | --- |
| Search scope | Optional exact definition | Initially mandatory for every search; broad omission restored in 3a21885 |
| Result shape | Schema 1, flat rows | Schema 2, nested item, complete context and execution fences |
| Native definition projection | definitionId, with resourceId fallback | Positive exact definitionId required; no base-ID fallback |
| Acceptance | Experimental dialect | Strict query, row, source, freshness and timing checks |
| Evidence | Native rows plus sanitized wire rows | Validated production native rows and authenticated route evidence |
| Rejected results | Limited failure diagnostics | Validation before persistence could erase the rejection reason and appear as a timeout |

The loss of broad discovery was a confirmed earlier capability regression,
already corrected before this task. The hypothesis for the latest timeouts was
a native projection or server result-validation failure hidden by the diagnostic
gap. The authorized live sample did not reproduce that hypothesis.

## 2. Targeted diagnostics added, without accepting different search results

`browser/production-v1/diagnostics.js` records bounded page events using a strict
allowlist. It retains only stage/time, booleans, numeric counts/statuses and
known field-type/error enums. No raw response bodies, credential values, auth
headers, session identifiers or arbitrary exception messages are logged.

`page.js` now emits entry, native invocation/callback/timeout, observed EA
response, native data shape, item-schema failure and completion/failure stages.
The native criteria, operation calls, projection acceptance rules and success
requirements are unchanged. Reading type metadata does not add a definition-ID
fallback or allow malformed rows.

`worker.js` records execution, received result, result POST, acknowledgement and
failure boundaries. It transfers the bounded page trace through the existing
extension-origin-restricted localhost service. A failed diagnostic upload does
not retry or repeat native execution. No result delivery retry was introduced.

`diagnostics.py`, `Store.diagnostic` and the `/diagnostic` route validate stage
metadata before append-only retention. Diagnostics are tied to an existing
command and the same account/document/host/worker/owner fences, with bounded
records and per-command event counts.

`Store.finish` retains a safe `RESULT_REJECTED` reason and typed summary outside
the rolled-back acceptance transaction. It still rejects the result, preserves
the original exception and does not forge an acknowledgement or empty market
response. Native outcome uncertainty remains UNKNOWN. Offline tests demonstrate
that a deliberately invalid auction field stays rejected while its reason
survives; private extra fields and malformed arbitrary values are excluded.

This fixes the confirmed failure-reporting defect. It is not a demonstrated fix
for the earlier native-search failure, whose cause was not recorded then.

## Offline verification before the live probe

`python -m unittest discover -s tests -v`: **548 tests passed, zero failures/errors**.
All **19 Node check scripts passed**, including the new executed page-diagnostics
checks. Exact commands, UTC times, counts, exit codes and captured-output hashes
are retained in [offline-checks/results.json](offline-checks/results.json).

Coverage includes actual production page/worker execution, callback and EA
response stages, failed result delivery without retry, strict context/fences,
rejection reasons surviving rollback, typed summaries of malformed values,
secret canaries, bounded records, append-only retention, historical row replay,
read-only command ordering and refusal to reopen a diagnostic checkpoint.
Only captured evidence/log hashes are checked; no mutable source hashes are
asserted.

## 3. Exactly one bounded live diagnostic broad search

Runner: `python -m fc_access.production_v1.diagnose_search`.
Its separate [checkpoint.json](checkpoint.json) was exclusively created before
desktop/service/native work. Budget: one authentication GET, one broad discovery
GET, 180 seconds, zero pricing searches/helpers/valuations/mutations/retries.
An existing checkpoint refuses execution before desktop or native access.

The reviewed localhost service and extension were reloaded, the verified official
FC27 Web App document was refreshed, and a higher public execution epoch fenced
the old mapping. The official Edge window and foreground were verified. The
normal selected PC session was used; no credentials were exported. Recovery
details are in [recovery.json](recovery.json) and
[prepared-readonly-health.json](prepared-readonly-health.json). Ordinary Web App
startup background traffic is not included in this explicit command count.

The diagnostic ran from **2026-11-14T01:55:06.088830+00:00** to
**2026-11-14T01:55:12.882708+00:00** through the actual production Foundation,
native adapter, serialized executor and durable journal. It performed these two
actual EA requests:

| Operation | Actual endpoint | Exact sanitized query | HTTP | Result |
| --- | --- | --- | --- | --- |
| Authentication | GET `/ut/game/fc27/user/credits` | empty | 200 | Native authenticated result accepted and acknowledged |
| Broad player discovery | GET `/ut/game/fc27/transfermarket` | `macr=1000&minb=11000&num=21&start=0` | 200 | 21 auctions across 12 exact definitions; accepted and acknowledged |

Both used host `utas.mob.v1.prd.futc-ext.gcp.ea.com` and had native authentication
header presence verified without exporting its value. Query ordering above is
descriptive; the captured query object is authoritative.

Authentication command: `2811a8dacca0d8e353adf6063257fd4c`.
Search command: `99f0e1d8fea4c6779da57e521bdaef5b`.

The search trace records:

```text
01:55:12.255Z WORKER_EXECUTE
01:55:12.264Z PAGE_ENTER
01:55:12.265Z native DTO: definition type=array, definition count=0
01:55:12.265Z NATIVE_INVOKE
01:55:12.827Z EA_RESPONSE: HTTP 200, one request
01:55:12.830Z NATIVE_CALLBACK: success=true, status=200
01:55:12.830Z NATIVE_DATA: object, 21 items
01:55:12.837Z PAGE_FINISHED: success=true, one request
01:55:12.839Z WORKER_RESULT
01:55:12.861Z WORKER_POST_RESULT
01:55:12.870Z WORKER_ACK
```

Native EA RTT was **559.0999999940395 ms**; native service time was
**572.5999999940395 ms**. Serialized executor queue wait was
**1825.6371000024956 ms** under its unchanged two-second pacing. Executor roundtrip
was **657.1110000077169 ms**, including the local diagnostic/result path. These
overlapping measurements must not be added as disjoint totals. This was not a
valuation-to-fresh-admission measurement and supplies no <30-second gate proof.

The full actual native response, sanitized identities/prices, successful Python
acceptance and ordered durable trace are in [checkpoint.json](checkpoint.json)
and [transport.json](transport.json). There were no `RESULT_REJECTED`, page
failure, worker failure or native timeout events in this sample. The actual
native DTO had an empty definition array, so omitted broad criteria were valid
for the loaded client in this run.

[independent-validation.txt](independent-validation.txt) verifies the two-read
budget, no pricing/gate/mutation, unchanged prior checkpoints, authenticated wire
filters, exact checkpoint/transport correlation and every expected trace stage.
The independent validator returned PASS for the diagnostic search and explicitly
NOT_CONFIRMED for the prior failure's root cause.

## Findings and proposed action for user review

**Confirmed:** the filtered native broad search is supported; the instrumented
production path can serialize and accept its real 21-row response. The earlier
loss of broad search was already repaired. The separate diagnostic-loss defect
was real and has now been covered by typed durable logging and negative tests.

**Not confirmed:** why the third/fourth attempts produced no accepted result.
Their missing error records cannot be recovered retrospectively. This one
successful sample does not prove the earlier result was rejected, that the
problem was only login, that a timing race exists, or that logging fixed an
underlying adapter defect. Instrumentation adds local IPC/timing, and the browser
document/service and market sample changed; those factors are not isolated.

**No adapter behavior fix is proposed as proven.** Retain the diagnostics; keep
the successful native request construction and strict identity/auth/freshness
checks. Do not relax validation, introduce a base-ID fallback or replace the
adapter based only on an unconfirmed hypothesis. A later user-authorized bounded
instrumented repetition could capture an intermittent failure; if it does, use
the exact rejected field/stage to propose a targeted regression and fix.

No such extra probe, confirming search, behavior fix or performance gate was
executed here. Steps 1–3 are complete. **Awaiting user review of these findings.**
