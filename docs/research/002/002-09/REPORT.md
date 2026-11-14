# 002-09: production native bulk Transfer List integration

Implemented and verified offline against production Python/JavaScript boundaries.
The native APIs retain their prior live proof in
[`002-bulk-transfer-operations/REPORT.md`](../../002-bulk-transfer-operations/REPORT.md).
This task made no EA requests, started no live production service or maintenance job, and did
not reopen the consumed finite research window. Production integration itself
was exercised with synthetic native services, not a new account mutation.

## Explicit caller contract

On an attached `fc_access.production_v1.foundation.Foundation`, call:

```python
foundation.bulk('clear_sold')
foundation.bulk('relist_all')
```

Each call is finite. Construction, imports and elapsed time do not launch it.
The ordinary production page and worker execute these operation names. The
separate `bulk_*` research dialect remains rejected by the production service.
The default service without an intent journal still rejects all mutations.

| Production operation | Native invocation (zero arguments) | Captured mutation contract |
| --- | --- | --- |
| `clear_sold` | `services.Item.clearSoldItems()` | One `DELETE /ut/game/fc27/trade/sold`, empty query/body |
| `relist_all` | `services.Item.relistExpiredAuctions()` | One `PUT /ut/game/fc27/auctionhouse/relist`, empty query/body |

There is no duration parameter in either production command or native call.
The browser blocks extra mutations, per-item paths, unexpected routes, queries
and bodies before XHR delivery. Clear Sold permits at most two ancillary native
Transfer List GETs, holding the same serialized boundary for the entire native
observable. Native response status must be 200. Metrics count ancillary requests.

## Authority, accounting and reconciliation

`fc_access/production_v1/bulk.py` composes the existing production adapter,
scheduled executor, journal authority, account write lock and capacity ledger.
Maintenance defaults to scheduler priority 0; watched/status/bid work defaults
to 90. The existing actor mailbox also routes explicit maintenance commands at
priority 0 through its sole broker. No recurring caller was added.

A forced fresh Transfer List read must establish matching wire, callback and
repository inventories, native end-of-list, unique physical items, ownership and
native sold/expired/active predicates. The intent records **all** inventory IDs,
all eligible IDs, both eligible counts, and the complete before-read. Manually
listed cards need no actor policy to be included. Preflight commits physical
occupancy with the intent; only independent verified readback releases slots.
An empty eligible set skips dispatch after a complete read.

Inactive/unclassified items, ownership ambiguity and contradictory native
predicates fail closed. Relisting with simultaneously present sold items is
unproven by the sealed live batch and is rejected before intent. Clear Sold can
run first; relisting then requires its own new complete read.

The immutable intent and separate consumed dispatch claim commit before the
native call. Context, owner/epoch and all host/worker/document fences must match
the production peer. The page rechecks native DTO identity, current membership,
prices, predicates, selected persona and document ownership before invocation.
Preflight must remain at most 30 seconds old through dispatch. A takeover or
stale preflight leaves the consumed claim unresolved and cannot authorize retry.

An ACK is not confirmation. A separately forced `transfer_list` command after
the handoff must prove exact physical inventory conservation, unaffected item
fields and nonincreasing unaffected expiry. Clear Sold must remove exactly its
sold set. Every relisted physical item must retain its definition and prices,
have a distinct new trade ID, and be active with zero bid and **observed expiry
exactly 3600 seconds**. Elapsed-time extrapolation is deliberately insufficient:
a delayed recovery that first observes 3599 seconds remains unresolved.

Readback, state advancement and physical capacity accounting share a commit.
Changed prices, duration, physical identity or unaffected inventory produce a
sticky incompatibility. Partial outcomes, missing reads and lost callbacks stay
unresolved unless an independent complete read proves all required invariants.
While any bulk intent is unresolved, acquisition and resale writes are blocked.

Restart recovery reads retained intents under the same full account context and
identity namespace with fresh current-epoch reads. It never reuses an old mapping
for mutation or resends an INTENT/UNKNOWN/ACKNOWLEDGED command. A call encountering
pending bulk work performs reconciliation only, even if that reconciliation
succeeds. It cannot dispatch the requested next operation in the same call.

## Repeatable acceptance checks

Run independently from the workspace:

```text
python tests/test_00209_bulk.py
python tests/validate_bulk_transfer_evidence.py
```

The first suite has 20 behavioral cases, including a native JavaScript VM suite
and ten real subprocess exits (both operations at intent/claim/send/ACK/readback).
It uses temporary SQLite databases and native doubles only. The second validates
sealed transaction captures, immutable logs, consumed budgets, the exact historical
DELETE/PUT requests and their independent readbacks. Neither hashes mutable source
or configuration files or requires fresh sold/expired EA inventory.

| Acceptance index | Evidence |
| --- | --- |
| 0 | Production protocol/SQLite tests; deployed page/worker VM checks zero native arguments, single guarded DELETE/PUT and no per-item fallback |
| 1 | Sealed evidence validator; empty-inventory test prohibits network/process creation and observes no research commands |
| 2 | Account-wide manual fixtures; fresh complete inventory negatives; intent/claim commit checks; all context/fence negatives; takeover/age tests; scheduler ordering; independent read/capacity checks |
| 3 | Exact successful relist readback; duration/price/identity/trade negative cases; native call arguments and empty request checks |
| 4 | Partial/no-effect ACKs, ambiguous/lost responses, sticky changed semantics, durable commit failures, read-only restart reconciliation and ten abrupt process exits |
| 5 | Construction/time-advance tests prohibit recurring workers; deployed page/worker does no import-time maintenance; all mutations are synthetic |

Existing production contract, foundation, native inventory, actor, occupancy,
capacity, enrollment, resale and finite research regression suites are also
checked. Historical protocol tests retain their sealed original operation subset;
new bulk behavior is covered by the dedicated suite.
