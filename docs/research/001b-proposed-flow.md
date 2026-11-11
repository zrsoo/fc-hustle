# Objective 001B selected discovery flow — T5 prototype and T6 recommendation

**T6 recommendation: CONDITIONAL GO for offline architecture implementation.**
Start with A's exact-version native watchlist and propose bounded C exploration;
no measured A/B/C yield winner exists. The live benchmark remains blocked at
the retained T4 checkpoint. Current authentication is NOT_RECHECKED_T6.
The [discovery benchmarks](001b-discovery-benchmarks.md),
[latency findings](001b-latency.md), [delta addendum](001b-obj002-addendum.md)
and final [one-page decision](001b-discovery-decision.md) define the evidence
boundary. The following retained T5 prototype behavior remains valid.

The isolated prototype is complete. **Live opportunity yield is UNOBSERVED**:
T4 retained zero authenticated observation seconds and no auctions after EA
returned HTTP 401. T5 makes zero new EA requests and does not retry that failure.
Zero qualifying candidates were observed; opportunities/hour and current
authentication remain unknown. The successful flow below is **SIMULATED**.

The [machine-readable report](../../experiments/market_discovery/runs/t5-pricing/report.json)
contains source hashes, historical estimator comparisons, ranked candidates,
100/250/500/1000-coin scenarios, fresh-read outcomes, buy/list intents and latency
metrics. Its inputs are the [retained asks](market/availability.json),
[T2 provider evidence](001b-price-providers.md),
[accessible sandbox response](../../experiments/market_discovery/runs/t2-providers-20261111T212333Z/sandbox-prices.json),
[T4 preflights](001b-t4-live-experiments.md) and
[deterministic fixtures](../../experiments/market_discovery/fixtures/t5-opportunities.json).
Historical rows are evaluated at their recorded completion time, never at a
fabricated current observation time. No synthetic result contributes to live yield.

Run from the workspace with Python 3.10+; the standard library suffices:

```text
python -m experiments.market_discovery.t5_pricing --output private-captures/t5-replay.json
python tests/test_t5_pricing.py
python tests/test_t5_pricing_artifacts.py
python tests/test_market_pricing.py
```

Use a new output path. The CLI refuses existing files. Local latency changes on
replay; fixture data, rankings, math, state transitions and intents are deterministic.

Source hierarchy and pricing
----------------------------

[opportunity.py](../../experiments/market_discovery/opportunity.py) imports the
preserved [pricing.py](../../fc_access/pricing.py) exact `(game, platform,
definition_id)` model and uses `evaluate`, `profit` and `floor_price`. PC never
inherits console prices or a base player's price. Full version ID, auction ID
and physical-item ID remain distinct. The sanitized existing search boundary
rejects unsupported platforms and malformed identities.

The authoritative target is the baseline's MAD-filtered lower quartile with one
legal tick undercut. The report compares the un-undercut lower quartile,
MAD-filtered median and MAD-filtered arithmetic mean on the same independent
comparable cohort. Each alternative floors to a legal modeled price; none is
selected merely because it reaches X. The diagnostic cohort delegates row
eligibility back to `evaluate` and checks its sample count against the baseline.
The candidate's trade **and physical item** are excluded. Duplicates cannot
increase sample size; contradictory copies and reused physical identities fail
closed. At least five independent comparables must survive outlier filtering.

| Retained exact PC version | Conservative target / profit | Robust median / profit | Robust mean / profit |
| --- | --- | --- | --- |
| 233731, acquisition 6100 | 6200 / -210 | 6500 / 75 | 6500 / 75 |
| 278230, acquisition 200 | 150 / -57 | 200 / -10 | 200 / -10 |

These are diagnostic results under explicitly hypothetical 150–15000000 caps
and the baseline's unverified full increment schedule. They are not live quotes
or verified executable limits. T5 uses a 60-second remaining-lifetime margin;
39 and 5 comparables survive respectively, versus the earlier proof's 30-second
margin and 40 and 6 samples. Actual observed caps remain missing for both cards.
Without supplied rules, the report returns `MISSING_CAPS`. Empty increment data
returns `MISSING_INCREMENTS`; stale/mismatched rules, off-grid prices and caps
with no legal price cannot prepare an intent. Observed ask extrema are never
treated as price caps. Near the minimum, the baseline keeps the minimum when
there is no lower legal tick; it never rounds upward to create a profit.

T2 retrieved no usable production feed. Its publicly accessible DataFluxor
sandbox contains fixed console examples. T5 loads these actual retained
references and explicitly rejects them for sandbox lineage, platform/version
mismatch, unverified mapping and stale publication. No numeric PC comparison
can be justified from them. A future exact, mapped, fresh production ask snapshot
can supply a diagnostic delta, with a 600-second maximum publication age. It
cannot substitute for missing EA samples, caps or increments. Future/missing
timestamps and unsupported price meanings are exposed in per-quote reasons.

Every ranking exposes the age upper bound, remaining-expiry lower bound,
baseline rejections, sample count and assumptions. Bounded, expiry-ordered pages,
filters and BIN ceilings bias coverage; robust statistics cannot repair that
selection bias or detect coordinated ask manipulation. An expensive target from
a broad scan may represent illiquid noise. Completed sales, sale probability and
time to sale remain null. The model assumes sale at the target without further
relisting cost; sell-through and empirical tax rounding remain unverified.

Profit and flow contract
------------------------

```text
expected_profit = target_sale_price - floor(target_sale_price * 0.05) - acquisition_price
tax = target_sale_price // 20
qualifies = valid_price_data AND expected_profit >= X
```

X is the only mandatory profit threshold: a configurable nonnegative integer
coin amount, including equality and X=0. There is no ROI, portfolio or additional
profit floor. Identity, freshness and legal pricing are validity requirements.
The floor formula uses integer division, including odd tax boundaries; it does
not claim a measured settled-sale debit.

`run_flow(read, mode, rules, clock, X, external)` is one finite state machine for
a reader returning the existing `Runner` sanitized records. It calls the reader
at most twice and has no execution callback:

1. **SCAN:** one bounded, fresh, broad league page.
2. **PRICE:** score all unique candidates with EA comparables and external audits.
3. **EVALUATE:** rank qualifying candidates by descending modeled profit, then
   freshness and stable auction identity. Surface unqualified/uncertain rows too.
4. **REVALIDATE_READ_ONLY:** request a new exact-version page with `fresh=true`.
   It must start after the original observation and no earlier than scan completion,
   contain fresh successful network evidence, and be no older than 30 seconds.
   Match game/platform/version/trade/physical item, unchanged BIN, active status
   and more than 60 seconds of conservatively decayed lifetime. Any conflicting
   identity/BIN copy fails. A missing bounded-page row means unobserved, not sold.
5. **REPRICE_AND_EVALUATE:** recompute using the new candidate and fresh page's
   comparables, the same rules and X. A previously passing score grants no intent
   if the sample, target, rules or profitability no longer qualifies.
6. **DRY_RUN_BUY_INTENT:** emit inert JSON with exact identity, revalidated BIN,
   target, tax, profit, X, revalidation time, lineage and pricing assumptions.
7. **PROPOSED_LISTING_INTENT:** emit the same physical-item identity, target BIN,
   legal modeled starting bid and proposed 3600-second duration, conditional on
   a future confirmed purchase and same-item inventory readback.

The fixture ranks two modeled opportunities: 1300 coins and 700 coins. Their
qualifying counts at X=100/250/500/1000 are 2/2/2/1. All four scenario runs select
the 1300-coin fixture: acquisition 2500, target 4000, tax 200. Both intents retain
SIMULATED lineage and hypothetical rules. Tests also exercise the same reader
interface with live-mode records; those synthetic interface tests provide no
new live evidence. The report refuses to use the no-live-candidate branch if its
retained T4 inputs change to contain successful candidate evidence.

Failures and metrics
--------------------

No candidate means one read and no intents. Authentication/read errors, missing
network freshness, stale/future reads, reused initial snapshots, changed IDs or
BIN, inactive/expiring auctions and absence all terminate revalidation. Fresh
insufficient comparables or profit below X terminate repricing. No retry follows
these outcomes; buy and listing intents stay null and prepared-intent latency is
null. The independent tests inject each failure and check both intents.

Each flow exports discovery rows, unique auctions and candidate counts by X;
pricing counts; revalidation attempts/passes and explicit failure reasons;
monotonic stage start/end offsets and durations; full search-to-prepared-buy-intent
latency; and complete-flow latency through listing proposal. Every latency
aggregate has n and median; p95 is withheld for n<20. End offsets include Python
computation and the time between stages. Fixture stage timings measure actual
local in-process replay time, not network or EA speed. The record's deterministic
50-ms service delay and component durations are separately modeled fixture data.
No live successful-result or prepared-intent latency was observed in T4.

Objective 002 can consume these pure scoring/revalidation interfaces and inert
intent fields after normal authenticated FC27 PC access and real current card
rules are available. The proposed narrow watchlist plus broad exploration still
needs live yield and coverage evidence; no opportunities/hour claim follows.
Production scheduling, durable execution, unattended write loops, real purchases,
inventory moves and listings remain outside this implementation. No original
bridge, pricing calculator, objective or verified transaction evidence was changed.

Selected architecture and adaptive scanning — T6
-----------------------------------------------

The source hierarchy is: (1) fresh native EA exact-FC27-PC auctions for candidate
BIN, comparables and independent revalidation; (2) an optional legitimately
accessible, mapped exact-PC third-party indicative snapshot for ranking and
diagnostics; (3) historical asks for offline replay only; (4) synthetic fixtures
for tests only. `last_sale_price` with unknown age and `market_average=null`
cannot fill current samples. Zero reference prices mean unavailable, not free.
No third-party production source is enabled. DataFluxor is the first conditional
commercial candidate based on documented PC contracts; its successful sandbox
retrieval proves neither production access nor exact PC mapping. FUT-DB's
entitlement/batch uncertainty and FUT.GG's 403/permission gap stay explicit.
The [T2 provider report](001b-price-providers.md) is retained evidence, not a
new price/terms lookup. External access is optional for the initial watchlist.

Begin with the independently observed exact versions 233731 and 278230. A
future scheduler should share one queue and minimum 30-second EA submission
gap. Keep the existing 90-second first-page cadence per watched version and
300-second paired-page refresh as starting targets (about 1.73 calls/minute
before revalidation). These are proposed schedules, not safe rate-limit claims.
Revalidation and inventory recovery/listing take priority; skip missed scans.

Proposed C exploration replaces a scheduled scan rather than adding traffic:
one league/club pair in each completed three-arm benchmark block, with targeted
rank 1/2 pairs in the remaining slots. Use the frozen protocol for comparisons.
Future production allocation is a separate Objective 002 policy: retain a
bounded exploration share, measure unique versions/auctions and qualifying
revalidation yield per actual request, reduce redundant/thin/stale cohorts,
and rotate exact versions only after independent identity/rule validation.
Do not promote a cohort because of high asks or fixture profit. Rank from the
preceding completed block only, using verified fresh external indicative asks
if available, else fresh native distinct-auction counts; fall back to the two
known versions. No cost estimate or automatic watchlist expansion is empirically
validated here. Nation, rarity and position filters remain unverified.

For executable targeted search, after a valid target is estimated, derive the
maximum acquisition BIN as `target_sale_price - target_sale_price // 20 - X`.
Use an actually legal search ceiling at or below that value; no positive legal
ceiling means no search candidate. The benchmark's fixed 7000/4000/6500
ceilings remain controlled exploration parameters, not evidence of profit.
Broad rows lacking five independent exact-version comparables trigger a
budgeted targeted comparable refresh or remain unevaluable. Never infer a
resale target from a lone broad listing or an external quote alone.

Freshness and legal pricing boundaries
-------------------------------------

The normative ages are comparables <=120 seconds, candidate/revalidation read
<=30 seconds, rules <=300 seconds and external publication <=600 seconds;
remaining lifetime must be strictly >60 seconds after conservative age decay.
Use UTC for persisted provenance and monotonic clocks for deadlines. Cache by
game/platform/definition/filter/page/network-read time; retain each identity,
price, expiry and publication time. HTTP receipt does not renew source age.
Do not reset native pagination between matching pages. Invalidate on criteria
change, conflicting identity, auth loss, stale data or rule change; native cache
callbacks alone do not prove a fresh network read.

Exact-card minimum/maximum and relevant native increment boundaries require
new attributable read-only evidence. The 150–15000000 caps and `DEFAULT_BANDS`
in fixtures are hypothetical. Accepted isolated 200/250 prices do not validate
a global ladder. The current `Rules` model carries supplied caps/time/bands,
not a proof that those rules came from EA; **Objective 002 must enforce rule
provenance outside the pure calculator before accepting an intent**. No rounding
up to meet X, no ask-extrema-as-caps, no console substitution. Target and listing
bid/BIN must all be legal for that exact card. Duration 3600 seconds is a
proposed value supported by historical listing evidence, not a new listing.

Concrete buy/list intent schemas
-------------------------------

These are the exact current `run_flow` emitted fields (examples use one
**SIMULATED** fixture). They are inert research JSON. Source/rule provenance,
epoch, durable scope, payload hash and semantic command IDs must be added by
the planned Objective 002 models/store/transport; current per-run pseudonyms
must never be treated as restart-safe execution IDs.

```json
{
  "buy_intent": {
    "mode": "DRY_RUN_ONLY",
    "lineage": "SIMULATED",
    "operation": "buy_now",
    "key": {"definition_id": 278230, "platform": "pc", "game": "fc27"},
    "trade_id": "trade:42781d8b23b0c88705b69dfd",
    "item_id": "item:06abeaf2c556215e299660d4",
    "buy_now_price": 2500,
    "target_sale_price": 4000,
    "tax": 200,
    "expected_profit": 1300,
    "X": 100,
    "revalidated_utc": "2026-11-12T12:00:00.100000+00:00",
    "assumptions": [
      "BOUNDED_EXPIRY_ORDERED_SAMPLE",
      "FILTER_AND_PRICE_CEILING_BIAS_POSSIBLE",
      "ASKS_NOT_COMPLETED_SALES",
      "LIQUIDITY_UNKNOWN",
      "SELL_THROUGH_UNMEASURED",
      "ASSUMES_SALE_AT_TARGET_NO_RELIST_COST",
      "CALLER_SUPPLIED_CAPS",
      "FULL_INCREMENT_SCHEDULE_UNVERIFIED",
      "TAX_ROUNDING_EMPIRICALLY_UNVERIFIED"
    ]
  },
  "listing_intent": {
    "mode": "PROPOSED_ONLY",
    "lineage": "SIMULATED",
    "key": {"definition_id": 278230, "platform": "pc", "game": "fc27"},
    "item_id": "item:06abeaf2c556215e299660d4",
    "starting_bid": 4000,
    "buy_now_price": 4000,
    "duration_seconds": 3600,
    "precondition": "CONFIRMED_PURCHASE_AND_SAME_PHYSICAL_ITEM_INVENTORY_READBACK"
  }
}
```

Before any future mutation, native dispatch must recheck identity, current BIN,
expiry, same-scope session, fresh target and rules, and `expected_profit >= X`.
These are data-validity conditions, not an additional profit/spend policy. X is
the only mandatory profit threshold; no per-trade approval, ROI or portfolio
restriction is added. Projected profit is not completed-sale evidence.

Failure behavior and Objective 002 consumption
--------------------------------------------

| Condition | Required behavior |
| --- | --- |
| No candidate / insufficient independent comparables | Return no intents; record unevaluable/empty separately from a measured zero arrival rate |
| Changed BIN/identity, stale/expired candidate, failed repricing | Discard both intents; a missing bounded-page auction is unobserved, not sold; no retry of the stale decision |
| Missing/unverified caps/ticks or provenance | `NOT_READY` at execution boundary, even if supplied fixture rules yield `OK` in the calculator |
| 401, challenge, restriction, detached bridge or schema/platform mismatch | Stop dispatch, invalidate decisions, require normal session recovery and same-scope reattachment; never override persona guards |
| 429/5xx/timeout | Suspend new research work; future scheduler honors Retry-After even above 300 seconds, otherwise backoff 30/60/120/240/300; no catch-up burst |
| Third-party 403/missing entitlement/stale quote | Disable that source without denial retries; continue only if native pricing validity is independently satisfied |
| Future unknown buy/list outcome | Persist intent and reconcile read-only before any new write; do not redispatch an ambiguous mutation |
| Future acquired card cannot be legally listed | Keep HELD, reconcile exact ownership and refresh rules/target; never substitute a different physical card |

Use [normalized / price_candidate / rank_candidates / revalidate / run_flow](../../experiments/market_discovery/opportunity.py)
as research interface references and [pricing.py](../../fc_access/pricing.py)
as the reusable pure implementation. `run_flow` is a finite two-read broad-first
demo, not the selected targeted scheduler. `Runner`'s live revalidation slots
remain diagnostic because no verified card-rule capture exists. Neither becomes
a production scheduler/executor by import. Research long polling is proposed
delivery only; preserve strict native validation and add the existing handoff's
pairing/epoch/durable-state contracts in a separate execution bridge.

Objective 002 should adapt these into its already planned providers, rules,
strategy, scheduler and transport modules after models/store/identity. See the
[exact module/interface delta](001b-obj002-addendum.md). S1–S4 can proceed
offline; S5/S6 and L1–L8 in the [existing handoff](obj002-handoff.md) still govern
live release and realized-sale claims. T6 implements no `fc_execution` module,
continuous runner or real account operation. The recommendation's live-yield
and transport-success conditions remain open; documentation completion does
not satisfy them.
