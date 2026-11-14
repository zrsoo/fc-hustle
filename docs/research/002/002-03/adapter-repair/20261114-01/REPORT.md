# Production adapter repair and sixth 002-03 gate

**READY TO RESUME ITEM 4.** The repaired production adapter passed both a live
special-version metadata-fanout test and the full read-only Foundation gate.
The genuine uncached valuation through fresh `BID/ELIGIBLE` admission took
**12.069805600 seconds**, strictly below 30.000 seconds. No account mutation,
actor or maintenance job was dispatched by this remediation.

The user explicitly authorized taking over, backing up, investigating, fixing,
testing end to end, committing/pushing this report, and then requesting the
orchestrator recheck. That instruction authorizes this new remediation; it does
not reinterpret or reopen any previous failed experiment.

## Backup and preserved history

Before changes, `main` and `origin/main` were at
`897968c69488d2507193634c79085453a5325345`, with a clean worktree. A local annotated
tag, `backup/adapter-repair-20261114T022713Z`, and a complete Git bundle preserve
that state. SQLite's consistent backup API copied the transport, Foundation,
completed-quotes and orchestrator databases; all four backup integrity checks
returned `ok`. See [backup-receipt.json](backup-receipt.json). The bundle and
private runtime backups remain under
`private-captures/adapter-repair-20261114/backup-20261114T022713Z/`.

All five prior gate checkpoints remain byte-for-byte unchanged and retain their
`FAILURE/BLOCKED` verdicts:

| Attempt | Checkpoint relative to `docs/research/002/002-03/` | Historical result |
| --- | --- | --- |
| 1 | `gate.json` | Desktop subprocess encoding failure; valuation never started |
| 2 | `attempts/20261114-preflight-remediation-01/gate.json` | No eligible candidate in the single exact discovery |
| 3 | `attempts/20261114-bounded-discovery-03/gate.json` | Discovery delivery unknown; valuation never started |
| 4 | `attempts/20261114-authenticated-retry-04/gate.json` | Authenticated credits, discovery delivery unknown; valuation never started |
| 5 | `attempts/20261114-instrumented-gate-05/gate.json` | Successful search callback rejected after two observed GETs; valuation never started |

Their evidence hashes are checked against the independently retained probe
captures and the new attempt's chained authorization. No implementation file is
hash-pinned. The sixth attempt has its own exclusive checkpoint and budget:
[authorization.json](../../attempts/20261114-adapter-repair-gate-06/authorization.json),
[gate.json](../../attempts/20261114-adapter-repair-gate-06/gate.json).
`selected_checkpoint()` now selects that sixth checkpoint; it never falls back
to an older PASS when a newer consumed checkpoint fails. The original checkpoint
still fails the PASS validator when explicitly selected.

## Root cause and actual fix

The native search call and its maxBid/minBuy mapping were correct. The faulty
integration assumption was **one native search always equals one EA request**.

The official native implementation has this conditional chain:

```text
services.Item.searchTransferMarket(criteria, 1)
  -> itemDao.searchTransferMarket(criteria)
     -> GET /ut/game/fc27/transfermarket
  -> for items whose databaseId differs from definitionId:
     services.PlayerMetaData.updateItemPlayerMeta(items)
       -> metaDAO.getAttributesMetaData(items)
       -> when exact-version metadata is missing:
          GET /ut/game/fc27/attributes/metadata?defIds=...
  -> notify the original search observable with the populated native items
```

Static review of the retained official public client identifies that chain.
The new special-version live probe independently verifies its two actual routes,
queries, HTTP200 responses, 21 returned auctions and successful observable result.
Base-card searches, or searches with already populated native metadata, can
produce only one GET. This explains how a broad search could work once and then
fail on a different set of card versions.

The fifth attempt definitively established `ambiguous_network` followed by
Python `wrong_native_route` and a localhost rejection. Its second endpoint was
erased to `/unexpected`; **its exact path cannot be retrospectively proven**.
The new metadata probe reproduces the same two-request condition the old wrapper
would reject. Missing third/fourth traces also prevent proving their exact routes.

Changes:

- `browser/production-v1/page.js` retains every observed FC27 request. A successful
  search requires exactly one matching market GET, plus at most one specifically
  reviewed metadata GET. Both must be authenticated, successful and on the same
  EA host. Metadata `defIds` must be positive numeric IDs, at most 21 entries,
  and match versions actually returned by that search. Repeated IDs are valid:
  the real native metadata request contained the same version 21 times.
- Target selection is independent of incidental request ordering. Duplicate
  market requests, duplicate metadata requests, unknown traffic, unexpected
  writes, mismatched metadata IDs, wrong filters, missing authentication and
  freshness/context conflicts still prevent success. Unknown paths remain
  redacted; no arbitrary URL, query value or response body is exported.
- `contracts.py` applies the same success rules independently. Total request
  counts and timings retain auxiliary work. A typed **failed** envelope can
  retain sanitized unknown/pending network observations without claiming they
  match the intended route. It is delivered as an explicit failure rather than
  being lost to a second validation error and a misleading transport timeout.
  `NativeAdapter` still raises that failure; uncertain writes remain UNKNOWN
  under existing no-blind-retry rules. Identity/owner/epoch checks are unchanged.
- `diagnostics.py` retains the reviewed metadata path and bounded numeric
  `defIds`, including when a result is rejected. No authentication value is read
  or persisted; only header-presence booleans are retained.
- The gate runner and validators recognize the separately authorized sixth
  attempt. Its budget is at most ten network-producing native invocations,
  up to six possible native metadata GETs, sixteen total EA GETs, 64 local helper
  batches, three discovery calls within 180 seconds and one timed valuation.
  The two pricing searches, 24-hour cache, X=500, tax, native legality,
  two-second native scheduling interval and all freshness rules are unchanged.
- `repair_probe.py` supplies two finite, exclusive, read-only contract windows;
  `metadata_probe.py` is the explicit special-version entry point. They cannot
  quote, bid, retry a command or reopen their consumed checkpoints.

No preflight authentication, foreground, official-tab or PC persona check was
relaxed. The existing explicit UTF-8 structured-JSON preflight remains intact.
The reviewed extension and read-only localhost service were reloaded. Edge was
verified and brought forward, then the official Web App was refreshed. A transient
Login label disappeared during normal initialization before a click could be
dispatched; no login credential was inspected. Attachment was verified separately
from the fresh native credits HTTP200 authentication proof.

## Actual live adapter probes

Both probes used the actual production Foundation, journal/cache paths, adapter,
extension and service, with selected FC27 PC context and mutations disabled.
Each made exactly one credits invocation followed by exactly one search
invocation; there were no retries, helpers, quotes or admission warmups.

| Probe | Sanitized actual wire requests | Result |
| --- | --- | --- |
| [Broad smoke](smoke-01/checkpoint.json) | GET `/user/credits`; GET `/transfermarket?macr=1000&minb=11000&num=21&start=0` | Two HTTP200s; 21 native auctions; localhost and worker ACK |
| [Special-version smoke](metadata-smoke-02/checkpoint.json) | GET `/user/credits`; GET `/transfermarket?definitionId=50573369&num=21&start=0`; GET `/attributes/metadata?defIds=` followed by 21 comma-separated copies of `50573369` | Three HTTP200s; 21 native auctions of that exact version; one native search invocation; localhost and worker ACK |

All paths above have prefix `/ut/game/fc27`. Captured host:
`utas.mob.v1.prd.futc-ext.gcp.ea.com`. Each request had the native authentication
header present; its value was never retained. The special search's measured native
service time was 285.900ms, including 279.400ms of captured EA RTT.

See the corresponding [broad transport trace](smoke-01/transport.json) and
[metadata transport trace](metadata-smoke-02/transport.json). These prove the
adapter repair live. The metadata probe is an exact-search contract test, not a
valuation or performance PASS; it created no completed pricing cache entry.
The final gate uses a different exact version.

## Actual sixth-attempt Foundation E2E

Command:

```text
python -m fc_access.production_v1.gate_00203_discovery --attempt 20261114-adapter-repair-gate-06
```

This attempt used one fresh broad discovery with `maxBid=1000/minBuy=11000` and
selected exact version **278046**, physical item
`item:a7ab887f475aec2049288c42`, auction
`trade:057aeb82a3b167642da7aeee`. The initial fresh native auction was active,
tradeable, not won, with starting bid 700, current bid 0, BIN 11000 and 1356 seconds
remaining. The genuine cache inventory contained no completed entry for that exact
version in the current account/game/platform scope. No native cap/helper/quote
warmup for that candidate preceded the timer.

| Stage | Actual GET under `/ut/game/fc27` | HTTP | Result |
| --- | --- | --- | --- |
| Authentication | `/user/credits` | 200 | 62127 available coins |
| Discovery | `/transfermarket?macr=1000&minb=11000&num=21&start=0` | 200 | 21 auctions |
| Timed caps | `/marketdata/pricelimits?defId=278046` | 200 | Native minimum 700, maximum 11000 |
| Timed pricing 1 | `/transfermarket?definitionId=278046&num=21&start=0` | 200 | 21 auctions; first minimum valid BIN **5200** |
| Timed pricing 2 | `/transfermarket?definitionId=278046&maxb=5200&num=21&start=0` | 200 | 20 auctions; final minimum valid BIN **4900** |
| Fresh final auction | `/transfermarket?definitionId=278046&macr=1000&minb=11000&num=21&start=0` | 200 | 18 auctions; exact original trade/item reacquired |
| Fresh final credits | `/user/credits` | 200 | 62127 available coins |
| Fresh final caps | `/marketdata/pricelimits?defId=278046` | 200 | Native limits unchanged |

There were eight actual EA GETs across the whole attempt, six inside the timer,
and no auxiliary metadata request for this base version. There were exactly two
pricing searches and no third. Forty-one returned pricing rows yielded 39 unique
comparables after excluding two duplicates. No 600/10000 templates appeared in
these live samples; their exclusion remains covered behaviorally offline.
No statistical trimming, sorting, undercut, page 2 or price-policy change occurred.

The normal production valuation produced resale **4900**, tax **245**, raw
profitability cap **4155**, and native legal floored cap **4100**. Fresh Foundation
admission returned **BID / ELIGIBLE**, amount **700**, cap **4100**, as a decision
only. The fresh credits, card limits, native ticks and exact auction identity
support that decision.

The first actual cache read missed; the final admission reused the just-completed
24-hour entry with zero additional valuation searches. Independent read-only
reopening of the real cache and journal found the completed two-sample payload,
resale 4900 and matching durable DECISION. There were zero journal bid commands.
See [restart-readback.json](../../attempts/20261114-adapter-repair-gate-06/restart-readback.json).

Complete commands, native rows, context/epoch fences, cache inventories, local
helpers and ordinary diagnostic evidence are in the
[gate checkpoint](../../attempts/20261114-adapter-repair-gate-06/gate.json),
[wire summary](../../attempts/20261114-adapter-repair-gate-06/wire-summary.json)
and [transport trace](../../attempts/20261114-adapter-repair-gate-06/transport.json).

The monotonic stopwatch starts before initial caps/helpers/cache lookup and ends
after the ordinary durable final decision and its checkpoint write:

- Start UTC: `2026-11-14T02:42:07.434681+00:00`.
- Final decision UTC: `2026-11-14T02:42:19.490383+00:00`.
- Monotonic elapsed: **12,069,805,600ns = 12.069805600s**.
- Thirty-two commands inside the timer; 34 total including authentication and
  broad discovery. Ordinary transport, helper, journal and diagnostic work remains
  inside the measurement. Passive evidence export/independent assessment and this
  report run afterward and do not substitute for timed production work.

| Recorded component | Milliseconds |
| --- | ---: |
| EA RTT | 1281.800 |
| Serialized executor queue | 8584.483 |
| Browser bridge | 1651.857 |
| Native helpers | 0.200 |
| Other native service work | 26.300 |
| Transport SQLite | 383.123 |
| Foundation SQLite | 54.969 |
| Diagnostic logging, inclusive | 51.967 |
| Diagnostic SQLite subset | 48.704 |
| Diagnostic non-SQLite subset | 3.262 |

Inclusive/subset timing fields overlap; summing this table is not a replacement
for the independently retained monotonic elapsed time.

## Behavioral regressions and independent assessment

Before the sixth gate, full discovery passed **553 Python tests** and **20 Node
suites**. Final discovery after the additional finite-harness regression passed
**554 tests, zero failures, zero errors**; all **20 Node suites** passed.
Exact argv commands, raw output, counts, exits and captured-log integrity hashes
are retained in [offline-checks/results.json](offline-checks/results.json) and
[final-checks/results.json](final-checks/results.json).

New executed regressions cover successful metadata fanout across the JavaScript
and Python boundary, actual retained request counts, wrong metadata identity,
wrong host/authentication/filter, incomplete response, duplicate target/metadata
requests, unknown reads and writes, failure delivery, no duplicate dispatch,
malformed pricing-row exclusion and consumed finite-window refusal. Native
availability, context, epoch and authentication negatives remain enforced.
There are no source-file hash assertions.

A post-gate focused offline run initially found one test-isolation failure:
`test_original_failure_immutable_new_attempt_independent_budget_and_selection`.
Its temporary second-attempt fixture isolated attempts 3–5 but omitted the new
sixth path, so the real sixth checkpoint correctly took precedence. The fixture
now isolates that path too. Its selector and failure assertions are preserved;
no test was deleted or skipped, and no live gate was rerun. Details are retained
in [outcome.json](outcome.json). The final 554-test run passes with the real sixth
checkpoint present. A defensive new metadata identity projection also preserves
the existing malformed-pricing-row exclusion contract.

All these passive independent checks returned exit 0:

```text
python tests/validate_adapter_repair.py
python tests/validate_00203_gate.py
python tests/validate_00203_stop.py
python tests/validate_00203_stop.py --original
python tests/validate_00203_stop.py --attempt 20261114-preflight-remediation-01
python tests/validate_00203_stop.py --attempt 20261114-bounded-discovery-03
python tests/validate_00203_stop.py --attempt 20261114-authenticated-retry-04
python tests/validate_00203_stop.py --attempt 20261114-instrumented-gate-05
python tests/validate_adapter_diagnosis.py
python tests/validate_remediation_live.py
python tests/validate_bulk_transfer_evidence.py
python -m fc_access.release_audit_v1
git diff --check
```

`validate_adapter_repair.py` reads the actual retained probes, checks independent
worker/local ACKs and one native invocation, validates the preserved historical
checkpoints, then reconstructs the sixth gate's pricing, legality, cache and fresh
decision proof. It sends no requests. Historical stop validators passing means
they correctly preserve failure and refuse re-entry; it does not promote those
failed attempts to successful live gates.

## Orchestrator handoff

**READY TO RESUME ITEM 4.** This establishes the read-only item 3 acceptance,
not the future trading outcomes or final item 12 E2E. No items 4–12 were
implemented or started here. The adapter's live special-metadata branch and the
read-only Foundation admission path are verified; actor, rebid, win, listing and
maintenance behavior remains the orchestrator's subsequent work.

After committing and pushing this report, tests, harness and evidence to `main`,
the final action is the existing orchestrator CLI:

```text
C:/hustle/agent-orchestrator/.venv/Scripts/orchestrator.exe --db C:/hustle/fc-hustle/.orchestrator/state.db recheck obj-29bea3b74eb3/002-03
```

This queues the existing blocked task; it does not replace the objective, edit
its DB state or replay any live gate. The worker can use the default retained
PASS validator and continue through normal independent acceptance. Stop this
remediation immediately after the recheck acknowledgement and let the
orchestrator own subsequent work. The recheck is intentionally still pending
when this pre-handoff report is committed.
