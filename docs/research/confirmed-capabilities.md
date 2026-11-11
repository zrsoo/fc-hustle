# Confirmed read capabilities — task_03

Report captured at `2026-11-11T18:22:34.010159+00:00`.

Status: **VERIFIED** for the read capabilities assessed below. No trading operation was performed.

Evidence: [attempts.json](capabilities/attempts.json), [verification.json](capabilities/verification.json), [source review](capabilities/source-review.json). Initial blocked attempts are preserved in the capture and [initial checkpoint](capabilities/attempts-initial.json). The separate read bridge attachment was resolved; its successful commands below supersede the original attachment blocker.

## Every attempted capability

Times are UTC command submission times. Duration includes the extension alarm wait (up to 30 seconds), native service work and local delivery; it is not EA-only latency. Missing fields remain null, rather than becoming zero or an empty pile. Error strings below are exact fixed local codes; numeric native/HTTP status and EA error code are retained separately. Raw server error messages are excluded at the privacy boundary.

| UTC timestamp | Transport / operation | JS method or HTTP operation; observed endpoint | Request shape | Status / exact error / EA code | Response fields and readback | Duration ms |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-11-11T14:50:27.353061+00:00 | edge / coins | `services.User.requestCurrencies(); no matching network request retained` | `{}` | `None` / `bridge_not_attached` / `None` | none; UNVERIFIED | 23.443 |
| 2026-11-11T14:50:27.376574+00:00 | edge / club | `services.Club.search(criteria); no matching network request retained` | `{"count": 20, "start": 0}` | `None` / `bridge_not_attached` / `None` | none; UNVERIFIED | 31.113 |
| 2026-11-11T14:50:27.407712+00:00 | edge / unassigned | `services.Item.requestUnassignedItems(); no matching network request retained` | `{}` | `None` / `bridge_not_attached` / `None` | none; UNVERIFIED | 32.145 |
| 2026-11-11T14:50:27.439886+00:00 | edge / purchased | `services.Item.requestPurchasedItems(); no matching network request retained` | `{}` | `None` / `bridge_not_attached` / `None` | none; UNVERIFIED | 31.395 |
| 2026-11-11T14:50:27.471297+00:00 | edge / transfer_list | `services.Item.requestTransferItems(); no matching network request retained` | `{}` | `None` / `bridge_not_attached` / `None` | none; UNVERIFIED | 15.965 |
| 2026-11-11T14:50:27.487281+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); no matching network request retained` | `{"count": 21, "fresh": true, "page": 1}` | `None` / `bridge_not_attached` / `None` | none; UNVERIFIED | 15.669 |
| 2026-11-11T14:50:27.502966+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); no matching network request retained` | `{"count": 21, "fresh": false, "page": 2}` | `None` / `bridge_not_attached` / `None` | none; UNVERIFIED | 16.847 |
| 2026-11-11T14:50:27.519848+00:00 | direct_http / coins | `GET (candidate REST mapping); no matching network request retained` | `{}` | `None` / `direct_session_provider_unavailable` / `None` | none; UNVERIFIED | 0.048 |
| 2026-11-11T14:50:27.519912+00:00 | direct_http / club | `GET (candidate REST mapping); no matching network request retained` | `{"count": 20, "start": 0}` | `None` / `direct_session_provider_unavailable` / `None` | none; UNVERIFIED | 0.033 |
| 2026-11-11T14:50:27.519955+00:00 | direct_http / unassigned | `GET (candidate REST mapping); no matching network request retained` | `{}` | `None` / `direct_session_provider_unavailable` / `None` | none; UNVERIFIED | 0.023 |
| 2026-11-11T14:50:27.519985+00:00 | direct_http / purchased | `GET (candidate REST mapping); no matching network request retained` | `{}` | `None` / `direct_session_provider_unavailable` / `None` | none; UNVERIFIED | 0.02 |
| 2026-11-11T14:50:27.520012+00:00 | direct_http / transfer_list | `GET (candidate REST mapping); no matching network request retained` | `{}` | `None` / `direct_session_provider_unavailable` / `None` | none; UNVERIFIED | 0.021 |
| 2026-11-11T14:50:27.520048+00:00 | direct_http / search | `GET (candidate REST mapping); no matching network request retained` | `{"count": 21, "fresh": true, "page": 1}` | `None` / `direct_session_provider_unavailable` / `None` | none; UNVERIFIED | 0.024 |
| 2026-11-11T14:50:27.520086+00:00 | direct_http / search | `GET (candidate REST mapping); no matching network request retained` | `{"count": 21, "fresh": false, "page": 2}` | `None` / `direct_session_provider_unavailable` / `None` | none; UNVERIFIED | 0.023 |
| 2026-11-11T18:12:08.308572+00:00 | edge / coins | `services.User.requestCurrencies(); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/user/credits` | `{}` | `200` / `none` / `None` | credits=29061; platform=pc | 10776.821 |
| 2026-11-11T18:12:35.782522+00:00 | edge / club | `services.Club.search(criteria); no matching network request retained` | `{"count": 20, "start": 0}` | `200` / `none` / `None` | items[27]; platform=pc | 13366.695 |
| 2026-11-11T18:12:49.153215+00:00 | edge / unassigned | `services.Item.requestUnassignedItems(); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/purchased/items` | `{}` | `200` / `none` / `None` | items[0]; platform=pc | 29909.016 |
| 2026-11-11T18:13:19.064450+00:00 | edge / purchased | `services.Item.requestPurchasedItems(); no matching network request retained` | `{}` | `None` / `service_unavailable` / `None` | none; UNVERIFIED | 29924.355 |
| 2026-11-11T18:13:48.994274+00:00 | edge / transfer_list | `services.Item.requestTransferItems(); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/tradepile` | `{}` | `200` / `none` / `None` | auctions[2]; platform=pc | 30199.167 |
| 2026-11-11T18:14:19.195356+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket` | `{"count": 21, "fresh": true, "page": 1}` | `200` / `none` / `None` | auctions[21]; platform=pc; cache_invalidated=true | 29976.583 |
| 2026-11-11T18:14:49.174281+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket` | `{"count": 21, "fresh": false, "page": 2}` | `200` / `none` / `None` | auctions[21]; platform=pc | 29896.501 |
| 2026-11-11T18:15:57.895531+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket` | `{"count": 21, "definition_id": 233731, "fresh": true, "max_buy": 7000, "page": 1}` | `200` / `none` / `None` | auctions[21]; platform=pc; cache_invalidated=true | 21231.349 |
| 2026-11-11T18:16:19.128936+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket` | `{"count": 21, "definition_id": 233731, "fresh": false, "max_buy": 7000, "page": 2}` | `200` / `none` / `None` | auctions[20]; platform=pc | 30010.932 |
| 2026-11-11T18:16:49.141922+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket` | `{"count": 21, "definition_id": 233731, "fresh": false, "max_buy": 7000, "page": 1}` | `200` / `none` / `None` | auctions[21]; platform=pc | 29949.608 |
| 2026-11-11T18:17:19.094143+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket` | `{"count": 21, "definition_id": 233731, "fresh": true, "max_buy": 7000, "page": 1}` | `200` / `none` / `None` | auctions[21]; platform=pc; cache_invalidated=true | 29943.235 |
| 2026-11-11T18:17:49.040138+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket` | `{"club": 9, "count": 21, "fresh": true, "max_buy": 7000, "page": 1}` | `200` / `none` / `None` | auctions[21]; platform=pc; cache_invalidated=true | 30985.684 |
| 2026-11-11T18:18:20.028848+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket` | `{"count": 21, "fresh": true, "league": 13, "max_buy": 7000, "page": 1}` | `200` / `none` / `None` | auctions[21]; platform=pc; cache_invalidated=true | 29982.121 |
| 2026-11-11T18:18:50.017309+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket` | `{"club": 2, "count": 21, "definition_id": 233731, "fresh": true, "max_buy": 7000, "page": 1}` | `200` / `none` / `None` | auctions[0]; platform=pc; cache_invalidated=true | 29172.877 |
| 2026-11-11T18:20:09.261532+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket` | `{"count": 21, "definition_id": 233731, "fresh": true, "max_buy": 6500, "page": 1}` | `200` / `none` / `None` | auctions[21]; platform=pc; cache_invalidated=true | 9860.722 |
| 2026-11-11T18:20:19.124416+00:00 | edge / search | `services.Item.searchTransferMarket(criteria, page); https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket` | `{"count": 21, "definition_id": 50596300, "fresh": true, "max_buy": 7000, "page": 1}` | `200` / `none` / `None` | auctions[21]; platform=pc; cache_invalidated=true | 30214.389 |

## Transport comparison

The Edge bridge produced **14 authenticated network readbacks**. Direct Python HTTP produced **0**. The direct path's exact local error is `direct_session_provider_unavailable`: no in-memory session provider is configured, no authenticated EA request was sent on that path, and no browser credentials were collected. Comparative authenticated latency remains UNVERIFIED. Local failure durations are not comparable to EA response latency.

Select the Edge native-service adapter for these reads. It keeps authentication in the existing signed-in page. DirectHTTPTransport remains replaceable through the same read interface and can accept a trusted in-memory Session provider; the CLI deliberately accepts no credentials. Its source-reviewed exact-version REST query uses definitionId, not maskedDefId (which can broaden to base-player matching). Neither transport implements login or a continuous trading loop.

Active authenticated endpoints observed in this task:

- `GET https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/purchased/items`
- `GET https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/tradepile`
- `GET https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket`
- `GET https://utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/user/credits`

The prior task_02 configuration additionally identifies `/ut/game/fc27/`, `FC27_JS_WEB_APP`, and `FUT27WEB`. Those are contextual public identifiers, not substitutes for the authenticated readbacks above. The original v2 observer on 8766 remains separate from the command bridge on 8767.

## Player, card-version and auction identity

`tradeId` identifies one auction and maps only to trade_id (`trade:` pseudonym). `itemData.id` identifies a physical card and maps only to item_id (`item:` pseudonym). `resourceId` is a card/version definition on wire responses; the current EA item factory explicitly constructs native **definitionId from wire resourceId** (`l.id=t.id,l.definitionId=t.resourceId`). See [native-item-mappings.json](capabilities/native-item-mappings.json), including the public source hash and exact factory snippet. Thus the live native definition_id is the exact version identity; it is not an auction or owned-item ID.

Native assetId maps to asset_id when present, and remains separate from the exact definition. Native entities do not expose the wire resourceId property here: resource_id remains null. Missing fields stay null; no synthetic resource_id or asset_id is filled to make validation pass. Source shows native databaseId is definitionId masked by ItemIdMask.DATABASE; the current projection does not collect that getter, so base-player asset mapping remains UNVERIFIED. This does not prevent exact-version comparisons using native definitionId. Preserve special versions; never group cards solely by player name, rarity, or base ID.

All native search requests set criteria.type='player'. Targeted comparisons use definition_id **233731**, PC, with max_buy **7000**; every nonempty targeted returned row is checked for the exact definition and a positive Buy Now price at or below the ceiling. Multiple auctions of the same definition have different trade and physical-item pseudonyms. A second targeted version test used full definition 50596300 and returned 21 exact matches; the full definition is preserved without base-ID masking. Lowering the first definition ceiling to 6500 returned 21 prices at or below 6500 and excluded the earlier 6600?7000 quotes. Player-name resolution remains UNVERIFIED; exact card definitions are the comparison key.

Comparable fields retained where exposed: starting_bid, current_bid, buy_now_price, expires, trade_state, bid_state; item definition_id, rating, rarity, nation, league, club, last_sale_price, market_average. Native position, untradeable, resource_id and asset_id are null when absent. market_average is UNVERIFIED; last_sale_price is OBSERVED. Zero last_sale_price values are preserved and do not imply a recent zero-price sale. Neither indicative field is an executable auction price.

Platform **pc** was read from the selected persona alongside the authenticated native results. False isPC does not imply PlayStation. The caller cannot override a browser persona's platform, and eligible comparable groups require one observed non-null platform plus exact definitionId. Cross-platform experiments are UNVERIFIED: no second-platform account was accessed and no console quote was blended into the PC sample.

## Supported filters and pagination

Native source mappings are independently retained in [native-source-shapes.json](capabilities/native-source-shapes.json): defId[0] → REST definitionId, maxBuy → maxb, minBuy → minb, nation → nat, league → leag, club → team, rarities → rarityIds. The loaded initial page bridge maps league and club correctly. Its nation input uses nationality and rarity input uses rarity, so **nation and rarity filter support are UNVERIFIED** through that bridge. No request was relabeled as testing an unsupported DTO field. Position was absent in the projected native data and was not asserted supported.

Live broad club=9 and league=13 queries test those filters independently of a preselected definition; returned rows must all match the requested field. A contradictory exact definition 233731 plus club=2 query tests the conjunction. Empty successful results are preserved as empty, not treated as network errors.

Supported filter assessment: `{"club": "VERIFIED", "league": "VERIFIED", "nation": "UNVERIFIED", "position": "UNVERIFIED", "rarity": "UNVERIFIED"}`.

Two relevant pages: **OBSERVED**. Broad pages returned 21 rows each; targeted pages returned 21 and 20. Both use the same exact definition, PC market and 7000 ceiling. Native service source sets offset=itemsPerPage*(page-1), count=itemsPerPage+1; its fallback visible page size is 20. The native service may override the requested count.

Ordering: **OBSERVED_EXPIRY_ASCENDING_BIN_UNSORTED**. Compare expiry within each response; do not assume Buy Now price order. Lookahead: **OBSERVED_ONE_ROW_OVERLAP**. The page-1 row at index 20 matches page-2 row 0 by the same auction pseudonym in the targeted capture; only the first 20 rows of page 1 belong to its visible page. Deduplicate that lookahead before aggregating comparables. Broad-page overlap can change while auctions expire between polls. A failed request never proves no next page.

Expiry readback: **OBSERVED_SECONDS_REMAINING**. Repeated targeted rows compare countdown changes with measured completion-time differences. This establishes remaining seconds for matching live auctions; absolute expiry timestamps and server clock drift are UNVERIFIED.

Caching and invalidation: native reset + network reads are **OBSERVED_NATIVE_RESET_AND_NETWORK_READ**. Explicit fresh=true invokes services.Item.clearTransferMarketCache() and network evidence shows the subsequent transfermarket GET. fresh=false calls exercise native cache behavior; the captured repeats still emitted matching transfermarket network activity. A cache hit, TTL and exact refresh-vs-query semantics remain **UNVERIFIED** because the 30-second command poll affects timing and raw query strings are not retained. Source shows page-number caches, cache expiry checks and auction refresh behavior; source inspection alone is not a measured cache hit. No local market cache or automatic retry exists.

## Live account state

- coins: **VERIFIED**; readback mode `NETWORK_READ`.
- club: **VERIFIED**; readback mode `NATIVE_SNAPSHOT_NETWORK_FRESHNESS_UNVERIFIED`.
- unassigned: **VERIFIED**; readback mode `NETWORK_READ`.
- purchased: **VERIFIED**; readback mode `SHARED_PURCHASED_UNASSIGNED_ENDPOINT`.
- transfer_list: **VERIFIED**; readback mode `NETWORK_READ`.

Coin balance was read after services.User.requestCurrencies() completed, with an authenticated user/credits GET. The club service returned 27 typed item snapshots from the live page immediately after that authenticated coin read, with native status 200 and PC context; it emitted no matching network request. Club data is an available native snapshot, while cache age and a fresh uncached club GET remain UNVERIFIED. A first club page is not proof of the entire club inventory. The source reviewed DTO may yield cached items beyond requested count.

The native services.Item.requestUnassignedItems() call emitted an authenticated GET to **purchased/items**, returning zero items. Current EA getUnassignedPile source explicitly uses **ItemPile.PURCHASED**, constructs that endpoint, generates items from response.itemData, and returns the unassigned repository. This establishes that purchased/unassigned are a shared queue in the current app, rather than substituting an unrelated pile. The separately attempted requestPurchasedItems method returned the exact local error **service_unavailable** and is not claimed to exist. See the exact read method and source in native-source-shapes.json. A separate purchased-only collection or purchase-history API is UNVERIFIED.

The transfer-list native read emitted an authenticated tradepile GET and returned two active auctions with distinct physical and trade pseudonyms, definition IDs, prices, expiry and last-sale fields. Every account read is its own timestamped observation; this is not an atomic snapshot. No purchase, movement or listing was needed for these read checks.

## Retention, commands and recovery

Transport Protocol.read(operation, params, evidence_key) is replaceable. The page projects positive allowlisted fields before extension transport; the loopback server validates them again and the Python harness validates before retention. Physical-item and auction IDs use distinct salted namespaces. Each resume phase uses its own random key; joins are valid within a phase only. Card definition IDs remain public numeric values. No raw cookies, session values, headers, query strings, account names, persona IDs, error messages or stacks are retained. Numeric balances are retained for this authorized research. Local processes or privileged extensions can forge observations; these are not cryptographic attestations.

Explicit commands from the workspace:

```text
python -m fc_access.read_server
python -m fc_access.harness compare
python -m fc_access.harness --output docs/research/capabilities/one-read.json read edge coins
python -m fc_access.report
python tests/test_integration_harness.py
python tests/test_capability_artifacts.py
python tests/validate_capabilities_live.py
```

read edge search --params accepts a JSON object with page, count, definition_id, max_buy, min_buy, nation, league, club, rarity, position and fresh; support limitations above apply. Only one bounded command is in flight. The server binds to 127.0.0.1:8767. Version 0.1.1 uses extension-origin POST /next for polling because Edge may omit Origin on extension GETs; strict origin, Host, payload and command validation are preserved. Command deadline is 60 seconds and native observable timeout is 15 seconds; late and duplicate responses are rejected.

The attachment prerequisite is resolved for this capture. For future lost attachment only: load browser/read-bridge in the same Edge profile, return to the existing HTTPS EA Ultimate Team Web App tab, and click FC read capability bridge. No browser restart, tab refresh or login is required unless the actual page needs it. python tests/check_read_prerequisite.py checks only attachment, not evidence or authentication. Cleanup is to disable this separate extension and stop only its server; the original observer is independent.

Deterministic tests run synthetic browser/HTTP behavior, credential canaries, timeouts, queue/origin enforcement, read-plan and identity checks in temporary files. The live validator reads only retained attempts.json and independently checks typed field readbacks, exact card and ceiling matches, supported filters, platform and each account state. Successful attachment or HTTP 200 alone cannot satisfy it.

## Primary source review (not live proof)

EA [compiled_2.js](https://www.ea.com/ea-sports-fc/ultimate-team/web-app/js/compiled_2.js) SHA256 `2cc8aec08628ea78c361b16456c93d672e1e80219ed246af0ace61f1b1018f83` provides the item factory resourceId → definitionId mapping. [compiled_3.js](https://www.ea.com/ea-sports-fc/ultimate-team/web-app/js/compiled_3.js) SHA256 `2442488651aa9c9fe68f7dd20dd8418e71affa3060f97f49876bbf77f6f9c80a` shows the native market UI and read methods. [ocompiled.js](https://www.ea.com/ea-sports-fc/ultimate-team/web-app/js/ocompiled.js) SHA256 `90c120d41798623f756f1732010db21fd3c849e695abfce4e968700fd84fb9a2` was decoded using static base64/string-table substitution only; no downloaded JavaScript was executed. Its retained snippets establish the purchased queue, filter mapping, pagination and cache implementation. Public source review timestamps and local file hashes are retained in source-review.json.

Independent machine assessment:

```json
{
  "errors": [],
  "facts": {
    "edge": {
      "attempts": 23,
      "authenticated_reads": 14,
      "elapsed_ms": [
        10776.821,
        29909.016,
        30199.167,
        29976.583,
        29896.501,
        21231.349,
        30010.932,
        29949.608,
        29943.235,
        30985.684,
        29982.121,
        29172.877,
        9860.722,
        30214.389
      ],
      "unavailable_reasons": [
        "bridge_not_attached",
        "service_unavailable"
      ]
    },
    "direct_http": {
      "attempts": 7,
      "authenticated_reads": 0,
      "elapsed_ms": [],
      "unavailable_reasons": [
        "direct_session_provider_unavailable"
      ]
    },
    "filters": {
      "nation": "UNVERIFIED",
      "league": "VERIFIED",
      "club": "VERIFIED",
      "rarity": "UNVERIFIED",
      "position": "UNVERIFIED"
    },
    "market_average": "UNVERIFIED",
    "last_sale_price": "OBSERVED",
    "comparable_groups": {
      "pc:173891": {
        "platform": "pc",
        "definition_id": 173891,
        "distinct_auction_pseudonyms": 1
      },
      "pc:186146": {
        "platform": "pc",
        "definition_id": 186146,
        "distinct_auction_pseudonyms": 1
      },
      "pc:200724": {
        "platform": "pc",
        "definition_id": 200724,
        "distinct_auction_pseudonyms": 1
      },
      "pc:202693": {
        "platform": "pc",
        "definition_id": 202693,
        "distinct_auction_pseudonyms": 1
      },
      "pc:207952": {
        "platform": "pc",
        "definition_id": 207952,
        "distinct_auction_pseudonyms": 1
      },
      "pc:209750": {
        "platform": "pc",
        "definition_id": 209750,
        "distinct_auction_pseudonyms": 1
      },
      "pc:211361": {
        "platform": "pc",
        "definition_id": 211361,
        "distinct_auction_pseudonyms": 1
      },
      "pc:211978": {
        "platform": "pc",
        "definition_id": 211978,
        "distinct_auction_pseudonyms": 1
      },
      "pc:212228": {
        "platform": "pc",
        "definition_id": 212228,
        "distinct_auction_pseudonyms": 1
      },
      "pc:218659": {
        "platform": "pc",
        "definition_id": 218659,
        "distinct_auction_pseudonyms": 1
      },
      "pc:220710": {
        "platform": "pc",
        "definition_id": 220710,
        "distinct_auction_pseudonyms": 1
      },
      "pc:224099": {
        "platform": "pc",
        "definition_id": 224099,
        "distinct_auction_pseudonyms": 1
      },
      "pc:231184": {
        "platform": "pc",
        "definition_id": 231184,
        "distinct_auction_pseudonyms": 1
      },
      "pc:231736": {
        "platform": "pc",
        "definition_id": 231736,
        "distinct_auction_pseudonyms": 2
      },
      "pc:232658": {
        "platform": "pc",
        "definition_id": 232658,
        "distinct_auction_pseudonyms": 1
      },
      "pc:233731": {
        "platform": "pc",
        "definition_id": 233731,
        "distinct_auction_pseudonyms": 61
      },
      "pc:235735": {
        "platform": "pc",
        "definition_id": 235735,
        "distinct_auction_pseudonyms": 1
      },
      "pc:235805": {
        "platform": "pc",
        "definition_id": 235805,
        "distinct_auction_pseudonyms": 1
      },
      "pc:236772": {
        "platform": "pc",
        "definition_id": 236772,
        "distinct_auction_pseudonyms": 3
      },
      "pc:236987": {
        "platform": "pc",
        "definition_id": 236987,
        "distinct_auction_pseudonyms": 1
      },
      "pc:237386": {
        "platform": "pc",
        "definition_id": 237386,
        "distinct_auction_pseudonyms": 1
      },
      "pc:239627": {
        "platform": "pc",
        "definition_id": 239627,
        "distinct_auction_pseudonyms": 1
      },
      "pc:239837": {
        "platform": "pc",
        "definition_id": 239837,
        "distinct_auction_pseudonyms": 2
      },
      "pc:241953": {
        "platform": "pc",
        "definition_id": 241953,
        "distinct_auction_pseudonyms": 1
      },
      "pc:242516": {
        "platform": "pc",
        "definition_id": 242516,
        "distinct_auction_pseudonyms": 1
      },
      "pc:243263": {
        "platform": "pc",
        "definition_id": 243263,
        "distinct_auction_pseudonyms": 1
      },
      "pc:243576": {
        "platform": "pc",
        "definition_id": 243576,
        "distinct_auction_pseudonyms": 1
      },
      "pc:245155": {
        "platform": "pc",
        "definition_id": 245155,
        "distinct_auction_pseudonyms": 1
      },
      "pc:246104": {
        "platform": "pc",
        "definition_id": 246104,
        "distinct_auction_pseudonyms": 1
      },
      "pc:246565": {
        "platform": "pc",
        "definition_id": 246565,
        "distinct_auction_pseudonyms": 1
      },
      "pc:247946": {
        "platform": "pc",
        "definition_id": 247946,
        "distinct_auction_pseudonyms": 1
      },
      "pc:250758": {
        "platform": "pc",
        "definition_id": 250758,
        "distinct_auction_pseudonyms": 1
      },
      "pc:251262": {
        "platform": "pc",
        "definition_id": 251262,
        "distinct_auction_pseudonyms": 1
      },
      "pc:253054": {
        "platform": "pc",
        "definition_id": 253054,
        "distinct_auction_pseudonyms": 1
      },
      "pc:253124": {
        "platform": "pc",
        "definition_id": 253124,
        "distinct_auction_pseudonyms": 3
      },
      "pc:253149": {
        "platform": "pc",
        "definition_id": 253149,
        "distinct_auction_pseudonyms": 4
      },
      "pc:253163": {
        "platform": "pc",
        "definition_id": 253163,
        "distinct_auction_pseudonyms": 1
      },
      "pc:257271": {
        "platform": "pc",
        "definition_id": 257271,
        "distinct_auction_pseudonyms": 1
      },
      "pc:257289": {
        "platform": "pc",
        "definition_id": 257289,
        "distinct_auction_pseudonyms": 3
      },
      "pc:257345": {
        "platform": "pc",
        "definition_id": 257345,
        "distinct_auction_pseudonyms": 1
      },
      "pc:257423": {
        "platform": "pc",
        "definition_id": 257423,
        "distinct_auction_pseudonyms": 1
      },
      "pc:258433": {
        "platform": "pc",
        "definition_id": 258433,
        "distinct_auction_pseudonyms": 1
      },
      "pc:259660": {
        "platform": "pc",
        "definition_id": 259660,
        "distinct_auction_pseudonyms": 1
      },
      "pc:261786": {
        "platform": "pc",
        "definition_id": 261786,
        "distinct_auction_pseudonyms": 1
      },
      "pc:262621": {
        "platform": "pc",
        "definition_id": 262621,
        "distinct_auction_pseudonyms": 1
      },
      "pc:263798": {
        "platform": "pc",
        "definition_id": 263798,
        "distinct_auction_pseudonyms": 1
      },
      "pc:264670": {
        "platform": "pc",
        "definition_id": 264670,
        "distinct_auction_pseudonyms": 1
      },
      "pc:270857": {
        "platform": "pc",
        "definition_id": 270857,
        "distinct_auction_pseudonyms": 1
      },
      "pc:273478": {
        "platform": "pc",
        "definition_id": 273478,
        "distinct_auction_pseudonyms": 1
      },
      "pc:274979": {
        "platform": "pc",
        "definition_id": 274979,
        "distinct_auction_pseudonyms": 1
      },
      "pc:276278": {
        "platform": "pc",
        "definition_id": 276278,
        "distinct_auction_pseudonyms": 1
      },
      "pc:278131": {
        "platform": "pc",
        "definition_id": 278131,
        "distinct_auction_pseudonyms": 1
      },
      "pc:278623": {
        "platform": "pc",
        "definition_id": 278623,
        "distinct_auction_pseudonyms": 1
      },
      "pc:278974": {
        "platform": "pc",
        "definition_id": 278974,
        "distinct_auction_pseudonyms": 1
      },
      "pc:279044": {
        "platform": "pc",
        "definition_id": 279044,
        "distinct_auction_pseudonyms": 1
      },
      "pc:279128": {
        "platform": "pc",
        "definition_id": 279128,
        "distinct_auction_pseudonyms": 1
      },
      "pc:50408058": {
        "platform": "pc",
        "definition_id": 50408058,
        "distinct_auction_pseudonyms": 1
      },
      "pc:50563169": {
        "platform": "pc",
        "definition_id": 50563169,
        "distinct_auction_pseudonyms": 1
      },
      "pc:50578738": {
        "platform": "pc",
        "definition_id": 50578738,
        "distinct_auction_pseudonyms": 1
      },
      "pc:50579536": {
        "platform": "pc",
        "definition_id": 50579536,
        "distinct_auction_pseudonyms": 1
      },
      "pc:50596300": {
        "platform": "pc",
        "definition_id": 50596300,
        "distinct_auction_pseudonyms": 26
      },
      "pc:74586": {
        "platform": "pc",
        "definition_id": 74586,
        "distinct_auction_pseudonyms": 1
      },
      "pc:76687": {
        "platform": "pc",
        "definition_id": 76687,
        "distinct_auction_pseudonyms": 1
      },
      "pc:77403": {
        "platform": "pc",
        "definition_id": 77403,
        "distinct_auction_pseudonyms": 1
      },
      "pc:77763": {
        "platform": "pc",
        "definition_id": 77763,
        "distinct_auction_pseudonyms": 1
      },
      "pc:79419": {
        "platform": "pc",
        "definition_id": 79419,
        "distinct_auction_pseudonyms": 1
      },
      "pc:80346": {
        "platform": "pc",
        "definition_id": 80346,
        "distinct_auction_pseudonyms": 1
      },
      "pc:82289": {
        "platform": "pc",
        "definition_id": 82289,
        "distinct_auction_pseudonyms": 1
      },
      "pc:82724": {
        "platform": "pc",
        "definition_id": 82724,
        "distinct_auction_pseudonyms": 1
      },
      "pc:85858": {
        "platform": "pc",
        "definition_id": 85858,
        "distinct_auction_pseudonyms": 1
      }
    },
    "pagination": {
      "two_nonempty_pages": "OBSERVED",
      "page_pairs": 2,
      "ordering": "OBSERVED_EXPIRY_ASCENDING_BIN_UNSORTED",
      "lookahead": "OBSERVED_ONE_ROW_OVERLAP",
      "caching": "UNVERIFIED",
      "invalidation": "OBSERVED_NATIVE_RESET_AND_NETWORK_READ",
      "observations": [
        {
          "page_1_at": "2026-11-11T18:14:19.195356+00:00",
          "page_2_at": "2026-11-11T18:14:49.174281+00:00",
          "page_1_count": 21,
          "page_2_count": 21,
          "overlap_count": 0,
          "lookahead_row_matches_next_page": false,
          "page_1_bin_nondecreasing": false,
          "page_1_expiry_nondecreasing": true
        },
        {
          "page_1_at": "2026-11-11T18:15:57.895531+00:00",
          "page_2_at": "2026-11-11T18:16:19.128936+00:00",
          "page_1_count": 21,
          "page_2_count": 20,
          "overlap_count": 1,
          "lookahead_row_matches_next_page": true,
          "page_1_bin_nondecreasing": false,
          "page_1_expiry_nondecreasing": true
        }
      ],
      "fresh_network_reads": 7,
      "cached_native_reads": 0
    },
    "expiry_readbacks": [
      {
        "first_at": "2026-11-11T18:15:57.895531+00:00",
        "second_at": "2026-11-11T18:16:49.141922+00:00",
        "elapsed_seconds": 59.965,
        "matched_auctions": 21,
        "countdowns_matching_elapsed_seconds": 21
      },
      {
        "first_at": "2026-11-11T18:15:57.895531+00:00",
        "second_at": "2026-11-11T18:17:19.094143+00:00",
        "elapsed_seconds": 89.91,
        "matched_auctions": 21,
        "countdowns_matching_elapsed_seconds": 21
      },
      {
        "first_at": "2026-11-11T18:16:49.141922+00:00",
        "second_at": "2026-11-11T18:17:19.094143+00:00",
        "elapsed_seconds": 29.946,
        "matched_auctions": 21,
        "countdowns_matching_elapsed_seconds": 21
      }
    ],
    "expiry_units": "OBSERVED_SECONDS_REMAINING",
    "coins": "VERIFIED",
    "coins_readback_mode": "NETWORK_READ",
    "club": "VERIFIED",
    "club_readback_mode": "NATIVE_SNAPSHOT_NETWORK_FRESHNESS_UNVERIFIED",
    "unassigned": "VERIFIED",
    "unassigned_readback_mode": "NETWORK_READ",
    "purchased": "VERIFIED",
    "purchased_readback_mode": "SHARED_PURCHASED_UNASSIGNED_ENDPOINT",
    "transfer_list": "VERIFIED",
    "transfer_list_readback_mode": "NETWORK_READ"
  }
}
```
