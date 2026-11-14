# 002-07: capacity pause/resume and independent coin DRAINING

Acquirer now checks balance and fresh complete Transfer List capacity at cycle
start, before discovery, including cycles with no eligible candidates. It checks
again after pricing under the bid lock. The existing atomic admission ledger is
still the final authority for prospective unresolved and combined capacity.

Full, over-cap, incomplete, stale, conflicting or unknown inventory pauses new
enrollment. Acquirer records CAPACITY_CHECKED and durable CAPACITY_PAUSED /
CAPACITY_RESUMED transitions with the three disjoint counters, physical occupancy,
configured limits, inventory read ID/completeness, independent coin state and
effective hold reason. Changed pause reasons are recorded without claiming a
release. Operator status exposes the last capacity transition; timeline/blocked
views retain it across process epochs. Historical state never grants permission
to reuse an earlier inventory read.

No executor-wide pause was added. Bidder retains independent reconciliation,
leading HOLD and capped rebids. The maintenance broker role and existing selling
maintenance reconciliation contracts remain available during capacity pauses.
The synthetic tests dispatch maintenance inventory reads through the shared
broker, and exercise existing bulk relist/clear reconciliation contracts while
Acquirer is paused. Production bulk-job integration/scheduling remains in the
subsequent objective tasks; this task adds no live mutation or recurring job.

Terminal LOST releases its potential-win slot. Missing/unknown status does not.
WON ends coin competition but retains its pending resale slot. Relisting and a
sale preserve physical occupancy. A sold clear receipt cannot release capacity;
fresh, complete verified absence is required. Incomplete absence readback keeps
the pause, even when coins increased or the fixture already removed the item.

AuctionQueue.reserve_check serializes durable replay and coin state changes.
Reserve-triggered DRAINING is checked before the capacity hold, including when
the prospective opening amount would cross the reserve. Exact-reserve enrollment
and its DRAINING event commit atomically. Temporary balance increases and capacity
release cannot clear the drain while any enrolled auction remains unresolved.
Terminal refresh no longer resets it, including the legacy reset_draining keyword.
Only a subsequent Acquirer cycle with every enrolled trade confirmed WON/LOST and
a fresh, unconsumed balance above reserve can record DRAINED. Admission then checks
the prospective bid amount again. One-shot admission respects the same sticky
state and cannot clear it. Coin events include the balance read ID, available
coins after local reservations, prospective amount and reserve target.

## Acceptance evidence

All verification is synthetic, with isolated temporary SQLite databases and native
page doubles. No Edge session or EA account operation was used. No implementation
or test source hash is enforced.

| Criterion (zero-based) | Behavioral coverage |
| --- | --- |
| 0 | Full/unknown holds; uncertain opening reconciled by Bidder; two existing-auction rebids across pauses; broker prioritizes reconciliation and still dispatches maintenance; selling relist/clear reconciliation contracts continue. |
| 1 | Missing status cannot release; terminal LOST permits next enrollment; sale and credits increase retain occupied capacity; incomplete clear readback holds; complete absence resumes; relist preserves occupancy. Dependency capacity tests also cover WON/pending resale and stale/duplicate inventory evidence. |
| 2 | Exact-reserve admission, projected reserve failure, simultaneous limits and coin precedence; capacity resume remains HOLD while draining; mixed LOST/WON, missing terminal coverage, stale/consumed balance and reserve equality cannot reset; future passing cycle can. Restart and one-shot paths preserve the drain. |
| 3 | Restart across real Foundation epochs; persisted reason-coded checks/transitions; failure injection rolls back pause/resume and DRAINED checkpoints before any new bid; seven exported journal/registry timelines and a causal artifact validator with three corrupted-evidence rejection cases. |

Run independently from the workspace:

```text
python tests/test_00207_enrollment.py
python tests/check_00207_artifacts.py
python tests/test_00206_capacity.py
python tests/test_00205_occupancy.py
python tests/test_00204_actors.py
python tests/test_bidding_v1.py
python tests/test_001d06_foundation.py
```

`timelines.json` contains the actual events captured by the passing 002-07 suite:
lost_release, sold_clear_verified, independent_work, selling_maintenance,
simultaneous_limits, restart and projected_reserve. It contains synthetic identities
and read IDs, and makes no live-success claim. To deliberately regenerate this
unsealed synthetic artifact after behavioral changes, run
`python tests/test_00207_enrollment.py --record`. Normal validation does not rewrite it.

The artifact validator checks ordered events, limit/count arithmetic, evidence for
resumption, precedence, all-terminal coin resets, passing reserve evidence and
restart epochs. It rejects removed resume events, erased coin precedence and an
invented capacity release. The behavioral suite independently exercises current
code and includes persistence failures; the recorded timeline alone is not proof
that the current implementation passes.
