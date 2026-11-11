# FC27 PC price-provider feasibility — T2

**No usable broad FC27 PC production feed was retrieved.** The single FUT.GG
manifest retest still returned **403**. DataFluxor and FUT-DB publish plausible
PC contracts, but ordinary anonymous production price requests returned **401**.
DataFluxor's public sandbox returned **200** twice; it explicitly serves fixed
illustrative data. Those responses establish authorized sandbox access, not
current PC prices, production coverage or a usable feed. T2 research is complete;
the EA-native fallback below is designed, and was not run as a new benchmark.

The [machine-readable findings and fallback](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/providers.json)
separate **MEASURED_HTTP**, **PROVIDER_DESCRIPTION**, **REPOSITORY_CLAIM** and
**PROPOSED_FALLBACK**. `null` means unknown, never zero coverage or free access.
Zero retrieved production quotes is a measurement of this research, not a claim
that providers have no quotes. All times below are UTC on 2026-11-11. The run
directory is a label; each request's actual timestamps are in the ledgers.

The five Objective 001 handoff documents and T1's scope/protocol were reviewed.
Existing evidence, objectives, pricing implementation and browser bridges were
preserved. No browser session, EA service, purchase runner or upstream program
was invoked. No account was created, message sent or subscription purchased.

## Retrieval evidence and boundaries

The [initial HTTP ledger](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/http.json),
[contract ledger](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/contracts/http.json)
and [terms ledger](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/terms/http.json)
contain 21 one-shot GETs with actual start/end times, elapsed milliseconds,
status, final URL, byte count, content type and original-body SHA-256. Client:
`fc-hustle-readonly-research/1.0`, standard Python TLS/proxy settings, no supplied
credentials, cookies, browser impersonation, retries or challenge solving.
The [collector](../../experiments/price_provider_research/collect_http.py) requires
new output directories. Offline validators never invoke it or the network.

| Requested URL or documented resource | Observed outcome | What it establishes |
| --- | --- | --- |
| `https://r2.fut.gg/27/manifest.json` | 403, **21:23:33.110603–21:23:33.200895**, 90.289 ms, 5,522 bytes, HTML | Exactly one retest; no JSON manifest, index, catalog or PC blob obtained. Access remains refused here; this does not establish service-wide downtime. |
| `https://datafluxor.com/fut-data`, `/terms`, `/docs`, `/openapi.json` | 200 | Public descriptions/specification, not production quote retrieval. |
| `https://datafluxor.com/api/v1/fut/prices?ea_ids=233731&platform=pc` | 401 | JSON says API key required; no production quote or verified mapping. |
| `https://datafluxor.com/api/fut-sandbox/prices?ea_ids=67340611,231747&platform=pc` | 200 | Fixed example returns **two PS/console rows despite requesting PC**, plus one unresolved ID that was not requested. This sandbox ignores query variation; it cannot test production mapping/platform correctness. |
| `https://datafluxor.com/api/fut-sandbox/cards/22950/history?market=pc&period=30d` | 200 | Three fixed illustrative PC points; no measured live history. |
| `https://fut-db.com/`, `/terms`; `https://api.fut-db.com/api/doc/v1/swagger.json` | 200 | Current public pricing, terms and FC27 OpenAPI contract. |
| `https://api.fut-db.com/api/players/1/price` | 401, empty body | Key gate on documented route; ID 1 is an authentication probe, not a verified card crosswalk. |
| `https://www.futbin.com/`, `/tos` | 403 | No production data; terms were readable separately in the web reader. |
| `https://www.futwiz.com/`, `/privacy`, `/contact` | 200 | Website and contact availability; no API entitlement or numeric PC quote extraction. |
| `https://www.fut.gg/` | 403 | Direct website access refused. Web reader can show public UI/legal links; that is not bulk access. |
| `https://stormstrike.gg/terms` | 200 | FUT.GG's linked automation restrictions. |
| `https://dsfut.net/api`; EA Community API announcement | 200 | Documentation only; neither is a public broad card-price feed. |

The [public text excerpts](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/public-documents.json)
retain source URLs, request references and relevant provider paragraphs. The
[reader review](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/reader-review.json)
records the separate reader/search channel, legal sections and scoped searches.
Reader HTTP status is unknown unless explicitly reported by the reader; it is
never substituted for a measured direct response. Original full HTML, challenge
bodies, GitHub metadata and full source remain only in ignored private captures.
Retained evidence has no response cookies, account IDs, session values or API
keys. A header *name* such as `X-API-Key` is documentation, not a credential.
Original-body hashes cannot be recomputed from sanitized excerpts; the
[artifact manifest](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/artifacts.json)
separately pins all retained bytes. Hashes establish local integrity, not upstream
authenticity or current availability.

## Provider feasibility

All counts, cadence and costs marked “describes” below are **provider
descriptions**, not measurements of a downloaded production feed. For every
candidate the measured priced-card count, production publication time and refresh
interval are **unknown**, and exact mapping against fresh EA PC data is unverified.

| Candidate | Contract, batching and platform | Access, current advertised cost/limits | Assessment and terms |
| --- | --- | --- | --- |
| [DataFluxor FUT Data](https://datafluxor.com/fut-data) | FC27; `GET /api/v1/fut/prices?ea_ids=…&platform=pc`, up to 500 exact versions; POST same read supports identity hints. `ps`/`xbox` share console; `pc` separate. Browse pages up to 100. | Describes **US$29/month**, before tax, 100,000 successful requests/month; a 500-card price batch costs one request. 120/min, 3 in flight/key, 6/organization. Errors and all-unknown batches uncharged; exhausted allowance 402, throttle 429/Retry-After. Production requires active FUT subscription/key; general Free credits do not include it. | Most explicit commercial PC contract; **not usable here without legitimate entitlement**. No purchase/trial initiated. [Terms](https://datafluxor.com/terms) permit results in own products subject to terms; raw API/service resale requires written agreement; data as-is, delayed, user responsible for EA terms. |
| [FUT-DB](https://fut-db.com/) | OpenAPI `info.version=27`; premium `GET /api/players/{playerId}/price` returns `pc` and `playstation`. Batch path exists in Swagger but conflicts with homepage FAQ; details below. | Describes **€79/month**, 20,000 requests/day, no recurring payment. Key `X-AUTH-TOKEN`, premium prices. Burst limit unknown. | Production GET 401. [Terms](https://fut-db.com/terms): advance/nonrefundable payment, no automatic renewal, content reproduction/distribution/modification needs permission, no data warranty. No right to redistribute inferred. |
| [FUTBIN](https://www.futbin.com/tos) | No public licensed broad-PC API contract obtained. Site IDs, batching and PC coverage not verified. Consumer UI/subscription is not a developer feed agreement. | Home and terms direct GET 403. API subscription cost, numerical quota and partner requirements unknown. | Terms §§4/13 require business-use license and written scraping permission; credited student/content-creator exception exists, eligibility for this project's automated use not established. No hidden API, legacy SDK or scraping fallback attempted. |
| [FUTWIZ](https://www.futwiz.com/) | Homepage describes FC27 console and PC prices. Scoped site documentation searches found no bulk developer price contract; this is not proof that private feeds do not exist. | Home/privacy/contact 200. Exact-version mapping, batching, API costs/limits and entitlement unknown. | UI access is not data permission. Privacy/EA-asset footer does not grant automated extraction rights. [Commercial contact](https://www.futwiz.com/contact) is a possible agreement route; no inquiry sent. |
| [FUT.GG / Stormstrike](https://stormstrike.gg/terms) | R2 manifest refused. Index, catalog, PC dataset and status meanings below are repository contracts only. | No verified supported public bulk entitlement, price or numeric limit. Anonymous URL/code availability does not establish permission. | Terms' License/Acceptable Use restrict automated access except where expressly permitted. Disable until legitimate access and terms are resolved; no hash guessing, direct-origin substitution or denial retries. |

The scoped [DataFluxor OpenAPI projection](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/datafluxor-openapi-projection.json)
and [FUT-DB OpenAPI projection](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/futdb-openapi-projection.json)
retain the exact relevant path definitions, authentication schemes and referenced
schemas. These are specification evidence, not verified server behavior. No
POST or body-bearing GET was needed for this investigation.

DataFluxor describes `ea_id` as the full EA card/version identity, `player_id`
as the shared base player and `futbin_id` as its catalog card ID for detail/history
paths. `ea_id=0`, ambiguity or disagreement with rating/rarity/club hints must
remain unresolved. Map only to `(fc27, pc, definition_id)` after independent
confirmation; names, base IDs and identical ratings do not prove the same version.
The live-read page describes roughly **22,000 versions**, **20,500 console-priced**,
measured **by the provider on 2026-11-10**; **PC priced count is not stated**.

Its described price is stored lowest BIN in coins, not median or guaranteed last
sale. `price_source=card` supplies same-read listings/ranges/recent sales;
`list` supplies a newer list-price observation. Recent sales are separate,
unverified source observations. Zero means no listing on latest read, never a
zero-cost purchase. Preserve `observed_at`, `checked_at`, upstream
`futbin_updated_at`/`source_updated_at`, age and source separately from HTTP receipt.
An HTTP Date or response `timestamp` does not make a quote fresh.

The current page describes top 5,700 list reads every **8 minutes**, other cards
every **25 minutes**, top 500 exact reads every **20 minutes**. Quotes are stale
after **15 minutes**, while summary `price`/`price_pc` can use a **24-hour** stale
threshold. History starts **2026-09-25**, retained up to 90 days exact/180 days
daily, at most 200 returned points. Requests read storage immediately; on-demand
refresh is excluded. Indexed search text instead described 21,000 cards and
45-minute/10-minute cadence; retained direct GET evidence takes precedence, and
neither cadence was measured. Page says concurrency may wait 20 seconds, whereas
OpenAPI emphasizes refusal; runtime queue behavior remains unresolved.

The retained [sandbox prices](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/sandbox-prices.json)
say `sandbox=true` and warn that values are fixed. Example EA IDs 67340611 and
231747 map to sample catalog IDs 22950/8 and PS prices 1,250,000/118,000;
the example response timestamp **2026-09-27T21:59:36Z** and quote times are not
2026-11-11 market observations. Its `age_seconds`/`stale=false` are fixture values,
not current freshness. [Sandbox history](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/sandbox-history.json)
returns three PC points dated September 26–27. Count them only as fixture rows.

FUT-DB's `PlayerModel.id` is a provider ID; nullable `resourceId` must be
crosswalked to full EA `definition_id`, while `resourceBaseId` is the base identity;
`futBinId`/`futWizId` are other site IDs. No empirical crosswalk was obtained.
The site describes **22,143 players**, not 22,143 priced PC versions. Quote fields
are nullable `price`, `minPrice`, `maxPrice`, `prp`, `priceUpdate`; exact price
methodology is unspecified. The schema oddly lists required `id` on `Price`
without declaring that property. The provider describes 30-minute to 24-hour
refresh by rating/rarity, with no inspected historical-price route. Swagger's
`GET /api/players/prices` uses a JSON array request body and says one request per
player, while the FAQ says multiple prices in one request are unavailable. Do
not infer batching savings, invent a query parameter or assert Xbox equivalence.

For scale only, 22,000 known IDs would take **44** DataFluxor price batches or
**220** browse pages at the advertised maxima. Polling all 44 batches every eight
minutes for 30 days would require 237,600 requests, exceeding 100,000; every
25 minutes would require 76,032 before catalog/history overhead. These are
arithmetic scenarios using approximate advertised counts, not measured coverage,
recommended traffic or proof all IDs have PC quotes. FUT-DB's 20,000/day also
cannot cover a claimed 22,143-card list daily if charged per player.

## Targeted repository and license review

The [revision-pinned source review](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/source-review.json)
records only the three requested repositories, selected source paths, numbered
anchors, source hashes and Git blob identities. Tree inventories locate those
files and check license presence; no unrelated repository audit, clone,
dependency installation or upstream execution occurred. Small source excerpts
are research references; no upstream implementation was incorporated into runtime.

| Repository and inspected revision | Relevant findings | License/reuse boundary |
| --- | --- | --- |
| [puredan824-hub/fc27-sniffer](https://github.com/puredan824-hub/fc27-sniffer/blob/e1488d6e51bdcafec6eaf61cdb06461358b7844d/r2_prices.py) `e1488d6e51bdcafec6eaf61cdb06461358b7844d` | `r2_prices.py:53–85`: manifest `_version`, per-key `_published_at`, filenames `key.v{version}.{hash}.json`; `player-prices-index` v2 uses `id0` plus cumulative positive deltas `d`; aligned `p`/`s`, streamlined-pool `o`/`r`. Hardcodes **PS5**, not PC. Docstring claims 20,811 cards and 2.5–5-minute publication; these are repository claims. It calls IDs FUT.GG `eaId`; no fresh EA crosswalk was measured. | MIT, copyright 2026 Puredan; later adaptation must retain notice. The upstream browser-like User-Agent and insufficient array/status checks were not adopted. MIT code permission does not license FUT.GG data. |
| [liusihang/fc27-copilot](https://github.com/liusihang/fc27-copilot/blob/fa0fdde132715b2c09a4cff1e51736a1794d635e/scripts/refresh_catalog.py) `fa0fdde132715b2c09a4cff1e51736a1794d635e` | Catalog refresh uses `https://www.fut.gg/api/fut/players/v2/27/`; R2 `play-styles`/`roles` mappings. Raw site `id`, `eaId`, `basePlayerEaId` become `futgg_id`, `card_ea_id`, `base_player_ea_id` through importer. Bundled manifest claims 19,676 versions/19,595 players from **September 18**; market prices are explicitly excluded. Catalog completeness is not price coverage. | MIT, FC27 Copilot contributors. Preserve notices if later adapting. Reference catalog identity only; do not run its multi-request refresh/retry loop or treat its bundled count as current feed proof. |
| [jgor80/11-lab](https://github.com/jgor80/11-lab/blob/fc5e4b04d4effbed3ea8d098db6f38d0a5665224/scripts/sync-futgg-prices.py) `fc5e4b04d4effbed3ea8d098db6f38d0a5665224` | Current source newly supplies explicit `pc -> player-prices-pc-dyn` and console mapping. `decode:40–70` validates v2, positive delta IDs, aligned arrays, integer prices/statuses and publication timestamp; retains only positive `s=0` market quotes. Source labels 1 as SBC costs, 2 objectives. SQLite snapshots are local history, not a historical feed. Native `pricecheck.ts` distinguishes exact `definitionId` from footballer `maskedDefId`. | No LICENSE/COPYING/NOTICE in current complete tree, no package license field. Reference-only; obtain a grant before adapting code. This revision is newer than Objective 001's `94b2e187…`; the old review alone would miss the PC collector. |

**No manifest-derived catalog/index/PC URL was fetched after the denial.** If
legitimate access is granted, follow only manifest-advertised keys/hashes; require
schema agreement, unique positive full-version IDs, all array lengths (including
statuses/rarities), integer coins, nonregressing per-PC publication timestamps
and validated status meanings. The sniffer's docstring mentions a first-price
placeholder while its loop aligns every slot; this discrepancy is unverified.
Never drop/shift a slot, guess a PC hash, infer semantics from PS prices or treat
SBC/objective costs as executable asks. Catalog API identity and R2 index identity
still require exact-version cross-checks. Provider history and retention remain
unknown even though repositories keep their own snapshots.

## Other documented public/partner possibilities

[EA's Community API announcement](https://www.ea.com/games/ea-sports-fc/news/pitch-notes-fc26-community-api-update)
dated July 27 names FUT.GG, FUTBIN and FUTWIZ as approved account-data partners
using optional official EA consent. It publishes no general developer bulk-price
contract, cost, limits, PC version mapping or price history. Partner status does
not transfer to this workspace. The FC26-titled article is not FC27 price proof.

[DSFUT's public API documentation](https://dsfut.net/api) looked plausible because
it has `/api/27/prices` and PC support. Its units are **USD per 100,000 coins**,
not a card's BIN in game coins. Its partner POP flow reserves a card and is
outside read-only research; it was never called. Described partner limits are
10 requests/10 seconds/console; no applicable per-card subscription, mapping,
publication, coverage count or history established. This is rejected on contract
meaning without invoking trading operations.

A [Parse FUTBIN marketplace listing](https://parse.bot/marketplace/1b6234f9-0dfb-4cca-99b4-2d6d37aec6a7/futbin-com-api)
was indexed as a two-credit single-card PlayStation price lookup, with a separate
history operation. Opening its detail page in the reader reported 404. Dollar
cost, quotas, batching, PC current-price support and rights are unknown; no
call was made. Marketplace scraping claims do not supply FUTBIN permission.
Generic football score/stat APIs have no demonstrated Ultimate Team version or
coin-price contract and were not expanded into an unrelated provider audit.

## EA-native fallback with explicit coverage limits

Use the existing official Web App native `search` through the retained local
read-only bridge, after attachment-only check and a fresh authenticated **FC27 PC
network GET**. Current attachment/authentication were **NOT_CHECKED in T2**.
Freeze [T1's protocol](001b/protocol.json) hash before new observations; this
document does not amend its preregistration or claim a new live benchmark.

Start with exact definitions **233731 and 278230** and only historically verified
club/league filters. Nation/rarity/position remain unverified. Preserve
`itemData.resourceId -> definition_id`; physical item and auction IDs remain
distinct, per-run pseudonyms. For each candidate gather independent exact-version
PC active-BIN comparables, exclude its auction and physical item, and feed the
existing pure pricing model. A conservative lower-tail ask estimate is not a
completed sale, full-market lowest price or sell-through guarantee. Unknown
mapping, insufficient independent comparables, stale quotes or other platforms
remain **UNKNOWN**, not zero or substituted prices.

Use pages 1/2, `count=21` including lookahead, identical filters within each pair,
one request in flight and at least 30 seconds between actual submissions. Nine
five-minute A/B/C windows permit at most 8 foreground GETs each, 72 total, with
two slots/window reserved for read-only revalidation. Cache-only/304 snapshots
do not establish fresh network observations. Retain request/native/receive UTC,
BIN, expiry, state and response provenance; apply T1's separate reference and
candidate freshness limits. Freeze the same explicit **unavailable** external
snapshot for all strategies in a block. Errors consume budget; follow T1 stop and
backoff rules without catch-up or rate probing. No buy, bid, move, list or relist.

Coverage is limited to these definitions, selected club/league/price bands and
moving expiry-ordered pages. Pages overlap and truncate; 20 visible listings are
not an exhaustive market. [Historical availability samples](market/availability.json)
contain **3 reads, 52 raw rows, 51 unique auctions, 2 versions**; these are replay
counts, not new T2 observations or live yield. History consists only of retained
local samples. Official caps, increments, tradability and tax assumptions must
be independently established; missing rules keep estimates diagnostic-only and
executable yield unknown. No broad card count or opportunities/hour can be
extrapolated from this watchlist. Authentication/challenge/access denial stops
the run; third-party 403 disables that source until legitimate access exists.

The operational choice is therefore the **EA-native bounded research fallback**.
DataFluxor is the best documented *candidate* for a later legitimately entitled
PC snapshot test, with batching, age and source fields; it is not a selected
working feed. Production retrieval, fresh exact-ID crosswalks, measured PC priced
coverage/freshness and applicable data rights remain prerequisites for promotion.

Offline reproduction: `python tests/test_001b_price_providers.py` checks every T2
criterion, replaying retained HTTP/schema/source/artifact evidence and adversarial
mutations. It requires no provider key, browser attachment, network or payment.
