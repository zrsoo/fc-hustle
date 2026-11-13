# 002-03 third attempt: bounded discovery and strict live gate

**BLOCKED — USER INSTRUCTION REQUIRED**

Attempt `20261114-bounded-discovery-03`: **FAILURE/BLOCKED**, reason `delivery_unknown_no_retry`.
Only read-only EA operations were authorized and permitted. No bids, purchases, listings, bulk mutations, actors or recurring jobs were run.

## Authorization and preserved history

The user explicitly authorized bounded discovery across current card versions and a separate third attempt, with a hard stop if valuation starts and fails. [authorization.json](authorization.json) records that scope, both prior captured checkpoint digests and the finite new budget. The original checkpoint at [../../gate.json](../../gate.json) and the second at [../20261114-preflight-remediation-01/gate.json](../20261114-preflight-remediation-01/gate.json) remain byte-for-byte unchanged and FAILURE/BLOCKED. Neither old verdict is reinterpreted as PASS.

The third checkpoint is [gate.json](gate.json). It is exclusively created before desktop/service/EA work and cannot be reopened for another execution. There is no reset/retry flag or arbitrary fourth-attempt name. Default dependency validation selects this newest checkpoint and fails closed for RUNNING or failed states. Explicit selection of either historical failed checkpoint still rejects dependent work.

## Discovery implementation and finite budget

The production `Search` DTO, native page and strict parser now support omitting definition ID **only for discovery**, with the same maxBid=1000, minBuy=11000, type=player, page=1 and count=21. The actual discovery query must contain only start=0, num=21, macr=1000 and minb=11000; unexpected definition selectors or filters are rejected. Exact discovery and pricing retain their previous contracts. Pricing still requires a positive exact definition ID, page 1/count 21, and only the second pricing search adds inclusive maxb=first_min. No pricing algorithm, freshness, legality, profitability, tax or cache policy was changed.

Before measurement: at most three broad page-1 discovery GETs within 180 monotonic seconds. Select an active, tradeable, not-won, none/outbid auction with >120s remaining, positive current/starting requirement <=1000 and BIN>=11000. Candidates are ordered by current/starting amount, then stable trade pseudonym. Read the actual completed-cache databases for each encountered exact version, without deleting, expiring, rekeying or warming any cache. Skip every version with a pre-existing completed row. No preliminary price search, caps, helper or credits request is allowed during discovery. Discovery eligibility is not a claim of modeled profitability; profitability and exact native minimum legality must be established by the timed valuation/admission itself.

Once one uncached discovery candidate is selected, start the existing strict timer before caps, helpers, first real cache lookup and pricing. Only one valuation may start. The unchanged Foundation performs at most two pricing GETs, fresh exact-auction discovery and credits reads, then final admission with fresh caps. Its normal journal, diagnostics and final-decision checkpoint work remain included. Total budget is nine EA GETs (up to three discovery plus six timed), 64 local helper batches of <=32 probes, one valuation, zero account mutations. A failed valuation stops without further candidate selection, fixes or retries.

New code: `fc_access/production_v1/gate_00203_discovery.py` provides the finite explicit runner; `gate_00203.py` distinguishes attempt 3, its captured authority and budgets and independently verifies its selected discovery identity/cache evidence. The acceptance and stop validators accept the fixed third attempt ID. Test doubles now model cross-version discovery separately from exact pricing; no fixture data is sent to EA.

## Offline verification before live work

| Command | Exit | Tests | Receipt |
| --- | --- | --- | --- |
| `python -m unittest discover -s tests -v` | 0 | 539 | [log](offline-checks/check-00.txt) |
| `node tests/bidding_v1_checks.cjs` | 0 | script | [log](offline-checks/check-01.txt) |
| `node tests/browser_observer_checks.cjs` | 0 | script | [log](offline-checks/check-02.txt) |
| `node tests/bulk_transfer_checks.cjs` | 0 | script | [log](offline-checks/check-03.txt) |
| `node tests/durability_page_checks.cjs` | 0 | script | [log](offline-checks/check-04.txt) |
| `node tests/durability_worker_checks.cjs` | 0 | script | [log](offline-checks/check-05.txt) |
| `node tests/e2e_live_v2_page_checks.cjs` | 0 | script | [log](offline-checks/check-06.txt) |
| `node tests/e2e_page_checks.cjs` | 0 | script | [log](offline-checks/check-07.txt) |
| `node tests/market_discovery_bridge_checks.cjs` | 0 | script | [log](offline-checks/check-08.txt) |
| `node tests/market_discovery_followup_v1_checks.cjs` | 0 | script | [log](offline-checks/check-09.txt) |
| `node tests/native_status_checks.cjs` | 0 | script | [log](offline-checks/check-10.txt) |
| `node tests/pricing_timing_checks.cjs` | 0 | script | [log](offline-checks/check-11.txt) |
| `node tests/production_inventory_checks.cjs` | 0 | script | [log](offline-checks/check-12.txt) |
| `node tests/production_page_checks.cjs` | 0 | script | [log](offline-checks/check-13.txt) |
| `node tests/production_worker_checks.cjs` | 0 | script | [log](offline-checks/check-14.txt) |
| `node tests/read_bridge_checks.cjs` | 0 | script | [log](offline-checks/check-15.txt) |
| `node tests/search_validation_v1_checks.cjs` | 0 | script | [log](offline-checks/check-16.txt) |
| `node tests/transaction_bridge_checks.cjs` | 0 | script | [log](offline-checks/check-17.txt) |
| `node tests/watched_bulk_v1_checks.cjs` | 0 | script | [log](offline-checks/check-18.txt) |
| `python tests/validate_00203_stop.py --original` | 0 | script | [log](offline-checks/check-19.txt) |
| `python tests/validate_00203_stop.py --attempt 20261114-preflight-remediation-01` | 0 | script | [log](offline-checks/check-20.txt) |
| `git diff --check` | 0 | script | [log](offline-checks/check-21.txt) |

All of these commands ran before the third live attempt. The focused 22 gate/preflight/discovery tests also passed during development. Coverage includes actual execution of the production native JavaScript broad DTO/wire route and mixed definitions, exact-pricing enforcement, cached/unavailable selection skips, three-search exhaustion, a real-Foundation offline third-attempt PASS, altered selection/provenance negatives, strict deadline failure after valuation, no further discovery/dispatch, immutable prior checkpoints and default dependency fencing. Offline tests do not establish live acceptance.

## Actual live execution

Explicit command: `python -m fc_access.production_v1.gate_00203_discovery`. The normal saved-account official FC27 PC session and production extension/localhost Foundation were used. Public account/persona labels and owner/document/worker/host epochs are retained in the checkpoint. Authentication values were never exported. Ordinary browser/extension recovery and service reattachment happened before the finite gate; no valuation or native caps/helpers were warmed. Normal Web App startup background traffic is not included in the explicitly instrumented command count.

Started UTC `2026-11-13T23:17:13.826571+00:00`; finished UTC `2026-11-13T23:17:48.367069+00:00`; final stage `BOUNDED_DISCOVERY`.
Valuation start ns `None`; final decision ns `None`; stopped ns `143053580884100`; measured elapsed seconds `None`. The required threshold is strictly <30.000 seconds; an absent timer is not a zero-second success.

Exact sanitized requests, HTTP statuses, native response rows, freshness, scope/fences, monotonic command timestamps, cache inventories and evidence digests are retained in [gate.json](gate.json). The table below includes local helpers (which have no EA wire request); counts are actual returned auction rows, not complete-market claims.

| Stage | Operation | Native parameters | Actual EA query | HTTP | Rows | Command ms |
| --- | --- | --- | --- | --- | --- | --- |
| BOUNDED_DISCOVERY | search | {"count": 21, "fresh": true, "max_bid": 1000, "min_buy": 11000, "page": 1, "purpose": "discovery"} | null | None | 0 | UNKNOWN |

Selected discovery identity and actual cache-check record:

```json
{
  "selection": null,
  "cache_inventory": null,
  "discovery_reads": []
}
```

Timing breakdown (native service/RTT and inclusive diagnostic/SQLite values overlap; do not add them as disjoint totals). Report assembly, evidence assessment and sealing are after the stopwatch:

```json
{
  "diagnostic": "valuation_not_started"
}
```

Actual quote and fresh final decision:

```json
{
  "uncached_quote": null,
  "decision": null
}
```

## Independent evidence verdict and final state

Prepared retained-evidence validators all matched their expected exit codes: `True`. [post-attempt-validation/results.json](post-attempt-validation/results.json) records exact commands, results and immutable output hashes. The acceptance validator exits 0 only for this third attempt's genuinely evidenced PASS. It still exits 1 for each of the two preserved historical failures. Stop validators verify one-shot consumption and correct dependency denial/admission without sending EA requests.

**BLOCKED — USER INSTRUCTION REQUIRED.** The third attempt is consumed. After its failure, only already-prepared offline evidence validators, reporting and Git delivery ran. No further fixes, candidate selection, pricing searches, retries or items 4–12 work occurred.
