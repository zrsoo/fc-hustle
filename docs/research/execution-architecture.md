# Autonomous execution architecture — task_06

Decision: **CONDITIONAL GO for Objective 002 implementation**, based on the retained 2026-11-11 research. This document specifies future implementation; it does not run or deliver a production trading loop. [Objective 001](../../objectives/001-fc27-api-research.md) authorizes the already completed bounded experiment only. The [handoff](obj002-handoff.md) identifies the implementation order and release conditions.

## Transport decision and proof boundary

Use Python orchestration with an Edge Manifest V3 native-service bridge in the existing signed-in official Web App. [Read verification](capabilities/verification.json) reports **14 authenticated network readbacks through Edge and 0 through direct HTTP**. The latter returned `direct_session_provider_unavailable`, before any authenticated direct request. Authenticated latency comparison is **UNVERIFIED**; fast local rejection is not evidence of faster transport. CDP was unavailable in the [access inspection](browser-access/inspection.json); no browser restart is needed for the selected bridge.

[Transaction verification](transaction/verification.json) independently proves purchase, movement, listing and status. One physical card, definition 278230, cost **200** coins; a fresh active listing had starting bid **200**, BIN **250**, requested duration **3600** seconds and **3570** seconds remaining. Relist is **UNVERIFIED** because no eligible expired item was present. These are particular accepted prices, not a complete price ladder, per-card cap or realized sale. [The journal](transaction/live.json) includes an initial cached-read failure and subsequent fresh restart reconciliation without repeating the purchase.

The adapter remains replaceable. Direct HTTP may replace it only after a trusted in-memory session provider and independent search, inventory/coins, Buy Now, movement, listing and status readbacks all work. Do not collect browser cookies or session headers to fill that gap. Discover game, host, client and SKU from current authenticated behavior; the observed FC27 host is a checkpoint, not a future constant.

## Interface contracts

All interfaces below are proposed Objective 002 contracts. Keep existing research commands bounded and unchanged. All coin values are integers, times are UTC with timezone, and durations/expiry are seconds. Reject booleans as integers. Unknown fields remain null rather than zero. `MarketKey=(game, platform, definition_id)` uses the full exact version. Native definitionId comes from wire resourceId; physical item ID and auction trade ID are separate identities. Never match special cards by name or base asset ID. See [native mappings](capabilities/native-item-mappings.json).

`Result[T]` contains `command_id`, `session_epoch`, `outcome` (OK, REJECTED, UNKNOWN), `value:T|null`, `observed_at`, `network_fresh`, `http_status|null`, `ea_code|null`, `error_code|null`. Write OK means acknowledged, not reconciled. A timeout, disconnect or malformed write result is UNKNOWN. Read snapshots also carry `complete`, pagination coverage and native cache invalidation evidence. An incomplete snapshot never proves absence. Persist only allowlisted projections, generic routes, numeric errors and timestamps; exclude raw URLs, request bodies, account names, headers, credentials and exception text.

| Interface | Input | Output | Dispatch / freshness / failure contract |
| --- | --- | --- | --- |
| CatalogPrices.catalog | game, platform, cursor? | exact-version keys, source, publication, next_cursor?, completeness | Start with PC definitions 233731 and 278230; complete catalog UNVERIFIED. No name-only substitution or fabricated PC bulk key. |
| CatalogPrices.quotes | MarketKey, now | indicative quotes with publication, version, content hash, source, age | Discovery hints only. FUT.GG manifest/catalog 403 means unavailable; no stale-success fallback. |
| CatalogPrices.rules | MarketKey, now | minimum, maximum, increment bands, observed_at, provenance, verification status | Missing/stale caps or unverified relevant ticks return NOT_READY; observed ask extrema are not caps. |
| Profitability.evaluate | MarketKey, observations, acquisition, rules, now, X, Policy | Estimate(status, target_sale_price, acquisition_price, tax, expected_profit, sample_count, meets_threshold, assumptions) | Reuse pure fc_access.pricing.evaluate; five independent comparables after candidate exclusion and outlier rejection. No network or write side effects. |
| Market.search | definition_id?, max_buy?, min_buy?, league?, club?, page, count, fresh | auctions(trade_id, item_id, definition_id, platform, BIN, bid, expires, trade_state, untradeable), network_at, page metadata | services.Item.searchTransferMarket(criteria, page); type=player; clearTransferMarketCache at refresh start. Page 1/2 only in retained bridge; deduplicate lookahead. Nation/rarity/position UNVERIFIED. |
| Trading.buy_now | command_id, session_epoch, MarketKey, trade_id, item_id, buy_now_price, candidate_network_at, rules_revision | Result[acknowledgement] | services.Item.bid(item, buyNowPrice); exact identity/BIN recheck in page before dispatch; never use bid=-1. Persist intent first; fresh owned-item and coin readback required afterward. |
| Inventory.snapshot | session_epoch, force_network, coverage | coins, unassigned/purchased items, transfer_list auctions, club items?, complete flags | requestCurrencies, requestUnassignedItems, requestTransferItems; purchased/items is shared unassigned queue. requestPurchasedItems returned service_unavailable. Club snapshot freshness UNVERIFIED; do not use it alone for purchase proof. |
| Movement.to_transfer | command_id, session_epoch, MarketKey, item_id | Result[acknowledgement] | services.Item.move([item], ItemPile.TRANSFER, false); require owned tradeable item; independently read exact destination before listing. |
| Listing.create | command_id, session_epoch, MarketKey, item_id, starting_bid, buy_now_price, duration, rules_revision, listing_generation | Result[acknowledgement] | services.Item.list(item, startingBid, buyNowPrice, duration); validate fresh caps/ticks, bid < BIN, one-hour duration initially; read new active trade ID, item/version, prices and expiry. |
| Status.read | session_epoch, force_network, item_id?, trade_id? | active/expired/sold/unknown listing state, current_bid, BIN, expires, settlement evidence? | requestTransferItems; fresh whole-pile coverage required. Missing listing is UNKNOWN, never automatically sold. Expired unsold item can use Listing.create with a new generation only after reconciliation; relist live behavior UNVERIFIED. |
| Session.ensure_ready | previous_epoch?, now | attachment, observed game/platform, epoch, READY/AUTH_REQUIRED/DETACHED/RESTRICTED | Health proves attachment only. Authenticated reads and exact local identity scope must also match; no password or token interface. |

The research v3 command validator limits buys to 200–500 coins and listings to 1000 with 50-coin steps. Those are experiment bounds, not Objective 002 spend policies. Build a separate reviewed versioned execution bridge using fresh market rules; do not silently widen or reuse the one-shot runner as a continuous executor.

## Autonomous sequence

The P0 loop is **scan → evaluate → buy → list → repeat**, without per-transaction approval or additional portfolio/spend policies. X is the configurable nonnegative integer minimum modeled profit, equality accepted:

```text
expected_profit = target_sale_price - floor(target_sale_price * 0.05) - acquisition_price
tax = target_sale_price // 20
```

Scan exact-version asks; evaluate with [the deterministic estimator](market-strategy.md). Exclude the candidate's physical item and auction, deduplicate, require at least five comparables, reject stale/wrong-platform/outlier rows, use the lower quartile and one legal tick undercut within verified caps. No `marketAverage`, `lastSalePrice` or third-party hint substitutes for comparables. `target_sale_price` is an estimate, never guaranteed proceeds.

On `expected_profit >= X`, schedule priority exact candidate revalidation in the same serialized queue. Recompute the estimate and validate session, unchanged physical/version/trade identity and BIN, tradability, caps, coin availability and transfer destination capacity. These are executable-state requirements, not capital allocation policies. Missing data skips the opportunity. Do not add daily budgets, position limits or an approval service.

Immediately before Buy Now, the page must revalidate the candidate and remaining expiry; a queued decision may age out. After confirmed acquisition, persist actual acquisition cost, move when needed, and list that same physical item at the calculated legal target. Revalidate the target before listing if comparables/rules have aged; use a fresh estimate, and retain acquired inventory as HELD if no legal target can be computed. Profit threshold selects acquisitions; it must not strand already acquired cards by demanding a new purchase approval. Read back the active listing before returning to scan. Existing active listings can remain while scanning repeats. Service reconciliation and sale monitoring take priority over new acquisition work.

## Durable state and accounting

Proposed storage: local SQLite, WAL, `synchronous=FULL`, foreign keys enabled; single OS process lock plus one in-flight command. Commit the operation intent before any native mutation. Commit response, readbacks and state transitions atomically. Never hold a database transaction across network waits. Durable unique keys suppress duplicate dispatch across process, server and page restarts; EA has no verified idempotency-key facility, so do not promise exactly-once remote writes.

| Table | Required fields and constraints |
| --- | --- |
| account_scopes | scope_id, platform, game, correlation_key_ref, last_session_epoch; local-only persona fingerprint; mismatch disables writes |
| acquisitions | scope_id, item_id, definition_id, purchase_trade_id, actual_cost nullable, acquired_at, cost_evidence_ref, state; UNIQUE(scope_id,purchase_trade_id), UNIQUE(scope_id,item_id) |
| operations | command_id PRIMARY KEY, scope_id, kind, semantic_key UNIQUE, immutable payload_hash, intent_at, dispatched_at?, outcome, response_ref?, reconciliation_ref? |
| listings | scope_id, item_id, generation, trade_id nullable, starting_bid, BIN, duration, target_revision, state, last_network_at, expires_at; UNIQUE(scope_id,item_id,generation), unique non-null trade_id; at most one active generation per item |
| observations | snapshot_id, scope_id, epoch, route, network_at, complete, sanitized projection/hash; keep causally ordered pre/post readbacks |
| settlements | scope_id, sale_trade_id UNIQUE, item_id, gross nullable, actual_tax nullable, net_received nullable, actual_cost nullable, realized_profit nullable, evidence_ref, status |

Stable identity is a required extension of the per-run research pseudonyms. Persist a local random correlation key with restricted Windows file permissions, separate from public reports and protected by backup. Reuse that key within one account scope across restarts to reproduce namespaced item/trade hashes; it is not an EA credential. Keep raw native IDs and entity maps in the page only. After reattachment, enumerate fresh piles under the same key to rebuild maps. A missing key or changed account scope makes historical joins unsafe: disable writes and restore the matching local state; never buy again under new pseudonyms. Do not join IDs from different research captures. No raw persona identifier is exported; derive a local-only stable fingerprint in the page for scope mismatch checking, with a protocol/security review before implementation.

Acquisition cost is immutable once verified from the exact candidate and owned-item/coin readback. A missing callback can still be reconciled automatically when fresh evidence unambiguously proves the same newly owned physical item and exact debit; the current one-shot runner is deliberately more restrictive. Concurrent manual account changes or sales can confound balance deltas: preserve UNKNOWN_COST, retain the item, and require attributable evidence; never replace missing cost with current price or zero. Back up the database and correlation key together. A lost/corrupt database must not launch an empty ledger against an occupied account.

Track expected profit separately from realized profit. Active and expired listings realize **nothing**. A sold trade with attributable settlement records `realized_profit = net_received - actual_cost`, and `actual_tax = gross - net_received` only when both are evidenced. If cost, proceeds or sale attribution is missing, keep realized_profit null with SETTLEMENT_PENDING; a balance increase or vanished item alone is insufficient. The locked modeled tax is floor(sale/20), but actual FC27 rounding remains **UNVERIFIED** until settled-sale evidence, including an odd 5% boundary, is obtained. Deduplicate settlement by sale_trade_id; do not increment profit again on every status poll. Sale cleanup/removal and bulk relist are outside the verified adapter and must not erase settlement evidence.

## State transitions and crash reconciliation

| From | Required evidence/event | To | Remote action allowed |
| --- | --- | --- | --- |
| SCANNING | fresh valid estimate reaches X | EVALUATED | none |
| EVALUATED | page revalidation and durable unique buy intent | BUY_INTENT | buy once |
| BUY_INTENT | exact new ownership plus attributable acquisition debit | OWNED | none |
| OWNED | absent from transfer pile, fresh owned item, durable move intent | MOVE_INTENT | move once |
| OWNED | already in fresh transfer pile | IN_TRANSFER | none |
| MOVE_INTENT | fresh exact destination readback | IN_TRANSFER | none |
| IN_TRANSFER | legal current target, no active listing, durable generation intent | LIST_INTENT | list once |
| LIST_INTENT | fresh matching active listing with new trade ID | ACTIVE | none |
| ACTIVE | independently observed unsold expiry | EXPIRED | none |
| EXPIRED | fresh unsold/tradeable identity, legal target, reconciled prior generation | LIST_INTENT | list once with new generation |
| ACTIVE | attributable sold trade observed | SETTLEMENT_PENDING | none |
| SETTLEMENT_PENDING | attributable net proceeds and known acquisition cost | SOLD | none |
| ACTIVE | listing verified; next independent cycle | SCANNING | none |

Any ambiguous write enters RECONCILING for its persisted operation, retaining its predecessor and payload. On process start: acquire lock, integrity-check/open storage, check scope/key, mark every pending/dispatched intent UNKNOWN, attach/handshake, obtain fresh authenticated coins, purchased/unassigned and transfer/status coverage, rebuild entity maps, then reconcile **before new writes**. Expire all candidate decisions across a restart. A queued command is single-delivery with a deadline, not permission to redeliver after reconnect. Late results may be retained for correlation but cannot advance a different command or epoch.

| Interrupted operation | Readback and resolution | If still ambiguous |
| --- | --- | --- |
| buy | Match original trade/item/version against before/after ownership and attributable debit; record actual cost and continue only unwritten move/list stages | Hold operation and stop new buys; never automatically redispatch the original buy, including a crash between intent commit and send |
| move | Find exact item in complete fresh transfer pile; mark moved and continue unwritten list | Retain inventory and reconcile again with backoff; absence alone does not authorize another move |
| list | Find exact physical item and current generation's active trade, prices and expiry; adopt it even when acknowledgement was lost | Hold item; do not create a second listing or infer sale from absence |
| relist | Match fresh active trade to the same expired physical item and new generation; adopt once | Keep prior generation and new intent unresolved; never bulk retry |
| settlement | Re-read sold trade and attributable proceeds, then UPSERT settlement and state in one database transaction | SETTLEMENT_PENDING, realized_profit null; never estimate realized profit |

There is no atomic commit shared by SQLite and EA. Failures immediately after intent commit can sacrifice an opportunity; failures after remote success can lose acknowledgements. Resolve through independent state, never deleting the intent or regenerating a command ID to force a retry. Definitive rejection permits a later newly observed opportunity only after proving no acquisition/listing for the old intent; immutable tombstones remain. Unresolvable evidence may require operational inspection, not routine transaction approval. Graceful shutdown stops scans, records in-flight state, and restarts through the same reconciliation path.

## Session lifecycle and bridge reconnection

Session renewal/expiry/logout recovery remain **UNVERIFIED** live. Let the official Web App manage its own renewal; the executor never implements login, stores authentication values or refreshes tokens. On 401: invalidate decisions, suspend mutations, probe attachment and one authenticated read after backoff. If the official page recovers, increment session_epoch, confirm scope/platform and reconcile pending operations before READY. If the normal login screen or challenge persists, AUTH_REQUIRED waits for normal completion directly in EA. No repeated login loop or challenge solver.

The v3 extension polls local `/next` every 0.5 minutes; `/health` attachment expires after 90 seconds. Navigation loses page hooks; browser restart loses `chrome.storage.session` tab selection. On DETACHED, stop dispatch and keep UNKNOWN writes. Retry local health at 5, 10, 20, 40 then 60 seconds maximum. Start only the intended localhost server if absent; preserve unrelated listeners. Reattach the reviewed extension to the same official tab when needed, without restarting Edge or altering its profile. Health/extension badge alone never proves authentication. Reconnection must negotiate protocol/version and new epoch, validate scope and fresh network reads, rebuild maps and reconcile; discard stale queued decisions. This is operational recovery, not a per-trade permission step.

The new bridge must retain strict Host/Origin/schema/size checks, fixed loopback bind, no arbitrary evaluation and no broad web CORS. Pin the installed extension origin and add a local pairing capability held only in memory by the server and extension, not in the page/report. Pairing and epoch checks do not make same-page scripts trustworthy: the authenticated page and local user remain in the trust boundary. Validate every command again in the page. Reload after a source/protocol update only with dispatch paused and all outstanding intents preserved.

## Measurement, pacing and errors

[Market capture](market/availability.json) contains three native calls with wall times **12220.924, 30012.495, 29961.553 ms**, including the local extension alarm wait. [Read capture](capabilities/attempts.json) contains many roughly 30-second calls. These are command cadences, not EA-only latency. The [task_02 observer checkpoint](browser-access/verification.json) retains eight observations over **16.241 seconds** (14:20:24.112–14:20:40.353 UTC), including request lifecycle rows; it does not establish a normal EA polling interval or sustained request rate. The append-only [observer trace](browser-access/live-v2.json) also contains later activity. Background Web App polling frequency remains **UNVERIFIED**. Keep a passive aggregate route/status/time counter in the future bridge, distinguish Web App traffic from bridge commands and include both in operational load; do not record tokens or raw bodies.

Ordinary proposed defaults, not measured service limits: serialize commands with **30 seconds minimum between submissions** and no catch-up burst. Page 1 for each of two watched versions every **90 seconds** uses about 1.33 calls/minute. Matching page 2 every **300 seconds** adds 0.4, about **1.73/minute** before account checks, revalidation or writes. Total nominal bridge capacity is at most 2 commands/minute; there is little spare capacity. Recovery, acquired-item listing and settlement work preempt scans. Skip missed scan slots, reduce active work when latency/load grows, and never accelerate polling to meet a stale schedule. Each write may also perform an internal freshness read: count actual native network calls, not just commands. Subsecond sniping and whole-market coverage are unsupported.

Cache by game/platform/exact definition, criteria signature, page, network time; persist full auction identities. Refresh invalidation applies at sample start, never between page 1 and 2. Offset pages are mutable and unsorted by BIN; deduplicate auction/physical identities, reject conflicts, and track coverage. A native callback/304/cache snapshot alone cannot satisfy a fresh state transition. The task_04 buy was acknowledged, but two subsequent inventory/transfer reads returned **304**; fresh reads after `repositories.Item.setDirty` resolved ownership. Use the reviewed [cache contract](transaction/native-cache-contract.json), then require observed network readback. Cache invalidation itself is not freshness proof.

| Condition | Ordinary response |
| --- | --- |
| stale sample/candidate | Samples max age 120 seconds including queue delay; candidate max age 30 seconds at submission and page recheck at mutation; require at least 60 seconds remaining, with measured dispatch delay plus 30-second margin; otherwise skip/re-evaluate |
| missing/stale rules | Caps max age 300 seconds; relevant increments require evidence. Skip new acquisition and hold owned item if no legal listing can be formed |
| public price feed | Refresh manifest every 300 seconds only when accessible; use conditional validators, changed advertised blobs, publication/version/hash and 600-second max age. Errors never refresh freshness |
| bridge_not_attached / bridge_unavailable / service_timeout | Suspend dispatch; a write becomes UNKNOWN and reconciles. Safe read retry only via the shared queue after backoff |
| 429 / transient 5xx | Honor Retry-After when present; otherwise 30, 60, 120, 240 then 300 seconds, capped at 300; Retry-After may exceed the cap. Reset after authenticated success; invalidate decisions, reconcile writes rather than retrying them |
| 401 / challenge / restriction | Suspend new dispatch, inspect normal page state, follow lifecycle above; confirmed restriction is RESTRICTED, without automatic market retries |
| 403 third-party feed | Mark source unavailable, stop its scheduled fetches until legitimate access is restored; EA targeted reads can continue if healthy and all execution prerequisites hold |
| invalid command / price band / insufficient coins / full pile | Record exact allowlisted code and numeric EA/HTTP status; no blind retries. Refresh relevant state; ambiguous writes reconcile first |
| service_unavailable / schema drift / unknown numeric EA code | Keep code without inventing an error meaning; suspend affected operation and review current source/schema, rather than changing hosts/identities blindly |

No numerical EA rate limit, current EA 429 threshold or 5xx behavior was measured. Historical observer 401s, detached-bridge errors, unavailable requestPurchasedItems, cached 304s and FUT.GG 403s are observed; 429/5xx responses above are design contingencies. A denied public feed is not evidence of EA market lock or service-wide outage. An empty authenticated search is a valid empty result, not an access failure.

## Enforcement facts and boundary

Checked 2026-11-11: [EA's FC rules](https://help.ea.com/en/articles/ea-sports-fc/fc-rules/) prohibit bots, automation and auto-buyers, and list Transfer Market restrictions and account bans among possible penalties. Using the official page as transport does not establish permission for automation. [EA's access guidance](https://help.ea.com/en/articles/ea-sports-fc/transfer-market-web-and-companion-apps/) distinguishes Web/Companion access and blocked-account messages. On a restriction, stop and use EA's normal access/support/appeal process. No enforcement outcome or safe cadence can be inferred from a successful experiment.

The design includes **no detection-avoidance claims, proxy rotation, fingerprint spoofing, CAPTCHA bypass, or restriction circumvention**. Backoff reduces operational load and respects errors; it provides no detection immunity. Local scope fingerprinting above only prevents cross-account writes and does not modify a browser fingerprint.

## Normative validation contract

This machine-readable block binds the numeric defaults and capability classifications checked by the artifact validator. It is design metadata, not an implementation or live success assertion.

```json
{
  "schema": 1,
  "transport": "edge_native",
  "authenticated_reads": {"edge": 14, "direct_http": 0},
  "direct_error": "direct_session_provider_unavailable",
  "pipeline": ["scan", "evaluate", "buy", "list", "repeat"],
  "per_transaction_approval": false,
  "additional_portfolio_spend_policies": [],
  "watchlist": [233731, 278230],
  "platform": "pc",
  "minimum_command_gap_seconds": 30,
  "scan_seconds": 90,
  "page2_seconds": 300,
  "manifest_seconds": 300,
  "quote_max_age_seconds": 600,
  "sample_max_age_seconds": 120,
  "candidate_max_age_seconds": 30,
  "minimum_remaining_seconds": 60,
  "caps_max_age_seconds": 300,
  "minimum_comparables": 5,
  "backoff_seconds": [30, 60, 120, 240, 300],
  "reconnect_seconds": [5, 10, 20, 40, 60],
  "idempotency": "durable_semantic_key_no_blind_write_retry",
  "realized_profit": "net_received - actual_cost",
  "unknown_realized_profit": null,
  "capabilities": {
    "purchase": "VERIFIED", "movement": "VERIFIED", "listing": "VERIFIED", "status": "VERIFIED",
    "relist": "UNVERIFIED", "session_renewal": "UNVERIFIED", "card_caps": "UNVERIFIED",
    "full_increment_schedule": "UNVERIFIED", "realized_tax_rounding": "UNVERIFIED",
    "bulk_pc_catalog": "UNVERIFIED", "numeric_history": "UNVERIFIED", "web_app_poll_interval": "UNVERIFIED"
  }
}
```
