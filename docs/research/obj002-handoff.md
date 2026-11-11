# Objective 002 implementation handoff — task_06

**CONDITIONAL GO**: implement the autonomous executor against [the execution architecture](execution-architecture.md), while retaining the explicit live release prerequisites below. Task_06 delivers specifications and offline artifact checks, not the production loop. No new trade or browser action is needed to finish this task. Objective 001's bounded purchase/listing proof must not be repeated merely to refresh an aged checkpoint.

## Stack and boundaries

Use Python **3.13** on this Windows workspace (existing harness is Python 3.10+), standard-library `sqlite3`, `dataclasses`, `unittest`, `http.server`, `urllib` and OS locking. Edge Manifest V3 uses locally authored JavaScript, activeTab, MAIN-world native services, memory-only tab selection and a fixed localhost bridge. Node **22+** runs JavaScript fixture tests only; it is not a required trading backend. Pin the supported Python/Edge/Node versions in the implementation setup, and verify installed SQLite WAL/FULL support. No framework, Redis, Celery, external extension binary, remote debugger or credential exporter is needed.

Keep new execution code in `fc_execution/` and `browser/execution-bridge/`. The existing `fc_access/` and one-shot bridges remain research/reproduction tools. Only the pure pricing module is reused directly. Use UTC persisted times plus monotonic timers for deadlines, with injectable clocks/transports in offline tests. Start one local process with one OS lock and one serialized command queue; its startup always reconciles durable state. Scope is scan → evaluate → buy → list → repeat automatically with configurable X, without per-transaction approval or additional portfolio/spend policies.

## Module and file plan

Paths below are **planned**, not files claimed to exist. Each module has a concrete responsibility and test. Existing source links in the next section do exist.

| Planned path | Responsibility / interface | Planned test artifact |
| --- | --- | --- |
| fc_execution/models.py | Typed MarketKey/Result/snapshot/rules/intent models; exact version, epoch, unknown versus empty, integer/time validation | tests/test_execution_models.py |
| fc_execution/store.py | SQLite schema, WAL/FULL, unique semantic keys, generations, atomic acquisition/listing/settlement transitions, local backups | tests/test_execution_store.py |
| fc_execution/identity.py | Local scope/correlation-key persistence, stable pseudonyms, account mismatch, page-map rebuild contract | tests/test_execution_identity.py |
| fc_execution/transport.py | Replaceable native adapter; attachment/protocol/epoch, strict loopback schema, outcome and deadline handling | tests/test_execution_transport.py |
| fc_execution/session.py | Session.ensure_ready, DETACHED/AUTH_REQUIRED/RESTRICTED, native renewal observation, reconnect and resume gates | tests/test_execution_session.py |
| fc_execution/providers.py | CatalogPrices interfaces, two-version watchlist, source provenance, optional conditional public feed and explicit unavailable state | tests/test_execution_providers.py |
| fc_execution/rules.py | Capture and validate exact-card caps and relevant price increments; NOT_READY on missing/stale/unverified rules | tests/test_execution_rules.py |
| fc_execution/strategy.py | Wrap fc_access.pricing.evaluate, revalidation and target revision, X equality and legal listing target | tests/test_execution_strategy.py |
| fc_execution/scheduler.py | One queue, minimum gaps, priority reconciliation/listing, skipped missed slots, shared backoff and passive aggregate load | tests/test_execution_scheduler.py |
| fc_execution/reconcile.py | Read-only resolution of pending buy/move/list/relist operations before any new write; ownership/debit/active-state proofs | tests/test_execution_reconcile.py |
| fc_execution/executor.py | Autonomous state machine, durable intent before dispatch, acquisition cost and listing generation, held inventory recovery | tests/test_execution_executor.py |
| fc_execution/settlements.py | Sold/expired distinction, attributable proceeds, nullable actual tax/profit, unique sale settlement | tests/test_execution_settlements.py |
| fc_execution/__main__.py | Reviewed CLI start/status/stop, configuration X/watchlist, integrity checks and graceful restart | tests/test_execution_cli.py |
| browser/execution-bridge/manifest.json | Separate versioned MV3 package with narrow official-page/loopback permissions | tests/execution_bridge_checks.cjs |
| browser/execution-bridge/worker.js | Pairing capability, pinned extension origin, deadlines, one delivery, epoch protocol and attachment | tests/execution_bridge_checks.cjs |
| browser/execution-bridge/page.js | Native search/buy/inventory/move/list/status, exact revalidation and allowlisted projections; no auth export | tests/execution_bridge_checks.cjs |
| docs/obj002/setup.md | Stack pinning, normal attachment/login recovery, state backup/restore, operator status and test commands | tests/test_execution_setup.py |
| tests/validate_execution_live.py | Read-only assessor of newly collected sanitized operation/settlement/lifecycle evidence, separate from executor | tests/test_execution_live_validator.py |

The new command schema must replace experimental price bounds with verified card rules. Reviewed research v3 limits are not a P0 budget. The new schema also needs stable local scope IDs, semantic command IDs, payload hashes, epochs, listing generations and complete snapshot coverage. Update protocol/page/server validation together and test rejection of mismatched versions. Pairing capabilities stay in the worker/server, never in page logs or reports.

## Reusable sources and license obligations

Existing local implementations are independently authored. Read their invariants, but do not treat research restrictions or checkpoint formats as a finished executor:

| Existing local source | Reuse / adaptation boundary |
| --- | --- |
| [fc_access/pricing.py](../../fc_access/pricing.py) | Reuse pure MarketKey, Observation, Rules, Policy, evaluate and profit; DEFAULT_BANDS is a hypothesis, so inject verified rules and inspect assumptions before execution |
| [fc_access/harness.py](../../fc_access/harness.py) | Protocol/read result validation and allowlisted projections; direct provider is unavailable; no credential CLI |
| [fc_access/transaction.py](../../fc_access/transaction.py) | Intent-before-dispatch, fsync, OS lock and independent readbacks as design references; Experiment is single-shot with restrictive resume logic and must not become the loop |
| [fc_access/transaction_server.py](../../fc_access/transaction_server.py) | Strict Host/Origin, bounded JSON, single delivery and deadline concepts; add durable operation lookup, pairing and epoch rather than copying its volatile queue as storage |
| [browser/transaction-bridge/page.js](../../browser/transaction-bridge/page.js) and [read-page.js](../../browser/transaction-bridge/read-page.js) | Native method mappings, source-backed tradability, page-side identity checks, cache invalidation and privacy projection; replace per-run maps/deduplication for durable scope/generations |
| [browser/transaction-bridge/worker.js](../../browser/transaction-bridge/worker.js) | 30-second local alarm and injection lifecycle; add negotiated execution protocol without widening the installed research bridge |
| [fc_access/transaction_checks.py](../../fc_access/transaction_checks.py) | Independent ownership/coin/listing proofs and assessment concepts; future assessor adds unknown outcomes, lifecycle and settled-sale accounting |

Upstream selections are pinned in [repository analysis](repository-analysis.md) and the [review ledger](evidence/repositories.json). Source-level availability is not independent live proof. Before copying any subset, review its transitive files/build hooks and save the exact license/copyright text with the adapted component, including a third-party notices file. No upstream code is copied by this task.

| Pinned upstream source | Selected component | Obligation / exclusion |
| --- | --- | --- |
| [Copilot page-inject.js](https://github.com/liusihang/fc27-copilot/blob/fa0fdde132715b2c09a4cff1e51736a1794d635e/extension/content/page-inject.js), [actions.py](https://github.com/liusihang/fc27-copilot/blob/fa0fdde132715b2c09a4cff1e51736a1794d635e/fc27/actions.py), [execution.py](https://github.com/liusihang/fc27-copilot/blob/fa0fdde132715b2c09a4cff1e51736a1794d635e/fc27/execution.py) | Native searchTransferMarket/buyNow/sendToTradepile/listOnMarket and ActionDispatcher/ExecutionService reconciliation concepts | MIT: preserve copyright and permission notice. Exclude batch approval and unrelated policies from P0; independently harden messaging |
| [Sniffer r2_prices.py](https://github.com/puredan824-hub/fc27-sniffer/blob/e1488d6e51bdcafec6eaf61cdb06461358b7844d/r2_prices.py) | decode_ids and advertised bulk manifest schema; optional discovery only | MIT: preserve copyright and permission notice. Current FUT.GG 403, PC coverage UNVERIFIED; no bundled code/data access rights inferred |
| [SP Tool price.ts](https://github.com/marchiartur/sp-tool/blob/e9cc12558492634a94934bc8084cc77cbcf0a897/src/lib/price.ts), [ea-main.js](https://github.com/marchiartur/sp-tool/blob/e9cc12558492634a94934bc8084cc77cbcf0a897/extension-static/ea-main.js) | Price parsing, stepAt/snap/up/down and criteria/cache questions | MIT: preserve copyright and permission notice. Ladder helpers still require empirical boundaries/caps; no cache alternation assumption |
| [Market Companion market.js](https://github.com/FrancescoPalasciano/Bot-Fc27/blob/925a61dfee4f3c13e35beb82104185942e51384b/src/market.js) | calculateTrade and summarizePrices ideas | MIT: preserve copyright and permission notice. Do not adopt name-keyed history, fixed 50-coin ladder or bundled FUTBIN data as licensed code |

XI Lab, FC27-Autobuyer and fut-web-app-api have no reviewed license grant: concepts/questions only, no copying/adaptation until a grant. Gallery Bot is reference-only with missing bridge parts. The historical fut-25-market client is reference-only; any later Apache-2.0 reuse requires the license, applicable attribution/NOTICE, and marked modifications. Its credentials, fingerprint changes, FC25 host and bid=-1 are excluded. Code licenses do not grant EA/FUT.GG/FUTBIN data or service rights.

## Dependency order

Stages are intentionally sequential at mutation boundaries; pure components can be developed offline. All stage dependencies must be satisfied before live execution.

| Stage | Depends on | Deliverable and exit condition |
| --- | --- | --- |
| S1 | none | Models, SQLite store, stable local identity and backup/restore; uniqueness, null accounting and crash-commit tests pass |
| S2 | S1 | Separate reviewed bridge/transport/session protocol; safe read-only handshake, privacy, epoch and stale-result tests pass |
| S3 | S2 | Fresh cap/range and relevant increment evidence, providers and strategy; missing rules prohibit execution; pure estimator tests pass |
| S4 | S3 | Scheduler, reconciliation, executor and settlements with injected transports/clocks; full crash/fault matrix passes offline |
| S5 | S4 | Setup, independent live assessor, bounded Objective 002 live acceptance with new evidence, normal renewal/reconnect and sale settlement verification |
| S6 | S5 | Enable continuous autonomous operation under Objective 002's execution scope; all required live conditions below passed and pending intents reconciled |

Do not wait for denied bulk/history access to build S1–S4. The targeted watchlist is sufficient for that implementation path. Do not substitute synthetic caps or a newly scraped third-party quote for S3's live rules. Relist can stay disabled until an eligible naturally expired listing is independently verified; do not fabricate expiry or cancel listings just to create a test case.

## Tests and artifact checks

Existing independent offline regression commands, runnable from this workspace:

```text
python tests/test_execution_artifacts.py
python tests/test_repository_research.py
python tests/test_market_pricing.py
python tests/test_market_artifacts.py
python tests/test_transaction.py
python tests/test_transaction_bridge.py
python tests/test_transaction_artifacts.py
```

The new task_06 artifact check validates both documents, typed interface coverage, state/recovery matrices, module dependency order, source paths/revisions/licenses, numeric pacing/freshness against task_05, and observed counts/prices/errors against retained JSON. It also mutates required contracts to demonstrate rejection. These checks validate a specification, not unimplemented execution code or new live behavior. They require no network, login, attached bridge or refreshed transaction capture.

Required Objective 002 test scenarios (planned paths in the module table):

| Test area | Concrete assertion / injected failure |
| --- | --- |
| Models/strategy/rules | Wrong special version/platform, zero/missing ID, boolean price, stale/future/cache-only rows, lookahead/conflicting duplicates, fewer than five comparables and missing/stale caps reject; threshold equality passes, X+1 fails; full tick boundaries need separate live evidence |
| Store/identity | Same semantic command and same sale cannot insert twice; payload mutation rejects; restored key reproduces identities; key loss/account switch/corrupt DB blocks writes; backup restore preserves actual cost and generations |
| Crash/reconciliation | Kill before intent commit, after commit before send, after native dispatch before response, after response before readback, after readback before commit, and after active listing before restart; each buy/move/list/relist resumes read-only and never redispatches an unknown write |
| Autonomous executor | Two distinct qualifying synthetic opportunities complete scan/evaluate/buy/move/list/readback/repeat without approval callbacks; nonqualifying scans do not buy; inventory HELD on invalid target recovers once legal; exact owned physical item is listed |
| Session/transport/bridge | Simulate 401 with native recovery, persistent login/challenge, tab navigation, browser/server restart, protocol mismatch, late/duplicate result, wrong epoch/account, lost acknowledgement and forged Origin/Host; all suspend/reconcile correctly, no auth values cross bridge |
| Scheduler/providers | Fake clock proves 30-second gap, no catch-up burst, priority recovery/listing, 429 Retry-After longer than 300, capped 5xx schedule, 403 source disabled, stale publication invalidated and background calls included in load |
| Accounting/status | Active/expired/vanished listing yields no realized profit; sold trade with unknown proceeds/cost stays null; attributable settlement UPSERT once survives restart; modeled floor tax and observed actual tax remain distinct |
| Independent assessor | Delete/mismatch ownership, coin, native freshness, identity, active trade, duration, settlement or lifecycle proof and validation fails; fixtures never write retained live files |

## Live acceptance conditions

These conditions apply to Objective 002, not a request to trade during task_06. Its collector and assessor must be separate. Retain sanitized timestamped evidence, per-operation IDs and immutable pre/post snapshots; a callback, fixture, source claim or HTTP 200 alone cannot pass. Existing proof is historical context, not a substitute for validating newly implemented code.

| ID | Required live evidence / pass condition |
| --- | --- |
| L1 | Current authenticated game/platform/configuration, reviewed execution bridge handshake and complete fresh coins/unassigned/transfer/status reads. Protocol badge alone fails |
| L2 | Current exact-card minimum/maximum and relevant increment boundaries from native source/read-only range state with attributable provenance; demonstrably valid proposed bid/BIN. Broader bands stay disabled until checked |
| L3 | Fresh exact-version comparables, independent candidate exclusion, legal target and expected_profit >= X at page-side dispatch, with age/expiry and current rules enforced; opportunity exists naturally, otherwise record NOT_OBSERVED rather than invent profit |
| L4 | Under Objective 002 execution scope, Buy Now leads to the same newly owned physical item and attributable acquisition cost; move if needed and independently prove exact destination |
| L5 | List that acquired physical card and independently observe new active trade ID, full version/platform, bid/BIN and duration/expiry; later status read agrees. At least two independent qualifying cycles demonstrate repeat without transaction approval; no promise either will sell |
| L6 | Disconnect/restart with preserved intents and state; fresh readbacks reconcile prior work and no duplicate mutation occurs. Native session renewal or normal reauthentication recovery observed and same-scope checks pass; account mismatch suspends |
| L7 | Naturally sold trade with attributable gross/net/cost verifies realized profit exactly once; observe tax rounding at an odd 5% boundary before claiming floor rounding is empirical. Until observed, settlement remains pending/UNVERIFIED |
| L8 | Observe ordinary aggregate traffic under the implemented bridge without load probing; confirm it respects schedule/backoff, stops on auth/challenge/restriction, and records unknown writes for reconciliation. Relist accepted only if an eligible naturally expired unsold item exists; otherwise remains UNVERIFIED and disabled |

Fault injection stays synthetic wherever a forced live failure would add an unnecessary mutation. Freshness expiry must never trigger a repeat purchase. If no naturally qualifying auction, sale or expired listing appears, report that live condition unresolved; do not loosen X, invent caps, force a sale or claim verification from mocks.

## Unresolved prerequisites and disposition

| Gap | Current evidence | Required next step / impact |
| --- | --- | --- |
| Exact PC per-card caps | UNVERIFIED; ask extrema and 200/250 accepted listing are insufficient | Add read-only native price-range projection with reviewed schema/provenance and 300-second freshness; blocks live acquisition/listing decisions |
| Complete increments | Selected 50/100-spaced points only; global schedule UNVERIFIED | Verify relevant native ladder/boundaries; keep unverified price regions disabled; blocks those execution regions |
| Tax and realized sale | Active listing only; actual settlement/rounding UNVERIFIED | Observe attributable natural sale and odd-boundary tax; blocks claims of verified realized accounting, not offline implementation |
| Session renewal/reconnect | Initial attachment and reads work; renewal/expiry/logout not live-tested | Implement epoch/scope recovery and observe normal lifecycle without exporting secrets; required before unattended readiness |
| Stable durable identity | Research IDs are per-run; in-memory maps and deduplication disappear | Implement persisted local correlation key/scope, replay-proof intents and map rebuild; blocks reliable restart execution |
| Broad PC catalog/bulk | FUT.GG manifest/catalog 403; no validated PC feed | Restore legitimate provider access/schema/terms only if expanding beyond targeted watchlist; optional for initial P0 |
| Numeric history | UI/provider descriptions, no timestamped numeric backfill | Optional legitimate history feed/local forward observations; never replace current comparable asks |
| Background polling/rate limits | Local alarm measured; normal EA interval and numerical EA limits UNVERIFIED | Add passive aggregate counters, honor actual statuses/Retry-After and reduce work on overload; no stress test to discover a threshold |
| Relist and sold cleanup | Relist UNVERIFIED; no eligible expired listing, cleanup contract absent | Keep disabled until natural eligibility and independent readback; preserve settlement before any later cleanup |
| Enforcement | EA prohibits automation and may restrict or ban accounts | Retain [factual enforcement boundary](execution-architecture.md#enforcement-facts-and-boundary); restrictions stop execution, with normal EA recovery only |

No current human intervention blocks completion of these task_06 documents and artifact checks. Future normal extension attachment/login may need the operator after actual loss of access; there is no new transaction approval layer. Essential purchase-to-list contracts are verified in [task_04](purchase-to-list.md); [task_05](market-strategy.md) supplies a tested estimator but explicitly missing live rules and negative modeled opportunities. Proceed with S1, then S2–S4; reach live release only through S5's retained conditions. No detection-avoidance claim or restriction workaround is part of this handoff.
