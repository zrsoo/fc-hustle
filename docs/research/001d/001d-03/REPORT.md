# 001d-03 native card caps and legal prices

IMPLEMENTED / OFFLINE_VALIDATED. 001D-S2 completed as bounded read-only client
and caps observation. Transaction acceptance outside the historical 800 bid is
LIVE-UNVERIFIED; this task executed no live bid or listing and started no actors.

The authoritative service is `fc_access/production_v1/prices.py` (`PriceService`,
`NativePrices`, `CardKey`, `ListingValidation`, service version 1), delivered by
`fc_access/production_v1/adapter.py`, `fc_access/production_v1/contracts.py` and
`browser/production-v1/page.js` over production schema 2 selected in 001d-02.
`fc_access/production_v1/executor.py`, `fc_access/production_v1/server.py`,
`fc_access/production_v1/store.py` and `browser/production-v1/worker.js` retain
the single-owner loopback transport on port 8784. This is an additive local
operation, not a second browser bridge or a rewritten legacy response route.

The exact native calls are:

| Operation | Native service | Evidence |
| --- | --- | --- |
| Exact-card caps | `services.Item.transfersDao.getItemMarketDataByDefId([definition_id])` | GET `/ut/game/fc27/marketdata/pricelimits?defId=...`; observable `response.marketData[].priceLimits.minimum/maximum` |
| Absolute next price | `UTCurrencyInputControl.getIncrementAboveVal(value)` | Loaded local client helper; no network request |
| Absolute lower price | `UTCurrencyInputControl.getIncrementBelowVal(value)` | Loaded local client helper; no network request |

`price_helpers` takes `{version:1, probes:[{direction:"above"|"below",value:int}]}`
with at most 32 probes, including an empty availability-only request. Its strict
operation-specific result is `{success,error,version,above_available,
below_available,probes,network:[]}`; each probe adds the absolute `price`.
Context, identity namespace, owner/worker/host/document fences and command/read ID
remain correlated exactly as in schema 2. Local results have `network_at=null`
and request_count=0; they do not claim authenticated network or market coverage.
Missing helpers/caps, changed shapes, wrong definitions and helper disagreement
fail explicitly. Error results never export native exceptions or partial probes.

Use `PriceService(adapter, unique_command_id_factory).load(key=CardKey(def_id))`.
This checks helper availability independently, then authenticates an exact-card
caps GET through the reviewed adapter. `minimum_bid`, `floor`, `profitable_cap`
and `validate_listing` consume that session's native services. A rules object is
bound to the complete context/fences and registered service instance; a new
attachment invalidates its use. Reloading caps for a card also supersedes the
previous snapshot and requires reconciliation of plans using it. Caps are listing
limits, never an observed BIN,
an economic quote, or an auction's minimum bid. A legal opening below the listing
minimum or a next bid above the listing maximum remains native bid arithmetic;
profitability and the auction BIN guard determine whether it is eligible.

`fc_access/bidding_v1/rules.py` now forwards to this service. The bidding adapter
and retained durability listing harness consume native evidence, replacing the
approved artifact hashes, LIVE_VERIFIED classification, 300-second artifact
freshness and whole-market certification gates. The SHA-256 recorded in a
durable legacy intent now describes the runtime inputs for audit only; it is
never an authorization allowlist. Historical modeled pricing fixtures remain
available to offline research. Native instances bypass their old artifact-age
and band logic; no production price service imports a static tick schedule.
Fresh auction/balance and local response checks still use schema 2's 30 seconds.

Opening participation uses the exact legal `startingBid` when currentBid=0.
Existing bids use the absolute above(currentBid), including 750 -> 800, with
reciprocal below/above agreement checks. The integer economic ceiling is
`resale_price - resale_price//20 - profit_threshold`; native successors bracket
the largest legal price no higher than that ceiling. Native below(off-grid)
can land two smaller ticks below the floor near a tier crossing. A bounded walk
of at most eight successors handles that case without guessing a delta; missing,
nonmonotonic, nonreciprocal or unbracketed results fail with helper_disagreement.
No rounding operation can increase the economic ceiling.

Standalone `validate_listing(resale_price, key=...)` fixes BIN=resale_price and
startingBid=below(resale_price). It returns LISTABLE only when both prices are
legal, reciprocal and within the exact card limits. Outside limits or a lower
start below the minimum/zero returns UNLISTABLE. Off-grid BIN, identity changes,
disagreement or unavailable evidence returns NEEDS_RECONCILIATION. It never
adjusts the resale price, substitutes another start, or submits a listing.
`validate_future_listing` also produces NEEDS_RECONCILIATION if loading caps or
helpers fails. For example 1500 -> 1400 is LISTABLE only when the limits permit
both; BIN at the minimum with no permitted lower tick is UNLISTABLE.

Production `dispatch_intent` additionally requires registered native prices,
an exact unchanged identity/context, independently issued fresh auction and
actual spendable balance, a legal minimum bid, and a cap supported by the fixed
resale price and integer profit threshold. It calls the injected durable
`journal.dispatch_once` only after these checks. The legacy adapter preserves
the existing independent comparable checks and intent-before-send journal.
The retained listing harness preserves conclusive owned physical identity,
actual paid amount, native pair/profit validation, reservation-before-send and
independent readback. Production has no listing operation. The installed HTTP
Store still has no write authorizer and rejects bids with
`mutation_requires_durable_intent`. Quote acquisition/cache and the full D5
production journal integration remain their own subsequent tasks; passing a
resale price is a caller economics input, not proof of a sale or settled profit.

S2 used `python -m fc_access.production_v1.investigate_s2 prepare`, the reviewed
production extension selected through verified Windows UI controls, then
`python -m fc_access.production_v1.investigate_s2 run`. AGENTS.md was reread before
recovery; this worker verified Edge foreground and the official EA tab, refreshed
normally, loaded `browser/production-v1`, and attached it to the new labeled
session. No credential values or authentication identifiers were read/exported.
The saved public labels are random correlation labels, unrelated to EA auth.

`s2-checkpoint.json` retains commands and sanitized responses. This window made
one authenticated GET for definition 261855 (minimum 700, maximum 10500) and eight local evaluations:
above(750,950,1000,9900), below(1500,1000,10000,card_minimum). It observed the
1400/1500 pair within that card's limits, in 0.202 seconds of the 90-second window.
Availability, exact caps authentication
and local helper results are separate from transaction verification, recorded
as UNVERIFIED_NO_BID_OR_LISTING_EXECUTED. No whole schedule or server listing
acceptance is inferred. The checkpoint reserves budget before delivery, persists
the original 90-second deadline, rejects rerunning a consumed window, and never
retries an ambiguous command. There were no other EA commands in this task.

`python tests/test_001d03_native_prices.py` independently executes real production
Python and JavaScript with faithful native-service doubles, negative contract
cases, economic rounding, cap edges, identity mismatch, unavailable services,
write guard failures, and offline checks of S2 observations. The deterministic
fixtures are not substituted for live evidence. The retained bidding/durability
suites use `tests/native_price_fixture.py` solely for native service doubles.

Pre-change reports, baselines, publication manifests and 001C observations are
unchanged. `migration.json` describes exactly five authorized tracked source/test
edits. Historical audit checks verify their original Git blobs against immutable
entry digests and current migrated bytes against the new audit manifest; all
other preservation checks remain byte-for-byte. The obsolete artifact-gate tests
were migrated to context/identity and native-limit tests. No runtime imports the
migration manifest or requires a file hash to authorize pricing.

`validation.json` and `validation-00.txt` through `validation-08.txt` record the
acceptance, prior contract/inventory, bidding, durability, modeled pricing,
search-validation, watched-bulk and E2E regression suites. All nine invocations
passed; these validation commands make no EA requests or live mutations.
