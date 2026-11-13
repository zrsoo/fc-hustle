# 001d-05 fresh inventory and bounded status investigation

Fresh inventory and balance primitives are IMPLEMENTED, OFFLINE_VALIDATED and
LIVE_VERIFIED in the exact scope below. Known-trade status is LIVE_VERIFIED for
one existing native trade retained in the current document. Reconnect lookup
without reacquiring its native mapping is unsupported; no such claim is made.
No new bid, purchase, move, cleanup or listing was executed.

The pre-change decisions are in `GAP-MAP.md`. The authoritative production paths
are `browser/production-v1/page.js:execute`,
`browser/production-v1/page.js:auction`,
`fc_access/production_v1/contracts.py:parse_response`,
`fc_access/production_v1/adapter.py:NativeAdapter`,
`fc_access/production_v1/inventory.py:watched_status`,
`fc_access/production_v1/inventory.py:compare_lite_identity`,
`fc_access/production_v1/server.py:Server` and
`fc_access/production_v1/store.py:Store`. The new retained-identity entry point is
`fc_access/production_v1/adapter.py:NativeAdapter.known_status`; local support
inspection uses `fc_access/production_v1/contracts.py:parse_status_support`.

| Operation | Production native primitive | Actual GET route | R1 status / rows |
|---|---|---|---|
| watched | `repositories.Item.setDirty(ItemPile.INBOX)` then `services.Item.requestWatchedItems()` | `/ut/game/fc27/watchlist` | 200 / 1 |
| unassigned | `repositories.Item.setDirty(ItemPile.PURCHASED)` then `services.Item.requestUnassignedItems()` | `/ut/game/fc27/purchased/items` | 200 / 0 |
| transfer list | `repositories.Item.setDirty(ItemPile.TRANSFER)` then `services.Item.requestTransferItems()` | `/ut/game/fc27/tradepile` | 200 / 8 |
| balance | `services.User.requestCurrencies()` | `/ut/game/fc27/user/credits` | 200 / 16,268 coins |

Each successful refresh requires exactly one captured native authenticated XHR
GET, the actual response status matching its observable result, a command/read ID,
same context and full fences, network timestamp within 30 seconds, and dirty
evidence for the three item piles. Query dictionaries for these four reads must
be empty. Unsupported invalidation/services, cache-only callbacks, wrong routes,
missing authentication, stale, ambiguous or malformed responses fail explicitly.
There is no substitution of `/user/currencies` and no successful refresh inferred
from repository contents. `native_is_won` calls native `isWon()` once when
available; otherwise it remains null. Trade/item/version and native trade_state,
bid_state, expires and current_bid are preserved per row. Native `untradeable`
differs between the watched and lite projections of the same item in this sample;
both values are preserved, never used to manufacture owned-item proof.

The one-shot interpreter returns UNKNOWN for a missing watched row even when
the watchlist is empty. Closed/highest and native isWon=true return PENDING with
`ownership_proven=false`, requiring independent exact owned physical-item proof.
Only an exact terminal outbid is classified LOST. These functions do not prove
actual paid cost or dispatch actions. The existing observed row is closed/outbid,
expires=-1, current_bid=1200, full definition 261855 and native_is_won=false.
No naturally won outcome occurred in this task.

`browser/e2e-resolution-v2/page.js` was inspected, together with
`docs/research/001c/001c-06-resume-01/source-contract.json`. Its reviewed
`getAuctionData(items)` function reads each descriptor's tradeId/isValid, sets
local isUpdating, sets cache=false, sends GET `/trade/status/lite?tradeIds=...`
and generates item entities from auctionInfo. The earlier experiment hardcoded
one trade, one identity key and a performance-resource recovery. Production
retains none of those historical restrictions or raw resource-history scans.

The current loaded DAO's SHA-256 was inspected locally and exactly matched the
reviewed function `6097c4fd909171eb067c77ad088c8fd8bd18024f5848663774f5488becf11c2a`.
A known_status call accepts only a trade/item/full-definition tuple previously
retained by a successful fresh native full-identity read in the same document and
epoch. It constructs the reviewed read-only descriptor using the privately
retained native ID. Unknown mappings and changed source fail before any EA call.
Wire `tradeIds` must exactly equal that private native trade ID; its public query
projection contains only the matching trade pseudonym. Raw IDs never leave the
page. The response must match exact trade and physical item; a nonzero different
definition fails. Native definition_id=0 or an omitted version is preserved as
0/null and means VERSION_UNOBSERVED against retained full identity, never a
different-card finding or a newly observed full version. Lite results never
overwrite the retained full mapping. This is session-scoped reusable support,
not universal resolution of newly enrolled, missing or arbitrary historic trades.

R1 completed at 14:49:43 UTC on 2026-11-13, using the already reviewed D1 bridge
and existing S2 attachment. After reviewing and offline-testing the additive
status implementation, the localhost service was restarted with its original
SQLite database, all seven prior commands acknowledged. Restart advanced its
epoch; account/persona/identity namespace and all consumed budgets were retained.
The extension and official tab were reloaded and explicitly reattached.
S1 then used its declared two read operations in dependency order: watched first
to retain a full native identity, followed by status for that exact existing row.
The status GET returned HTTP/native 200, closed/outbid at 1200, expires=-1 and
definition_id=0; trade and physical item matched the independent full watched row.
The production API was retained after that live support check and the native-mock
tests, which also execute the exact reviewed DAO function on arbitrary fixture IDs.

A further explicit page reconnect preserved the same context and advanced the
owner epoch, creating a new document. Its local source inspection still matched,
but retained native mappings dropped from one to zero. No extra watched or status
request was sent after reconnect. The initial reconnect attachment was attempted
while the page was loading and `/health` reported attached=false. A second normal
extension click established the new peer; no ambiguous native command was retried.
The pre-attachment check emitted `new_document_attachment_required` before any
local inspection reservation or EA request. The final inspection completed once.
The mocked-native tests independently verify lookup is rejected with zero
requests after an epoch change/new page, and can resume only after a fresh full
identity read. Actual lookup after that reacquisition is LIVE-UNVERIFIED.

| Window / stage | Reserved / actual EA requests | Local source inspections | Mutations |
|---|---:|---:|---:|
| R1, four fresh reads, 60-second ceiling | 4 / 4 | 0 | 0 |
| S1, watched + known status, 60-second ceiling | 2 / 2 | 2 | 0 |
| Reconnect, local mapping/source inspection | 0 / 0 | 1 | 0 |
| This task total | 6 / 6 | 3 | 0 |

These are exactly six explicit EA probes, serialized with no retries. Including
the previously completed S2 caps read yields seven of the Objective 001D ten
allowed native probes. Its eight helper evaluations remain consumed. R2's three
pricing probes were not run. Actual timestamps, freshness, IDs and results are in
`r1-checkpoint.json` and `s1-checkpoint.json`; `transport-evidence.json` independently
extracts their acknowledged delivery/results and reservation events from SQLite.
No completed window was replayed, no command was duplicated and no deadline or
allowance was reset. Ordinary Web App startup/refresh background traffic outside
these explicit calls was not globally instrumented; counts are experiment-command
counts, not an account-wide traffic claim. Any observed fanout during a probe
would stop it. All explicit probes had exactly one GET.

AGENTS.md was explicitly reread before this worker's recovery, service reload
and reconnect. The saved UI evidence establishes this worker's own foreground
Edge/window/official-tab control, rather than borrowing another worker's clicks.
The loopback service, reviewed production extension attachment, selected native
PC persona binding, presence-only authentication header telemetry and EA success
are separate gates. No login challenge was encountered; challenges remain for
the user. No saved credentials, cookies, tokens, headers or session identifiers
were extracted. Port 8784 still requires its separately running local service.
Sealed 001C and preceding 001D evidence/checkpoints were preserved. The original
001d-02 protocol snapshot stays unchanged; its test now checks its original
operations, with the additive schema-2 status contract covered by this task.

Precise Objective 002 dependencies, with no trade creation to force an outcome:

- **002-STATUS-RECONNECT**: native IDs are memory-only and disappear across
  document/epoch changes. On a real enrolled trade, retain the stable full
  account/game/platform/version identity, reacquire a matching full native row,
  then verify one independently correlated status GET after reconnect under 002's
  budget. If the row is absent, return UNKNOWN and reconcile without retries or
  cross-key inference. No live status success across reconnect is claimed here.
- **002-STATUS-HISTORY**: old 001C artifacts contain pseudonyms under unrelated
  identity keys. Their raw native trade IDs were not exported and cannot be
  reconstructed from those hashes. The new live row is proven within the R1/S1
  namespace only; it is not cryptographically linked to an unrelated historical
  hash. Validate existing historical trades only when an actual retained native
  mapping and independent exact identity are available; otherwise preserve UNKNOWN.
- **002-NATURAL-OUTCOMES**: missing-row resolution, closed/highest ownership,
  actual paid cost and naturally won branches were not observed. Validate them
  against real enrolled trades and independent owned-item/balance evidence before
  any move/list/sale; native isWon alone cannot authorize a confirmed win.

Independent validator: `python tests/test_001d05_inventory.py`. It executes the
production JS, fifty-row dirty/read mocks, exact identity/state projections,
unsupported/cache/freshness/auth/route failures, lite omissions, current-context
lookup and reconnect loss/reacquisition. It also audits actual route/status/time
evidence, transport records, sealed history and refusal to replay consumed windows.
All validator commands are offline; none calls a live capture or browser recovery.
