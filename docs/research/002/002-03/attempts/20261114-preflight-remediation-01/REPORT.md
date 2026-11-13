# 002-03 desktop preflight remediation and newly authorized attempt

**BLOCKED — USER INSTRUCTION REQUIRED**

New attempt `20261114-preflight-remediation-01`: **FAILURE/BLOCKED**. Reason: `no_real_eligible_candidate_single_discovery`.
No bids, purchases, listings, bulk operations, actors or scheduled jobs were executed. Items 4–12 were not run.

## Encoding cause and bounded changes

The original subprocess used `text=True` without an explicit encoding. On Windows its reader selected cp1252; a UTF-8 UI label contained byte 0x81, which cp1252 cannot decode. Reader failure left stdout missing and `.splitlines()` raised AttributeError. The original failure occurred before valuation, not because of a slow quote.

`fc_access/production_v1/ui.ps1` now sets UTF-8 console output and supports a `preflight-json` action that emits only the structured desktop summary. A `-JsonOnly` switch also suppresses unrelated labels during ordinary browser recovery. All existing unique-window, intended-tab, official-host, foreground, native selected-persona and authentication checks remain in place. No credential or header value is exported.

`gate_00203.desktop_preflight()` captures bytes (`text=False`), explicitly decodes strict UTF-8 with optional BOM, and parses exactly one JSON object. It bounds output size and validates the exact schema, boolean types and fresh UTC observation. Missing/empty output, duplicate JSON keys, mixed labels, malformed JSON, invalid UTF-8, stale timestamps, failed process, unavailable executable and timeout produce controlled local reasons. It never parses or persists subprocess stderr or arbitrary UI labels.

The gate CLI accepts only the specifically authorized new attempt ID. Its checkpoint is exclusively created before desktop/service/native work; any preflight failure is sealed there. Existing checkpoints reject re-entry before further desktop work. There is no reset, retry, automatic candidate change or arbitrary attempt-name option. `run` accepts that already consumed window instead of opening the old checkpoint. The independent validators support `--original` or the fixed `--attempt` identity; the default dependency check selects the new checkpoint when present, including RUNNING/failed states, without falling back. Only a sealed independently evidenced PASS permits item 4.

No pricing optimization, trading-policy change or freshness relaxation was made. The existing monotonic gate, production Foundation, two-search algorithm, 24-hour cache and native legality checks are reused.

## Preserved original and separate budget

Original checkpoint: [../../gate.json](../../gate.json). Original report: [../../REPORT.md](../../REPORT.md). Both remain unchanged. The old checkpoint remains **FAILURE/BLOCKED**, zero pricing GETs, no valuation time or eligible decision. It must never be interpreted as a PASS.

New checkpoint: [gate.json](gate.json). Explicit user authorization and original captured-file integrity digest: [authorization.json](authorization.json). The new checkpoint carries attempt=2, its unique attempt ID, that authority and the original checkpoint digest. It does not replace or renew any historical experiment.

Independent new budget: one gate invocation, at most seven EA GETs (discovery, initial caps, two pricing GETs, fresh discovery, credits, final admission caps) and at most 64 local helper batches of <=32 probes. It has its own operation/cache-read lists and one valuation timer. No price/cap/helper warmup or candidate valuation took place before this timer.

Before the attempt, the existing official Edge tab and reviewed extension were reloaded to use the current timing-instrumented production page. An explicit higher local owner epoch fenced the old document/worker mapping, and the production extension was reattached to the same selected account/persona context. Read-only service health and public recovery fences are retained in `recovery-health.json`, `recovery-epoch.json` and `prepared-readonly-health.json`. Local health/activation issued no EA commands. Normal Web App reload background requests were not globally instrumented and are outside the explicit gate request count.

## Offline behavioral regressions before live work

Command: `python -m unittest discover -s tests -v`. Final result: **533 tests passed, zero failures/errors**, including 16 gate/preflight tests. All **18 Node check scripts** passed. The original hard-stop validator also passed. Exact commands, UTC times, exit codes and immutable output hashes: [offline-checks-final/results.json](offline-checks-final/results.json).

The first offline full run had one Windows localhost connection abort (`WinError 10053`) in `test_browser_access.BrowserAccessTests.test_criterion_4_localhost_sink_rejection_and_no_logging`; all gate/preflight regressions passed. That run is preserved in [offline-checks/results.json](offline-checks/results.json). No unrelated implementation or test was changed; the subsequent full offline run passed. This was an offline regression rerun before the single live attempt, not a gate retry.

New regressions cover the original UTF-8 D0 81/cp1252 failure, missing stdout, optional BOM, invalid bytes, mixed labels, duplicate/malformed JSON, output bounds, types, stale time, child-process failure/timeout, all desktop guards, independent attempt budgets, original rejection, lost/crashed checkpoint fencing and no repeated dispatch. The existing real-Foundation offline test is also exercised with the new attempt authority. Offline fixtures are not presented as live proof.

## Single live command and retained outcome

```text
python -m fc_access.production_v1.gate_00203 --attempt 20261114-preflight-remediation-01
```

Started UTC: `2026-11-13T23:03:22.849244+00:00`. Finished UTC: `2026-11-13T23:03:39.714789+00:00`. Final stage: `DISCOVERY`.
Completed recorded EA requests: 1; recorded pricing searches: 0; local helper commands: 0; account mutations: 0.

Every command, exact sanitized query, HTTP status, native result, operation monotonic times, cache-read record and command evidence digest is retained in `gate.json`. Uncompleted commands, if present, remain RESERVED/UNKNOWN evidence and are not counted as successful responses.

Monotonic valuation start ns: `None`; final decision ns: `None`; stopped ns: `142204928605900`.
Measured elapsed seconds: `None` (strict limit <30.000). An absent timer means valuation did not start; it is not a zero-second success.

```json
{
  "valuation_elapsed_seconds": null,
  "diagnostic": "valuation_not_started"
}
```

Timing totals include the existing native/transport/helper work and normal Foundation journal/diagnostic writes plus final-decision checkpoint inside the measured window. Retained-evidence assessment, report assembly and sealing occur afterward. Diagnostic logging and SQLite totals overlap; they must not be added together as disjoint components.

Pricing wire requests:

| Search | Parameters | Actual EA query | HTTP | Returned rows |
| --- | --- | --- | --- | --- |

Initial quote and final decision (actual retained values, not expected results):

```json
{
  "uncached_quote": null,
  "decision": null
}
```

## Independent validation and stop policy

Prepared offline validators were run against the retained new checkpoint and the original checkpoint. Exact commands and expected/nonexpected exit statuses: [post-attempt-validation/results.json](post-attempt-validation/results.json). The original acceptance validator must exit 1 because that historic attempt failed. The new acceptance validator exits 0 only for a genuine evidenced PASS; the hard-stop validator verifies exclusive checkpoint consumption and correct dependency denial/admission.

All validator exit statuses matched expected outcomes: `True`.

The newly authorized attempt is consumed and blocked. **STOPPED: no further fixes, gate retries, additional candidates, pricing optimizations or items 4–12 were performed after its failure. BLOCKED — USER INSTRUCTION REQUIRED.**
