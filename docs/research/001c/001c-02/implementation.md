# 001c-02: bounded bidding foundations, protocol 1

Classification: **OFFLINE_VALIDATED**. This task implements reusable primitives.
It made zero EA requests and zero account mutations. Authentic FC27 bid results,
watched-list completeness/capacity, actual caps/ticks, and timing feasibility
remain subject to the later bounded live work in Objective 001C. This document
does not promote the historical 001/001B evidence or fixture outcomes to live proof.

The dependency review is [001c-01's gap map](../001c-01/gap-map.json).
REUSE: `fc_access/pricing.py`, the strict public auction projection/validator in
`fc_access/harness.py`, and the byte-identical uppercase-PC persona helper.
ADAPT: the reviewed native observable, paging, cache-invalidation, and XHR
presence-only instrumentation patterns. IMPLEMENT: the isolated Python package
`fc_access/bidding_v1/`, `browser/bidding-v1/page.js`, and the acceptance tests.
PROVE LATER: the authentic network/service and account behavior listed above.
Historical adapters and sealed artifacts are unchanged.

## Integration contract

`contracts.py` defines frozen `Search`, `Identity`, `AuctionStatus`, `Balance`,
`Freshness`, `Coverage`, `BidIntent`, `BidResult`, and `Snapshot` records. JSON
envelopes and journal events carry schema/version 1. Trade/item values are stable
local pseudonyms; scope, owner, command IDs, and epochs are **local correlations**,
never EA credentials or authentication/session identifiers. Keep scope and
evidence key stable when resuming an existing task. The caller verifies the
intended account and supplies an injected UTC clock.

`NativeAdapter` takes a `PageExecutor`, journal, and rules provider. The executor
maps `attach(scope, owner, epoch)`, `execute(envelope)`, and
`reconciled(scope, owner, epoch, evidence_key, trade_id)` to the same named methods
on `window.__fcBiddingV1`, in the official EA tab's MAIN world. Load the copied
`persona.js` before `page.js`. No extension, HTTP listener, polling worker, or
actor is automatically installed or started. Browser transport integration is a
separate caller responsibility. The page API is an internal capability behind
the reviewed host, not a public mutation endpoint.

`search(command_id, Search(...))` calls
`services.Item.searchTransferMarket(criteria, page)`, preserving count 21 and
pages 1/2. It maps `max_bid` to **maxBid**, `min_buy` to **minBuy**, exact version
to `defId`, and uses the existing PC classification. It never interprets maxBid
as a player's profitable cap. `has_more` stays nullable; page lookahead and repeat
rows are deduplicated conservatively by the consumer. There is no claim that two
pages cover the entire market or that the requested search filters are enforced
by EA until authenticated live requests are inspected.

`watched(command_id)` calls `services.Item.requestWatchedItems()` once, accepts
`data/response.items` or `.auctionInfo`, and produces one bulk snapshot (up to
100 projected rows, including the 50-auction queue seam). It does not issue 50
status calls. Recognized authenticated successful XHRs supply request count and
a conservative network-start timestamp; cached, unrecognized-route, and failed
reads have no authoritative network freshness. Unsupported native payloads fail
closed. XHR routes are source hypotheses pending live verification; an actual
different route produces no fresh proof. Empty success, `hasMore=false`, and
HTTP 200 alone do not prove complete coverage. Native coverage defaults to
incomplete, account capacity unknown, even for an empty watchlist. `Coverage`
requires a separate evidence correlation before complete coverage is accepted.
Missing/conflicting rows always remain UNKNOWN. Closed/highest is PENDING until
independent ownership and actual paid-price readbacks establish WON.

`balance(command_id)` calls `services.User.requestCurrencies()`, projects coins
only, and leaves held coins unknown when the source does not explicitly supply
them. No refund is inferred from a write response.

`bid_once(intent, status, balance, rules, observations=..., X=500)` recomputes
exact-version five-comparable pricing using the existing estimator and supports
at most 100 supplied observations. It rejects stale/mismatched identity, missing
comparables, unsupported rules, a cap above the profitable rounded cap, and any
amount other than the minimum legal opening bid/rebid. Leading means HOLD;
pending/unknown, expired, over-cap, insufficient balance, and BIN-equivalent
amounts do not dispatch. It invokes `services.Item.bid(item, amount)` exactly
once on the native physical item from a fresh search/watch snapshot. The page
also fences duplicate commands and auctions, epoch/owner, stale identities, and
deadlines. The host, rather than an untrusted page argument, validates rules
and economics. Acknowledgment remains separate from verified account effects.

## Rules and persistence

`RulesProvider(reviewed_hashes, allow_offline=False)` loads a JSON artifact with
exact fields `schema`, `classification`, `source`, `observed_at`, `key`,
`minimum`, `maximum`, `bands`. `key` is the existing exact-card `MarketKey` shape;
each band has `start`, exclusive `stop`, and `step`. Source must be
`native_card_caps_and_increment_schedule`. Its bytes must match an explicitly
reviewed SHA-256. No cap or increment schedule is installed by default. Stale,
changed, gapped, overlapping, mismatched, or off-tick limits are rejected. A
classification string alone never registers an artifact as reviewed. Native
writes require LIVE_VERIFIED rules and native reads; offline/source-confirmed
artifacts and fake executor results require explicit `fixture=True` mode.
Keep test SQLite files and evidence separate from live journals.

`Journal` uses SQLite WAL, FULL synchronization, transactional intent/event
insertion, and immutable-event UPDATE/DELETE triggers. A command begins UNKNOWN.
Before send, a separate dispatch claim is durably committed; the one-use local
dispatch authority is never reconstructed from storage. The final epoch fence
and synchronous send hold the database write transaction, preventing ownership
takeover while the send executes. A process crash before/after send, lost result,
malformed result, or service failure requires fresh independent reconciliation;
there is no mutation retry path. A new epoch invalidates old ownership and cannot
clear unresolved commands. One unresolved write gates further writes in its scope.
Reconciliation matches full identity, post-intent network reads and independent
read correlations, including fresh balance. It permits a new decision on observed
leading/outbid/terminal state; it never replays the old command. The first stored
per-auction cap cannot increase. Page unlock follows committed reconciliation.

Events retain reason-coded decisions, requested amounts/caps, source, pricing
inputs (sanitized comparable identities, asks, timestamps, freshness), a digest of
those inputs, rules digest, target/tax/profit/sample counts, balance observations,
ACK/UNKNOWN/verified transitions, lifecycle failures, and latency/request counts.
Only the positive payload schema is persisted; exception text, native objects,
query strings, raw identifiers, tokens, headers, and credential values are excluded.
Sequence gives chronology even if the UTC wall clock moves backwards. Query an
existing database without changing it:

```powershell
python -m fc_access.bidding_v1.journal path/to/events.sqlite --scope <local-32-hex-scope> --trade-id trade:<local-24-hex-id>
```

## Scheduling and policy seams

`Scheduler` has injected monotonic time, configurable native interval (default
zero), concurrency, queue capacity, deadline ordering, and write priority.
`delivery()` records local delivery latency; only `next()` starts a native
request slot. `complete()` records observed duration/request count. An optional
journal persists delivery, native timing, and skipped deadlines. The caller must
invoke `next()` immediately before sending and must not replay its in-memory
queue after process restart. A write still passes the durable journal fences.
There is no asserted EA 30-second requirement and no claim that pacing protects
an account from restrictions. The old historical bridge's engineering delay is
unchanged; the new native adapter has no built-in provider cadence.

`AuctionQueue` is a single-owner policy seam, limited to 50 unresolved entries
or a smaller independently known account capacity. Pending admissions reserve
funds against the supplied spendable balance. Reaching or being prevented by the
5,000 reserve enters sticky DRAINING, and balance recovery cannot reopen entry.
Admission and its DRAINING event commit together. Replay preserves exact identity,
reservations, consumed balance read IDs, and DRAINING. Independent status refresh
releases pending reservations; an old pre-reservation balance cannot be reused.
Only confirmed terminal outcomes remove entries. The caller supplies a fresh
balance after reconciliation; UNKNOWN/missing/cache snapshots never free a slot.
No actor service loops, discovery campaigns, live bids, listing automation, or
continuous monitoring run in this implementation.

## Reproducible validation

`python tests/test_bidding_v1.py` exercises contracts, rules, pricing, native JS
via Node's VM, 50 entries, conflict/dedup, pending funds, deadlines, capacity,
sticky DRAINING/replay, HOLD, minimum rebids, cap boundaries, independent outcome
reconciliation, privacy, rollback, append-only triggers, ownership, latency, and
duplicate-write prevention. The crash test terminates an actual child process
immediately after a simulated native write, then reopens SQLite and checks that
no replay is allowed. The 25-second refresh test models a 200ms single bulk
request at each finite checkpoint; it is a fixture model, not a live EA latency
measurement or guarantee. `validation-plan.json` maps every acceptance index to
named executable checks. `tests/check_bidding_v1_artifacts.py` checks that mapping,
paths, version boundaries, absence of actor loops, and preserved persona bytes.

Regression commands (all passed during implementation):

```powershell
python tests/test_market_pricing.py
python tests/test_transaction.py
python tests/test_market_discovery_followup_v1.py
python tests/test_001c01_audit.py
```

These run 11, 11, 9, and 18 tests respectively. All newly generated fixture state
is confined to temporary directories. No historical evidence was rewritten.
