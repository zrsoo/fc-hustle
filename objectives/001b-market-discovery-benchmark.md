# Objective 001B — FC27 Market Discovery & Execution-Flow Benchmark

## Goal

Find and **empirically benchmark** the most efficient way to identify profitable FC27 Ultimate Team player-market acquisitions, and demonstrate a **research prototype** of the proposed `scan → price → evaluate → revalidate → buy-intent → relist-intent` flow.

This is the research/design bridge between completed Objective 001 and future Objective 002. **Do not implement or run the production autonomous trading bot.** Reuse Objective 001's verified Edge integration, data models, pricing code and recorded purchase-to-list evidence. No new live purchase or listing is needed or authorized.

Repository: `zrsoo/fc-hustle`. Read `docs/research/final-report.md`, `market-strategy.md`, `confirmed-capabilities.md`, `execution-architecture.md`, and `obj002-handoff.md` before starting. Treat recorded verification as historical evidence, not proof of a currently attached browser.

## Locked future P0 behavior

1. Scan the live FC27 player transfer market.
2. Determine a realistic target resale price from comparable listings, aided by external reference prices.
3. Compute `expected_profit = target_sale_price - floor(target_sale_price * 0.05) - acquisition_price`.
4. If `expected_profit >= X` (configurable integer coin threshold), buy the exact listed card at the currently revalidated Buy Now price.
5. List that acquired physical card at the target resale price; repeat autonomously.

X is the only mandatory profit threshold. Do not add portfolio or per-trade approval policies. Target price is an estimate, not a guaranteed sale; record assumptions about sell-through and tax rounding.

## Research questions and required experiments

### 1. Which third-party price feeds are actually usable for FC27 PC?

Investigate and, wherever possible, make **real read-only requests** to:

- FUT.GG's advertised FC27 bulk manifest, price index and PC dynamic prices (`https://r2.fut.gg/27/manifest.json`) and relevant source implementations in `puredan824-hub/fc27-sniffer`, `liusihang/fc27-copilot`, and `jgor80/11-lab`.
- Documented commercial/bulk options, including DataFluxor FUT Data and FUT-DB, validating actual endpoint contracts, platform coverage, batching, terms and current pricing rather than accepting advertising claims.
- FUTBIN/FUTWIZ/FUT.GG and any other plausible documented public/partner feeds, with reproducible accessible evidence.

For each candidate quantify where verifiable: FC27/PC compatibility, **exact version/card ID mapping**, count of priced cards, price meaning (lowest ask/median/estimated/last sold), publication timestamp, refresh interval, historical data, request cost/limits, access requirements, subscription price, terms, and observed HTTP results. Distinguish measured values from provider descriptions and repository claims.

Previous FUT.GG manifest/catalog calls returned HTTP 403; retest once through ordinary documented access and report whether still blocked. Do not circumvent paywalls, anti-bot controls or access restrictions. Do not purchase plans, register paid accounts, leak credentials or claim a feed is accessible without a successful authorized retrieval. If no usable broad feed exists, design and benchmark a viable EA-native fallback with explicit coverage limits.

### 2. How do we discover actual underpriced *live auctions* with minimal search work?

Compare at least:

**A — Targeted per-card searches.** Use external price references (when available) to calculate profitable max-BIN thresholds, then search exact FC27 card/version IDs.

**B — Broad filtered EA searches.** Search price bands and validated EA filters (e.g., club/league); use exact-card price lookup to score each returned listing. Investigate pagination, expiry ordering, lookahead overlaps and truncation. A broad page of 20 results is not an exhaustive market sample.

**C — Adaptive hybrid.** Combine bulk-price discovery/ranking, targeted searches for promising versions, and broader exploration; explicitly trade off freshness, unique-card coverage, total requests and candidate yield.

Use the authenticated Edge native services, if attached, **read-only**. Reuse the existing research bridge or create a separate narrowly scoped benchmark adapter. Do not clone/reference competitors without reviewing source/license; no need to repeat Objective 001's broad repository audit.

Design a fair, bounded, reproducible comparison with alternating strategy windows and a comparable EA request budget. Aim for at least **30 minutes of live read-only observation**, including multiple search/filter/page combinations; record start/end UTC, requests, response sizes, end-to-end latency, unique auction/version counts, duplicates, age, errors and search coverage. If authenticated access is unavailable, report a live benchmark blocker instead of substituting mocks. Do not stress-test or intentionally trip rate limits. Preserve sanitized raw-enough observations to replay results offline.

Outcome metrics: unique exact card versions and auctions observed per request/minute, **candidate opportunities** whose conservative projected after-tax profit reaches X, estimated opportunity arrival rate, false positives on fresh revalidation, coverage bias, and extrapolation limits. Report multiple X scenarios (e.g., 100/250/500/1000 coins) without changing the locked P0 semantics.

### 3. Can command-delivery/search-to-action latency be reduced materially?

The existing research extension uses a **30-second `chrome.alarms` polling interval** in `browser/transaction-bridge/worker.js`. Separate local bridge delay, Web App/native API response time, and Python decision time; do not mislabel end-to-end waiting as EA latency.

Benchmark at least the existing baseline and one **reviewed low-latency alternative** (e.g., request-driven local transport, long polling, or an authenticated localhost signaling design), using read-only traffic and controlled local command timing. An alternative design that cannot be exercised should be clearly labeled proposed, not benchmarked.

Measure median, p95 (where sample size supports it), time-to-first-result, full search→evaluate→fresh-revalidation→prepared buy-intent latency, and observed errors. Keep the bridge local, avoid credential export, and do not weaken native command validation. Do not perform actual Buy Now, bid, move, list or relist requests in this objective.

### 4. What discovery and pricing strategy has the best expected yield?

Use the current exact-version/platform price model and `fc_access/pricing.py` as the starting baseline. Compare lower-tail estimators (e.g., low quartile/undercut) with robust mean/median and, if live sources permit, external price references. Explicitly exclude the candidate's own auction from comparables.

Evaluate:
- Small/biased samples and expiry-ordered results;
- Stale and cross-platform third-party quotes;
- Missing market price caps or increment boundaries;
- Liquidity and plausible resale price vs actual completed-sale evidence;
- Price-confidence / watchlist selection and revalidation speed;
- Whether scanning broader filters yields useful unique candidates or just cheap, illiquid noise.

Use the historical Objective 001 native samples and any new read-only observations. **Do not fabricate profitable opportunities.** If no live candidate qualifies, demonstrate the scoring/execution flow on clearly labeled deterministic synthetic/recorded replay fixtures while reporting live yield as zero or unobserved.

## Prototype boundary: demonstrate the proposed flow, not the full bot

Implement only a **reproducible research prototype** under `experiments/market_discovery/` (or comparably isolated path) that:

1. Loads accessible external price snapshots (or explicit unavailable status) and live/sanitized EA listing samples.
2. Normalizes exact `(game, platform, definition_id)` and auction/physical-item identities.
3. Evaluates opportunities and X using real EA comparables; produces a ranked candidate list with data freshness and uncertainty.
4. Selects an actual live candidate *if observed*, performs fresh **read-only** identity/BIN/expiry revalidation, and emits a structured **DRY-RUN buy intent** and the proposed subsequent listing intent. If none qualifies, replay this exact state machine with fixtures, clearly marked SIMULATED.
5. Benchmarks the discovery strategies and bridge latencies and exports machine-readable metrics.

No production scheduler, persistent trading executor, unattended write loop, new real-coin transactions, or expensive third-party purchase. The *execution* portion is an executable decision/intent demonstration plus Objective 001's independently verified buy/list API contracts—not a new authenticated write. Never describe this as a confirmed profitable purchase or sale.

## Deliverables (commit to the repository)

1. `docs/research/001b-price-providers.md` — source/provider feasibility table, tested endpoints/results, exact card/platform compatibility, limits, costs and availability gaps.
2. `docs/research/001b-discovery-benchmarks.md` — reproducible A/B/C results, standardized request budgets, actual observation period, unique-auction/unique-version coverage, after-tax opportunity yield per hour and limitations.
3. `docs/research/001b-latency.md` — baseline vs alternative, separated latency components, sample counts, median/p95 and defensible root-cause analysis.
4. `docs/research/001b-proposed-flow.md` — recommended acquisition-discovery strategy, source hierarchy, target pricing and X policy, adaptive scan selection, fresh revalidation, buy/list intent schema and explicit failure/unknown behavior. Explain how Objective 002 should consume it.
5. `docs/research/001b-obj002-addendum.md` — only the changes to Objective 002's existing handoff: selected provider(s), search strategy, latency solution, exact new modules/interfaces, dependencies and open blockers.
6. Isolated research prototype, runnable commands, sanitized timestamped inputs/benchmark results, synthetic or replay fixtures, and deterministic tests. Keep existing Objective 001 evidence and bridge contracts intact.

## Acceptance / validation

- At least one actual third-party feed retrieval or an evidence-backed explanation of why available candidates were inaccessible; no speculative feed labeled working.
- A/B/C discovery strategies compared on observed FC27 listings using comparable request budgets; if live benchmark blocked, explicitly report **BLOCKED/PARTIAL** and identify the exact prerequisite.
- Measured baseline bridge latency and a measured or explicitly unvalidated alternative; show EA latency separate from extension queue/poll delay.
- Actual live opportunity yield and freshness/candidate false-positive measurements where data exists; synthetic opportunity success never counts as live yield.
- Reproducible dry-run execution intents following the locked P0 math, validated identity, legal pricing assumptions, and no real account mutations.
- Deterministic tests and commands, honest data lineage and test outcomes.
- Objective 002 handoff updated **without implementing Objective 002**.

Finish with a one-page **GO / CONDITIONAL GO / NO-GO** decision for the *discovery architecture*: best third-party source, best search approach, realistic opportunities/hour, latency bottleneck, exact unverified prerequisites. A bounded/partial live run is not a successful throughput benchmark.

## Execution constraints

- Work locally; signed-in Edge session may need normal extension reattachment.
- Research-only EA access; **no purchases, bidding, listing, relisting, or other account mutations**.
- No credential/cookie/token exports or public log leakage. No bypass of CAPTCHA, access restrictions, rate limiting, or third-party provider controls.
- No unjustified repository cloning, unrelated UI or trading-engine features, or external paid subscription.
- Preserve Objective 001's immutable verified evidence and original objective text.
