# 001d-05 pre-change gap map

- REUSE: `browser/production-v1/page.js:execute`, schema 2 contracts,
  `NativeAdapter.watched/balance/unassigned/transfer_list`, pinned localhost
  service 8784 and the existing S2 account/persona/identity namespace.
- IMPLEMENT: stricter unsupported dirty/read handling, exact read query checks,
  one-shot watched outcome interpretation and explicit lite identity comparison.
- INVESTIGATE: reviewed `services.Item.transfersDao.getAuctionData` source from
  `browser/e2e-resolution-v2/page.js` and 001C source-contract evidence. Check
  actual retained native trade identity in this worker's browser context and
  after reconnect before exposing any reusable lookup.
- DEFER-TO-002: unavailable historic native IDs, reconnect identity recovery,
  absent natural outcomes and independent owned-item/paid-cost proof. No trade
  creation, cleanup, bid, move or listing.
- REPLACE: no additional bridge dialect. Investigation telemetry will use the
  reviewed production bridge; no raw native IDs or authentication values leave
  the page.

AGENTS.md was explicitly reread on 2026-11-13 before this worker's recovery
inspection. Own Windows UI automation verified one foreground Edge window and
the official Web App tab. Port 8784 is already running, read-only, attached in
the completed S2 context. Attachment is separate from persona/auth/market reads.
The completed S2 window (one native caps request, eight helper evaluations) will
not be replayed. R1 permits four reads/60 seconds; S1 permits at most two
reads/60 seconds. No R2 searches are authorized by this task.
