# 002-08 — Exact physical-card ownership, movement and resale

Implemented and verified offline. No live account writes, browser recovery, new
experiments, or trading windows were used. Final integrated live evidence remains
item 002-12.

Bidder keeps closed/highest and native WON candidates PENDING until a separate,
fresh unassigned read contains the enrolled physical item and exact definition,
tradeability, and positive owned-card lastSalePrice matching the terminal trade
and the dispatched bid. Missing or contradictory cost remains uncertain. Market
comparable lastSalePrice and balance deltas do not authorize ownership or affect
the stored resale price. LOST cannot enter the resale lifecycle.

The shared Bidder invokes the finite resale cycle. Before movement it refreshes
both terminal status and owned inventory again; before listing it refreshes a
complete Transfer List and requires the same inactive physical card and paid
cost. Native card limits are fetched for each stage. Native helpers validate BIN
exactly equal to the enrollment's resale_price and starting bid exactly equal to
getIncrementBelowVal(BIN), including reciprocal tick legality. Proven illegal
pairs become UNLISTABLE; absent price evidence remains recoverable. Stored
resale policy and mutation envelopes are immutable in SQLite.

Native operations are services.Item.move([item], ItemPile.TRANSFER, false) and
services.Item.list(item, startingBid, buyNowPrice, 3600), through the existing
serialized executor. Move waits if the physical pile already contains 50 cards;
listing an already present card remains possible at capacity. Context, persona,
document and epoch fences apply in Python, transport and the native bridge.

Each mutation commits intent, then a consumed claim, before dispatch. ACK alone
never advances state. Move requires fresh destination presence and independent
unassigned absence. Listing requires the exact physical card, a different active
trade identity, fixed prices and one-hour expiry anchored to the dispatch
interval. Incomplete, contradictory or missing readback stays unreconciled.
Read-only reconciliation can adopt the current epoch after reconnect; it never
redispatches a completed or ambiguous stage, including an intent-only crash.

RESALE_UNKNOWN counts as pending capacity even when a later complete pile read
shows the card missing. Independently verified presence and mutation settlement
commit the pending-to-occupied handoff together. Existing account-wide capacity
reads cannot prematurely release that reservation.

Run independently from the repository root:

- `python tests/test_00208_resale.py` — behavioral criteria 0–4, actual native JS
  VM checks, rollback failures and ten abrupt process-death boundaries.
- `python tests/check_00208_artifacts.py` — inspect captured synthetic ownership,
  fixed parameters, intent/claim/readback ordering, fences, native ticks/caps and
  reservation conservation; rejects seven evidence corruptions.
- `python tests/test_00206_capacity.py` — existing atomic capacity and concurrency
  regressions, using explicit owned cost in its winning fixture.

`scenarios.json` is synthetic evidence produced by the passing suite with
`--record`. It contains successful move/list and missing ambiguous-listing
observations. It is not live EA transaction evidence. No source hashes are
enforced by these validators.
