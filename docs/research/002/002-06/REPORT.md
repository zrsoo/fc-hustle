# 002-06: atomic combined capacity

The shared auction journal now stores capacity independently of coin escrow.
`fc_access/bidding_v1/capacity.py` installs an additive SQLite ledger, keyed by
account scope, trade and exact physical item/version. It migrates historical
enrollments, verified outcomes and orphan bid intents without rewriting events.
Read-only historical journals remain readable and report inventory as unknown.

`AuctionQueue.admit` takes `BEGIN IMMEDIATE`, reloads durable state, checks the
prospective unresolved limit and `occupied + pending_resale + unresolved` limit,
and commits the enrollment event and reservation together. Both limits default
to 50 and can only be configured downward. Both Acquirer and the one-shot
`Foundation.admit` obtain validated fresh, complete Transfer List evidence.
Missing, incomplete, stale, conflicting or out-of-order inventory fails closed.

UNKNOWN, missing status, pending intent, lost response, process death and coin
escrow release retain the slot. Independent terminal LOST frees it. Verified WON
changes UNRESOLVED to PENDING_RESALE in the same transaction as terminal evidence
and command reconciliation. An exact item/version in a proven Transfer List read
changes pending resale to OCCUPIED. A later complete absence read can release
occupied capacity; absence alone never frees pending resale. Duplicate/late
readbacks cannot replay a transfer or undo a possible win.

The three accounting buckets are disjoint physical commitments. If Transfer List
presence arrives before the auction's terminal proof, the exact item remains
accounted for in UNRESOLVED until WON is confirmed. It is counted once throughout
that ordering. `physical_occupied` separately reports the full pile size, including
manual and sold entries. Registry/operator `capacity` reports both counts, the
three buckets, total, freshness, read ID and pending resale trade IDs. Readers use
one SQLite snapshot; writers commit phase and inventory changes together.

Verification is synthetic and performs no EA account operations. Run each command
independently from the workspace:

```
python tests/test_00206_capacity.py
python tests/test_bidding_v1.py
python tests/test_001d06_foundation.py
python tests/test_00204_actors.py
python tests/test_00205_occupancy.py
```

The targeted suite covers all four acceptance criteria: concurrent admission
(12 contenders for the last slot), concurrent duplicate enrollment, the separate
50-auction limit, 40 occupied plus 5 pending and 5 unresolved blocking another
enrollment, lifecycle transitions, duplicate and conflicting readbacks, version
mismatches, unknown dispatch, legacy migration and nine real process termination
boundaries around enrollment, intent, dispatch, WON and Transfer List commits.
Failure injection checks rollback of both evidence and reservation changes.
Integration tests exercise the actual Acquirer/Bidder and one-shot admission
through the production adapter against the local synthetic native fixture.
