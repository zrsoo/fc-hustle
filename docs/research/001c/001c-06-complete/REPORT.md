# 001c-06 bounded E2E completion and account reconciliation

**Bounded task complete. Objective 002 remains CONDITIONAL GO, not FULL GO.** The genuine minimum ordinary entry, authoritative leading/balance readbacks, already-leading HOLD, eventual LOST and available-coin return are now demonstrated. Active outbid/rebid, timer extension, a live 25-second whole-queue cycle, WON-item movement/listing and sale/profit remain live-UNVERIFIED. No unobserved branch is promoted by fixture tests.

## Actual account result

The account started with **16,268**, fell to **15,468** after one independently verified **800** bid, and returned to **16,268** following an independently verified loss. Net available-coin change and actual acquisition cost are **0**. No new owned or unsold card was created; no move, listing, sale or realized profit is claimed. There are no unresolved active bids. One expired outbid Transfer Target remains in place; it was not removed because no cleanup mutation was part of this test.

Two actual bid commands were sent across distinct preserved windows: the original 700 command and the successful 800 entry. Gross journal reservations total **1,500**, not 1,500 spent. The first command's historical acceptance remains unverified; its separate exact terminal-status reconciliation established no remaining exposure/acquisition. The 800 held amount is inferred from matching leading status and available-coin debit. An independent direct held-balance field was not available. The later 800 available-coin recovery plus terminal LOST supports the return; the exact transient escrow/refund time during the outage was not observed.

## Window boundaries and interruption

| Window | Native requests | Mutations | Outcome / limits |
|---|---:|---:|---|
| Original 001c-06 | 18 | 1 | 700 PUT ACK unresolved; closed on missing independent watched state. |
| Resume 01 | 4 | 0 | Four reads / 120 seconds; original trade independently closed/non-leading at 800, no acquired item, balance 16,268. |
| Resume 02 | 18 | 1 | Separate 900-second, 40-read window; one auction, up to two bids/four mutations, gross 2,000, per-bid ceiling 1,000 and reserve 5,000. Actual: 17 reads and one 800 bid. |
| Resume 03 | 4 | 0 | Four reads / 120 seconds after the outage; exact terminal status, full-version watched state, unassigned and balance. |

All 44 native requests were individually correlated to their durable ledgers and captures. Browser input and account operations were serialized. Immutable command/stage IDs prevent replay. Full synchronous SQLite reservations precede delivery; no delivered command is redelivered. Native request counts are scoped to these explicit experiment commands, not an assertion that the Web App had no unrelated background reads.

AGENTS.md was reread before recovery. Each worker established its own verified Edge/window/official-tab control. Normal attachment, public uppercase PC persona validation, presence-only authentication telemetry and native service success are separate fields. No sign-in credential or authentication/session value was exported. The localhost services and isolated reviewed extension paths were distinct; old consumed windows were not reset.

Resume 02 had a real pre-write server restart while all three prior reads were acknowledged. The process fence changed, while its original wall deadline and three charged reads remained unchanged. Policy was adapted to allow minimum first participation above an existing other-party bid; this is an ordinary entry, not a personal rebid. The page helper was also corrected: UTCurrencyInputControl.getIncrementAboveVal returns the next price, so adding currentBid again was wrong. The new JavaScript fixture uses the native helper's absolute-price semantics and captures the actual numeric request body. Old sealed sources and evidence were preserved.

The supervisor then stopped on a usage/quota interruption after watched-cycle-3 and a 25-second sleep. No planned watched-cycle-4 command exists, and it was not replayed on recovery. The process was absent and the 900-second window had expired. Recovery sealed the existing ledger without dispatching any new native operation in that expired window. Terminal observation used the separately recorded read-only Resume 03; unused mutation allowance and the original deadline were never reset.

## Real Acquirer, leading HOLD and economics

The exact PC FC27 version **261855**, trade `trade:d59ab1cf05df393676e66e4e`, physical item `item:c4a01aa3ed2e3986921c209e`, was discovered using native `maxBid=1000` / `minBuy=10500` (wire `macr=1000` / `minb=10500`). A different 256630 candidate disappeared from a fresh filtered availability read; its empty result is retained and no bid was sent on it.

For the selected auction, 12 independent exact-version comparable BIN asks remained after robust rejection of nine outliers. Fresh native card caps and the observed client ticks supported a conservative target **2,800**, projected tax **140**, X=500 and a downward-rounded profitable cap **2,100**. The experiment separately limited any bid to **1,000**. The existing current bid was **750**, so the minimum first-participation amount was **800**. Projected profit at 800 was **1,860**, conditional on a future sale at the estimated target; it was not realized profit. The nested estimator acquisition_price 10,500 / expected_profit -7,840 describes a hypothetical BIN reference, not an actual payment.

At **2026-11-13T03:28:00.868Z**, services.Item.bid(item,800) emitted a genuine ordinary PUT. The sanitized request-body projection retained only bid=800. HTTP/native 200 was followed by separate fresh authenticated watched and balance GETs: exact trade/item/version active/highest at 800, and spendable 15,468. The journal moved that one command to RECONCILED only after these independent readbacks.

Two HOLD decisions use fresh active/highest watched states. Both retain journal reasons, read IDs, unchanged before/after command and exposure counters, and exactly one actual bid PUT in Resume 02. Three additional watched snapshots continued to show highest at 800. No additional bid was sent merely because the profitable cap allowed more.

## Competition, timing and terminal classification

The original experiment witnessed a current-price advance from 0 to 750; the successful entry joined an auction already at 750. Post-interruption, independent exact-trade and full-version watched responses both show **closed/outbid at 1,200, expiry -1**, matching the exact physical item. This proves a genuine eventual **LOST**, not missing coverage interpreted as loss. Lite status returned definition ID 0, so version was supplied by the independent full-version watched row (261855), not invented from the lite payload. No authoritative active-outbid transition was captured before the outage; the live conditional rebid path remains UNVERIFIED and no rebid was sent.

Resume 02 native watched durations (including the initial empty read): 76.000 ms, 93.800 ms, 91.800 ms, 106.600 ms, 97.600 ms. Each refresh used one native bulk GET. The bid took 343.700 ms native, 377.398 ms host round trip and 4.393 ms from durable claim to request start. The first independent watched response completed 158.000 ms after the PUT response. Actual successive active-refresh start intervals were 58.326, 48.736, 41.391 seconds; these manual samples do not establish a 25-second cadence. The requested 25-second sample was interrupted.

Pre/post ordinary-bid expiry snapshots (1,037 then 1,036 seconds) and subsequent leading countdowns (978, 929, 888), together with terminal expiry -1, are retained with request timestamps. No near-expiry timer reset was witnessed. Small live watchlists plus fixture processing of 50 rows cannot establish a 25-second whole-queue live guarantee.

No WON state was observed. Consequently no physical-item move/list was authorized or sent. Offline tests exercise conclusive ownership, independent read IDs, exact paid cost, native WON flag, legal listing prices and duplicate/pending-write rejection; those tests do not upgrade live WON/listing support. No sale or profit is inferred.

## Chronological evidence and verification

`timeline.json` contains all **44** correlated commands in order, with canonical standalone argv, parameters where applicable, sanitized network routes/statuses/body bid amount, timestamps and durations. Some invocations were coordinated via Python stdin calling capture.main sequentially; standalone argv in captures are canonical reproductions rather than claims about a different literal shell process. HOLD and reconcile decision artifacts retain actual stdin argv and exact local RPC parameters. Ledgers retain reservation, delivery, result, independent reconciliation and HOLD events.

The original report, manifest and closed SQLite bytes remain intact. In particular, `tests/check_e2e_v1_acceptance.py` still exits 1 for that historical window's missing opening/HOLD; its result was not rewritten or suppressed. The independent current aggregate validator is `tests/validate_001c06_complete.py`, which checks all eight criteria using the supplemental live evidence and emits remaining live-UNVERIFIED branches. `checks.json` records exact current test argv, exit codes and outputs.

```text
python tests/test_e2e_live_v2.py
python tests/test_e2e_reconcile_v1.py
python tests/test_e2e_complete_artifacts.py
python tests/validate_001c06_complete.py
```

All validators run offline and independently from the workspace. The evidence audit detects changed request amounts, false leading readbacks even when both capture and SQLite result are changed, fabricated terminal wins, missing coverage, duplicate commands, rewritten bounds and changed sealed content.

## Exact bounded continuation for unobserved branches

No continuation is required for the lost auction: current exposure and paid acquisition cost are zero. Leave the expired Transfer Target untouched unless cleanup is separately authorized. Never replay either historic PUT or reopen a consumed window.

An additional separately recorded test would be needed for remaining live capabilities: **one auction, at most 900 seconds, 40 reads, two bid writes, four mutations total, gross exposure 2,000, per-bid ceiling 1,000 and reserve 5,000**. Choose a fresh eligible auction whose expected expiry fits the remaining window. Recompute five-plus exact-PC comparables and native caps. Only after an authoritative active outbid, obtain fresh eligibility/balance/economics and send the minimum next price within the stored cap. Use natural late traffic for pre/post expiry observation. If conclusively WON, obtain independent exact physical ownership and actual paid-cost proof before reserving one move and one legal listing, each with fresh readback. Stop on ambiguity, access challenge or exhausted limits; unwitnessed conditional events remain UNVERIFIED.

This continuation specification is not a command to launch another auction, an actor loop, a synthetic opponent or an automatic relisting campaign.
