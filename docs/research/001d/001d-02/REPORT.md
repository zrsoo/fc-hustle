# 001D-02 production native bridge consolidation

Status: **IMPLEMENTED / OFFLINE_VALIDATED** for D1. Protocol is **schema 2**;
`production_v1` names the first production release, not the wire schema number.
The machine-readable companion is `docs/research/001d/001d-02/protocol.json`.
`fc_access/production_v1/contracts.py` is the executable validation authority;
artifact tests check the companion and actual JavaScript responses against it.
Unknown fields and schema 1 envelopes are rejected. There is one production
dialect; experimental namespaces remain historical consumers only.

No live EA requests or browser recovery ran in this task. Installed attachment,
current authentication/persona, and this new extension against EA remain
**LIVE-UNVERIFIED**. Native-route statements below cite sealed observations,
not new transactions. The broader 001D foundation remains PARTIAL: D2 price
legality, D3 quoting/cache, D4 generalized status investigation, and D5 full
journal/scheduler integration are separate tasks. No recurring actors ran.

## Authority and migration decisions

The pre-change map remains byte-identical at `docs/research/001d/REPORT.md`
(001d-01); this report is its implementation supplement. Its proposed reuse
decisions are now applied to this precise production call graph:

Explicit one-shot caller -> `fc_access/production_v1/adapter.py` NativeAdapter
-> `fc_access/production_v1/contracts.py` command ->
`fc_access/production_v1/executor.py` EdgeExecutor -> local HTTP `/run` ->
`fc_access/production_v1/server.py` Server ->
`fc_access/production_v1/store.py` Store durable reservation/claim ->
`browser/production-v1/worker.js` -> `browser/production-v1/page.js` -> EA native
service -> strict nested response -> same parser before persistence or use.
`browser/production-v1/persona.js` reuses the reviewed PC classifier verbatim.
`browser/production-v1/manifest.json` pins only localhost port 8784 plus activeTab
injection into the explicitly selected official Web App tab.

| Prior path | Decision / final production replacement |
|---|---|
| `browser/bidding-v1/page.js` | Retain historical schema 1 harness. Adapt positive projections, serial owner and native DTO logic into production page. |
| `browser/durability-v1/page.js` | Retain historical lifecycle fixture. Adapt document fencing and dirty-before-read; production rejects other historical bridge globals at attachment. |
| `browser/e2e-live-v2/page.js` | Retain flat schema 1 experiment. Adapt observed credits/inventory/caps services and criteria. Never feed flat results to production parser. |
| `fc_access/bidding_v1/contracts.py` | Preserve old consumers; implement schema 2 explicitly, including complete context and lifecycle fences. No production imports of its Search/Identity dialect. |
| `fc_access/bidding_v1/adapter.py` | Preserve its `/user/currencies` expectation for sealed tests only. Production directly expects actual credits, with no alias substitution. |
| `fc_access/durability_v1/adapter.py` | Retain legacy compatibility code; retire its internal credits-to-currencies relabeling from the production graph entirely. |
| `fc_access/durability_v1/executor.py`, `fc_access/durability_v1/server.py`, `fc_access/durability_v1/store.py`, `browser/durability-v1/worker.js` | Adapt pinned-origin local delivery, epochs, durable single claim and UNKNOWN restart. Replace finite window/read/exposure policies with one-shot production admission. No experimental dispatcher is imported by production. |

The production service still requires a separately running local server, started
explicitly with `python -m fc_access.production_v1.server --database production.sqlite`.
It binds 127.0.0.1:8784, derives the unpacked extension ID from the absolute
reviewed extension path, and pins extension Origin for hello/next/result.
No external Codex supervisor is required. `/activate` assigns local scope/owner;
click the production extension in the intended official tab to attach. Importing
the package, idle polling and alarms issue zero EA requests. A new document,
worker or host needs explicit scope reattachment and an appropriate higher
owner epoch; historical ledgers and completed probe windows are never reused.

## Command, scope and retention contract

Every command has exactly `schema,id,operation,params,context,fences`.
Every response has exactly
`schema,command_id,operation,context,fences,result,freshness,coverage,timing`.
The `context` contains account/persona opaque local labels, game=fc27,
platform=pc and `identity_namespace`; these labels are assigned by the trusted
caller/operator, not discovered from cookies or login material. Attachment
privately binds the actual selected user/persona objects and requires the PC
classifier. A selected-persona change, including another PC persona, fails
before dispatch and again after service completion. This prevents reuse within
a changed page context. It does **not** independently certify a named EA account
across a reload: the operator must select/rebind the intended account. This
boundary remains explicit for D5/002 integration, rather than inventing a stable
account fingerprint from session data.

Fences contain `owner,epoch,host_epoch,worker_epoch,document`: the positive integer
owner epoch fences ownership, and public random generation labels fence host
process, extension worker and page document. These are local correlation values,
never EA session identifiers. Every response must echo the exact context/fences,
operation and command/read ID. The host accepts only the attached peer, one poll
owner and one queued/delivered native command. Page execution has its own mutex
and command-owner marker. Duplicate delivery/results and stale peers fail.

Trade pseudonym `trade_id` identifies an auction; `item_id` identifies its physical
item; positive integer `definition_id` is the exact native card version, never
an asset/resource-ID fallback. Row allowlists retain starting/current bid, BIN,
expires, native trade/bid state, optional native `isWon()` and diagnostic-only
`last_sale_price`. Owned-item reads project item IDs in the same namespace.
Coverage remains incomplete: empty/native success does not prove completeness.
No closed/highest result is synthesized into a confirmed win.

Pseudonyms are SHA-256 namespace projections of native numeric identifiers, kept
distinct from raw native IDs, which stay page-local. Equality is meaningful only
inside the identical account/game/platform/persona/identity_namespace context.
Never compare pseudonyms generated under unrelated keys to infer stable native
identity. Changing a namespace does not migrate auction ownership or recover
native mappings. Page reload loses mappings and requires a fresh exact read;
general known-trade resolution across reconnect remains D4 investigation.

`result`, item/auction/caps rows, network evidence, freshness, coverage and timing
all use positive field allowlists. Network evidence contains only host, method,
sanitized path, seven permitted numeric query fields, HTTP status and the boolean
`session_header_present`. Header values, full URLs, arbitrary response bodies,
native messages and exception strings never cross the boundary or enter SQLite
or logs. The page observes presence of X-UT-SID without reading/exporting its
value. Python only speaks loopback HTTP, never direct authenticated EA HTTP.

## Exact native routes and evidence

| Operation | Native entry | Actual route |
|---|---|---|
| search | `services.Item.searchTransferMarket(UTSearchCriteriaDTO,1)` | GET `/ut/game/fc27/transfermarket` |
| watched | dirty INBOX then `requestWatchedItems()` | GET `/ut/game/fc27/watchlist` |
| balance | `services.User.requestCurrencies()` | GET `/ut/game/fc27/user/credits` |
| unassigned | dirty PURCHASED then `requestUnassignedItems()` | GET `/ut/game/fc27/purchased/items` |
| transfer_list | dirty TRANSFER then `requestTransferItems()` | GET `/ut/game/fc27/tradepile` |
| caps | `services.Item.transfersDao.getItemMarketDataByDefId([definitionId])` | GET `/ut/game/fc27/marketdata/pricelimits` |
| bid (guarded protocol primitive) | `services.Item.bid(nativeItem,amount)` | PUT `/ut/game/fc27/trade/:trade/bid` |

Retained `docs/research/001c/001c-06-resume-02/balance-after-opening.json`
records authenticated GET `/ut/game/fc27/user/credits`, HTTP 200, from
2026-11-13T03:28:01.422Z through 03:28:01.492Z. There is no relabeling to
`/user/currencies` in production. Receiving that legacy route fails closed;
the observed path remains unchanged in the page result. No response route is
rewritten even temporarily for a legacy validator.

`docs/research/001c/001c-06-resume-02/comparables-2.json` records search
`definitionId=261855,start=0,num=21`. The historical max-BIN observation is
`docs/research/001c/001c-04/comparables-3.json` (query `maxb=10000`,
definitionId=227323, authenticated GET HTTP 200); these are retained evidence,
not an assertion that the new bridge has been observed live. Caps/list/inventory
projections are adapted from the native calls and sanitized network capture in
the retained E2E implementation, with caps evidence in
`docs/research/001c/001c-06-resume-02/caps-2.json` and watched/owned/status evidence
in `docs/research/001c/001c-06-resume-03/`. The caps observable shape uses
`response.marketData[].priceLimits.minimum/maximum`, as source-confirmed in
`docs/research/001c/001c-04/native-source-contract.json` and observed in
`docs/research/001c/001c-04/rules-and-availability.json`; the wire response's
minPrice/maxPrice array is a different projection. Both source-confirmed shape
and exact request defId are mocked-native validated. Changed client shape must
fail closed and be checked in D2's bounded investigation.

Discovery and pricing are separate canonical `Search` constructors. Both require
exact native `defId=[definition_id]`, page 1, count=21 and fresh cache invalidation.
Discovery alone sets `maxBid=1000,minBuy=11000` (observed numeric wire fields
`macr,minb`). Pricing sets neither; its optional native `maxBuy` maps to observed
wire `maxb` and is inclusive. Host and page verify the numeric wire criteria
against the command, so a maxBuy incorrectly emitted as maxBid fails. Tests
include a listing exactly equal to maxBuy and retain it. No sort is assumed.
This task supplies request primitives, not the D3 two-search orchestration/cache.

## Failure, mutation and reconciliation boundaries

Successful responses require exactly one matching authenticated 2xx network
request, matching native status, timezone-aware network/observation times within
30 seconds, matching source/read ID, and operation-specific payload. Cache-only,
wrong route/method/definition, extra requests, malformed fields, missing auth,
wrong persona, future/stale sources and fabricated completeness are rejected.
Fixture sources require explicit fixture mode; live persistence requires native.

Timeouts and malformed/ambiguous results remain UNKNOWN, never empty-success or
definite rejection. Store reserves and claims before delivery, persists command
IDs, and marks interrupted queued/delivered commands UNKNOWN on restart while
incrementing owner epoch. A lost result cannot be blindly replayed. The page
poisons its command owner after timeout or ambiguous network fanout so an
outstanding request cannot overlap another command. Every native observer and
XHR instrumentation hook is detached/restored after completion/failure.

There is no production per-bid 1000 ceiling, minBuy=10500, finite experiment
lifetime, cumulative read budget, fixed player or auction ID. Discovery's 1000
filter remains solely in its constructor. The fixture native bid is 2500 on
version 7654321, under cap 9000, after fresh status/balance with independent IDs.
Native bid guards retain exact identity, tradability, active/nonleading state,
expiry/deadline, native absolute minimum next bid, cap, available coins and
one-use command/auction fencing.

The shipped server rejects every bid with `mutation_requires_durable_intent`:
`Store.authorize_bid` is unset and no HTTP/CLI flag enables it. This is the
objective's read-only authorization boundary, not an experimental bid ceiling.
`NativeAdapter.dispatch_intent` requires an injected journal `dispatch_once`
interface; D5 must supply durable intent authorization/reconciliation and D2/D3
must supply runtime price legality/profitability before live writes are enabled.
The schema and mocked native write route are ready, not live write authorization.
Historical static-rule/five-sample estimators are not production dependencies.

Independent readback correlation revalidates fresh post-dispatch status and
balance against their original issued commands, complete context and fences,
separate precondition and readback command IDs, exact trade/item/version, and
network timestamps at/after dispatch. Missing/conflicting identity is UNKNOWN;
closed/highest is PENDING, never paid ownership. Correlation does not unlock
another native write or certify a win; D5/002 owns full lifecycle reconciliation.

## Acceptance checks and historical preservation

`python tests/test_001d02_contract.py` runs real production Python against actual
production page code in a Node VM, real loopback HTTP delivery, SQLite restart,
malformed response/secret canaries, strict correlation and artifact checks.
`tests/production_page_checks.cjs` supplies native DTO/service/XHR doubles, not
a replacement page implementation. `tests/production_worker_checks.cjs`
executes the shipped worker with a mocked extension API and host. Neither makes
EA requests. Validators fail if the route is relabeled, maxBuy becomes macr,
discovery contaminates pricing, IDs/fences change, old ceilings reappear or
secrets are retained. All seven task acceptance criteria have explicit checks.

The obsolete future-absence assertion in `tests/test_001d01_inventory.py` is
explicitly migrated to absence in the captured 001d-01 entry manifest and its
published no-implementation flag. All its publication hashes, baseline checks,
historical source/evidence preservation checks and substantive assertions remain.
No sealed report/fixture/source or historical test is otherwise changed.

Regression results and exact invocations are retained in
`docs/research/001d/001d-02/validation.json`. The 001d-01 baseline already records
unrelated release-audit/objective-hash drift and plain-discovery failures; these
are not repaired by rewriting history. No claims of current attachment,
authentication, server reachability or live transaction success are made.
