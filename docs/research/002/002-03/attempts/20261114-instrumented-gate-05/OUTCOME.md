# Fifth attempt: adapter rejection identified; performance gate blocked

**BLOCKED — USER INSTRUCTION REQUIRED.** Valuation never started. No fix or retry
followed this failure.

This time the retained diagnostics identify why the search was not acknowledged.
The failure was not merely an unexplained lost response: the localhost server
received the browser's result and explicitly rejected it.

## Observed failure chain

Authentication succeeded first: one native `/ut/game/fc27/user/credits` GET200 was
accepted and acknowledged. Then one native broad-search invocation requested
maxBid=1000/minBuy=11000, page 1, count 21, without an exact definition selector.

| UTC on 2026-11-14 | Actual event |
| --- | --- |
| 02:18:42.317 | Native search invoked; native DTO definition array empty |
| 02:18:42.915 | Intended `/ut/game/fc27/transfermarket` GET completed with HTTP200 |
| 02:18:43.010 | A second FC27 GET completed with HTTP200; path projected as `/unexpected` |
| 02:18:43.011 | Native callback reported success=true/status=200 |
| 02:18:43.011 | Page wrapper emitted `ambiguous_network`, request_count=2, success=false |
| 02:18:43.032 | Worker posted the returned result to localhost |
| 02:18:43.037 | Server persisted diagnostic `RESULT_REJECTED`, reason `wrong_native_route` |
| 02:18:43.039 | Worker recorded `local_rejected` at `post_result` |
| 02:19:04.325 | Gate sealed FAILURE/BLOCKED, `delivery_unknown_no_retry` |

Search command: `0cfebb45bc0e2c23789c0bc5ba64d05d`.

The rejected-result summary independently retained these two wire observations:

```text
GET /ut/game/fc27/transfermarket
  macr=1000, minb=11000, num=21, start=0
  HTTP 200; native authentication header present

GET /unexpected
  sanitized query: empty
  HTTP 200; native authentication header present
```

`/unexpected` is the adapter's constant for an unrecognized path. The actual
second endpoint and its purpose were not retained. It may be auxiliary native
work or concurrent Web App traffic; that classification is not proven. It is
not a second observed `/transfermarket` request. Neither authentication value
was exported.

## Confirmed adapter failure mechanism

The production capture in `browser/production-v1/page.js` observes **all FC27 UT
requests** during the command and maps unrecognized paths to `/unexpected`.
The search completion guard then requires `network.length === 1`. Observing the
second GET therefore converts a successful native callback into
`ambiguous_network` before auction-row projection occurs.

The Python parser in `fc_access/production_v1/contracts.py` requires **every**
network entry to match the command's route, including in this failure envelope.
The `/unexpected` entry fails that test with `wrong_native_route`.
`Store.finish` rejects the result and leaves no accepted result for the waiting
caller. The worker receives a local rejection, and `/run` eventually times out.
The new diagnostics preserve this complete chain despite the rejected result.

The historical `browser/e2e-live-v2/page.js` capture included only paths in its
known route set. The newer all-FC27 capture plus exact-one-request/per-operation
route validation is therefore a concrete integration difference. The earlier
diagnostic search succeeded with one captured search-window GET; this attempt
encountered two and failed. That establishes this attempt's mechanism. Missing
records prevent proving that the earlier third/fourth failures had the same cause.

This does not establish a malformed auction row or a pricing defect: the wrapper
failed before projecting auction rows. The auction count for this search is
unknown. It also does not establish a problem with the maxBid/minBuy parameters;
the intended search's captured query and HTTP200 are correct.

## Proposed fix for review — not executed

1. Identify/classify the second GET safely, using a reviewed route template and
   sanitized metadata. Do not label all unknown requests harmless or silently
   discard them.
2. Correlate the intended search request separately from auxiliary/concurrent
   traffic. Preserve separate truthful counts and timing evidence. Continue to
   reject duplicate intended market searches, wrong filters, unexpected writes,
   identity conflicts and missing authenticated target responses.
3. Preserve a failed/ambiguous result's diagnostic metadata without forcing every
   observed auxiliary path to equal the target route. Keep native outcome UNKNOWN
   where appropriate; do not convert it into success or an empty search response.
4. Add an executed regression reproducing this two-GET trace, plus duplicate-search
   and unexpected-write negatives, then verify with a bounded read-only smoke test
   before another separately authorized performance gate.

These are proposed changes only. No capture-scope, route-validation, error-protocol
or pricing behavior fix was implemented after the failed gate.

## Scope, checks and retained records

The native capture observed three GETs across the two explicit commands: one
authentication GET plus two during the search window. No pricing search, helper,
card-cap read, final credits recheck or admission decision occurred. No auction
was selected. `valuation_start_ns` and `elapsed_ns` are absent; wall time must not
be substituted for the unmeasured strict <30-second gate.

The final offline run before live work passed **549 Python tests and 19 Node
scripts**. The initial unrelated Windows localhost-test abort is retained. No
unrelated test or implementation was changed. Prepared independent outcome/stop
validators matched the expected failure and preserved all four prior failures.

See [root-cause.json](root-cause.json), the ordered captured diagnostics in
[transport-diagnostic.json](transport-diagnostic.json), the consumed
[gate.json](gate.json), [authorization.json](authorization.json), and the broader
[attempt report](REPORT.md). The prior successful standalone adapter diagnostic
also remains unchanged. No additional gate, candidate, search, fix, actor or
Objective 002 item 4–12 work followed the failure.
