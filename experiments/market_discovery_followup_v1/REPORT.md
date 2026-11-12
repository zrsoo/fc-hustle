# FC27 discovery integration follow-up v1

**VERIFIED** at 2026-11-12 06:22:57 UTC. One bounded search through the new long-poll
research bridge returned a fresh authenticated FC27 transfer-market **HTTP 200**
and 21 exact-version PC auctions. No account mutation or discovery benchmark ran.

## Findings and fix

EA's public `ocompiled.js` defines `GamePlatform.PC` as uppercase `"PC"`.
`compiled_2.js` derives `UTPersonaEntity.platform` and `isPC` from the selected
club. The active page independently reported `platform="PC"`, boolean
`isPC=true`, and `GamePlatform.PC="PC"`. The original research adapter rejected
this representation before calling the native market service. The older working
adapter accepted the derived `isPC` flag even when its platform string differed.

The additive follow-up recognizes the observed enum plus its consistent boolean
flag. It preserves lowercase `pc` and missing/null platform plus a true flag as
supported alternatives. Explicit unknown and console platforms never become PC
just because a flag is true; conflicting flags and malformed objects fail closed.
Auction/physical-item pseudonyms, exact definition IDs, response validation,
origin pinning, one-command ownership and native-service invocation are retained.

The historical 401 was **not reproduced after normal login**. The unchanged
Objective 001 read bridge returned HTTP 200 at 2026-11-11 23:05:44 UTC. The new
bridge also returned HTTP 200 at the timestamp above. This supports stale or
expired prior authentication as the explanation; the exact historical rejection
reason cannot be recovered from a 401 alone. No authentication transport, session
provider, header reuse, cookie handling or challenge behavior was changed.

## Live acceptance

Evidence: [new long-poll capture](runs/20261112T062256Z/search.json).

| Requirement | Independent observation |
| --- | --- |
| Existing Edge tab attachment | Server health: attached, active long poll, revision 0.2.0 |
| Selected PC persona | Allowlisted public projection: `PC`, true, matching native enum; accepted |
| New command delivery | Server monotonic queue delivery 0.0457 ms; matching worker telemetry ID |
| Native market search | `services.Item.searchTransferMarket(criteria, 1)` after cache invalidation |
| Fresh authenticated FC27 response | `utas.mob.v1.prd.futc-ext.gcp.ea.com/ut/game/fc27/transfermarket`, GET 200, session-header presence only |
| Python result and exact identities | 21 auctions, 21 distinct trade pseudonyms and 21 distinct item pseudonyms, every definition ID 233731, platform pc |
| Independent timings | Separate server, page, worker and Python measurements below; independent validator PASS |

Query: exact definition 233731, Buy Now ceiling 7000, page 1, count 21, fresh=true.
The selection is a normal card version, not an asset-ID substitution. No raw
auction/physical IDs, account/persona IDs, names, headers or credential values
were retained. The random per-run correlation key was not exported to artifacts.

| Measured component | Milliseconds | Method |
| --- | ---: | --- |
| Queue delivery | 0.0457 | Server monotonic enqueue to delivered command |
| Worker receipt to native start | 2.5000 | Normalized browser Performance clocks |
| Native service | 136.6000 | Page native call to observable completion |
| Native start through page return | 137.8000 | Page Performance duration, including projection |
| Result return residual | 5.3432 | Server delivery-to-result receipt minus measured page/dispatch durations |
| Worker dispatch through page return | 141.8000 | Independently measured worker Performance duration |
| Result POST round trip | 3.7000 | Worker POST start through local acceptance acknowledgement |
| Python end to end | 172.4210 | Monotonic `/run` request through complete response decode |

Result-return residual and POST round trip are distinct measures, not a claimed
one-way network measurement. Native-service time includes Web App/service work;
it is not isolated EA server latency. Python end to end excludes local prerequisite
GETs, subsequent telemetry collection and disk output. One successful sample
supports neither p95, throughput superiority nor MV3 lifecycle reliability.

## Request bounds and preservation

There were two successful authenticated account-market searches in this follow-up:
the [unchanged baseline](runs/20261111T230544Z/baseline-search.json) before the quota
interruption and the new long-poll search more than seven hours later. The
[original guard reproduction](runs/20261111T230544Z/original-guard-reproduction.json)
returned `schema_unrecognized`, no native duration and zero EA requests. Local
persona inspection and long polling make no EA requests. Every future native
submission in the new page is paced at least 30 seconds from its previous one.
Other research callers were not launched; no nine-window A/B/C run occurred.

All task-entry tracked bytes remain unchanged. Original transactions, source
pins and sealed audit artifacts were preserved. The old passive observer appended
sanitized observations while running; its sink alone was stopped, its output was
[archived separately](runs/20261111T230544Z/observer-continuation.json), and the
tracked file was restored byte for byte to the task-entry commit. See
[preservation records](runs/20261111T230544Z/historical-preservation.json) and
[seal hashes](runs/20261111T230544Z/preserved-seals.json).

Implementation is entirely additive under `experiments/market_discovery_followup_v1`:
the persona helper, adapted search page and worker, manifest, diagnostics/timing
server, one-search CLI and independent validator. New regression files are
`tests/market_discovery_followup_v1_checks.cjs` and
`tests/test_market_discovery_followup_v1.py`. No Objective 002 code was added.

## Exact verification commands

Run from `C:\hustle\fc-hustle`. The server was started with the exact loaded ID:

```powershell
python -m experiments.market_discovery_followup_v1 serve --extension-id efjplmigngambdonapdohhbofhomlfim
```

The actual one-search command and subsequent read-only assessment were:

```powershell
python -m experiments.market_discovery_followup_v1 search --output experiments/market_discovery_followup_v1/runs/20261112T062256Z/search.json
python -m experiments.market_discovery_followup_v1 validate --input experiments/market_discovery_followup_v1/runs/20261112T062256Z/search.json
```

The recorded output path is intentionally immutable; another capture requires a
new timestamped path. Do not rerun a search just to replay validation.

```powershell
python tests/test_market_discovery_followup_v1.py
python -m unittest discover -s tests -p "test_*.py"
python tests/validate_001b.py --precommit
```

Results: **9 focused tests passed; 183 total tests passed; Objective 001B
precommit artifact audit PASS; new live-capture validator PASS.** The focused
suite also runs the real authored JavaScript against synthetic native fixtures,
including the observed persona, alternatives, consoles, malformed objects,
identity/privacy, request pacing, HTTP 401 and real loopback transport rejection.

Historical commit-specific validators are unchanged. The task-entry Objective
001B commit gate already fails because its commit included the observer file
that its T7 entry excluded; Objective 001's exact-set gate predates Objective
001B's added deliverables. These failures are recorded in
[the check log](runs/20261111T230544Z/offline-checks.json), not repaired by changing
history. All original source-hash pins and artifact checks in the regression
suite and Objective 001B precommit audit pass.

Remaining limitations: no full benchmark, latency distribution, session-expiry
experiment, console account, MV3 suspension/reconnect test or autonomous trading
validation. A local hostile process could forge loopback evidence; sanitized
observations are not cryptographic attestations. These limits do not negate the
observed authenticated HTTP 200 through the corrected long-poll bridge.
