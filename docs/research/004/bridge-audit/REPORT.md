# Controller bridge audit and balance repair

2026-11-16. Starting main: `c604ca1bbaf445f53d9c4b403d8a9a9f2383e47f`.
That committed state is the pre-change source backup. No existing runtime
database, historical checkpoint, experiment budget or objective was modified.

**Balance is repaired and verified live. Overall controller readiness remains
BLOCKED by a separately reproduced request-attribution defect in the shared
schema-2 bridge.** Successful ordinary reads do not clear that defect. Remaining
mutation coverage is described below; this is not a full trading E2E PASS.

## Scope and evidence classes

The request authorized the balance fix and an audit of all bridge operations
needed by `controller_v1`. This audit launched no controller/actor/cron job and
performed no bid, purchase, item move, listing, sold clear or relist. Two new
finite, read-only windows used the real Edge Web App, reviewed production
extension, production controller adapter and localhost service. Both services
had `write_authority=False` and held the canonical account/native/port guards.
All commands were allowlisted reads, with durable reservations before delivery.

Existing official Web App authentication was retained. Foreground control was
verified by this worker; a second Edge window required selection of the actual
FC tab/window and the existing foreground recovery helper. The production
extension was reloaded and a fresh document selected. Normal attachment bound
the current native user/PC persona to the established public account context.
No saved credentials, cookies, authentication values or EA session identifiers
were inspected or exported. Only header-presence booleans are captured.

Evidence below distinguishes **current live ordinary-path success**, **offline
behavioral failure**, **historical live proof**, and **not exercised**. An empty
inventory response proves the empty response path, not nonempty ownership or
transaction completion. Offline fixtures are never presented as live requests.

## Fixed defect F1: balance native return shape

The old readiness failure is preserved under
`private-captures/controller-readiness/20261116T203140Z`: a genuine authenticated
HTTP200 followed by `schema_unrecognized`, not a failed login. The earlier
offline diagnosis is retained separately under
`private-captures/controller-balance-diagnosis/20261116T203726Z`.

EA's DAO converts HTTP `currencies[].name/funds` into native currency objects.
`services.User.requestCurrencies()` updates the user and returns
`UTServiceResponseDTO.data={coins,packs,points,tokens}`. Its COINS object has
`type`, `amount` and `value()`. The schema-4 controller originally looked only
for `(response.response ?? response.data).credits`, a field absent from that
service DTO. The schema-2 page also supported refreshed user coins; that native
contract was lost when Objective 004 added the separate adapter.

The primary native fixture hardcoded `response:{credits:90000}` and could not
override the balance payload with its ordinary data option. That invented
callback shape hid the regression. Prior 004 live probes exercised
watched/status/watched and supplied no genuine balance callback coverage.

### Applied changes

- `browser/production-v1/controller.js`: consume the native `data.coins.value()`
  and require COINS type plus a nonnegative safe integer. Privately extract
  exactly one COINS/funds value from the **same owned XHR** and require equality.
  This adds no GET. Zero remains a valid balance. No cached-user fallback,
  authentication relaxation, endpoint change, pricing change or Python output
  schema change was introduced. Other native failure checks remain in force.
- `tests/controller_native_checks.cjs`: model the actual currency DTO and wire
  currencies array, including explicit invalid-payload and response-type options.
  Existing functional assertions remain.
- `controller_balance_native_checks.cjs`: 39 cases run the shipped bridge and
  the captured official DAO/service/currency-VO methods. They test replacement
  of stale 17 coins by fresh 54321, legitimate zero, text/JSON/arraybuffer XHR,
  missing/duplicate/wrong currency, invalid numbers, wire/DTO disagreement,
  failed auth/status/persona, no owned send, timeout, replay prevention and
  cleanup/non-poisoning. The reviewed public method excerpt is
  [native-currency-contract.json](native-currency-contract.json); no source hash
  or source-byte assertion authorizes execution or passes a test.

The real fixed balance read at **20:53:13.242 UTC** captured exactly one
`GET /ut/game/fc27/user/credits`, HTTP200, designated account verified and
**63702** coins. The complete sanitized response is in
[live-01/checkpoint.jsonl](live-01/checkpoint.jsonl). This is the current live
verification of F1, independent of the synthetic 54321 test value.

## Operation inventory

All endpoints below are under `/ut/game/fc27/`. All current captured EA GETs
returned HTTP200 from `utas.mob.v1.prd.futc-ext.gcp.ea.com`. Native method names
are actual current production calls; request selectors stay private in Edge.

| Controller capability | Native API and wire operation | Current evidence / outcome | Remaining issue or proposed action |
| --- | --- | --- | --- |
| Entry balance, schema4 | `User.requestCurrencies()`; GET `user/credits` | LIVE PASS: 63702, one GET; native DTO/wire equality enforced | F1 fixed; 39 offline cases |
| Watched, schema4 | `Item.requestWatchedItems()`; GET `watchlist` | LIVE PASS: valid empty set, account verified | Nonempty path has prior 004 live proof; currently no watched targets |
| Watched, schema2 | Same native method/GET | LIVE ordinary empty path PASS | F2 attribution FAIL; fix shared capture |
| Exact batch status, schema4 | `Item.transfersDao.getAuctionData([nativeDTO,...])`; GET `trade/status/lite?tradeIds=...` | LIVE PASS: ten fresh market targets, ten returned, no omissions, all full-version links validated | No current watched/participation case because watchlist empty; no guessed historical IDs |
| Discovery, schema2 | `Item.searchTransferMarket(criteria,1)` after native cache invalidation; GET `transfermarket` | LIVE ordinary PASS: 21 rows, `start=0,num=21,macr=1000,minb=11000` | F2 attribution FAIL; fix shared capture |
| Exact-version pricing, schema2 | Same native search with `criteria.defId=[251852]`; second adds `maxBuy=4600` | LIVE ordinary PASS: two 21-row samples; actual second wire `maxb=4600` | Shared search inherits F2; valuation/cache evidence does not repair ownership |
| Native card limits | `Item.transfersDao.getItemMarketDataByDefId([251852])`; GET `marketdata/pricelimits?defId=251852` | LIVE ordinary PASS: min700/max11250, correct version | F2 attribution FAIL; fix shared capture |
| Native increments / legality | `UTCurrencyInputControl.getIncrementAboveVal/BelowVal` | LIVE local PASS: above500=550, below11000=10750; production legal/floor calls completed | No EA request; existing scope/helper-consistency checks retained |
| Complete Transfer List | `Item.requestTransferItems()` after dirtying; GET `tradepile` | LIVE ordinary PASS: five active rows, native/wire/repository counts all5, complete=true | F2 attribution FAIL; fix shared capture |
| Unassigned | `Item.requestUnassignedItems()` after dirtying; GET `purchased/items` | LIVE ordinary empty-path PASS | F2 attribution FAIL; nonempty owned-item path not freshly live verified |
| Exact owned item | `Item.requestItemsById([exactRawId])`; GET `item?idList=...` | NOT EXERCISED LIVE: no freshly known closed/highest native-won watched target | Offline contract tests pass; F2 reproduced. Retest after a genuine known win; never substitute another card or historical ID |
| Initial bid / rebid, schema4 | `Item.bid(exactRaw,minimum)`; PUT `trade/<exact>/bid`, body `{bid:amount}` | OFFLINE PASS: exact body/identity, native receipt, empty/stale/rejected/timeout/non-replay cases and independent status handoff | No fresh mutation in this audit. Prior repaired primitive has genuine bid/readback proof; that does not certify this controller's full active bidding lifecycle |
| Move known won card | `Item.move([exactRaw],ItemPile.TRANSFER,false)`; PUT `item` | OFFLINE composition PASS; not dispatched live | Shared-path F2 boundary needs correction; exact paid ownership/capacity and independent readbacks still required. No current live move certification claimed |
| List known won card | `Item.list(exactRaw,start,storedBIN,3600)`; POST `auctionhouse`, followed by native status refresh | OFFLINE composition PASS; not dispatched live | Same shared boundary concern; preserve fixed native tick, stored BIN, 3600 and owned auxiliary GET. No current live list certification claimed |
| Bulk Clear Sold | `Item.clearSoldItems()`; DELETE `trade/sold`, with native Transfer List refresh | OFFLINE current composition PASS. HISTORICAL LIVE PASS: five sold removed, expired/active preserved | No new mutation and no sold rows currently observed; shared boundary concern. One mutation can have additional native GETs; do not enforce one total request |
| Bulk Relist All | `Item.relistExpiredAuctions()`; PUT `auctionhouse/relist`, empty query/body | OFFLINE current composition PASS. HISTORICAL LIVE PASS: four expired relisted at unchanged prices/3600 | No new mutation and no expired rows currently observed; shared boundary concern. Duration is observed server behavior, not an input parameter |
| Completed pricing cache | Production `PricingService` + `QuoteCache`, TTL86400 | LIVE PASS: completed quote reused with zero extra GET; reopened cache readable | Preserves original observation time/scope. Cache is valuation evidence, never bid or ownership authority |

The historical bid proof is
`docs/research/003/003-04/bid-receipt-repair-01/REPORT.md`.
Historical bulk outcomes and exact requests are in
`docs/research/002-bulk-transfer-operations/REPORT.md`; their consumed windows
were not replayed. `002-08/REPORT.md` explicitly describes offline move/list
verification, and `002-12/REPORT.md` remains PARTIAL. Those publications are not
upgraded to live move/list success by this audit.

## Additional confirmed defect F2: shared request attribution

`page.js:capture()` wraps global `XMLHttpRequest.open/send` and accepts matching
traffic without proving that the XHR was sent by this command's native request.
`controllerReadInvocation()` wraps native queue requests to disable retry/reauth
and clean up, but the capture does not consume an ownership marker or require
that any tagged native request actually sent. Exact URL/query/status checks are
necessary but insufficient to establish causality.

The finite diagnostic command is:

```powershell
node tests/audit_controller_bridge_attribution.cjs <new-output.json>
```

It executes the shipped page/controller in the offline native scene with
synthetic HTTP and native DTOs; zero live EA traffic or account mutations occur.
The [expanded result](attribution-audit-expanded.json) contains nine checks:

- **Six FAILs:** search, watched-v2, caps, transfer_list, unassigned and
  owned_item accept `success=true` when the native invocation sends nothing
  through the queue and a separate matching unowned GET occurs. Exact owned
  provenance should have been rejected, even though the native callback and
  HTTP shape look valid.
- **One FAIL:** a real shared search plus an unrelated status GET returns
  `ambiguous_network`; unrelated UI traffic should be diagnostic background.
- **Two PASS controls:** schema4 watched rejects an unowned lookalike when its
  native request does not send, and accepts its genuine owned read alongside
  unrelated background traffic.

This command **exits1** because the current contract fails. Its failures are not
skipped, relabeled successes or hidden behind the passing conventional suite.
The first smaller diagnostic is retained as [attribution-audit.json](attribution-audit.json).
The expanded result is a separate capture, not an overwrite of that evidence.

The same shared capture is used for move/list/clear/relist. Their normal fixture
paths pass, but they cannot be certified robust against UI interleaving from
those positive tests. The direct false-attribution reproduction covers the six
reads above; it is not a claim that a live mutation was falsely acknowledged in
this audit. Current schema4 bid/balance/watched/status have their separate
request-object ownership implementation and do not use this shared capture.

### Proposed F2 fix, not applied

1. Add private request-object-to-XHR ownership to the **new-mode shared seam**,
   reusing the schema4 design. Tag the request created by the actual invocation;
   keep its send wrapper through queue delay. Capture protocol evidence only
   during that owned object's send, not every matching global XHR or every
   request while an observable is pending. Zero native sends must fail even if
   an unowned request has the same method, endpoint, query and status.
2. Treat unowned traffic only as bounded sanitized diagnostics. Preserve all
   existing scope, current-document, raw-item identity, body, query, status,
   freshness and server-intent/tombstone validation.
3. Explicitly associate native child requests with their parent invocation:
   search attributes/metadata, list's exact new-trade status refresh and Clear
   Sold's Transfer List reads. Do not use a global callback/busy window as proof
   of ownership. Enforce exactly one primary read/mutation and only the reviewed
   auxiliary contracts. Preserve required native follow-ups and their counts.
4. Retain per-request no-retry/no-reauth for mutations, scoped timeout/late
   cleanup and no replay. Abort/remove only owned requests; keep ordinary
   ambiguous outcomes non-blocking for unrelated future controller work. Leave
   legacy entry-point policies and sealed historical evidence unchanged.
5. Integrate the adversarial matrix into the regular Node behavioral suite,
   require all nine results PASS, and expand to each mutation plus auxiliary
   reads with synthetic side effects. Repeat bounded read-only live checks in
   a new checkpoint. Real mutation/live lifecycle validation remains separate;
   no endpoint substitution, guessed ID, strategy change or blind retry.

This is a bridge ownership repair, not an EA API change or a request-parallelism
change. It also addresses the mechanism by which manual UI activity can spoil
shared reads; user clicks are not evidence that failed bot writes succeeded.

## Actual live windows and pricing evidence

| New window | Limit | Reserved | Captured GETs | Native commands | Mutations |
| --- | --- | ---: | ---: | ---: | ---: |
| [live-01](live-01/result.json) | 18 EA requests, 80 commands, 600s | 12 | 9 | 25 | 0 |
| [live-02](live-02/result.json) | 3 EA requests, 2 commands, 600s | 3 | 2 | 2 | 0 |
| Total | Separate single-use checkpoints | 15 | **11** | **27** | **0** |

Search reserves up to two GETs to allow reviewed attribute fanout; helpers reserve
zero. Actual captures used no metadata fanout. The remaining 16 live-01 commands
were local helper evaluations, not additional EA GETs. Both services closed with
zero pending WAITING/CLAIMED commands. Live-02 used fresh discovery because the
current watched set was empty; its targets came from that new document's native
read, never a historical/native-ID guess.

| UTC request start | Operation and sanitized query | HTTP | Returned |
| --- | --- | ---: | ---: |
| 20:53:13.242 | GET user/credits | 200 | 63702 coins |
| 20:53:15.247 | GET watchlist, schema4 | 200 | 0 rows |
| 20:53:17.261 | GET watchlist, schema2 | 200 | 0 rows |
| 20:53:19.241 | GET tradepile | 200 | 5 active rows, complete |
| 20:53:21.251 | GET purchased/items | 200 | 0 items |
| 20:53:23.242 | GET transfermarket: start0/num21/macr1000/minb11000 | 200 | 21 rows |
| 20:53:25.241 | GET marketdata/pricelimits: defId251852 | 200 | min700/max11250 |
| 20:53:27.275 | GET transfermarket: start0/num21/definitionId251852 | 200 | 21 rows |
| 20:53:29.244 | GET transfermarket: same exact version, maxb4600 | 200 | 21 rows |
| 20:55:55.633 | GET transfermarket: start0/num21/macr1000/minb11000 | 200 | 21 rows |
| 20:55:57.644 | GET trade/status/lite: exact ten retained native trade selectors | 200 | 10 rows, zero missing |

The full pseudonymized identities and exact sanitized queries/statuses are in
each append-only checkpoint. Native IDs and authentication values are private.
`sealed-live-evidence.json` preserves integrity of seven captured response/log/
experiment-state files only; it does not hash current source, tests or instructions.

The selected real pricing version was **251852**. The first minimum valid BIN
was **4600**, allowing the second pricing search. Its real wire parameter was
`maxb=4600`. The combined minimum became **4200**, with 39 valid unique comparable
auctions after excluding the candidate once and two duplicates. No default
600/10000 templates occurred in this sample; their exclusion remains covered by
behavioral tests. Tax is210, profit threshold500, raw ceiling3490 and native legal
ceiling**3400**. Exactly two pricing searches occurred; no third pricing GET.
Completed cache reuse returned4200 with zero additional GET and survived close/
reopen. This was an operation audit, not another timed 002-03 gate or a bid.

`tests/check_controller_bridge_audit.py` independently parses every retained
command/response at its original observed time, checks the read-only budgets,
methods/statuses/context and exact ten-target links, and replays the actual
production PriceService/PricingService over those sealed response envelopes in
temporary storage. It reproduces first_min4600/resale4200/cap3400/exclusions and
a zero-request cache hit. It never invokes Edge, localhost or EA.

## Verification and current disposition

The recorder stores full stdout/stderr, commands, exit codes and timings under
`checks/`; no old receipts were regenerated. Results are:

| Command / group | Result |
| --- | --- |
| `python -m unittest discover -s tests -v` | PASS: 1064 executions, 1047 distinct methods; zero failures/errors/skips; 478.201s wall time |
| Every `tests/*checks.cjs`, via `python tests/record_00405.py node ...` | PASS: all34 Node suites, including39 balance cases |
| `python tests/record_00405.py independent ...` | PASS: nine validators over retained evidence and legacy contracts |
| `python tests/check_controller_bridge_audit.py` | PASS: seven captured-file integrity checks, all11 GETs, exact ten-target links, independent pricing/cache replay |
| `python tests/test_controller_bridge_audit.py` | PASS: both final balance/retained-evidence regressions |
| `node tests/audit_controller_bridge_attribution.cjs <new-output.json>` | **FAIL, exit1: seven failures / two passing controls**; six false-attribution cases plus interference breaking search |
| `git diff --check` | PASS |
| `powershell -NoProfile -File tests/collect_00405_state.ps1` | No production workers/listeners or scheduled mutation jobs; retained in final-state.json |

The nine existing independent commands are the two 004 artifact gates, retained
002-03 gate/stop validators for `20261114-adapter-repair-gate-06`, adapter repair,
bulk blocker recovery, 003 baseline, 003 production prepublication, and sealed
bulk transfer evidence. They do not contact EA. The new standalone checker is
additional. The final command receipts and failing audit result are in
`checks/final/`; the known failing diagnostic is recorded as FAIL, not converted
to PASS because its failure was anticipated. It is a separate adversarial audit
tool rather than a skipped conventional test. Integrating its contract checks
into the regular suite is part of the proposed F2 repair.

The adversarial attribution failure remains the readiness blocker regardless
of the passing conventional regression results. The minimal watchdog monitors
process progress; it does not detect this semantic provenance defect or make it
safe to trade through it.

**Do not launch live trading on the strength of the repaired balance alone.**
F1 is fixed; F2 needs the implementation above. Exact owned-item, active
bid/rebid, physical move/list and new-mode bulk mutation outcomes remain outside
this fresh live audit. Missing live prerequisites are evidence limitations, not
fabricated operation failures or requests for the user to manufacture a win.
No automatic recovery/restart or orchestrator recheck was started.
