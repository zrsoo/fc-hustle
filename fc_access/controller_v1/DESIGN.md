# Controller v1 implementation boundary (004-01)

This document records the 004-01 design. Implementation is supplied by tasks
004-02–04; final verification and publication belong to 004-05. See
`docs/research/004/REPORT.md` for the implemented contracts and evidence limits.
The design task started no runtime, service, migration or EA operation. The authoritative input is
`objectives/004-single-controller-implementation.md`, read in full, including the
non-blocking uncertainty rules and targeted-verification execution boundary.

## Ownership, API and configuration

One controller process owns the designated account. Exactly **ACQUIRING** and
**MANAGING** are operational phases. A separate lifecycle field has STOPPED,
RUNNING, PAUSED and HALTED values; these never become phases. Low entry credits
produce HALTED plus a durable reason, preserving the phase and batch for audit.
Pause/stop prevent new claims, wait for the finite in-flight operation to finish
or become durably uncertain, persist a checkpoint and release ownership. Status
is a read-only local projection. Import and CLI help/status default to zero EA
activity. `run` will require an explicit command; no scheduled start or cutover.

Proposed modules and interfaces:

| Module | Responsibility / boundary |
| --- | --- |
| `config.py:ControllerConfig` | Validated immutable settings; EA spacing initially 2s, entry threshold 40000, management target 5s; strategy defaults in policy matrix. Snapshot effective config with each batch. |
| `store.py:ControllerStore` | New SQLite file; short transactions for phase, candidates, membership, intentions, claims, observations, results, tombstones and checkpoints. No native calls from storage. |
| `authority.py:BatchAuthority` | Server-side durable validation of mode, account, lifecycle, batch/decision, candidate, cap, exact identity, observation provenance and owner/document epochs. Atomic single-use dispatch claim. |
| `protocol.py` | Strict separately versioned new-mode commands/results; exact-target array status and explicit batch authority reference. No permissive extra keys or arbitrary `new_mode=true` escape. |
| `adapter.py:ControllerAdapter` | Existing pricing read interface plus new-mode writes/status; keeps original observation ages, current document mapping and independent result correlation. |
| `executor.py:SerializedExecutor` | One native invocation at a time; central network pacing and request attribution. Local helpers use the executor but consume zero EA slots. |
| `controller.py:Controller.step` | New phase state machine, sequential decisions, urgent deadlines before resale/maintenance. Never subclasses Acquirer/Bidder or forks their loops. |
| `resale.py`, `maintenance.py` | Adapt verified ownership/list/bulk mechanisms to the same authority, preserving independently checked outcomes. No extra workers. |
| `__main__.py` | Future explicit run/status/pause/stop; fixture ports/state must be disjoint from production; no import-time activity. |

Proposed native API: `status_batch(targets)` accepts 1–10 unique public
`(trade_id,item_id,definition_id)` tuples retained by the current document.
Privately resolve current native DTOs and invoke
`services.Item.transfersDao.getAuctionData([nativeItemA,...])` once, producing one
GET `/ut/game/fc27/trade/status/lite?tradeIds=...`. Record requested, returned,
missing and unexpected sets individually. Reject duplicates, wrong physical
items, malformed rows and conflicting full versions. Lite 0/null version remains
unobserved; link explicitly to retained full-version evidence and the current DTO
for new-mode bid authority. Never rewrite the original response, reverse a
pseudonym, guess an ID or carry mappings over reconnect.

New-mode bid delivery takes a durable command reference, not caller supplied
permission. The server loads authoritative batch/candidate/quote/observation/
owner records, validates legal minimum and amount <= stored cap, and consumes a
claim before calling the page. Authentication, scope, endpoint/body, schema and
epoch fences remain mandatory. Receipt acceptance is separate from independent
participation. HTTP200 and input-derived service itemIds confer no membership.
An exact highest OR outbid personal observation may confirm participation. WON
still requires exact ownership and paid cost. Acknowledgement, absence, elapsed
time, rejection and uncertainty never substitute for those proofs.

## Exact reuse and compatibility map

These are intended imports from the current tree, checked for symbol existence
by the 004-01 validator. Reuse categories distinguish safe primitives from
policy-bearing compositions. No import below grants blanket compatibility.

| Exact imports / native mechanisms | Use and required adaptation |
| --- | --- |
| `production_v1.pricing.{PricingService,Quote,affordable_cap,select_comparables}`; `price_cache.{QuoteCache,TTL_SECONDS}` | Import unchanged exact-version two-search/cache algorithm; supply the existing adapter-compatible read interface. Completed cache hits issue zero pricing searches. Shared quote cache is copied to a new-mode file first; legacy DB is never opened with a writing constructor. |
| `production_v1.prices.{CardKey,NativePrices,PriceService}`; `bidding_v1.rules.minimum_bid` | Import native caps, absolute increment and floored profitable cap helpers. Preserve their adapter identity binding; test reuse through the new adapter. Local price_helpers are serialized but unpaced. |
| `production_v1.contracts.{Search,context,fences,fields,integer,stamp,token}` | Reuse strict identity/scalar/read primitives. Existing `command`/`parse_response` remain legacy dialects; add explicit new-mode validators rather than relax them globally. Pricing reads continue their current dialect. |
| `production_v1.inventory.{KnownTrade,compare_lite_identity}` | Retained full-version comparison; add new-mode proof linkage without widening legacy status admission. |
| `production_v1.bid_receipt.{shape,validate,ordinary_rejection}` | Retain receipt shape/semantics and archival parsing. New-mode result delivery records UNCONFIRMED without poisoning unrelated work; no fake ACK. |
| `production_v1.foundation.scope_for`; `actors_v1.locking.process_lock`; `continuous_v1.runtime.account_locks` | Reuse canonical public scope and cross-mode ownership lock paths. Canonical owner/native guards exclude existing legacy launchers. Avoid invoking runtime.run, Broker or recovery constructors. |
| `bidding_v1.scheduler.{Scheduler,Work}`; `production_v1.foundation.ScheduledExecutor` | Reuse pacing semantics and timing split where strict legacy envelope permits. New-dialect delivery requires a narrow parser injection or separate thin wrapper; do not copy the trading engine. Keep one executor and two-second configurable spacing. |
| `production_v1.executor.{EdgeExecutor,NoRedirect}` | Reuse loopback/no-redirect transport mechanics through a strict new route/parser. Explicit matching service/intent-store identity; attachment is not authentication or market success. |
| `production_v1.resale.{verify_win,win_inventory,fresh_read}`; `production_v1.bulk.{classify,parameters}`; `actors_v1.occupancy.assess` | Reuse physical ownership, paid-cost and complete inventory/target validation. These helpers accept a Foundation-shaped context; provide a small explicit adapter or extract pure validation, retaining legacy wrappers. Do not call Resale.cycle/BulkTransfer.execute unchanged. |
| `bidding_v1.journal.{Journal,payload}`; `production_v1.store.Store` | Reuse short-transaction, append-only and at-most-once patterns, not constructors on live DBs. Legacy Journal migrations, restart updates and global uncertain gates cannot be new-mode storage initialization. New ControllerStore uses the additive draft schema. |
| `browser/production-v1/{page.js,worker.js,persona.js}` | Retain official native auth, safe identity projections, current-document DTO mappings and one native executor. `services.Item.bid(raw,amount)`, move/list, `clearSoldItems()`, `relistExpiredAuctions()` remain the native methods; no raw HTTP/auth-header construction. |

All module paths above are under `fc_access/` unless prefixed `browser/`.

## Required shared seams and affected callers

| Current policy seam | Planned shared change and callers to verify |
| --- | --- |
| `Foundation.admit/bid/reconcile`, `NativeAdapter.dispatch_intent`, `Journal.intend/dispatch/reconcile`, `JournalAuthority.__call__` | Legacy fresh credits/readback and unresolved gates remain. Add separate BatchAuthority and ControllerAdapter paths. Existing callers: actors Acquirer/Bidder, once, durability/final harnesses, verify_bid_receipt, continuous recovery, resale/bulk authorization. Their defaults must keep old semantics. |
| `Store.enqueue/claim/finish`, production Server `/run` and worker command/result validation | Explicit new dialect/store authority registration selected by trusted server construction, never by an unauthenticated request flag. Validate stale owner, duplicate claims and authority mismatch on both routes. Existing production server, bulk research server, legacy worker/page tests remain valid. |
| `page.js` bid preconditions, `observe`, `capture`, `captureBid`, `execute`, `poisoned`; worker delivery | Bind captured requests to the native invocation/owned request boundary. Keep manual/background traffic as bounded diagnostics. Missing owned GET still fails. Scoped late-callback quarantine and restoration on success/error/timeout/interruption replace new-mode page-wide poisoning only. Old requests retain old policy. Test actual worker/page code, not a parallel model. |
| `ScheduledExecutor.run_one/execute`, Scheduler, `actors_v1.native.Broker.run_one` | Add parser/authority seam only where needed for new protocol. Preserve local-helper zero-slot behavior and serialized EA calls. Do not reuse Broker's stop-on-error state machine or launch actor mailbox workers. |
| `resale.Resale.cycle/dispatch`, `bulk.BulkTransfer.execute`, capacity.install/status | Extract minimum verified validation/readback helpers if needed; retain legacy wrappers, capacity accounting and old uncertainty reservations. New storage separately counts known inventory/participation and exposes discarded uncertain effects without restoring a hidden global reservation gate. Existing actors maintenance/relist/sold and continuous watchdog remain legacy callers. |
| `actors_v1.actors`, Config, `continuous_v1.runtime/watchdog`, final supervisor | No new-mode imports of loops/supervision. Retain legacy 600s discovery, 25s monitor, 5000 DRAINING, 50-queue and stop policies. New controller uses its own policy; no deferred orchestrator changes. |

Historical Foundation pricing handoff is PARTIAL at its publication time. Bid
receipt repair demonstrated the stale/empty-success false positive; do not
reinterpret old bids. Production-06's missing captured credits request and
production-07's HTTP200 outbid rebid remain failed/unconfirmed historical
observations, even though later independent recovery was recorded. New-mode
non-blocking outcomes change future policy, never those verdicts. Verified bulk
research windows (five sold removed/four expired relisted) are consumed and will
not be replayed.

## Durable state and transaction protocol

`docs/research/004/004-01/storage.sql` is an executable design fixture only. It
creates new `c1_` tables in an isolated empty SQLite file, never in legacy state.
Future initialization refuses existing legacy DBs and mismatched account/schema.
No migration, importing live active commands or rewriting old event histories is
authorized by 004-01. Before later implementation, copy completed cache data into
new storage through validated projections; retain source TTL and observation
times. Known unresolved/manual inventory must be read as compatibility facts,
not automatically enrolled or treated as empty. Explicit future read-only
reconciliation is required before any new production ownership handoff.

Store account scope/owner generation, exactly two phases and distinct lifecycle;
batch ID/config/credits/discovery/inventory provenance; selected exact identities
and observation ages/expiry deadlines; immutable quote/BIN/cap/native limits;
intent/action key/command ID and claimed state; independent observations/results;
confirmed membership; physical resale and maintenance deadlines; transition log;
permanent tombstones and probe budget/checkpoints. Preserve public identity tuples
only. Browser raw selectors live privately in current-document memory. Store
allowlisted status/error enums/counts/timestamps, never raw IDs, headers, native
exception text, credentials, cookies, EA session identifiers or unrelated bodies.

Sequence: (1) short transaction saves batch/selection; (2) short transaction saves
individual intent and dedup action key; (3) short compare-and-set transaction
checks owner/lifecycle/deadline and claims once, writes tombstone, commits; (4)
native I/O outside all SQLite transactions and general account data locks; (5)
short transaction appends result; (6) separate exact-target observations confirm
membership/terminal proof and advance phase atomically with transition event.
Check owner generation before claim and when applying a result; late results are
audit evidence, never instructions to redispatch or regress newer state.

Use WAL, foreign keys, synchronous FULL, finite busy timeout and one account
owner. The canonical OS process ownership guard lasts for the process, preventing
competing modes; it is not a general account-data lock. Native calls are serialized
by one executor, not by a database write lock spanning awaits. No transaction or
broad data lock crosses awaited network I/O. Tests must acquire another SQLite
writer during a suspended native call and verify it can commit while another
controller/legacy launcher still cannot acquire process ownership.

Claimed/possibly sent commands become abandoned UNKNOWN after restart, never
dispatch work. An initial-enrollment tombstone key binds scope + exact trade/item/
version + initial-bid operation, excluding both batch and observation identity:
new discovery cannot retry an uncertain initial enrollment of the same auction.
Rebid action keys additionally bind amount + originating independent decision
observation, excluding batch identity. A fresh independent observation may
justify a distinct later rebid, retaining the earlier uncertainty audit.
Uncertain initial attempts do not enter membership without proof; uncertain
rebids retain prior membership. Unknown is neither rejection nor loss, conveys no
refund, and creates no invisible globally blocking queue. Ten attempts/members
per batch does not guarantee ten actual participations across successive batches.

Complete inventory validity: same account/context and document generation,
complete end-of-list with consistent native/wire counts, <=30 seconds old at
batch authorization. Invalidate after any known inventory mutation, mapping
loss, conflict or observed external account change. Share that snapshot across
the burst only while valid; invalidity skips affected bids rather than requiring
per-candidate GETs or inventing freshness. Track known pending wins and all
manual/sold/expired/inactive occupied cards; enforce physical and known pipeline
<=50 without counting discarded uncertainties as a global stop. Record residual
capacity uncertainty openly. This bounds known state, not unknowable EA effects.

## Implementation and proof

`plan.json` maps every policy to 004-02–05, concrete observables and negative
cases. `probes.json` specifies exclusive, separately bounded future probe
windows. Task 004-01 executes none. Targeted checks never authorize an autonomous
controller, legacy actor, scheduled job, full-batch lifecycle E2E or soak.
004-05 must run complete current Python/Node discovery and applicable offline
validators; repair real failures without editing sealed receipts or source hash
gates. Commit/push belongs to the overall objective's final handoff, not a claim
that 004-01 implements or live-verifies the controller.
