# 002-05: Complete Transfer List occupancy

Status: OFFLINE_VERIFIED. Native service/XHR fixtures and finite actor cycles were
used. No live account request, login, item deletion, or sustained actor was run.

`requestTransferItems()` still follows TRANSFER cache invalidation and requires a
fresh authenticated native GET of `/ut/game/fc27/tradepile`. The production reader
now compares every physical item across the captured wire response, native
callback, and Transfer List repository. Repository `endOfList=true`, no positive
`hasMore`, matching counts, unique physical items, and matching identities/states
are required for complete coverage. Unknown state does not remove a physical item
from the count. Inactive entries sharing a no-auction sentinel are counted
separately. Historical reads without completeness evidence remain unknown.

Acquirer obtains a new read under its bid lock immediately before queue admission.
`max_transfer_list_occupied` defaults to 50 and can be lowered independently of
`max_enrolled_auctions`. Full or existing over-cap occupancy blocks enrollment;
75 pre-existing items remain 75 items. No clear, move, relist, or delete operation
is introduced. This task enforces the occupied bucket; atomic combined
occupied+pending+unresolved reservations remain the separate 002-06 task.

Each guard decision is persisted in the append-only registry with a reason code,
read correlation, coverage evidence, observed count, trusted occupied count (only
when complete), limit, and enrollment decision. Missing/failed delivery retains
an explicit unknown pause; its transport attempt is in executor metrics. Operator
`status`, `blocked`, `timeline`, and `export` expose this evidence. Status marks
old observations stale and never reuses them as admission authority.

Reasons: TRANSFER_LIST_AVAILABLE, TRANSFER_LIST_UNKNOWN, TRANSFER_LIST_STALE,
TRANSFER_LIST_TRUNCATED, TRANSFER_LIST_CONFLICT, TRANSFER_LIST_FULL,
TRANSFER_LIST_OVER_CAP. Bidder management and sticky coin DRAINING retain their
independent policies.

Acceptance validators (run from the workspace):

- `python tests/test_00205_occupancy.py`: executes actual production JavaScript,
  checks native complete/incomplete reads, all states including sold uncleared
  and manual entries, freshness boundaries, contradictory coverage and identity,
  0/49/50/51/75/100 occupancy, custom limits, Acquirer pause/resume, persistent
  reasons, operator replay, and Bidder operation while the pile is over cap.
- `python tests/check_00205_artifacts.py`: independently replays the retained
  synthetic native fixtures at their recorded times, checks negative cases,
  all-state cardinality, and the actual CLI configuration contract.

`native-fixtures.json` is explicitly synthetic protocol evidence, not captured EA
account evidence. `verification.json` records command results. No mutable source
hashes are asserted. Run `python tests/record_00205_checks.py` to refresh the local
verification artifacts after changing behavior.
