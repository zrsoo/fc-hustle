# Objective 001B finite live benchmark v1

This is an additive completion runner and offline analyzer, not a trading bot.
It reuses the frozen protocol, the original `Runner` plans/ranking/budgets/stops,
and the verified uppercase-PC follow-up bridge on port 8771. Historical sources,
transactions and seals are not modified.

Current captured experiment: [20261112T064306Z](runs/20261112T064306Z/REPORT.md).
It is **BLOCKED/PARTIAL**, not a completed A/B/C comparison: A completed one
300-second window and eight HTTP-200 searches; the first B command failed
locally with `bridge_not_attached`, before any EA request. C did not start.

## Capture

The CLI performs one authenticated HTTP-200 preflight using the existing signed-in
EA page, then waits at least 30 seconds before the benchmark. Preflight budget is
separate, as frozen in the original protocol. The scheduled experiment has nine
300-second windows, A/B/C/B/C/A/C/A/B, eight slots/window, no catch-up, one command
in flight and at most 24 actual EA requests/arm (72 total). The existing native
30-second submission guard remains unchanged. At normal completion, the wrapper
waits through all 2700 seconds, including the last window's idle tail.

The actual capture invocation was:

```powershell
python -m experiments.market_discovery_live_v1 --output-dir experiments/market_discovery_live_v1/runs/20261112T064306Z
```

Every read is fsynced to `records.jsonl`; `progress.json` is mutable only while
that new run is active. `observations.json` is an immutable final snapshot.
Existing output directories are rejected before preflight. Queue/native/return
and Python timing, exact per-run auction/item pseudonyms, filters and HTTP status
are preserved. Keys, headers and session material are never exported.

**Do not restart nine windows blindly after this interruption.** Eight A requests
have already been consumed. Remaining study budgets are A=16, B=24, C=24. Preserve
the completed A window and failed zero-EA B attempt. Any continuation that changes
the original uninterrupted timing must first freeze a versioned technical
pause/recovery amendment; it cannot discard requests or claim continuous exposure.
No such amendment or continuation was silently activated in this capture.

## Replay and audit (no EA traffic)

```powershell
python -m experiments.market_discovery_live_v1.report --run-dir experiments/market_discovery_live_v1/runs/20261112T064306Z
python -m experiments.market_discovery_live_v1.validate --run-dir experiments/market_discovery_live_v1/runs/20261112T064306Z
python tests/test_market_discovery_live_v1.py
python tests/test_market_discovery_live_analysis_v1.py
python -m unittest discover -s tests -p "test_*.py"
```

Report output paths are new-only. Once the report is retained, inspect it or run
the validator; do not overwrite it by invoking the report writer again. The
validator distinguishes integrity PASS from completion BLOCKED and returns
nonzero for an incomplete comparison. Fixture tests are explicitly SIMULATED;
the report writer rejects fixture lineage and invalid evidence.

Indicative pricing delegates to the existing conservative calculator, excludes
candidate trade/item identities, uses only observed same-window prefixes and
keeps hypothetical caps/increments explicitly unverified. Executable yield,
profitable revalidation rate and realized profit stay unknown. Missing B/C
observations never become zero opportunity yield. No hourly yields or a strategy
winner are inferred from a partial prefix.

The optional `passive` companion reuses the original observer sink on port 8766,
redirecting all output into this new run. It only receives allowlisted metadata
and makes no EA requests. Its append-only metadata/heartbeat ledger explicitly
records missing attachment and limited coverage. The observer did not attach in
this capture, so background traffic is unknown, not zero.

Minimal current external prerequisite: inspect the full WAIT hover message and
reattach **FC discovery integration follow-up READ ONLY** on the existing official
EA tab while its server is healthy. Normal login is needed only if EA actually
requests it. Neither the source nor the evidence identifies a new 401.
