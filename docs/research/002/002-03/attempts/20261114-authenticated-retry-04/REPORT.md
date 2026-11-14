# 002-03 authenticated fourth attempt

**BLOCKED — USER INSTRUCTION REQUIRED**

Attempt `20261114-authenticated-retry-04`: `FAILURE/BLOCKED`; reason `delivery_unknown_no_retry`.

The user explicitly instructed “try again now” after discussing normal login recovery. [authorization.json](authorization.json) pins the three prior captured failures and records this distinct new budget. All three old checkpoint files remain unchanged and FAILURE/BLOCKED. This attempt never reopens their windows or counters.

## Preparation and changes

Recovery identified three Edge windows and uniquely located the official FC27 Web App tab. The existing desktop helper required a single Edge window globally. `desktop_window.ps1` now selects the unique window containing that intended tab (or a caller-verified explicit handle); missing and ambiguous matches still fail closed. `ui.ps1` retains its official URL, foreground, unique-tab and action checks. JSON remains UTF-8 and strict-schema validated. Offline PowerShell doubles exercise multi-window selection and ambiguity without accessing a real desktop.

The verified official window was brought forward and refreshed. Its UI exposed Home and Transfer controls, without login/continue or security-challenge prompts. Existing normal authentication could therefore be used; no credential value was read or exported. These UI indications alone are not treated as EA authentication. The fourth attempt explicitly requires a fresh native `/user/credits` GET200 under the selected PC persona before any discovery, with the actual command/response retained. No pricing, caps or helpers are warmed by that read.

The gate runner adds only this authentication prerequisite and the separate fixed fourth-attempt authority/checkpoint. Discovery and exact-version pricing behavior, profitability/tax rules, freshness, scheduler interval and the strict monotonic <30.000s requirement are unchanged. The new budget is one authentication GET, up to three discovery GETs within 180s, six timed EA GETs, up to 64 helper batches, one valuation and zero account mutations. Total EA GET budget: 10. No arbitrary fifth-attempt or reset flag is available.

## Offline verification before live work

Full Python discovery: 542 tests, exit 0. Node scripts: 18. All recorded offline checks passed: True. The focused 25 gate/preflight/discovery tests also passed. Exact commands, counts, UTC times and immutable log hashes are in [offline-checks/results.json](offline-checks/results.json). New coverage includes authenticated-read ordering, missing/forged auth proof, fourth-attempt authority, preserved failures, default dependency rejection and multi-window selection. Offline fixtures are not live evidence.

## Actual execution

Command: `python -m fc_access.production_v1.gate_00203_discovery --attempt 20261114-authenticated-retry-04`.

Start UTC `2026-11-14T01:24:55.816640+00:00`; finish UTC `2026-11-14T01:25:26.923317+00:00`; final stage `BOUNDED_DISCOVERY`.
Valuation start ns `None`; final decision ns `None`; stopped ns `150712137123300`; elapsed seconds `None`. An absent timer is not a zero-second PASS.

The actual sanitized commands, native EA statuses/queries/rows, cache inventories, selected identity, epochs, timing split and diagnostic evidence are retained in [gate.json](gate.json). A missing response means unknown EA outcome; it never means a zero-row market result. Browser reload background traffic was not globally instrumented and is outside these explicit native-command counts.

| Stage | Operation | Parameters | Actual EA query | HTTP | Retained auctions | Command ms |
| --- | --- | --- | --- | --- | --- | --- |
| AUTHENTICATION | balance | {} | {} | 200 | 0 | 338.279 |
| BOUNDED_DISCOVERY | search | {"count": 21, "fresh": true, "max_bid": 1000, "min_buy": 11000, "page": 1, "purpose": "discovery"} | null | UNKNOWN | UNKNOWN | UNKNOWN |

Authentication proof, selected identity and actual outcomes:

```json
{
  "authenticated_read_id": "5bef03a3ca10eff135ea08c6ef73502c",
  "selection": null,
  "uncached_quote": null,
  "decision": null
}
```

Timing breakdown (components overlap; do not add inclusive diagnostic/SQLite or service/RTT totals). Normal timed Foundation journal/diagnostics and final checkpoint work remain inside the stopwatch. Evidence assessment, report assembly and sealing happen afterward.

```json
{
  "diagnostic": "valuation_not_started"
}
```

## Independent assessment and final state

Prepared independent validators matched expected outcomes: True. [post-attempt-validation/results.json](post-attempt-validation/results.json) retains their commands and exit statuses. Default dependency validation selects the fourth checkpoint and fails closed unless it contains an independently evidenced PASS. The previous three checkpoints still reject dependent work.

**BLOCKED — USER INSTRUCTION REQUIRED.** The new attempt is consumed. No fixes, further native operations, another candidate, valuation retry or items 4–12 followed the failure. Only retained-evidence checks, reporting and Git delivery continued.
