# Objective 001C independent E2E report

Audit timestamp: **2026-11-13T06:19:39.871380+00:00**. Decision: **CONDITIONAL GO**; actor execution remains gated.
This is a read-only audit of retained 2026-11-13 observations. It makes no claim about the account at audit time.
The [independent validator](../../fc_access/release_audit_v1.py) reads captures and immutable SQLite directly, without importing prior audit or execution code.
The [claims record](001c/001c-07/release.json) and [task-entry preservation map](001c/001c-07/entry.json) are versioned.

Four separately bounded windows contain **44 native requests, 42 reads and two bid PUT attempts**.
Original: 18 commands / one 700 request. Resume 01: four reads / 120 seconds. Resume 02: 18 commands / one 800 request,
900 seconds, 40-read ceiling, two-bid/four-mutation ceilings, gross 2000, individual 1000 and reserve 5000.
Resume 03: four reads / 120 seconds. Every window is closed. No deadline or consumed budget was reset.
These are explicit command counts; unrelated Web App background traffic is outside the instrumentation scope.

The original 700 command (`6371060d0cef5803cffa1797eddc6264`) concerned
`trade:83105610f7508574b2e36139`, `item:178f6a3fd2bc1c19690e3ffe`, version 261855.
Its PUT returned HTTP/native 200 but the request body amount and independent leading readback were not retained.
Historical acceptance remains **UNVERIFIED**; it is not counted as a verified enrolled loss.
Separate exact terminal status later showed closed/non-leading, no acquired item and spendable 16268.
The [original failed checkpoint](001c/001c-06/report.json) remains unchanged.

The successful minimum first participation was on **trade:d59ab1cf05df393676e66e4e**,
physical **item:c4a01aa3ed2e3986921c209e**, exact PC version **261855**.
Fresh maxBid=1000/minBuy=10500 search, independent wire rows, native caps and >=5 exact-version comparables preceded entry.
12 asks survived nine outlier exclusions: target 2800, projected tax 140, X=500, downward-rounded cap 2100.
The test separately limited bids to 1000. Existing current bid 750 required minimum **800**, not a jump to the cap.
At 2026-11-13T03:28:00.868Z, command `edf54a0285e16ea5ad508fa594721711` sent native `services.Item.bid(item,800)`.
The wire allowlist retained numeric bid=800, HTTP/native 200, native 343.700 ms and host 377.398 ms.
Separate post-ACK GETs proved active/highest at 800 and spendable 15468; the journal then reconciled the command.
Two fresh leading HOLD decisions reserved no further native commands or exposure; exactly one bid write occurred in Resume 02.
The estimator's nested acquisition_price=10500/expected_profit=-7840 is a hypothetical BIN reference, not payment.
Projected profit at 800 was 1860 before a possible sale; no sale was observed.

Account accounting at the last retained independent readbacks:

| Asset / exposure | Before | After verified entry | After separate terminal reconciliation |
|---|---:|---:|---:|
| Spendable coins | 16268 | 15468 | 16268 |
| Held amount inferred from leading/debit | unknown for original attempt | 800 | 0 |
| Actual paid competitive acquisition cost | 0 | unresolved pending outcome | 0 |
| New owned / unsold test cards | 0 | 0 confirmed | 0 |
| Active unresolved bids | original acceptance unknown | one confirmed | 0 |

Gross reservations **1500** are 700+800 across separate windows, not 1500 spent.
The 800 available-coin recovery and exact terminal LOST support returned funds; direct held balance and transient refund time were not exposed.
No WON item, move/list write, completed sale, sale proceeds or realized profit is claimed. One expired outbid Transfer Target remains untouched.
The terminal price **1200** and closed/outbid status agree in independent lite and full watched responses.
Lite definition_id=0 is an omitted version; only the full watched row supplies 261855.
A missing auction never becomes LOST solely by absence.

Native watched durations in Resume 02: 76.000, 93.800, 91.800, 106.600, 97.600 ms.
Active refresh start intervals: 58.326, 48.736, 41.391 seconds.
These manual samples do not establish a 25-second cycle. The requested sample was interrupted; no catch-up command was replayed.
Expiry snapshots before/after entry were 1037/1036, then 978/929/888 and terminal -1.
Active outbid/rebid, timer extension, live 25-second whole-queue monitoring, competitive WON transfer/list and sale/profit remain **live-UNVERIFIED**.
The terminal observation occurred after the outage in Resume 03, not inside the expired Resume 02 window.

The complete sanitized commands below are canonical standalone argv recorded by the captures. Some actual invocations were Python stdin
calling capture.main sequentially; these argv are reproductions, not a claim about the literal shell parent process.
They are historical provenance: do not replay mutations or reopen any consumed window. Local decision RPCs are documented below.
Each row includes UTC network start/end, HTTP/native status, host/native duration, ledger state, actual observed result and capture link.
The full [machine timeline](001c/001c-07/commands.json) also retains native request parameters and wire/entity rows.

| Window / stage / command | UTC start -> end | Status / host ms / native ms | Ledger state and actual result | Exact sanitized argv / capture |
|---|---|---|---|---|
| 001c-06/balance-before `a769b30ea2445cda3f5e6a13c5d31856` | 2026-11-13T03:04:08.127Z -> 2026-11-13T03:04:08.250Z | 200/200 / 169.388 / 123.100 | ACKNOWLEDGED; spendable=16268 | `["{python}","-m","fc_access.e2e_v1.capture","balance-before","balance","{}"]` [docs/research/001c/001c-06/balance-before.json](001c/001c-06/balance-before.json) |
| 001c-06/watched-before `45512e015c10b379cdd9434fa8e32e49` | 2026-11-13T03:04:08.748Z -> 2026-11-13T03:04:08.873Z | 200/200 / 160.272 / 124.800 | ACKNOWLEDGED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","watched-before","watched","{}"]` [docs/research/001c/001c-06/watched-before.json](001c/001c-06/watched-before.json) |
| 001c-06/search-1 `aca66d20808fb01c399939d5cc5fccd7` | 2026-11-13T03:04:09.403Z -> 2026-11-13T03:04:09.649Z | 200/200 / 305.721 / 246.100 | ACKNOWLEDGED; rows=21; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","search-1","search","{\"max_bid\": 1000, \"min_buy\": 10500, \"page\": 1, \"count\": 21}"]` [docs/research/001c/001c-06/search-1.json](001c/001c-06/search-1.json) |
| 001c-06/comparables-1 `985583b239837ab25c53450f4d7c2fe6` | 2026-11-13T03:04:22.402Z -> 2026-11-13T03:04:22.537Z | 200/200 / 172.733 / 135.200 | ACKNOWLEDGED; rows=21; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","comparables-1","search","{\"definition_id\": 261855, \"page\": 1, \"count\": 21}"]` [docs/research/001c/001c-06/comparables-1.json](001c/001c-06/comparables-1.json) |
| 001c-06/caps-1 `30262517c77d7a1d74e3125470a2ab70` | 2026-11-13T03:04:23.065Z -> 2026-11-13T03:04:23.169Z | 200/200 / 144.845 / 104.100 | ACKNOWLEDGED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","caps-1","caps","{\"definition_id\": 261855}"]` [docs/research/001c/001c-06/caps-1.json](001c/001c-06/caps-1.json) |
| 001c-06/availability-1 `79141d02e01838c6fcc520bae94f3f34` | 2026-11-13T03:04:23.698Z -> 2026-11-13T03:04:23.927Z | 200/200 / 282.624 / 228.900 | ACKNOWLEDGED; rows=10; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","availability-1","search","{\"definition_id\": 261855, \"max_bid\": 1000, \"min_buy\": 10500, \"page\": 1, \"count\": 21}"]` [docs/research/001c/001c-06/availability-1.json](001c/001c-06/availability-1.json) |
| 001c-06/balance-prebid `f9b8d3f5c4fe1a16d495f26b83efec12` | 2026-11-13T03:04:24.455Z -> 2026-11-13T03:04:24.525Z | 200/200 / 126.129 / 69.900 | ACKNOWLEDGED; spendable=16268 | `["{python}","-m","fc_access.e2e_v1.capture","balance-prebid","balance","{}"]` [docs/research/001c/001c-06/balance-prebid.json](001c/001c-06/balance-prebid.json) |
| 001c-06/opening-1 `6371060d0cef5803cffa1797eddc6264` | 2026-11-13T03:04:38.756Z -> 2026-11-13T03:04:38.927Z | 200/200 / 213.566 / 170.300 | ACKNOWLEDGED; requested=700; ACK only (readbacks required) | `["{python}","-m","fc_access.e2e_v1.capture","opening-1","bid","{\"trade_id\": \"trade:83105610f7508574b2e36139\", \"item_id\": \"item:178f6a3fd2bc1c19690e3ffe\", \"definition_id\": 261855, \"amount\": 700, \"status_operation\": \"search\", \"status_id\": \"79141d02e01838c6fcc520bae94f3f34\", \"balance_id\": \"f9b8d3f5c4fe1a16d495f26b83efec12\", \"caps_id\": \"30262517c77d7a1d74e3125470a2ab70\", \"comparables_id\": \"985583b239837ab25c53450f4d7c2fe6\"}"]` [docs/research/001c/001c-06/opening-1.json](001c/001c-06/opening-1.json) |
| 001c-06/watched-after-opening `6ab892eaefee64471f6f819f9d1d54bf` | 2026-11-13T03:04:39.543Z -> 2026-11-13T03:04:39.614Z | 200/200 / 131.695 / 71.700 | ACKNOWLEDGED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","watched-after-opening","watched","{}"]` [docs/research/001c/001c-06/watched-after-opening.json](001c/001c-06/watched-after-opening.json) |
| 001c-06/balance-after-opening `cc28531071d4e8054a09a7daa540e0ed` | 2026-11-13T03:04:40.181Z -> 2026-11-13T03:04:40.255Z | 200/200 / 112.223 / 73.600 | ACKNOWLEDGED; spendable=16268 | `["{python}","-m","fc_access.e2e_v1.capture","balance-after-opening","balance","{}"]` [docs/research/001c/001c-06/balance-after-opening.json](001c/001c-06/balance-after-opening.json) |
| 001c-06/availability-after-opening `672cc3ba9fbf6218043905f849f2c142` | 2026-11-13T03:05:10.154Z -> 2026-11-13T03:05:10.365Z | 200/200 / 263.910 / 210.600 | ACKNOWLEDGED; rows=10; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","availability-after-opening","search","{\"definition_id\": 261855, \"max_bid\": 1000, \"min_buy\": 10500, \"page\": 1, \"count\": 21}"]` [docs/research/001c/001c-06/availability-after-opening.json](001c/001c-06/availability-after-opening.json) |
| 001c-06/watched-reconcile `199849c88acb70645f63cc6b267dd65f` | 2026-11-13T03:05:10.958Z -> 2026-11-13T03:05:11.033Z | 200/200 / 94.015 / 74.700 | ACKNOWLEDGED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","watched-reconcile","watched","{}"]` [docs/research/001c/001c-06/watched-reconcile.json](001c/001c-06/watched-reconcile.json) |
| 001c-06/unassigned-after-opening `e6617073c0fccd6cd35597c4fec52bc8` | 2026-11-13T03:05:50.264Z -> 2026-11-13T03:05:50.384Z | 200/200 / 176.186 / 120.300 | ACKNOWLEDGED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","unassigned-after-opening","unassigned","{}"]` [docs/research/001c/001c-06/unassigned-after-opening.json](001c/001c-06/unassigned-after-opening.json) |
| 001c-06/transfer-list-reconcile `751cfd425d40b5073e3896c0bb113ffd` | 2026-11-13T03:06:25.518Z -> 2026-11-13T03:06:25.623Z | 200/200 / 165.312 / 105.900 | ACKNOWLEDGED; rows=8; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","transfer-list-reconcile","transfer_list","{}"]` [docs/research/001c/001c-06/transfer-list-reconcile.json](001c/001c-06/transfer-list-reconcile.json) |
| 001c-06/search-after-expiry `89a330f0a7aa92d1598638cdf88492a3` | 2026-11-13T03:07:20.016Z -> 2026-11-13T03:07:20.204Z | 200/200 / 219.671 / 187.800 | ACKNOWLEDGED; rows=9; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","search-after-expiry","search","{\"definition_id\": 261855, \"max_bid\": 1000, \"min_buy\": 10500, \"page\": 1, \"count\": 21}"]` [docs/research/001c/001c-06/search-after-expiry.json](001c/001c-06/search-after-expiry.json) |
| 001c-06/watched-after-expiry `7dfd2f881e09ec4e3ce14eb37979dd92` | 2026-11-13T03:07:20.699Z -> 2026-11-13T03:07:20.772Z | 200/200 / 119.829 / 72.600 | ACKNOWLEDGED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","watched-after-expiry","watched","{}"]` [docs/research/001c/001c-06/watched-after-expiry.json](001c/001c-06/watched-after-expiry.json) |
| 001c-06/unassigned-after-expiry `8d794a65116b5d5e8613f961514cbc51` | 2026-11-13T03:07:21.275Z -> 2026-11-13T03:07:21.340Z | 200/200 / 106.347 / 65.600 | ACKNOWLEDGED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_v1.capture","unassigned-after-expiry","unassigned","{}"]` [docs/research/001c/001c-06/unassigned-after-expiry.json](001c/001c-06/unassigned-after-expiry.json) |
| 001c-06/balance-final `22945ae1e8505481aed369908657d4cc` | 2026-11-13T03:07:21.864Z -> 2026-11-13T03:07:21.934Z | 200/200 / 118.856 / 70.400 | ACKNOWLEDGED; spendable=16268 | `["{python}","-m","fc_access.e2e_v1.capture","balance-final","balance","{}"]` [docs/research/001c/001c-06/balance-final.json](001c/001c-06/balance-final.json) |
| 001c-06-resume-01/status `0c37de34c35cc2b90cede140d6ac93f4` | 2026-11-13T03:21:46.468Z -> 2026-11-13T03:21:46.580Z | 200/200 / 192.693 / 112.200 | OBSERVED; trade_id=trade:83105610f7508574b2e36139; item_id=item:178f6a3fd2bc1c19690e3ffe; definition_id=0; current_bid=800; bid_state=none; trade_state=closed; expires=-1 | `["{python}","-m","fc_access.e2e_reconcile_v1.capture","status"]` [docs/research/001c/001c-06-resume-01/status.json](001c/001c-06-resume-01/status.json) |
| 001c-06-resume-01/watched `3da6836109515620726f58592f0a18a2` | 2026-11-13T03:21:47.129Z -> 2026-11-13T03:21:47.248Z | 200/200 / 166.038 / 119.200 | OBSERVED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_reconcile_v1.capture","watched"]` [docs/research/001c/001c-06-resume-01/watched.json](001c/001c-06-resume-01/watched.json) |
| 001c-06-resume-01/unassigned `2fa490da2a1844462f732b060d377779` | 2026-11-13T03:21:47.756Z -> 2026-11-13T03:21:47.869Z | 200/200 / 154.099 / 113.700 | OBSERVED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_reconcile_v1.capture","unassigned"]` [docs/research/001c/001c-06-resume-01/unassigned.json](001c/001c-06-resume-01/unassigned.json) |
| 001c-06-resume-01/balance `59f27c9d0f91392b514f4b34ea913748` | 2026-11-13T03:21:48.358Z -> 2026-11-13T03:21:48.476Z | 200/200 / 148.812 / 118.500 | OBSERVED; spendable=16268 | `["{python}","-m","fc_access.e2e_reconcile_v1.capture","balance"]` [docs/research/001c/001c-06-resume-01/balance.json](001c/001c-06-resume-01/balance.json) |
| 001c-06-resume-02/balance-before `7d3553550abbffcbe290c26528338e2a` | 2026-11-13T03:25:34.851Z -> 2026-11-13T03:25:34.922Z | 200/200 / 124.695 / 71.300 | ACKNOWLEDGED; spendable=16268 | `["{python}","-m","fc_access.e2e_live_v2.capture","balance-before","balance","{}"]` [docs/research/001c/001c-06-resume-02/balance-before.json](001c/001c-06-resume-02/balance-before.json) |
| 001c-06-resume-02/watched-before `51f3c6749bd1ffc72ad4f762b5297cea` | 2026-11-13T03:25:35.437Z -> 2026-11-13T03:25:35.513Z | 200/200 / 125.545 / 76.000 | ACKNOWLEDGED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_live_v2.capture","watched-before","watched","{}"]` [docs/research/001c/001c-06-resume-02/watched-before.json](001c/001c-06-resume-02/watched-before.json) |
| 001c-06-resume-02/search-1 `dc1961e73bedaef09ebf4662faa4ef9d` | 2026-11-13T03:25:36.050Z -> 2026-11-13T03:25:36.311Z | 200/200 / 300.535 / 260.500 | ACKNOWLEDGED; rows=21; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_live_v2.capture","search-1","search","{\"max_bid\": 1000, \"min_buy\": 10500, \"page\": 1, \"count\": 21}"]` [docs/research/001c/001c-06-resume-02/search-1.json](001c/001c-06-resume-02/search-1.json) |
| 001c-06-resume-02/comparables-1 `3471bfa73b67ac65bf905751cf70f092` | 2026-11-13T03:27:15.466Z -> 2026-11-13T03:27:15.600Z | 200/200 / 195.756 / 133.900 | ACKNOWLEDGED; rows=21; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_live_v2.capture","comparables-1","search","{\"definition_id\": 256630, \"page\": 1, \"count\": 21}"]` [docs/research/001c/001c-06-resume-02/comparables-1.json](001c/001c-06-resume-02/comparables-1.json) |
| 001c-06-resume-02/caps-1 `6c2e90a3e5c50a91a24817d2f020ed15` | 2026-11-13T03:27:16.234Z -> 2026-11-13T03:27:16.339Z | 200/200 / 140.252 / 105.000 | ACKNOWLEDGED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_live_v2.capture","caps-1","caps","{\"definition_id\": 256630}"]` [docs/research/001c/001c-06-resume-02/caps-1.json](001c/001c-06-resume-02/caps-1.json) |
| 001c-06-resume-02/balance-prebid `43abd29ed69c413e7fe9fbd80bd332ee` | 2026-11-13T03:27:16.865Z -> 2026-11-13T03:27:16.934Z | 200/200 / 99.928 / 69.100 | ACKNOWLEDGED; spendable=16268 | `["{python}","-m","fc_access.e2e_live_v2.capture","balance-prebid","balance","{}"]` [docs/research/001c/001c-06-resume-02/balance-prebid.json](001c/001c-06-resume-02/balance-prebid.json) |
| 001c-06-resume-02/availability-1 `4ea831b11fd36c7a672e51dd0b6df14b` | 2026-11-13T03:27:16.997Z -> 2026-11-13T03:27:17.213Z | 200/200 / 248.867 / 215.900 | ACKNOWLEDGED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_live_v2.capture","availability-1","search","{\"definition_id\": 256630, \"max_bid\": 1000, \"min_buy\": 10500, \"page\": 1, \"count\": 21}"]` [docs/research/001c/001c-06-resume-02/availability-1.json](001c/001c-06-resume-02/availability-1.json) |
| 001c-06-resume-02/search-2 `e8cc667219af458dddaaa466881ac00e` | 2026-11-13T03:27:40.782Z -> 2026-11-13T03:27:41.011Z | 200/200 / 287.268 / 229.700 | ACKNOWLEDGED; rows=21; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_live_v2.capture","search-2","search","{\"max_bid\": 1000, \"min_buy\": 10500, \"page\": 1, \"count\": 21}"]` [docs/research/001c/001c-06-resume-02/search-2.json](001c/001c-06-resume-02/search-2.json) |
| 001c-06-resume-02/comparables-2 `97bc6cbda3a6bba4f2ac81f48cc6b683` | 2026-11-13T03:27:58.997Z -> 2026-11-13T03:27:59.129Z | 200/200 / 176.207 / 131.500 | ACKNOWLEDGED; rows=21; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_live_v2.capture","comparables-2","search","{\"definition_id\": 261855, \"page\": 1, \"count\": 21}"]` [docs/research/001c/001c-06-resume-02/comparables-2.json](001c/001c-06-resume-02/comparables-2.json) |
| 001c-06-resume-02/caps-2 `800d43d9931c296330bb7f877d9fd8d1` | 2026-11-13T03:27:59.760Z -> 2026-11-13T03:27:59.865Z | 200/200 / 149.588 / 104.600 | ACKNOWLEDGED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_live_v2.capture","caps-2","caps","{\"definition_id\": 261855}"]` [docs/research/001c/001c-06-resume-02/caps-2.json](001c/001c-06-resume-02/caps-2.json) |
| 001c-06-resume-02/balance-prebid-2 `8ed1ab9e0b2b5ad2c8659a622ad5da36` | 2026-11-13T03:28:00.386Z -> 2026-11-13T03:28:00.454Z | 200/200 / 107.291 / 68.400 | ACKNOWLEDGED; spendable=16268 | `["{python}","-m","fc_access.e2e_live_v2.capture","balance-prebid-2","balance","{}"]` [docs/research/001c/001c-06-resume-02/balance-prebid-2.json](001c/001c-06-resume-02/balance-prebid-2.json) |
| 001c-06-resume-02/availability-2 `043b0e613082aa3ad1ab409f222b56e4` | 2026-11-13T03:28:00.513Z -> 2026-11-13T03:28:00.745Z | 200/200 / 299.189 / 233.000 | ACKNOWLEDGED; rows=8; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_live_v2.capture","availability-2","search","{\"definition_id\": 261855, \"max_bid\": 1000, \"min_buy\": 10500, \"page\": 1, \"count\": 21}"]` [docs/research/001c/001c-06-resume-02/availability-2.json](001c/001c-06-resume-02/availability-2.json) |
| 001c-06-resume-02/opening-1 `edf54a0285e16ea5ad508fa594721711` | 2026-11-13T03:28:00.868Z -> 2026-11-13T03:28:01.212Z | 200/200 / 377.398 / 343.700 | RECONCILED; requested=800; ACK only (readbacks required) | `["{python}","-m","fc_access.e2e_live_v2.capture","opening-1","bid","{\"trade_id\": \"trade:d59ab1cf05df393676e66e4e\", \"item_id\": \"item:c4a01aa3ed2e3986921c209e\", \"definition_id\": 261855, \"amount\": 800, \"status_operation\": \"search\", \"status_id\": \"043b0e613082aa3ad1ab409f222b56e4\", \"balance_id\": \"8ed1ab9e0b2b5ad2c8659a622ad5da36\", \"caps_id\": \"800d43d9931c296330bb7f877d9fd8d1\", \"comparables_id\": \"97bc6cbda3a6bba4f2ac81f48cc6b683\"}"]` [docs/research/001c/001c-06-resume-02/opening-1.json](001c/001c-06-resume-02/opening-1.json) |
| 001c-06-resume-02/watched-after-opening `1a248702fa0785e597781e65d089e79b` | 2026-11-13T03:28:01.276Z -> 2026-11-13T03:28:01.370Z | 200/200 / 121.843 / 93.800 | ACKNOWLEDGED; trade_id=trade:d59ab1cf05df393676e66e4e; item_id=item:c4a01aa3ed2e3986921c209e; definition_id=261855; current_bid=800; bid_state=highest; trade_state=active; expires=1036 | `["{python}","-m","fc_access.e2e_live_v2.capture","watched-after-opening","watched","{}"]` [docs/research/001c/001c-06-resume-02/watched-after-opening.json](001c/001c-06-resume-02/watched-after-opening.json) |
| 001c-06-resume-02/balance-after-opening `f2a8cebd83e7aa510f27c364f81598b8` | 2026-11-13T03:28:01.422Z -> 2026-11-13T03:28:01.492Z | 200/200 / 113.244 / 69.200 | ACKNOWLEDGED; spendable=15468 | `["{python}","-m","fc_access.e2e_live_v2.capture","balance-after-opening","balance","{}"]` [docs/research/001c/001c-06-resume-02/balance-after-opening.json](001c/001c-06-resume-02/balance-after-opening.json) |
| 001c-06-resume-02/watched-cycle-1 `f35fe530f1b3348552710c5fd9c0ca5f` | 2026-11-13T03:28:59.602Z -> 2026-11-13T03:28:59.694Z | 200/200 / 123.090 / 91.800 | ACKNOWLEDGED; trade_id=trade:d59ab1cf05df393676e66e4e; item_id=item:c4a01aa3ed2e3986921c209e; definition_id=261855; current_bid=800; bid_state=highest; trade_state=active; expires=978 | `["{python}","-m","fc_access.e2e_live_v2.capture","watched-cycle-1","watched","{}"]` [docs/research/001c/001c-06-resume-02/watched-cycle-1.json](001c/001c-06-resume-02/watched-cycle-1.json) |
| 001c-06-resume-02/watched-cycle-2 `01491141cdd83794a814cdcae72239ee` | 2026-11-13T03:29:48.338Z -> 2026-11-13T03:29:48.445Z | 200/200 / 162.888 / 106.600 | ACKNOWLEDGED; trade_id=trade:d59ab1cf05df393676e66e4e; item_id=item:c4a01aa3ed2e3986921c209e; definition_id=261855; current_bid=800; bid_state=highest; trade_state=active; expires=929 | `["{python}","-m","fc_access.e2e_live_v2.capture","watched-cycle-2","watched","{}"]` [docs/research/001c/001c-06-resume-02/watched-cycle-2.json](001c/001c-06-resume-02/watched-cycle-2.json) |
| 001c-06-resume-02/watched-cycle-3 `aec34da45b7f07889fc10227220352ee` | 2026-11-13T03:30:29.729Z -> 2026-11-13T03:30:29.826Z | 200/200 / 128.994 / 97.600 | ACKNOWLEDGED; trade_id=trade:d59ab1cf05df393676e66e4e; item_id=item:c4a01aa3ed2e3986921c209e; definition_id=261855; current_bid=800; bid_state=highest; trade_state=active; expires=888 | `["{python}","-m","fc_access.e2e_live_v2.capture","watched-cycle-3","watched","{}"]` [docs/research/001c/001c-06-resume-02/watched-cycle-3.json](001c/001c-06-resume-02/watched-cycle-3.json) |
| 001c-06-resume-03/status `753afaf72ebfabd34e30af71ee8695b0` | 2026-11-13T05:59:42.029Z -> 2026-11-13T05:59:42.150Z | 200/200 / 204.221 / 121.400 | OBSERVED; trade_id=trade:d59ab1cf05df393676e66e4e; item_id=item:c4a01aa3ed2e3986921c209e; definition_id=0; current_bid=1200; bid_state=outbid; trade_state=closed; expires=-1 | `["{python}","-m","fc_access.e2e_resolution_v2.capture","status"]` [docs/research/001c/001c-06-resume-03/status.json](001c/001c-06-resume-03/status.json) |
| 001c-06-resume-03/watched `f944bbdb84bb9ffded4ed92fa97c1c3d` | 2026-11-13T05:59:42.668Z -> 2026-11-13T05:59:42.831Z | 200/200 / 193.966 / 162.700 | OBSERVED; trade_id=trade:d59ab1cf05df393676e66e4e; item_id=item:c4a01aa3ed2e3986921c209e; definition_id=261855; current_bid=1200; bid_state=outbid; trade_state=closed; expires=-1 | `["{python}","-m","fc_access.e2e_resolution_v2.capture","watched"]` [docs/research/001c/001c-06-resume-03/watched.json](001c/001c-06-resume-03/watched.json) |
| 001c-06-resume-03/unassigned `025db71264a88923529933e6802645ae` | 2026-11-13T05:59:43.335Z -> 2026-11-13T05:59:43.452Z | 200/200 / 161.823 / 116.900 | OBSERVED; rows=0; see capture for exact identities/preconditions | `["{python}","-m","fc_access.e2e_resolution_v2.capture","unassigned"]` [docs/research/001c/001c-06-resume-03/unassigned.json](001c/001c-06-resume-03/unassigned.json) |
| 001c-06-resume-03/balance `71096b7b31feb90b50065bda899ea341` | 2026-11-13T05:59:43.906Z -> 2026-11-13T05:59:44.030Z | 200/200 / 146.899 / 124.900 | OBSERVED; spendable=16268 | `["{python}","-m","fc_access.e2e_resolution_v2.capture","balance"]` [docs/research/001c/001c-06-resume-03/balance.json](001c/001c-06-resume-03/balance.json) |

Local decisions are not additional EA writes: [reconcile-opening](001c/001c-06-resume-02/reconcile-opening.json),
[hold-opening](001c/001c-06-resume-02/hold-opening.json), and [hold-cycle-2](001c/001c-06-resume-02/hold-cycle-2.json)
retain actual argv, RPC request parameters, counters and results. Durable events tie status/balance read IDs to the bid command.
The [closed window](001c/001c-06-resume-02/closed.json) proves no native request after expiry.

Independent reproduction and actual results follow. These offline commands create only temporary fixture state.
The historical failing gate is retained as a failed result. Full discovery failures are reviewed below, not silently converted to passes.
Complete stdout/stderr, timestamps, exit codes and SHA-256 are in [checks.json](001c/001c-07/checks.json).

| Exact argv | Actual exit | Retained output |
|---|---:|---|
| `["{python}", "tests/test_001c01_audit.py"]` | 0 | [docs/research/001c/001c-07/check-00.txt](001c/001c-07/check-00.txt) |
| `["{python}", "tests/test_bidding_v1.py"]` | 0 | [docs/research/001c/001c-07/check-01.txt](001c/001c-07/check-01.txt) |
| `["{python}", "tests/check_bidding_v1_artifacts.py"]` | 0 | [docs/research/001c/001c-07/check-02.txt](001c/001c-07/check-02.txt) |
| `["{python}", "tests/test_watched_bulk_artifacts.py"]` | 0 | [docs/research/001c/001c-07/check-03.txt](001c/001c-07/check-03.txt) |
| `["{python}", "tests/test_search_validation_artifacts.py"]` | 0 | [docs/research/001c/001c-07/check-04.txt](001c/001c-07/check-04.txt) |
| `["{python}", "tests/test_durability_v1.py"]` | 0 | [docs/research/001c/001c-07/check-05.txt](001c/001c-07/check-05.txt) |
| `["{python}", "tests/test_durability_artifacts.py"]` | 0 | [docs/research/001c/001c-07/check-06.txt](001c/001c-07/check-06.txt) |
| `["{python}", "tests/test_e2e_v1.py"]` | 0 | [docs/research/001c/001c-07/check-07.txt](001c/001c-07/check-07.txt) |
| `["{python}", "tests/test_e2e_artifacts.py"]` | 0 | [docs/research/001c/001c-07/check-08.txt](001c/001c-07/check-08.txt) |
| `["{python}", "tests/test_e2e_live_v2.py"]` | 0 | [docs/research/001c/001c-07/check-09.txt](001c/001c-07/check-09.txt) |
| `["{python}", "tests/test_e2e_reconcile_v1.py"]` | 0 | [docs/research/001c/001c-07/check-10.txt](001c/001c-07/check-10.txt) |
| `["{python}", "tests/test_e2e_complete_artifacts.py"]` | 0 | [docs/research/001c/001c-07/check-11.txt](001c/001c-07/check-11.txt) |
| `["{python}", "tests/validate_001c06_complete.py"]` | 0 | [docs/research/001c/001c-07/check-12.txt](001c/001c-07/check-12.txt) |
| `["{python}", "tests/test_market_pricing.py"]` | 0 | [docs/research/001c/001c-07/check-13.txt](001c/001c-07/check-13.txt) |
| `["{python}", "tests/test_transaction.py"]` | 0 | [docs/research/001c/001c-07/check-14.txt](001c/001c-07/check-14.txt) |
| `["{python}", "tests/run_offline_suite.py", "tests/test_watched_bulk_v1.py"]` | 0 | [docs/research/001c/001c-07/check-15.txt](001c/001c-07/check-15.txt) |
| `["{python}", "tests/run_offline_suite.py", "tests/test_search_validation_v1.py"]` | 0 | [docs/research/001c/001c-07/check-16.txt](001c/001c-07/check-16.txt) |
| `["{python}", "tests/run_offline_suite.py", "tests/test_readiness_regressions.py"]` | 0 | [docs/research/001c/001c-07/check-17.txt](001c/001c-07/check-17.txt) |
| `["{python}", "tests/check_e2e_v1_acceptance.py"]` | 1 | [docs/research/001c/001c-07/check-18.txt](001c/001c-07/check-18.txt) |
| `["{python}", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]` | 1 | [docs/research/001c/001c-07/check-19.txt](001c/001c-07/check-19.txt) |

Full discovery ran **361 tests**, with two pre-existing failures, both in test_browser_access:
`test_criterion_0_inspection_is_current_and_does_not_assume_cdp` rejects an inspection older than 86400 seconds;
`test_review_matches_executed_bridge_sources_and_retained_metadata` rejects stale live-v2 observations
(`stale_live_evidence`, `no_current_page_observations` and dependent freshness errors).
Rewriting sealed dates to make those historical assertions green would destroy provenance. Their current failure remains explicit.
The original `check_e2e_v1_acceptance.py` exits 1 for missing verified opening/HOLD in its original window;
the independent aggregate completion validator passes using separately retained supplemental evidence.
Legacy rejected-HTTP fixtures use run_offline_suite.py to coalesce headers/body in one send on Windows,
with unchanged assertions/responses and no retries. Earlier plain-client WinError 10053 failures remain in 001c-05 logs.
The complete staged `git diff --cached --check` exits 2 for retained log CRCRLF/trailing blank lines;
the scoped source/tests/release-document whitespace check passes. Exact argv, actual exits and full outputs are in
[git-checks.json](001c/001c-07/git-checks.json). Sealed logs were preserved byte-for-byte instead of normalized.

Release validation additionally runs `python tests/test_release_audit.py` and `python tests/check_release_publication.py`.
The latter verifies actual main ancestry, byte-for-byte committed payload, remote main equality and exclusions.
[Release check output](001c/001c-07/release-checks.json) records the new audit test run; Git publication is checked independently against the remote.
The [payload manifest](001c/001c-07/payload-manifest.json) hashes source, tests, docs and sanitized versioned evidence.
Pre-existing files are checked against all 645 task-entry hashes; unrelated AGENTS.md is preserved and excluded from the commit.
Ignored .orchestrator/private-captures state and working SQLite/WAL/shm files are excluded from publication and untouched.

No extra live experiment was launched for the audit. Remaining live branches require the separately bounded continuation in
the [handoff](001c-architecture-handoff.md), never a replay of the original commands. No autonomous actor loops are included.
