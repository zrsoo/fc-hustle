# FC27 native bulk Transfer List operations

**Both capabilities PASS; API contracts READY for integration.** Live execution on
2026-11-13 used the official FC27 PC Web App in Edge and the production native
extension/localhost transport. Exactly one Clear Sold invocation removed five sold
entries. Exactly one Relist All invocation relisted four expired cards at unchanged
prices for one hour. Separate forced EA Transfer List GETs confirmed both outcomes.

| Capability | Native API | Live outcome | Integration status |
| --- | --- | --- | --- |
| Bulk Clear Sold | `services.Item.clearSoldItems()` → `DELETE /ut/game/fc27/trade/sold` | PASS: five removed, four expired and three active preserved | READY: contract verified; scheduled job unimplemented |
| Bulk Relist All | `services.Item.relistExpiredAuctions()` → `PUT /ut/game/fc27/auctionhouse/relist` | PASS: four relisted, prices preserved, 3600 s each, three active preserved | READY: contract verified; scheduled job unimplemented |

This assessment covers these maintenance capabilities. It does not establish that
Objective 002's actors or recurring jobs have been implemented or validated.
This work did not modify Objective 002. During the push, remote `main` advanced
through planning commits `7295203` and `e6500e9`; they were retained by rebasing this
work. The updated objective locks one-hour listings, 61-minute bulk relisting and
combined 50-slot capacity. This report supplies the targeted bulk API proof for
item 9. It does not execute the pricing gate or any other ordered Objective 002
implementation item, and does not change its locked strategy or acceptance rules.

## Authorization, account selection and bounded execution

The initial authorization covered two sold and one expired entry. Fresh inventory
instead contained five sold, four expired and three active. No mutation was sent
under that mismatch. The user explicitly expanded authorization: **"Authorize all
5 sold and 4 expired"**. [user-authorization.json](user-authorization.json) and the
`EXPLICIT_USER_AUTHORIZATION_REVISION` event in [durable-ledger.json](durable-ledger.json)
record that change.

After the user's login correction, the unique saved-account suggestion matching
the user-designated account was selected through normal Edge UI, followed by NEXT
and SIGN IN. No credential values, authentication headers, cookies or session
identifiers were exported. A new public account/persona context was bound to the
selected native user/persona objects. The earlier
[initial-transfer-list.json](initial-transfer-list.json) is quarantined: it predates
that explicit login selection and supplied no authority for either write. It is
not assumed to be the same account. The fresh
[selected-account-initial.json](selected-account-initial.json) independently found
the same counts after the designated login.

Public local correlation labels for the executed operations:

```json
{
  "account": "aaa083e34a2b2243919889ab1c2a9d7e",
  "persona": "4508543c69902bc52e86f5fc36bdf8d5",
  "identity_namespace": "fee5075c1ad619c51fa7a805c8d8b65a",
  "game": "fc27",
  "platform": "pc",
  "owner": "3e5ad73a0453bcb4338421575d06857f",
  "epoch": 16,
  "document": "e90d3a6e668f2028dac89e5e7ceee8f4",
  "host_epoch": "ccbbd2e0c2f4a378c1360b9f560f779c",
  "worker_epoch": "73716681bbf6aa030267f3ed0c54c4ae"
}
```

These are local pseudonyms and execution fences, not EA authentication values.
Runtime item/trade hashing provides correlation within this namespace. No source
hash, source byte comparison or historical-source assertion authorizes execution.
The native selected user/persona must remain the same objects and the platform
must remain PC throughout the operation; a context or document change requires
new reads and reconciliation.

The finite research window retained its original deadline (20:52:02.818 UTC),
counters and consumed slots across recovery, account selection and the explicit
authorization revision. Limits: eight inventory commands, eight local inspections,
one write slot per bulk operation. Consumed: six external inventory commands, two
local inspections, both write slots. The six explicit reads plus Clear Sold's
internal refresh comprise **seven GETs; with the DELETE and PUT, nine captured EA
requests in total**. Inspections issued zero EA requests. These counts cover the
explicit instrumented experiment, including the quarantined read; they do not
claim to count unrelated login/startup background traffic globally.

## Discovered native contracts

The loaded client's Item service, transfers DAO, Transfer List controller,
viewmodel and AuctionData methods were inspected locally. Captures:
[source-inspection.json](source-inspection.json),
[selected-account-source.json](selected-account-source.json). Behavioral tests
execute the captured DAO functions in isolated native doubles and check their
requests and response mapping. Live requests/readbacks establish actual behavior.
Historical context was read in [purchase-to-list.md](../purchase-to-list.md),
[transaction/source-review.json](../transaction/source-review.json) and
[transaction/verification.json](../transaction/verification.json). Earlier
individual listing evidence did not establish either bulk operation.

### Clear Sold

Call **`services.Item.clearSoldItems()` with zero arguments**. Its observable
callback receives `(sender, UTServiceResponseDTO)`; use `observe(owner, callback)`
and detach that observer on completion. The optional Item argument selects the
individual operation; do not pass one for bulk maintenance.

The service calls `services.Item.transfersDao.removeSold()` with no argument.
The DAO's omitted selector defaults to `"sold"`. The actual FC27 request was:

```http
DELETE https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/trade/sold
Query: none
Body: empty
Response: HTTP 200, empty body
```

The historical `DELETE /tradepile` candidate is not this client's Clear Sold
contract. One native bulk invocation produced **one DELETE**, never per-item
deletes. The high-level service also obtains the transfer inventory, marks it
dirty after success and refreshes it before notifying. Here the initial service
read used the preflight-populated native repository; its post-delete refresh
issued one GET. With a dirty initial repository, the service can also issue a
pre-delete GET (covered offline). Reserve the serialized executor for this whole
native observable and budget its ancillary reads.

The actual high-level callback projected `success=true`, `status=200`, no numeric
error code and `data.itemIds` containing the exact five removed physical item
identities. These IDs are derived by the Item wrapper's before/after comparison;
the DELETE body itself provides no affected-ID list. An additional independent
fresh GET remains required.

The operation addresses the selected account's sold Transfer List entries
globally. There is no actor-ownership/item subset input. Manually listed eligible
cards are within its scope. Five sold entries were tested; the four expired and
three active entries were preserved.

### Relist All

Call **`services.Item.relistExpiredAuctions()` with zero arguments**. It delegates
to `services.Item.transfersDao.relistExpiredAuctions()`. Actual request:

```http
PUT https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/auctionhouse/relist
Query: none
Body: empty
Response: HTTP 200
JSON keys: tradeIdList, dynamicObjectivesUpdates
tradeIdList: four objects whose idStr values identify the new auctions
```

The DAO maps `response.tradeIdList[].idStr` to
`UTHttpResponseDTO.response.auctionIds`; it also processes optional objective
updates. The higher Item wrapper copies success/status/error, marks the transfer
repository dirty, and does **not** forward those auction IDs as its callback data.
The actual high-level projection was success=true/status=200/empty item_ids.
Obtain the new physical-item→trade mapping from the independent native readback;
the sanitized wire list corroborates it. Opaque objective update values were not
exported.

There is **no duration, price, item-list or prior-trade-list parameter**. The
selected account's eligible expired auctions are relisted in bulk, including
manually listed cards. One invocation produced exactly one PUT and four new
auctions. FC27 preserved both existing prices and assigned exactly **3600 seconds**
remaining to every relisted card in the immediate fresh read. One hour is the
observed server default, not a duration transmitted by this request. Future
integration must verify that invariant after each operation and stop/reconcile
if it changes; it must never compensate with another listing mutation.

The native viewmodel's Unsold section can also include valid inactive items.
This experiment contained expired unsold entries and no inactive entries; it
does not establish bulk relist behavior for inactive/unlisted inventory.

## Complete initial Transfer List

The immediate pre-clear native GET ran at 20:43:09.538–20:43:09.675 UTC. It returned
12 auction rows, capacity 100, native `transfer.endOfList=true`, and matching raw
EA/native inventory rows. Native predicates counted five sold, four expired and
three active. All rows had trade_owner=true and bid_state=none. Native sold entries
are represented as trade_state=`closed` with current_bid>0; expired unsold entries
have trade_state=`expired`, current_bid=0 and expires=-1.

| Definition | Physical item pseudonym | Trade pseudonym | Native state | Start | Current bid | BIN | Expires (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 278230 | item:34540558edb339a26932446d | trade:1120c585e1274cdfd9fc98a7 | expired | 200 | 0 | 250 | -1 |
| 234378 | item:5709bad48e1f38e59465dc18 | trade:74fdf685b34620aa5de4312d | closed | 13000 | 13500 | 13500 | -1 |
| 243702 | item:be1bd853bf0166855f3647ca | trade:b67367b238267e25f011e29a | closed | 950 | 1000 | 1000 | -1 |
| 246420 | item:667414cd5f800b38311dc827 | trade:2cf3efa2b13b896814bb558e | closed | 2700 | 4000 | 4000 | -1 |
| 239085 | item:6c1821fd50efcf26deca9cb1 | trade:7d9d8a003cde43cf2eb8be7b | expired | 45000 | 0 | 46000 | -1 |
| 241084 | item:6b630821fa38e4c83ee1f3aa | trade:83b9e8966e5b647b720234bb | expired | 13750 | 0 | 14250 | -1 |
| 236772 | item:baedbe1a7c161538497cdc85 | trade:05233e668e6070caf29b3e9c | expired | 6000 | 0 | 6200 | -1 |
| 257534 | item:918c2f0e64ff7532869be540 | trade:31f72cf86fe24e0d11e54680 | closed | 2200 | 2700 | 3300 | -1 |
| 241096 | item:d67692089850cd9c44d7b20c | trade:54555cdf00fee2c126d75b89 | closed | 2300 | 2300 | 3500 | -1 |
| 247103 | item:5859eff756a310898bae2ece | trade:4d7d8dcef3f8ccadb61e3469 | active | 650 | 0 | 850 | 149100 |
| 244669 | item:d9eeec4640229a959c3145fb | trade:05249929dbc0d3558b281d48 | active | 650 | 0 | 750 | 149116 |
| 220834 | item:0eb531d104feb860cffcade7 | trade:07c13813b33f74951726d718 | active | 650 | 0 | 700 | 149134 |

The three `active` rows above were outside both mutation targets. Their original
longer listing durations were preserved. `expires` is native seconds remaining,
with -1 for ended entries. No absolute server expiration timestamp was invented.

## Actual request chronology and independent readbacks

All requests below used the same official host shown above, no query parameters,
an empty body and the existing native authenticated context. Captures store only
`session_header_present=true`, never the header value. Times are UTC on
2026-11-13. Counts refer to projected auction rows or returned trade IDs.

| Capture | Request | Start UTC | End UTC | HTTP | Rows / trade IDs |
| --- | --- | --- | --- | --- | --- |
| [before-clear-sold.json](before-clear-sold.json) | GET /ut/game/fc27/tradepile | 2026-11-13T20:43:09.538Z | 2026-11-13T20:43:09.675Z | 200 | 12 |
| [clear-sold.json](clear-sold.json) | DELETE /ut/game/fc27/trade/sold | 2026-11-13T20:43:09.747Z | 2026-11-13T20:43:09.883Z | 200 | empty |
| [clear-sold.json](clear-sold.json) | GET /ut/game/fc27/tradepile | 2026-11-13T20:43:09.884Z | 2026-11-13T20:43:09.965Z | 200 | 7 |
| [after-clear-sold.json](after-clear-sold.json) | GET /ut/game/fc27/tradepile | 2026-11-13T20:43:10.055Z | 2026-11-13T20:43:10.133Z | 200 | 7 |
| [before-relist-all.json](before-relist-all.json) | GET /ut/game/fc27/tradepile | 2026-11-13T20:43:22.610Z | 2026-11-13T20:43:22.691Z | 200 | 7 |
| [relist-all.json](relist-all.json) | PUT /ut/game/fc27/auctionhouse/relist | 2026-11-13T20:43:22.755Z | 2026-11-13T20:43:23.303Z | 200 | 4 |
| [after-relist-all.json](after-relist-all.json) | GET /ut/game/fc27/tradepile | 2026-11-13T20:43:23.352Z | 2026-11-13T20:43:23.428Z | 200 | 7 |

Clear Sold command `9259f48e2f78c40ff6dc093c462faaad` followed fresh read
`f204b8270f12c9c07cde8e59fecb5ff8`. The independent post-read
`f1fe05ccc906ab648e1c452d1ccab3b9` started after the DELETE and native internal
refresh completed. Occupancy fell **12→7**, exactly five. The removed identities
are the five closed/sold table rows; all four expired rows remained expired, and
every other field of all seven retained entries was unchanged (expiry can decline
with elapsed time). No external inventory changes were observed. See
[clear-sold-reconciliation.json](clear-sold-reconciliation.json).

Relist command `b5f40caf74204c85dc9a6b30453e11e6` used its own new pre-read
`784b0935ab363cff5a486b77ca34586e`. The independent post-read
`ec476d2366e80e3a7e03ca07839d6411` began after the PUT completed. Occupancy stayed
**7→7**; states changed from zero sold/four expired/three active to zero sold/zero
expired/seven active. All physical identities and exact definitions were stable.
The four returned wire trade IDs exactly match the four new native auction IDs.

| Physical item (unchanged) | Previous trade | New trade | Start (unchanged) | BIN (unchanged) | New expiry (s) |
| --- | --- | --- | --- | --- | --- |
| item:34540558edb339a26932446d | trade:1120c585e1274cdfd9fc98a7 | trade:a81cfb6241ee263e68692ab2 | 200 | 250 | 3600 |
| item:6c1821fd50efcf26deca9cb1 | trade:7d9d8a003cde43cf2eb8be7b | trade:5101b056da54f4fdef96d191 | 45000 | 46000 | 3600 |
| item:6b630821fa38e4c83ee1f3aa | trade:83b9e8966e5b647b720234bb | trade:c6c99019d7a03ff6f5e5d8e7 | 13750 | 14250 | 3600 |
| item:baedbe1a7c161538497cdc85 | trade:05233e668e6070caf29b3e9c | trade:86431fe277f64521fb6091da | 6000 | 6200 | 3600 |

The three pre-existing active cards retained their item IDs, trade IDs, prices,
bid and owner states. Their expiry values immediately before/after Relist All
were respectively 149087/149103/149121 seconds, unchanged by that operation.
No sold entries remained during Relist All, so preservation of simultaneously
present sold entries by relisting was not separately live-tested. Credits were
48351 in all immediate before/after reads. No acquisition, bid, movement or
individual listing occurred.

The expanded authorization enabled **four-item live verification of this bulk
API**. This is stronger than a single-expired-item invocation; it remains one
observed batch, not proof of arbitrary batch sizes or atomic partial-failure
behavior. [relist-all-reconciliation.json](relist-all-reconciliation.json) records
the result; [durable-ledger.json](durable-ledger.json) retains both durable intents,
all ten local commands (two inspections and eight remaining commands), responses
and ordered events. Both intent states are CONFIRMED after independent readbacks.

## Python / JavaScript integration contract

The reusable finite harness is in `fc_access/bulk_transfer_v1/` and
`browser/production-v1/bulk-transfer.js`. It uses the existing production extension,
same native ownership/fences and localhost port 8784. The ordinary production
server rejects this research-only dialect. The separate finite server enables
only inventory, local inspection and one invocation of each authorized bulk
operation; bids and other mutations remain unavailable.

The native invocation forms for future executor integration are:

```javascript
// Run only after a persisted authorized intent and complete fresh inventory.
const observable = operation === 'bulk_clear_sold'
  ? services.Item.clearSoldItems()
  : services.Item.relistExpiredAuctions();
observable.observe(observerOwner, (sender, response) => {
  sender.unobserve(observerOwner);
  // Project success/status/error only. Journal ACKNOWLEDGED_UNRECONCILED.
  // A separate forced requestTransferItems() must prove the outcome.
});
```

Do not call the DAO directly, construct authentication headers in Python or send
raw HTTP mutations. The normal native auth delegate supplies the selected
account/persona context privately. Require the official tab, authenticated PC
persona, local origin restriction, expected extension origin, one executor owner
and matching account/game/platform/persona plus owner/host/worker/document epochs.
Public labels alone do not prove an EA login; selection and private native-object
binding supply that link. A reconnect invalidates the cached inventory/mappings.

Research command JSON schema (validated strictly; extra fields rejected):

```text
{
  schema: 2,
  id: 32-lowercase-hex unique command ID,
  operation: bulk_inventory | bulk_inspect | bulk_clear_sold | bulk_relist_all,
  context: {account, persona, identity_namespace, game: fc27, platform: pc},
  fences: {owner, epoch, host_epoch, worker_epoch, document},
  params: {} for reads/inspection, otherwise {
    before_read_id,
    expected_item_ids: [all eligible physical item pseudonyms],
    expected_inventory_ids: [all current Transfer List physical item pseudonyms],
    expected_sold_count,
    expected_expired_count,
    duration_seconds: 3600  // relist only; local assertion, NEVER sent to EA
  }
}
```

Input counts and target sets must match the complete native read under the same
context/fences, at most 30 seconds old. This finite run's counts were explicitly
authorized as 5/4; relist then required 0/4 and an independently confirmed clear.
No targets means skip without dispatch. Cross-check native isSold/isExpired
predicates against owned ended-state/current-bid classification. Unclassified or
incomplete inventories require operator/reconciliation handling. Recheck current
ownership, target membership and current prices while holding the shared executor;
external/manual account activity can still race the server operation and must be
identified during reconciliation.

Positive output schema:

```text
{
  schema, command_id, operation, context, fences, observed_at,
  success: boolean, error: allowlisted_local_reason | null, status: integer | null,
  network: [{host, method, path, query_empty, request_body: null, body_kind: empty,
             status, session_header_present: boolean, started_at, ended_at,
             response: allowlisted_projection}],
  sources: [{owner, name, source}], // local inspection only
  inventory: null | {rows, occupancy, capacity, complete, native_counts,
                      repository_end_of_list},
  callback: null | {success, status, error_code: integer | null, item_ids}
}
row = {trade_id, item_id, definition_id, starting_bid, current_bid,
       buy_now_price, expires, trade_state, bid_state, trade_owner}
```

Allowlisted wire projections contain empty/json/unparsed kind; recognized key
names and a count of omitted keys; sanitized auction rows/trade IDs; optional
numeric credits/error codes. They omit raw bodies and opaque authentication or
objective-update payloads. Python output after reconciliation must include the
operation, intent/command ID, before/after read IDs, CONFIRMED/UNKNOWN outcome,
removed physical IDs or each physical item's old/new trade and unchanged prices,
observed expiry and occupancy delta.

Required durable lifecycle:

1. Acquire the shared serialized executor under the intended account scope. Give
   urgent Bidder reconciliation/bids priority over maintenance; a dispatched native
   operation itself cannot be preempted. Refresh the full Transfer List using
   `repositories.Item.setDirty(ItemPile.TRANSFER)` followed by
   `services.Item.requestTransferItems()`; verify an actual GET200, matching native
   and wire rows, capacity and endOfList. Preserve all unrelated rows for comparison.
2. Persist the operation, full target identities, prices, before-read ID/context,
   occupancy, authorization, timestamps and immutable intent ID transactionally
   before command delivery. Block writes if durability fails. The harness uses
   the production SQLite durable transaction/journal and append-only events.
3. Dispatch the zero-argument Item method exactly once. The browser rejects repeat
   command IDs, consumes its operation slot before the call and blocks a second
   mutation request before it can be sent. Durable server intent slots survive
   browser/host restarts. Response delivery is also never retried as execution.
4. Record native callback and wire outcome without declaring success. Force a
   new native GET after the write; do not use the service's own cache or refresh
   as the sole independent evidence. Confirm exact sold removal/occupancy change,
   or stable physical IDs, current auction mappings, unchanged prices and active
   one-hour listings. Compare every unrelated entry; expected expiry countdown is
   allowed. Then persist CONFIRMED and update inventory/capacity/registry mappings.
5. On timeout, connection loss, unknown response, unexpected endpoint/body/fanout,
   missing item or conflicting identity, retain UNKNOWN/RECONCILING and the consumed
   intent. Run bounded independent reads under valid authentication; never issue
   the bulk mutation again because a response was lost. Partial results require
   explicit diagnosis, not automatic per-item fallbacks or another bulk invocation.

The native-observable wait is bounded at 18 seconds in the finite harness. HTTP
errors (including auth/access/market locks, throttling and server errors) and native
failure callbacks must retain sanitized status/code, stop writes and enter
recovery/backoff/reconciliation. A locked-transfer-market branch exists in the
loaded Relist Item wrapper. Actual error responses and timeouts were not induced
live; negative cases are deterministic offline tests. A native success or HTTP200
without matching fresh state remains insufficient.

The finite harness permanently keys a consumed slot by operation for this research
window, and refuses an existing capture even before contacting localhost. **Do not
rerun the consumed live commands or reset their files, slots, counters or deadline.**
Future recurring integration needs distinct durable maintenance-batch IDs scoped
to account/game/platform, fresh eligibility snapshots and deduplication of all
unresolved intents across restarts. A later genuinely new eligible batch is a new
intent; a timer firing while an earlier batch is unresolved is never permission
to redispatch it.

Recommended future scheduling: trigger Clear Sold when fresh inventory shows sold
entries; refresh/update occupied capacity only after confirmed removal. Run the
Relist All maintenance check every 61 minutes, skip if no expired items, preserve
prices and verify the observed one-hour result. Both jobs must enqueue through
the Bidder/Acquirer's shared native executor with urgent Bidder work first. Bulk
operations cannot isolate bot-created listings from manually listed eligible
cards, so that account-wide scope must be an explicit maintenance policy. These
jobs and the autonomous actors were **not implemented, started or scheduled**.

## Verification and final state

All checks below ran offline, issuing zero EA requests or mutations. The full
Python suite passed **482 tests, zero failures, zero errors**. The focused suite
contains 15 tests and is also included in full discovery. All **16 Node scripts**
passed. The independent live-evidence validator checks actual wire counts,
statuses, chronology, account selection, exact affected sets, native/wire equality,
new trade mappings, unchanged prices, exact 3600-second live expiries, durable
confirmation and restoration of read-only service.

| Command | Result | Receipt |
| --- | --- | --- |
| `python -m unittest discover -s tests -v` | 482 tests; PASS (exit 0) | [check-00.txt](checks/check-00.txt) |
| `python tests/test_bulk_transfer_v1.py` | 15 tests; PASS (exit 0) | [check-01.txt](checks/check-01.txt) |
| `node tests/bidding_v1_checks.cjs` | PASS (exit 0) | [check-02.txt](checks/check-02.txt) |
| `node tests/browser_observer_checks.cjs` | PASS (exit 0) | [check-03.txt](checks/check-03.txt) |
| `node tests/bulk_transfer_checks.cjs` | PASS (exit 0) | [check-04.txt](checks/check-04.txt) |
| `node tests/durability_page_checks.cjs` | PASS (exit 0) | [check-05.txt](checks/check-05.txt) |
| `node tests/durability_worker_checks.cjs` | PASS (exit 0) | [check-06.txt](checks/check-06.txt) |
| `node tests/e2e_live_v2_page_checks.cjs` | PASS (exit 0) | [check-07.txt](checks/check-07.txt) |
| `node tests/e2e_page_checks.cjs` | PASS (exit 0) | [check-08.txt](checks/check-08.txt) |
| `node tests/market_discovery_bridge_checks.cjs` | PASS (exit 0) | [check-09.txt](checks/check-09.txt) |
| `node tests/market_discovery_followup_v1_checks.cjs` | PASS (exit 0) | [check-10.txt](checks/check-10.txt) |
| `node tests/production_inventory_checks.cjs` | PASS (exit 0) | [check-11.txt](checks/check-11.txt) |
| `node tests/production_page_checks.cjs` | PASS (exit 0) | [check-12.txt](checks/check-12.txt) |
| `node tests/production_worker_checks.cjs` | PASS (exit 0) | [check-13.txt](checks/check-13.txt) |
| `node tests/read_bridge_checks.cjs` | PASS (exit 0) | [check-14.txt](checks/check-14.txt) |
| `node tests/search_validation_v1_checks.cjs` | PASS (exit 0) | [check-15.txt](checks/check-15.txt) |
| `node tests/transaction_bridge_checks.cjs` | PASS (exit 0) | [check-16.txt](checks/check-16.txt) |
| `node tests/watched_bulk_v1_checks.cjs` | PASS (exit 0) | [check-17.txt](checks/check-17.txt) |
| `python tests/validate_bulk_transfer_evidence.py` | PASS (exit 0) | [check-18.txt](checks/check-18.txt) |
| `python -m fc_access.release_audit_v1` | PASS (exit 0) | [check-19.txt](checks/check-19.txt) |
| `python tests/test_001d07_handoff.py` | 7 tests; PASS (exit 0) | [check-20.txt](checks/check-20.txt) |
| `git diff --check` | PASS (exit 0) | [check-21.txt](checks/check-21.txt) |

[checks/results.json](checks/results.json) records exact commands, exit codes,
UTC times and integrity hashes of captured command output. No mutable source
hashes are asserted. [evidence-manifest.json](evidence-manifest.json) seals the
captured JSON evidence and verification logs only; the live-evidence validator
was run again after sealing and passed its integrity and semantic checks. The
manifest contains no implementation files. Captured native responses also passed
the repository's private-field check. Behavioral coverage includes state filtering, scope mismatch,
changed prices/wrong durations, stable physical/new auction identity, unrelated
inventory protection, stale or wrong-context reads, default production rejection,
intent-before-dispatch, concurrent lock ownership, duplicate native request
prevention, lost callbacks/ambiguous outcomes, restart suppression and independent
reconciliation. Captured DAO behavior is exercised without byte-identity tests.

After integrating remote Objective 002 planning commits, full discovery was run
again: **482 Python tests passed, zero failures/errors; all 16 Node scripts passed**.
The live-evidence validator (including the sealed evidence manifest), independent
release audit, seven handoff checks and whitespace check also passed again.
[post-sync-checks/results.json](post-sync-checks/results.json) records those exact
commands, UTC times, exit codes and hashes of the additional immutable output logs.
The earlier receipts and all live captures were preserved unchanged. This repeat
was entirely offline; neither bulk operation was repeated.

The finite mutation-enabled service was stopped after both intents became
CONFIRMED. [restored-readonly-health.json](restored-readonly-health.json) records
the ordinary production service, attached extension, mutations_enabled=false,
and the selected public account scope at epoch 17. Its diagnostic database is
`private-captures/002-bulk-transfer-operations/production-readonly-after.sqlite3`.
The consumed research journal and prior account database were retained. No sealed
historical evidence or earlier experiment counter was changed.

Remaining limits: only this PC account and one five-sold/four-expired batch were
tested; full-capacity batches, inactive entries, mixed sold+expired during relist,
partial server failure/atomicity, rate limits, future server-default changes and
recurring-job load are not live-proven. Offline tests establish guards and failure
handling, not those market-dependent outcomes. Both requested live capabilities
nevertheless have matching independent EA readbacks and satisfy this task's
success criteria. **READY for implementing these contracts in Objective 002's
shared executor; maintenance jobs and actors remain future work.**
