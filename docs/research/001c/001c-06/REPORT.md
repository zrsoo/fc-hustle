# 001c-06 bounded competitive-auction E2E

**UNRESOLVED / CONDITIONAL GO.** One real ordinary 700-coin bid command was dispatched, but a successful enrolled opening and leading HOLD were not independently proved. The consumed campaign is closed and must never be replayed or reset. No Objective 002 actor was launched.

The live commands ran from 2026-11-13T03:04:08.094066+00:00 through 2026-11-13T03:07:21.936Z. The fixed window allowed 900 seconds, 40 reads, four total mutations, two bid writes, one auction, 2,000 gross reserved coins, maximum 1,000 per bid and a 5,000 spendable reserve. Actual consumption was 17 reads and one mutation: 18 native requests, with 700 coins conservatively reserved. The run ended early after an unresolved mutation. All operations were serialized. SQLite FULL/WAL committed each reservation before delivery; command IDs and stage artifacts are exclusive. Public owner, worker, document and process fences are local correlations, never EA authentication values.

## Actual Acquirer attempt

The current worker verified its own Windows UI Automation access, Edge foreground and the official signed-in Web App. It loaded the isolated reviewed `browser/e2e-v1` extension (ID `adjoadkfnhmdnmfemioehilkaikmfjcf`) and started its dedicated loopback service on 127.0.0.1:8780. Attachment, public uppercase PC persona, authenticated network presence and native success are separate retained fields. No login or security challenge occurred. Historical sources and evidence listed in entry.json were preserved. The previous 001c-05 window stayed closed and its zero-mutation budget was not changed.

The actual search transmitted `macr=1000` and `minb=10500`. Fresh exact-version 261855 comparable asks and fresh native card caps supported the candidate `trade:83105610f7508574b2e36139`, physical `item:178f6a3fd2bc1c19690e3ffe`. Fifteen independent deduplicated listings remained after candidate exclusion and five price outliers. The conservative estimated target was 2,200, projected tax 110, X=500 and rounded profitable cap 1,500. The minimum ordinary opening was 700; projected profit at that price was 1,390, conditional on a later sale at the estimate. The separate experiment imposed a 1,000 bid ceiling. No observed estimate is a sale or realized profit.

The reused estimator's nested BIN-reference acquisition price 10,500 and expected profit -8,410 refer to a hypothetical Buy Now purchase; they are not the actual bid or a paid cost. Client increment observations plus fresh native card caps supported this explicitly bounded empirical test. The strict reusable bidding_v1 provider still rejects unverified server rules. No artifact was fabricated as LIVE_VERIFIED to bypass that provider; the isolated experiment does not establish server acceptance of the full tick schedule.

At 03:04:38.756 UTC the native `services.Item.bid(item,700)` invocation emitted one PUT to the sanitized `/ut/game/fc27/trade/:trade/bid` route. HTTP/native status was 200. Its independently projected response already reported `outbid`, current bid 750 and 92 seconds remaining. The invoked amount and durable intent were 700; the request body was not retained, so server-applied amount/acceptance is not inferred. The following fresh watched GET returned an empty array, while a separate balance GET still reported 16,268. A second watched GET and the visible Transfer Targets (0 winning, 0 outbid) agreed on emptiness. A separate filtered search showed the same physical auction at 750 but bidState `none`.

This is live auction-price movement, but it is not authoritative proof that our opening was accepted, that we held leadership, or that an enrolled personal outbid occurred. The bid response and independent coverage do not establish those facts. The persistent `unreconciled` mutation guard prevented every further mutation. mutation-stop.json records the stop and a four-read-only tail within the original deadline. No second bid, HOLD claim, transfer or listing occurred.

## Timing and resolution

Actual bulk watched host durations: 160.272 ms, 131.695 ms, 94.015 ms, 119.829 ms. Each was one authenticated native GET with an empty payload array. Bid dispatch after durable claim took 4.472 ms, actual native PUT took 170.300 ms, and host round trip took 213.566 ms. The independent first watched response completed 687.000 ms after the PUT response. Every command retains native start/end, payload bytes, page and host duration in its artifact and timeline.json. Empty watchlist samples cannot establish a 25-second cycle for 50 live entries. Offline 50-entry and scheduling proofs remain separate.

Pre/post expiry snapshots are retained in report.json, including filtered availability, the write response and the independent later search. They show no witnessed near-expiry extension experiment. Auction extension remains live-UNVERIFIED; no artificial opponent traffic was generated.

After the maximum observed expected expiry, the four tail reads were: filtered exact-version search, watched, unassigned, balance. The auction was absent from that bounded search; watched and unassigned were empty. Absence is UNKNOWN, never LOST. There was no independent terminal trade status, conclusive WON or LOST, refund, paid acquisition cost or verified new owned physical card. The eight transfer-list cards observed earlier are baseline inventory, not acquisitions of this run. No won-item transfer/list condition was reached; no sale or realized profit is inferred.

## Account accounting

All four spendable reads were **16,268**. Observed net available-coin delta is **0**. Gross potential exposure reserved by the journal is **700**, retained conservatively against the one unresolved command. Paid cost, held balance and returned coins are **unknown**, rather than zero: snapshots cannot resolve transient escrow/refunds between reads. No new owned card was found; no unsold card or listing created by this run can be confirmed. The unresolved bid and any ownership uncertainty remain explicitly carried forward.

## Every actual command

Each capture file contains the exact standalone argv, input parameters, before/after health and sanitized response. timeline.json and the sealed live-final.sqlite enumerate the same commands with correlated journal events. No command was retried.

| Stage | UTC | Operation | Native route/status | Host ms | Rows / coins |
|---|---|---|---|---:|---|
| balance-before | 2026-11-13T03:04:08.254Z | balance | /ut/game/fc27/user/credits / 200 | 169.388 | 16268 |
| watched-before | 2026-11-13T03:04:08.874Z | watched | /ut/game/fc27/watchlist / 200 | 160.272 | 0 rows |
| search-1 | 2026-11-13T03:04:09.654Z | search | /ut/game/fc27/transfermarket / 200 | 305.721 | 21 rows |
| comparables-1 | 2026-11-13T03:04:22.539Z | search | /ut/game/fc27/transfermarket / 200 | 172.733 | 21 rows |
| caps-1 | 2026-11-13T03:04:23.169Z | caps | /ut/game/fc27/marketdata/pricelimits / 200 | 144.845 | 0 rows |
| availability-1 | 2026-11-13T03:04:23.930Z | search | /ut/game/fc27/transfermarket / 200 | 282.624 | 10 rows |
| balance-prebid | 2026-11-13T03:04:24.527Z | balance | /ut/game/fc27/user/credits / 200 | 126.129 | 16268 |
| opening-1 | 2026-11-13T03:04:38.928Z | bid | /ut/game/fc27/trade/:trade/bid / 200 | 213.566 | 0 rows |
| watched-after-opening | 2026-11-13T03:04:39.615Z | watched | /ut/game/fc27/watchlist / 200 | 131.695 | 0 rows |
| balance-after-opening | 2026-11-13T03:04:40.260Z | balance | /ut/game/fc27/user/credits / 200 | 112.223 | 16268 |
| availability-after-opening | 2026-11-13T03:05:10.366Z | search | /ut/game/fc27/transfermarket / 200 | 263.910 | 10 rows |
| watched-reconcile | 2026-11-13T03:05:11.033Z | watched | /ut/game/fc27/watchlist / 200 | 94.015 | 0 rows |
| unassigned-after-opening | 2026-11-13T03:05:50.385Z | unassigned | /ut/game/fc27/purchased/items / 200 | 176.186 | 0 rows |
| transfer-list-reconcile | 2026-11-13T03:06:25.627Z | transfer_list | /ut/game/fc27/tradepile / 200 | 165.312 | 8 rows |
| search-after-expiry | 2026-11-13T03:07:20.207Z | search | /ut/game/fc27/transfermarket / 200 | 219.671 | 9 rows |
| watched-after-expiry | 2026-11-13T03:07:20.772Z | watched | /ut/game/fc27/watchlist / 200 | 119.829 | 0 rows |
| unassigned-after-expiry | 2026-11-13T03:07:21.340Z | unassigned | /ut/game/fc27/purchased/items / 200 | 106.347 | 0 rows |
| balance-final | 2026-11-13T03:07:21.936Z | balance | /ut/game/fc27/user/credits / 200 | 118.856 | 16268 |

## Exact continuation and reproduction

First use a **separately recorded read-only reconciliation window**, at most four commands / 120 seconds / zero mutations. Review a current native independent exact-trade status method before using it; obtain that status plus fresh watched, exact-owned and balance evidence for the original command. Do not guess an endpoint or reinterpret empty coverage as a terminal loss. Preserve UNKNOWN if a supported independent method cannot resolve it. Never replay the original 700 PUT.

Only after original mutation reconciliation, a separate explicitly recorded live window can attempt the missing leading opening/HOLD proof: one auction, 900 seconds, 40 reads, two bid writes, four total mutations, gross 2,000, bid ceiling 1,000 and reserve 5,000. Recompute all pricing and native caps. Immediately obtain watched and balance readbacks after an opening. Journal a genuine leading HOLD with unchanged write count. Observe genuine outbid/expiry; one conditional rebid must use the minimum amount and stored cap. If conclusively won, verify exact physical ownership and paid cost before move/list and their readbacks. Every unwitnessed conditional branch remains live-UNVERIFIED. This is a continuation requirement, not authorization to reset or restart this consumed run.

Offline reproduction:

```text
python tests/test_e2e_v1.py
python tests/test_e2e_artifacts.py
python tests/check_e2e_v1_acceptance.py
```

The first checks validate fixture behavior and integrity/truthfulness of retained live evidence. The acceptance command independently rederives all eight criteria and **exits 1**, identifying missing successful Acquirer readback (criterion 1) and live leading HOLD (criterion 2), using zero-based indices. It must not report success merely because an accurate unresolved report exists. Tests never attach a browser or consume any remaining account budget. Exact validation outputs are retained in checks.json.
