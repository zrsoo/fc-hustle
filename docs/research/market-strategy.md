# Market availability and offline profitability proof — task_05

Research checkpoint: **2026-11-11**, native reads **19:10:03–19:11:15 UTC**. Task_05 is complete as research and an offline proof. Objective 002 remains **CONDITIONAL GO**: targeted EA data works, but current per-card caps, a complete increment schedule, realized-sale tax rounding, broad bulk access and historical numeric series remain gaps. This task contains no production continuous bot. Indicative prices are never guaranteed sale prices; an asking price is evidence of supply, not a completed sale or a fill-time prediction.

The locked flow remains scan → evaluate → buy → list → repeat, with configurable profit threshold X and no added per-trade approval or portfolio policies. This proof performs only finite offline evaluation; the separately retained single purchase/listing experiment is not repeated.

## Current source evaluation

[availability.json](market/availability.json) retains three actual native searches, their exact request shapes, allowlisted results, network status, platform, timestamps and wall times, followed by public HTTP probes. [web-review.json](market/web-review.json) distinguishes the web reader from direct Python access. No cookies, credentials or raw account objects were captured. Auction/item IDs are per-capture pseudonyms; do not join them across capture runs.

| Source | Current evidence | Use and access gap |
| --- | --- | --- |
| Targeted EA searches | `services.Item.searchTransferMarket(criteria, page)`; all three returned HTTP 200 with authenticated GET `/ut/game/fc27/transfermarket`, platform `pc`, and exact requested definition IDs | Primary live ask source. Full `definition_id`, platform and game must match; missing `resource_id`/`asset_id` does not authorize substituting a base player ID. |
| EA comparable BINs, definition 233731 | Page 1: 21 rows; page 2: 21 rows; 42 rows / 41 distinct auctions, 6100–7000 coins. Ceiling `max_buy=7000` | This is a truncated, ceiling-biased sample, not the whole market. One overlapping auction is counted once. No sort-by-BIN contract. |
| EA comparable BINs, definition 278230 | One exact-version page, no BIN ceiling: 10 rows / 10 auctions, 200–4000 coins | Six remaining near-floor asks survive the replay's candidate exclusion and outlier filtering. Thin supply and manipulated asks remain possible. |
| EA `marketAverage` | `market_average=null` in all 52 projected rows | Not available in these native models. This does not prove the wire API universally omits it. Never fill missing values with zero. |
| EA `lastSalePrice` | `last_sale_price=0` in 24 rows; positive in 28 rows. Definition 233731 has 4900–6900 positive values; definition 278230 has 200 | Zero means unavailable here. The physical item's prior sale is not a timestamped version/platform-wide median; age and semantics are unverified. Diagnostic cross-check only, excluded from estimator samples. |
| FUT.GG FC27 manifest | Direct `GET https://r2.fut.gg/27/manifest.json` returned **403** at 19:11:15 UTC; web reader also could not access it | Current bulk availability is blocked from this environment. Do not infer service-wide downtime. No manifest body, publication timestamp, hash, cardinality, bulk price or PC coverage was obtained. |
| FUT.GG catalog | Direct `https://www.fut.gg/api/fut/players/v2/27/?pageSize=1` returned **403** | No validated catalog mapping or schema from current data. A readable player directory is not an accessible JSON API. |
| FUT.GG history / ranges | Python returned **403** for momentum, player-history and price-range pages. Web reader rendered the UI | Momentum has 6h/12h/24h controls, but no numeric timestamped series was extracted. “Player History” means past player cards, not market-price history. No exact PC cap is verified. |
| Other historical prices | [FUTGenie's own description](https://www.futgenie.gg/posts/view-on-futgenie) was reachable (200) and describes history and recent sales by Console/PC | Article availability is provider-claim evidence only. No series, retention, coverage, sample timestamps or automated endpoint was verified. No API credential was supplied or subscription purchased. |

The current endpoint host was `utas.mob.v1.prd.futc-ext.gcp.ea.com`; it is observed evidence, not a host to hardcode in future clients. [Task_03's targeted capture](capabilities/resume-targeted.json) separately demonstrated club/league filters, a contradictory definition/club filter yielding no results, expiry countdown decay, and fresh resets. The current 42-row two-page capture has one overlap and unsorted BIN prices, consistent with [the retained capability assessment](capabilities/verification.json). Offset paging is not a stable cursor: listings can disappear, appear, expire or repeat between reads. No measured query provides exhaustive all-card coverage.

The [pinned sniffer implementation](https://github.com/puredan824-hub/fc27-sniffer/blob/e1488d6e51bdcafec6eaf61cdb06461358b7844d/r2_prices.py#L57) supplies a **source contract**, not live bulk proof: `_version`, `_published_at`, hashed filenames `key.v{version}.{hash}.json`, `player-prices-index` (`id0` + deltas `d`), `player-prices-ps5-dyn` (`p`/`s`) and `streamlined-pool` (`o`/`r`). If access returns, fetch only advertised URLs; check schema version, positive unique decoded card IDs, monotone publication times and all aligned lengths before use. Interpret status codes only after validation. PC data is not established by PS5 prices. Never invent a PC filename/hash or merge console prices into PC samples. No bulk blob was fetched because the manifest was denied. The manually invoked probe follows advertised supported keys if a valid manifest becomes available; it is not a production feed decoder.

Readable first-party UI references: [FUT.GG momentum](https://www.fut.gg/players/momentum/), [player-history directory](https://www.fut.gg/players/history/), [price ranges](https://www.fut.gg/price-ranges/). Different access channels have different results; a web-rendered shell does not override direct 403 evidence. Historical-price availability is therefore **UNVERIFIED for numeric backfill**. Existing local observations provide a few minutes of asks, not a long-term history or evidence of completed sales. Retaining future observations locally could build a series; this task does not run that collector continuously.

## Scan universe, cadence, caching and revalidation

Initial scan universe: the two independently observed **PC FC27 definitions 233731 and 278230**. This is a small watchlist, not all FC27 players. A future catalog/bulk source may rank other exact versions for admission; every admitted version still needs EA comparables and its own current price caps. No name-only matches, cross-platform averages or special/base-version blending. A bulk quote is a discovery hint only.

Proposed operating defaults for Objective 002 (design, not an implemented loop):

| Work | Cadence / cache | Coverage and latency limit |
| --- | --- | --- |
| Public reference manifest | Every 300 seconds; conditional ETag/Last-Modified where provided; retain publication time and content hash | Download changed advertised blobs only. Cache successful snapshots by `(game, platform, publication, version)`; reject missing timestamps, age over 600 seconds, invalid schema or reversed publication time. HTTP errors do not refresh freshness. Current 403 means unavailable, with no silent fallback to an old quote. |
| Live EA first-page inspection | Each of the two watched versions every 90 seconds, serialized global minimum 30 seconds between command submissions | About 1.33 calls/minute; at most 21 rows per page, one of which may be lookahead. Observed end-to-end calls: 12220.924, 30012.495, 29961.553 ms, including extension alarm waits. These are not server-only latency or a rate-limit guarantee. |
| Comparable reference refresh | Recompute from every live first page; fetch page 2 for each watched version every 300 seconds, immediately after a matching first-page refresh | Adds 0.4 calls/minute, total about 1.73/minute before opportunity work. Maximum two pages in the retained bridge. Old page-2 rows age out; minimum samples must still hold. The sample is not necessarily the cheapest 40 auctions and cannot imply time-to-sale. |
| Opportunity revalidation | Priority work immediately before a future purchase; consumes the same serialized request budget and can delay periodic work | Fresh exact-version first page, exact trade and physical-item identity, unchanged executable BIN, active status and sufficient remaining lifetime; recompute comparables, caps, tax and `expected_profit >= X`. If candidate disappears or sample/price changes, skip/re-evaluate. No cached decision grants purchase authority. |

Under the measured bridge delay, an opportunity may take another 30–60 seconds to revalidate and dispatch; subsecond sniping is unsupported. At two watched versions these cadences fit nominal capacity with little spare time. A larger universe reduces freshness or requires a smaller active set; do not promise whole-market coverage at this rate. Page boundaries can move during the measurement. Stop new dispatches on challenge/auth loss; honor Retry-After or exponential backoff on 429/5xx, and invalidate opportunity decisions. Errors and actual timings override proposed schedules; no cadence claims immunity from restrictions.

EA reference cache key: `(game, platform, definition_id, filter signature, page, native network read time)`. Store full auction identity, BIN, expiry and freshness, not only aggregates. Deduplicate by auction and physical item; conflicting duplicates invalidate that identity. The estimator accepts only network-fresh observations no older than **120 seconds**, including collection/queue delay. Compare remaining lifetime after age decay. Native search reset/invalidation is requested at the beginning of a refresh, followed by an actual network GET; `fresh=false` alone does not establish either a cache hit or miss. In this capture all three searches had network reads. Task_04's [cached-read failure and recovery](purchase-to-list.md) demonstrates why native callback success is insufficient. Never reset pagination between the first and second page of a sample; invalidate the whole sample after a criteria change.

The offline default rejects remaining lifetime **<=30 seconds**. For a future execution adapter set `Policy(min_remaining=60)` or greater to cover the measured dispatch delay plus a 30-second margin, and require a candidate read within 30 seconds of submission. Reject missing/changed caps or caps older than **300 seconds**. Recheck session/platform, exact item/trade/version, tradability, legal BIN and reference freshness at execution. Reconcile an ambiguous purchase and suppress duplicate writes using task_04's journal before any further action. Objective 002 must then list the acquired physical item at the revalidated target and read it back; a real sale may still fail to occur.

## Deterministic estimator and arithmetic

[pricing.py](../../fc_access/pricing.py) is a pure integer/Fraction calculator with no network or transaction API. `MarketKey` is `(game, exact definition_id, platform)`. `Rules` must have that same key, fresh explicit minimum/maximum caps and a supplied increment schedule. Missing caps produce `MISSING_CAPS`; wrong/stale caps and intervals containing no legal price also fail closed. Observed BIN extrema are not price caps. Caller-supplied synthetic caps permit an offline example but cannot establish a live execution prerequisite.

1. Reject wrong variants/platforms/games, malformed or noninteger prices (including booleans), missing identities, future/stale times, nonnetwork cache reads, inactive/expiring auctions, prices outside caps and off-grid BINs. Unknown data remains unknown.
2. Exclude the proposed acquisition's trade AND physical item so the cheap candidate cannot set its own resale price. Deduplicate repeated auctions. Conflicting price/key/item copies and multiple trade IDs for the same physical item are excluded. Consistent repetitions use the freshest valid read; observations are not independent just because they occur on two pages.
3. Require **at least five distinct comparables** before and after outlier filtering. Compute exact median `m` and median absolute deviation `MAD`; keep `abs(price-m) <= max(3*MAD, m/5)`. The 20% floor prevents zero-MAD collapse while rejecting extreme cheap/expensive tails. No inflation from historical/indicative fallback. Thin markets return an insufficient-samples status and no target. A clustered manipulated market can defeat this heuristic; no sale probability is inferred.
4. Sort retained BINs, use index `floor((n-1)/4)` as the lower quartile reference, round down to the greatest legal price within caps, then undercut by one legal tick. At the minimum legal price, keep that minimum rather than round up. Never exceed an observed cap to reach X. Ordering of input rows has no effect.
5. `target_sale_price` is that indicative proposed BIN, **not a guaranteed sale price**. `acquisition_price` is the currently revalidated candidate BIN in coins; it is not the starting/current bid. `X` is configurable nonnegative integer minimum modeled profit, with equality accepted.

```text
expected_profit = target_sale_price - floor(target_sale_price * 0.05) - acquisition_price
tax = target_sale_price // 20
meets_threshold = sufficient_valid_data AND expected_profit >= X
```

Integer division exactly implements the locked 5% floor formula without floating-point error. `meets_threshold` is an offline modeled signal, never an executable order. For 6000 target and 5000 acquisition: tax 300, expected profit 700, so X=700 passes and X=701 fails. For 250 target and 200 acquisition: modeled tax 12 and profit 38. These are arithmetic examples, not observed settled proceeds.

## Empirical bands, rounding and unresolved behavior

The fresh low-price capture contains BINs **200, 250, 4000** and starting bids **150, 200, 3900**. Definition 233731's BINs range **6100–7000** on 100-coin grid points. [Task_04](purchase-to-list.md) independently verified buying at 200 and creating/reading an active listing with 200 starting bid and 250 BIN. These demonstrate accepted particular prices and 50/100-coin spacings in sampled regions, not all legal ticks or the global price range. No probing writes were used to discover bands.

| Modeled interval | Modeled increment | Empirical status |
| --- | --- | --- |
| 150 <= price < 1000 | 50 | Selected low-price points and 200/250 listing observed; complete interval and minimal increment **UNVERIFIED** |
| 1000 <= price < 10000 | 100 | 6100–7000 grid points and 4000 observed; transition at 1000 and minimal increment **UNVERIFIED** |
| 10000 <= price < 50000 | 250 | **UNVERIFIED** |
| 50000 <= price < 100000 | 500 | **UNVERIFIED** |
| 100000 <= price <= 15000000 | 1000 | **UNVERIFIED**, including maximum global bound |

This schedule is an explicit configurable hypothesis in the offline proof. Tests around 950/1000, 9900/10000, 49750/50000 and 99500/100000 verify implementation of the hypothesis, not EA acceptance. Exact-card PC minimum/maximum caps were not captured and remain **UNVERIFIED**. Realized tax debit, rounding down versus another rule, and tax at odd 5% boundaries remain **UNVERIFIED**: task_04 proved an active listing, not a completed sale with coin settlement. The floor formula is required by the locked objective; no empirical tax claim follows from the 200/250 transaction. A future settled-sale readback and fresh native price-limit/range evidence are needed before treating these assumptions as verified.

## Retained offline proof and validation

[offline-proof.json](market/offline-proof.json) is reproducible from the sanitized native capture, evaluated at its retained completion time. With missing observed caps both markets return `MISSING_CAPS`. With explicitly **hypothetical** 150–15000000 caps, the 233731 replay excludes its 6100 candidate, deduplicates one row, retains 40 comparables, proposes 6200, models tax 310 and profit **-210**. The 278230 replay excludes its 200 candidate and three outliers, retains six comparables, proposes 150, models tax 7 and profit **-57**. Neither meets even X=0. These negative results demonstrate that the data does not itself prove an executable profit.

[Synthetic fixtures](../../tests/fixtures/market-pricing.json) are labeled separately from live evidence. They cover profitable/equal/failed thresholds, low and high outliers, zero MAD, thin markets, minimum/transition rounding and tax floors. Tests additionally inject variant/platform mismatches, malformed data, duplicate/conflicting identities, stale/future observations, missing/stale/cross-market caps, price changes and cache-only reads. Artifact checks recompute the retained proof from native observations, cross-check report quantities and transaction prices, inspect code boundaries and resolve evidence links.

Run independently from the workspace, Python 3.10+ standard library only (no browser, network, third-party package or login required for validation):

```text
python tests/test_market_pricing.py
python tests/test_market_artifacts.py
python -m fc_access.market_replay
```

Optional fresh research capture: `python -m fc_access.market_probe`. It submits exactly three read-only searches through the already attached reviewed transaction bridge, followed by bounded public GETs, and updates only `market/availability.json`. It never buys/lists or alters task_04's journal. A new capture requires re-running the replay and updating the retained proof/report to the new observations; validators deliberately detect drift. Public 403 responses require restored legitimate data access for future bulk/history use, not a fabricated successful feed. Current source access gaps do not block this offline task's completion.
