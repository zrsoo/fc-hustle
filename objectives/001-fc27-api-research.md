# Objective 001 — FC27 Integration Research & Live Capability Validation

## Outcome

Establish and **independently verify** the EA Sports FC 27 Ultimate Team capabilities needed to implement Objective 002, a fully autonomous player-market trading bot. Inspect existing implementations, build the minimum local integration harness, run live authenticated capability tests, and deliver an implementation-ready engineering handoff.

**Research alone is insufficient.** A repository's README, mocks, offline tests, or an HTTP 200 without state readback do not prove live trading capability. Do not call the objective complete if essential live functions remain unverified.

### Locked Objective 002 P0 flow (scope reference; do not build the full bot here)

1. Continuously scan FC27 player transfer-market listings.
2. Estimate a realistic target resale price from comparable listings (e.g., robust mean / median / lower-end distribution); compute expected net profit after FC's 5% sales tax.
3. If expected net profit meets configurable threshold **X** (coins), automatically Buy Now.
4. Move the acquired card as needed and list it at the calculated target price.
5. Repeat autonomously without per-transaction approval.

Formula: `expected_profit = target_sale_price - floor(target_sale_price * 0.05) - acquisition_price`. Validate rounding/price bands empirically. A market average or third-party indicative price is **not** a guaranteed sale price. Avoid comparing distinct card versions/platforms.

P0 has no additional portfolio, daily-spend, or per-trade-approval policies. Correctness, operational errors, and duplicate-write prevention remain engineering requirements. Objective 001 authorizes **only the minimum low-cost real transaction needed to validate the integration**, not running a live automated trading loop.

## Environment and access

- Workspace: `zrsoo/fc-hustle`; this objective runs locally through the existing Codex/orchestrator setup with unrestricted command execution (YOLO).
- **Microsoft Edge** is already signed into the official FC27 Ultimate Team Web App on the operator's Windows machine. Do not assume that an existing Edge tab is automatically accessible through CDP.
- Establish local browser access using an Edge-compatible extension/page bridge, CDP if correctly configured, or another practical mechanism. Reuse the signed-in profile/session where possible. If remote debugging requires restarting Edge, do not silently destroy user sessions; prefer a bridge that works in the existing profile, or document precisely what manual re-login/action is required.
- Keep debugger/bridge endpoints bound to localhost; do not exfiltrate, print, commit, or include authentication secrets, cookies, session IDs, phishing tokens, or personal account data in reports.
- Never collect account passwords in objective files, prompts, or logs. The user may intervene only for a necessary browser/login action.
- GitHub/source inspection should be **remote-first** (GitHub API/MCP/raw files). Clone only when deeper integration/testing genuinely requires it. No untrusted third-party executables or extensions should be blindly installed/executed; review source first.

## Workstream 1 — Source-level repository investigation

Inspect actual code, tests, release/status evidence, and licenses; capture exact GitHub paths and preferably commit SHAs.

**FC27 API / transaction implementations:**
- https://github.com/liusihang/fc27-copilot — browser bridge, `extension/content/page-inject.js`, Python action dispatcher/reconciliation
- https://github.com/jgor80/11-lab — captured FC27 network operations and normalized market captures
- https://github.com/Vladisllavy/FC27-Autobuyer — browser-side scan/buy/list loop
- https://github.com/RanuK12/fc27-gallery-bot — browser bridge / acquisition-listing flow

**FC27 prices / search helpers:**
- https://github.com/puredan824-hub/fc27-sniffer — FC27 bulk prices, scanning signals and price series
- https://github.com/marchiartur/sp-tool — Web App search criteria, cache management and local extension integration
- https://github.com/FrancescoPalasciano/Bot-Fc27 — market observation, pricing calculations

**Historical/secondary references:**
- https://github.com/sauravhiremath/fut-25-market — Python HTTP transport and operation examples (FC25, do not assume current compatibility)
- https://github.com/AbdoD97/fut-web-app-api — FC26 unofficial endpoint documentation

Discover other truly relevant open-source implementations as warranted. For each candidate decide: **reuse, adapt, reference only, or discard**, with technical reasons (completeness, compatibility, quality, dependencies, license, security). Explicitly distinguish claims from working implementation and live evidence.

## Workstream 2 — Establish live FC27 integration

Compare and, where feasible, test:

**A. Direct Python HTTP client** calling EA's internal endpoints using a valid authenticated session.

**B. Authenticated Edge Web App bridge** invoking its internal JS services from the signed-in page, with a local Python caller. In prior source, promising calls include `services.Item.searchTransferMarket`, `services.Item.bid`, `services.Item.move`, `services.Item.list`, `services.Item.requestTransferItems`, and `services.Item.relistExpiredAuctions`.

Do not hardcode the historical host. Earlier FC27 browser captures reported `utas.mob.v1.prd.futc-ext.gcp.ea.com:443/ut/game/fc27/` and client `FC27_JS_WEB_APP` / SKU `FUT27WEB`; independently read the active configuration/request path. FC25/26 request bodies and login flows are references, **not** FC27 proof.

Select the simplest working architecture. Prefer direct HTTP if all necessary operations work; otherwise use the Edge browser bridge. Keep the transport behind a well-defined adapter so it can later be replaced. Do not reverse-engineer CAPTCHA solutions, bypass security challenges, or misrepresent unsupported operations as functional.

## Workstream 3 — Live operation capability matrix

Using the authenticated FC27 account, attempt the following with the minimal local harness. For each operation retain sanitized, reproducible evidence: timestamp, active endpoint or JS method, request shape, response fields/status, observed state before/after, and exact result/error. Store no secrets.

| Capability | Verification requirement |
| --- | --- |
| Session | Authenticated connection; current version/host and session lifecycle observed |
| Transfer-market search | Actual live results, card identifiers, auction identifiers, prices, expiry |
| Search filters | Player/card-version matching, Buy Now ceiling, supported filters |
| Pagination / caching | At least two relevant pages where available; document lookahead semantics and cache invalidation |
| Market sample | Comparable listings and underlying price fields (`marketAverage`, `lastSalePrice` where present) |
| Account | Current coin balance, club/unassigned/purchased items, transfer list |
| Buy Now | **One inexpensive, tradeable player purchased live** with exact trade/card match |
| Purchase verification | Re-read inventory/coin state; prove a newly acquired item and appropriate coin delta |
| Item movement | Move acquired item to transfer list where required; verify destination |
| Create listing | List acquired item at a valid bid/Buy Now price and duration |
| Listing verification | Re-read transfer list; verify item identity, live trade ID, price and active state |
| Status/relist | Verify status-read capability; test relist behavior only if an eligible expired listing exists (otherwise mark unverified) |

**A live Buy Now followed by a verified listing is the critical proof.** Do not fabricate success or silently skip it. Use a single low-cost card and minimum necessary calls. Do not continue trading beyond what demonstrates the capabilities. If a required action cannot be completed without operator interaction or suitable market access, document the exact blocker and recovery instructions; the objective must report PARTIAL/BLOCKED.

Note: `tradeId` (auction), `itemData.id` (physical item), and card-definition / `resourceId` (card/version) are different identities. Verify model mappings, especially for special versions and platform market separation.

## Workstream 4 — Prove data availability and define profitability model

Investigate broad FC27 scanning, latency, filters, query pagination/order, Web App caching and natural request behavior. Evaluate targeted EA searches against FUT.GG FC27 bulk price data (reported manifest: `https://r2.fut.gg/27/manifest.json`), EA `marketAverage`, real comparable BIN listings, and available historical prices. Check whether sources are still reachable and actually useful **now**; do not assume third-party indicative quotes are executable prices.

Recommend a deterministic comparable-listings estimator including the handling of outliers, thin markets, stale prices, wrong card variants, price increments, market price caps, and insufficient observations. Define `target_sale_price`, `acquisition_price`, after-tax profit, and the configurable X decision. Explain the scan universe, how often to update reference prices versus inspect live listings, and how an opportunity is revalidated before buying.

Implement a small offline pricing/calculation proof with fixtures and tests; **do not implement the production continuous bot**.

## Workstream 5 — Autonomous-loop feasibility and operational behavior

Design for Objective 002's `scan → evaluate → buy → list → repeat` loop without transaction-by-transaction confirmation. Specify clean interfaces for:
- Market/catalog and price providers;
- Profitability evaluation and target-price choice;
- Buy Now / inventory / listing operations;
- Session renewal, reconnection and restart behavior;
- Purchase/listing readback, state reconciliation and idempotency;
- Persisted acquisition cost, listing status and realized profit.

Examine observed Web App request frequency, existing polling, caching, rate limiting, error modes and market access failures. Recommend ordinary, non-disruptive request pacing and respect backoff/errors; do not claim any pattern avoids detection or that automation is permitted by EA. No proxy rotation, fingerprint spoofing, CAPTCHA bypass or account-restriction circumvention. Record enforcement risks as facts, without inserting unrelated capital constraints or manual approvals into the intended P0 design.

## Deliverables (commit to this repository)

1. `docs/research/repository-analysis.md` — repo-by-repo source-level findings, exact file/function references, revisions, licensing, selection.
2. `docs/research/confirmed-capabilities.md` — **live evidence matrix** for every required FC27 operation, exact endpoint/service contracts, results, gaps, sanitized observations.
3. `docs/research/market-strategy.md` — scanning design, sources, price estimator/after-tax profit model, coverage/latency limits.
4. `docs/research/execution-architecture.md` — direct HTTP vs Edge bridge decision, module interfaces, session persistence, autonomous loop and crash/duplicate recovery.
5. `docs/research/obj002-handoff.md` — implementation-ready Objective 002: stack, module/file plan, source components to reuse, dependency order, tests, live acceptance conditions, remaining unknowns.
6. A **minimal retained integration harness** (source, setup instructions, deterministic tests) sufficient to reproduce live readback and purchased-card listing verification without retaining any secrets. Include a sanitized validation log/summary and exact test commands.

## Acceptance / reporting

- All primary repositories assessed with concrete source citations or access blockers.
- Authenticated FC27 integration established and independently validated against **current** FC27.
- Search, account reads, **one Buy Now**, acquired-item readback, listing and listing readback independently demonstrated; anything not tested is explicitly UNVERIFIED.
- Direct HTTP versus browser bridge decision supported by measured results, not assumption.
- P0 scan/pricing design and interface contract are actionable for Objective 002; offline profit-model tests pass.
- No simulation, source implementation, or mock is described as live transaction proof.
- Finish with **GO / CONDITIONAL GO / NO-GO**, what works, what is blocked, evidence locations, and the precise next steps. If the live purchase-to-list path fails or browser access cannot be established, report **PARTIAL/BLOCKED** rather than claiming completion.

Keep this an engineering objective. Do not expand scope into dashboards, optional trading strategies, account-management products, or production implementation of Objective 002.
