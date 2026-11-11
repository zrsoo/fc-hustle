# Existing Edge session access — task_02

Status: **VERIFIED** for authenticated read-only access and active configuration, observed 2026-11-11 UTC. The reviewed v2 bridge reached the existing authenticated page without restarting, replacing or navigating Edge. No further operator action is pending for this task. This does not establish trading capability, direct HTTP access, repeated authenticated readback or session renewal.

## Active configuration from current authenticated behavior

These values occur together on the actual authenticated club response in [live-v2.json](browser-access/live-v2.json), not in a fixture or a historical default:

| Field | Observed value |
| --- | --- |
| FC version | `fc27` |
| API host | `utas.mob.v1.prd.futc-ext.gcp.ea.com` |
| Request prefix | `/ut/game/fc27/` |
| Client identifier | `FC27_JS_WEB_APP` |
| SKU | `FUT27WEB` |

At **2026-11-11T14:20:27.316Z**, the page observer recorded an authenticated `GET` on the generic `club` route, HTTP **200**, presence of the session header, and a recognized **itemData** array response shape decoded from **text**. Only that shape is retained: no inventory contents, player/item identifiers, balances or account information were exported. A URL or HTTP 200 by itself is insufficient for this proof.

The current trace has eight observations from **2026-11-11T14:20:24.112Z** through **2026-11-11T14:20:40.353Z**. One response met the structural authentication check. Four successful GETs with the same public configuration and a session-header-presence signal followed it, ending at **2026-11-11T14:20:40.353Z**. This is observed request activity after an authenticated read. Those later responses have an unrecognized response shape and are not counted as additional authenticated readbacks.

Lifecycle limits: repeated authenticated readback, renewal, expiry and logout/reconnect remain **UNVERIFIED**. No secret values were compared to identify a session. Two historical 401 responses on 2026-11-08 are retained in the 21-row archive, separately from the eight current observations. No identity continuity or automatic renewal across the intervening days is inferred. Original archive [live.json](browser-access/live.json) and prior [PARTIAL/BLOCKED checkpoints](browser-access-history.md) are preserved unchanged.

## Access mechanisms and session preservation

[inspection.json](browser-access/inspection.json) was refreshed on 2026-11-11. Fourteen Edge processes were observed, with no remote-debugging port or pipe flags, no Edge-owned listening sockets, and no default-profile `DevToolsActivePort` markers. Both localhost CDP discovery attempts failed. Five packaged extension manifests exposed no debugger or loopback permission candidates; this limited manifest scan does not enumerate unpacked registrations. Custom user-data locations and enterprise policies remain outside that scan. Initial document-control discovery returned no connected sessions. A signed-in tab was never assumed to expose CDP.

The selected mechanism is the locally authored Manifest V3 **FC configuration observer** with `activeTab` and MAIN-world injection into the selected EA page. It uses only memory-only `chrome.storage.session` for a tab number. It passively observes ordinary page Fetch/XHR traffic and sends sanitized metadata to the local sink. The separately reviewed native probe invokes one app-native read only when the operator runs it. No third-party executable or upstream credential-capturing bridge was installed or run.

No Edge process was stopped, restarted, reprofiled or navigated by the agent. A previous attempt to activate its window returned false before any keystrokes were sent; no clipboard operation occurred. Operator setup and the native read action were subsequently resolved. Browser authentication remained inside the existing profile. The agent did not repeat those completed actions during final verification.

## Reproduction and recovery instructions

These steps are retained for reproduction or a future lost attachment; no repetition is required now.

1. From `C:\hustle\fc-hustle`, run `python -m fc_access.server` only if the sink is not already running. `http://127.0.0.1:8766/health` identifies `fc-config-observer-v1`. Preserve any unrelated service if the port is occupied.
2. In the **same Edge profile**, open `edge://extensions`, turn on **Developer mode**, choose **Load unpacked**, and select `C:\hustle\fc-hustle\browser\observer`. For an existing copy, reload only after an actual source update; the reviewed version is 0.2.0. Do not remove the profile, change managed browser policy or restart Edge to enable debugging.
3. Return to the existing official HTTPS EA Ultimate Team Web App tab and click **FC configuration observer** in the Extensions menu. **No tab refresh** is needed. `ON` means attachment, not authentication; `WAIT` means the selected page, sink or extension restriction needs inspection. `python tests/check_browser_prerequisite.py` checks only v2 attachment, never FC acceptance. It is not a completion validator.
4. Use ordinary read-only Club or transfer-market navigation. If cached UI navigation emits no requests, review and run [native-read-probe.js](../../browser/observer/native-read-probe.js) in that tab's F12 Console, using the top EA Web App frame. It guards the HTTPS EA location, invokes at most one `services.User.requestCurrencies()` read and returns `undefined`; errors are suppressed rather than dumping account-bearing objects. Wait at least 30 seconds for the normal observer poll. Do not buy, bid, move or list an item for this access task.
5. Only if an actual login screen appears, sign in and complete any normal challenge directly with EA. Never supply passwords, cookies, session values, account objects or screenshots of account details to the harness. A 401 alone is not a demand to log in again. If policy prevents extensions or console use, record **PARTIAL/BLOCKED** and the exact restriction without bypassing it.
6. A full page navigation loses the page hooks, so click the extension again after that navigation. A browser restart clears its memory-only tab selection. Disabling the extension stops polling; a page refresh removes injected hooks. Stop only this local server when no longer needed. No logout or browser restart is required for cleanup.

## Review and retention boundary

The source review hashes for the extension, native probe and Python sink are in [review.json](browser-access/review.json). The initial repository review is [task_01](repository-analysis.md). V2's single public client-ID getter was checked against EA's current public source, then read from the actual page; that public source was not treated as authenticated evidence. Identifier regexes do not supply default configuration values. Missing identifiers remain null.

The extension destination and active sink bind are fixed to **127.0.0.1:8766**. Final OS inspection found only that bridge listener; the original 8765 sink was no longer listening, and was not stopped by this verification. The live service identity and loopback bind were checked at their actual destination. No non-localhost debug or bridge endpoint was opened.

The sink accepts bounded JSON with exact Host, an extension Origin and a positive field/value allowlist before writing. It rejects unknown fields, resource-specific paths and arbitrary client strings; suppresses access/error logging and exception details; and exposes no arbitrary evaluation, credential or trading API. No CORS permission is granted to ordinary web pages. It retains only public configuration, generic route/type/response shape, timestamps, numeric statuses and a session-header-presence boolean. Raw URLs, query strings, bodies, headers, authentication values and personal data never enter retained observations. Local processes or another extension could forge observations; this is not cryptographic proof against a hostile machine.

## Validation

Run independently from this workspace:

```text
python tests/test_browser_access.py
python tests/validate_browser_live.py
python tests/test_repository_research.py
```

The first checks artifacts, actual JavaScript behavior with synthetic requests, request preservation, native-read guards, privacy rejection, loopback HTTP enforcement and checkpoint restoration. Synthetic tests use temporary files and never write live evidence. Mutation tests reject missing authentication, identifiers, request lifecycle events, sensitive fields, future timestamps and stale-only proof.

The second validates the real current trace. All retained rows are privacy-checked; archived rows are excluded from current proof. It requires a recognized authenticated FC27 read carrying observed client/SKU identifiers and later successful same-configuration request activity. It distinguishes that activity from repeated authenticated readback and renewal, which remain unverified. The earlier validator incorrectly failed the entire preserved history as stale and required a second authenticated read beyond the stated lifecycle-observation criterion; those issues were corrected without counting an untyped HTTP 200 as an authenticated read.

The dependency's source-review tests also pass. Actual validation results and the machine-readable current configuration/lifecycle facts are in [verification.json](browser-access/verification.json). All original task_02 acceptance criteria are covered; this point-in-time result must be recollected when the current evidence exceeds its 24-hour freshness window.
