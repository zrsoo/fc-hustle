# ACK does not establish bid registration

## New operator evidence

On 2026-11-16 the user clarified that the complete Transfer Targets history for
the last two to three days contains only Isak, Cherki and two Adeyemi auctions.
The user states that other logged bids did not actually go through. The retained
watched read independently contains precisely those four player definitions:
233731, 251570 and two 251852 rows.

The blocked commands instead target definition 246191 (Alvarez), command
`6b3faed8a418890da8147b59eae039fc`, and definition 271421 (Doue), command
`ff4174653771149736e63b1ac12630f9`. Neither appears in that history. These must
not be described as independently confirmed bids that subsequently lost.
The earlier operator-loss audit is historical operator evidence, not proof of
EA registration; this subsequent clarification must remain alongside it without
rewriting the original journal or captured responses.

## Proven implementation gap

The current page calls `services.Item.bid(raw, amount)`, checks the callback's
`success === true`, observes one authenticated 2xx bid route and then sets its
own result `success=true`. There is no bid-specific validation of returned
auction items, an accepted account-relative bid state, native error code or
updated/stale auction entity. The Python adapter maps that boolean directly to
`ACKNOWLEDGED/NATIVE_ACK`.

The captured official `UTTransfersDAO.bid` implementation demonstrates why the
native success flag is insufficient. It copies the HTTP response flags into its
result and converts `auctionInfo` to items. If there are no returned items, it
marks the input auction stale; it does not independently turn copied success
into false. It notifies ITEM_BID only when returned items exist.

The captured Item service wrapper also preserves success. On the success path,
it constructs `data.itemIds` from the **input** item ID, even when the DAO returned
no auction item. That itemIds array is not an independent acceptance receipt.

Resulting path:

```text
HTTP/native success with zero auction items
  -> DAO marks input stale, retains success
  -> Item service retains success and reports the input item ID
  -> production page reports success without validating bid registration
  -> Python persists ACKNOWLEDGED/NATIVE_ACK
```

## Offline behavioral reproduction

`private-captures/ack-diagnosis/offline-reproduction-v2.json` retains the valid
reproduction. It executes the captured native DAO and service functions with
synthetic response/transport objects, then exercises the actual current
production page through its existing VM harness. No browser, EA request, account
mutation, command replay or historical evidence modification occurred.

The injected HTTP response is explicitly an offline fixture: success true,
status 200, empty auctionInfo and unchanged credits. Observed results:

| Layer | Actual reproduced behavior |
|---|---|
| Native DAO | success true; zero returned items; input marked stale |
| Native Item service | success true; one reported input item ID |
| Current production page | success true; error null; no auction evidence |
| Python's existing mapping | ACKNOWLEDGED / NATIVE_ACK |

The production-page success is observed, not a test requirement that should
preserve this defect. This experiment establishes an executable false-positive
ACK path. It does not manufacture or reconstruct the historical EA responses.

An initial exploratory reproduction used an incorrectly oriented mock for
`assignPropertyValues` and did not populate native success fields; its separate
`offline-reproduction.json` is superseded by the corrected v2 experiment, not
historical live evidence. The corrected experiment checks the native success
flags and response item count explicitly.

## What remains unproven

The historical production results discarded the native DAO auctionInfo/items,
error-code details and stale marker. They also normalize bid URLs to a generic
route without retaining an independently checked wire-target/amount binding.
Consequently, the exact historical server response or rejection reason for the
two attempts cannot be recovered from those retained envelopes alone. Empty
auctionInfo is a reproduced mechanism, not a claim about their captured bodies.

The user's account history, missing watched entries, unchanged aggregate credits
and later account-relative state none are consistent with unregistered attempts.
They should direct diagnosis to bid submission/acceptance rather than treating
the attempts as proven successful participation followed by an unknown loss.

## Required repair direction

1. Capture only allowlisted native bid response evidence: error code, item count,
   exact pseudonymized identity, current bid, account-relative bid state and stale
   marker. Inspect no authentication fields, headers, tokens or credential data.
2. Validate the actual private wire trade selector and bid amount against the
   retained intended identity/amount before sanitizing them for retention.
3. Distinguish transport/native acknowledgement from demonstrated bid acceptance.
   Empty, stale, mismatched or explicitly rejected native outcomes must not be
   reported as successful participation. Unknown consumed requests remain
   protected against replay; independently established rejections should follow
   their explicit rejection reconciliation path, not require a fictional loss.
4. Add behavioral regressions for HTTP 200 with empty items, native errors,
   unchanged/stale DTOs, wrong wire targets/amounts and valid accepted outcomes.
5. Keep independent account readbacks. Do not fix this by ignoring none, inventing
   highest/outbid/lost, weakening identity checks or repeating either old command.

This entry records investigation only. No production fix, new live bid, actor
restart, recheck or state clearance was performed for this diagnosis. The
orchestrator-policy enhancement remains separately deferred in IMP-004.
