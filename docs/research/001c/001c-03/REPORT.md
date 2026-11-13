# 001c-03: native watched-auction read investigation

**LIVE_VERIFIED:** the authenticated FC27 PC account returned a fresh empty
watchlist, and its loaded native repository and server setting independently
reported **50** Transfer Targets slots. **UNVERIFIED:** nonempty coverage,
live auction status reliability, saturation, and sustained monitoring of 50
auctions. No account mutation or enrollment was performed by this task.

REUSE: 001c-02 typed status/coverage records, queue reconciliation, and the
previously verified uppercase-PC persona projection. ADAPT: native cache
invalidation and the response freshness contract. IMPLEMENT: the isolated
`experiments/watched_bulk_v1/` read-only probe, transport, status conversion and
validators. PROVE: actual network/cache behavior, empty UI agreement and loaded
capacity. The entry hashes preserve every historical file present at task entry,
including the dependency's untracked implementation; no old evidence is relabeled.

## Recovery and independent readiness layers

AGENTS.md was read before recovery, and explicitly reread before the ordinary
page refresh. This worker used Windows UI Automation to select the uniquely
identified Edge window and EA tab and verified foreground and the official URL
before input. `edge-preflight.txt`, `edge-v2-attached.txt` and
`targets-after-fresh.txt` retain sanitized UI checks. The session was already
signed in; no credentials, cookies, authentication values or session IDs were
read or retained. No login challenge required human intervention.

No relevant localhost service was initially listening. An additive, reviewed
extension was loaded from `experiments/watched_bulk_v1/browser`; Edge showed ID
`bbdmlnhehokodegoodepjkoebhbhdhbc`. Chromium hashes the Windows unpacked path as
UTF-16LE. An initial UTF-8-derived pin on port 8773 rejected attachment and sent
zero native reads. Correcting the pin on 8774 enabled the first two calls.
An attempted process termination was rejected by automatic approval review;
subsequent recovery used additive listeners and left the earlier services idle.
The extension currently connects only to **127.0.0.1:8775**. No process was killed.
After refresh, an early attachment was lost during navigation and one local
inspection timed out. A later explicit attachment succeeded. That local timeout
was not an EA failure and did not consume a watched-read invocation.

`readiness.json` records loopback service health and the observed extension ID.
Attachment means local polling only. `inspect-3.json` independently establishes
the selected PC persona. Authenticated successful FC27 market-service readiness
comes from the XHR presence flag and HTTP 200 in `watched-3/4.json`, not the badge,
persona, home screen or health endpoint. Review hashes are in `review.json` and
`review-v2.json`; the latter covers the final injected scripts.

## Native requests, empty comparison and freshness

Each command invoked `services.Item.requestWatchedItems()` exactly once. The
positive projection retains method, sanitized route, native request count,
HTTP/native status, elapsed time, UTF-8 response-text byte length, network start
and end times, presence-only authentication and allowlisted auction fields.
The byte length is the decoded response body, not compressed wire bytes.
XHR hooks are removed in `finally`. Queries, bodies, headers, raw auction/item
IDs, response objects and exception text never enter live artifacts. Item/trade
identities are stable local SHA-256 pseudonyms. With zero rows, live field-value
parsing remains unproved; the 50-row fixture exercises that projection.

| Capture | Native status | Actual EA GETs | Native service ms | Result |
| --- | ---: | ---: | ---: | --- |
| watched-1 | 200 | 1 | 247.7 | Empty network response |
| watched-2 | 304 | 0 | 0.4 | Successful cached empty snapshot |
| watched-3 | 200 | 1 | 70.4 | Empty after inbox cache invalidation |
| watched-4 | 200 | 1 | 120.8 | Independent repeated fresh empty read |

All three fresh reads used **GET `/ut/game/fc27/watchlist`**, HTTP 200 and a
44-byte body. Four native invocations produced three instrumented EA requests.
Counts cover FC27 XHR sends during each invocation only; ordinary navigation and
startup traffic outside the command windows is excluded. Fetch is not hooked.
The loaded native implementation uses XHR, as observed in the actual reads.

The summary screen showed Transfer Targets **0 Items**, Winning **0**, Outbid
**0** (`transfers-summary.txt`). The dedicated Transfer Targets screen showed
the empty bidding/watched/won sections and the Expired Items heading in
`targets-after-fresh.txt`, captured 44 seconds after the last network read.
The empty expired-section placeholder was also inspected through UI Automation
before that final capture; it was below the visible viewport in the retained
final projection. No known enrolled auction was available for an identity match.
Both the full native inbox repository and returned auction array had zero rows.
This supports a verified empty account at these observations, without asserting
that a successful empty array or a 304 alone proves emptiness.

## Cache, completeness and reported account capacity

`native-source-decoded.json` decodes public EA string constants using static
custom-base64 substitution and the unique rotation checksum. No downloaded JS
was executed. Every retained method was matched byte-for-byte to the function
inspected in the loaded app. `native-repository-source.json` additionally matches
the loaded repository methods to current official `compiled_2.js` and preserves
the server-setting assignment. Public source inputs are separately retained in
`private-captures/001c-03-public-source/`.

The native service delegates to `itemDao.getWatchPile(includeAll)`. A clean inbox
repository returns its cached items with native **304** and no XHR. A dirty inbox
makes one noncached watchlist request, converts `auctionInfo`, and timestamps the
repository. The v2 probe uses the source-confirmed local
`repositories.Item.setDirty(ItemPile.INBOX)` before the same public read method.
This only invalidates local cached data. It is not an account write. A fresh
status conversion still requires an observed authenticated network response.

The native method has no page/count parameters. The witnessed requests had no
start/count query values. `has_more` was absent/null, not false. The repository's
`setWatchedItems` replaces the inbox and sets its local `endOfList=true`; that is
client behavior, not independent proof against server truncation. Empty reads
cannot test pagination at a boundary, duplicate pages, hidden exclusions, or
coverage of 50 real auctions. Nonempty complete coverage remains false in the
adapter even when the UI and zero-row repository agree.

The loaded `repositories.Item.getPileSize(ItemPile.INBOX)` and
`repositories.ServerSettings.getSettingByKey(TRANSFER_TARGET_SIZE)` both returned
**50**. Public source starts this pile at a default **30**, then overwrites it
from server settings. Therefore this is an observed loaded-account capacity
report, not a copied queue default. The client checks `isPileFull(INBOX)` before
watching/bidding. We did not fill the pile or observe a server rejection; a hard
server maximum and future capacity changes remain unproved. The application queue
setting of 50 is separate: use the smaller confirmed account limit, account for
other watched/won/unresolved entries, and recheck changed account configuration.

## Supplemental reads and status reliability

The current service can filter to **won items only** when
`PLATFORM_SPLIT_FOR_TRANSFER_MARKET` is enabled. This account's loaded feature
flag was **false** in inspection and both v2 reads. Returned zero rows, full
repository zero rows and visible empty Targets agree. No supplementary request
was necessary. Current source supports `itemDao.getWatchPile(true)` as an
unfiltered bulk alternative, but it was **SOURCE_CONFIRMED_ONLY**, not invoked or
claimed live verified. No speculative older-game pile-size or trade-status HTTP
endpoint was called. If the flag changes, require independent coverage evidence
or validate that supported alternative before relying on the filtered service.

No live active/leading/outbid/won/lost/expired/removed auction was observed.
The new conversion contract preserves missing/conflicting/cache-derived states
as **UNKNOWN**. Closed/highest is **PENDING** until independent ownership and
actual paid-price evidence establish WON. Expired/outbid alone does not establish
a terminal outcome in this contract. A missing row never frees a queue slot.
The existing 001c-02 adapter remains preserved; callers should use the new
cache-aware contract rather than assume its plain watched invocation is fresh.
There was no opportunity to measure a competing bid or countdown extension.

## Refresh budget, fixtures and handoff

For this empty account, a forced fresh bulk refresh required **one EA request**;
a cached invocation required zero and was unsuitable as fresh monitoring. Expect
one request for a whole queue **only if** the bulk route covers that queue.
There is no evidence requiring 50 per-auction GETs. Any necessary future
supplemental/paged reads would add separately measured requests; none is assumed.
The observed 70.4–247.7 ms native service times are three empty samples, not a
p95, 50-auction latency estimate, throughput benchmark or account rate limit.
A 25-second refresh target is plausible from empty latency alone, but remains
unverified at 50 auctions and under sustained traffic.

The 30-second gap is this finite experiment's guard, not an EA requirement.
Six watched invocations were authorized in this probe; **four** were consumed,
including the cached call. V2 started from the consumed-two checkpoint and
persists consumption before delivery. No completed discovery windows, mutation
commands or consumed experiment budgets were replayed/reset.

`contract.to_snapshot` imports 001c-02 records and queue behavior, preserves the
observed capacity separately from configuration and rejects failed reads. Cache
snapshots carry no authoritative network time. `fixtures/watched-50.json` is
explicitly OFFLINE_VALIDATED. Tests cover actual page projection with 50
synthetic rows in a single XHR, ingestion, stable identities, duplicates,
conflicts, missing entries, expiry/pending states, deadline order, smaller account
capacity, local processing time and no inferred terminal outcomes. They prove
local correctness, not live nonempty semantics or 50-auction EA performance.

Run independently from the workspace:

```
python tests/test_watched_bulk_v1.py
python tests/test_watched_bulk_artifacts.py
```

The artifact validator derives fresh/cache counts and timings, checks independent
UI and capacity evidence, matches source and extension hashes, rejects weakened
or promoted claims, and verifies historical preservation. Regression commands
`python tests/test_bidding_v1.py`,
`python tests/test_market_discovery_followup_v1.py`, and
`python tests/test_001c01_audit.py` passed 25, 9 and 18 tests respectively.
`checks.json` records final command results. Validators make no EA requests.
