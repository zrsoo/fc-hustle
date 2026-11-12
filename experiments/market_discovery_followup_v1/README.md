# Objective 001B integration follow-up v1

Live integration: **VERIFIED** on 2026-11-12 at 06:22:57 UTC. See
[the report](REPORT.md) and [the new capture](runs/20261112T062256Z/search.json).

This versioned follow-up preserves every Objective 001/001B source and sealed
artifact. It performs public persona inspection and one bounded exact-version
FC27 PC market search. It has no account-write commands and does not run the
nine-window discovery benchmark.

EA's `ocompiled.js` defines `GamePlatform.PC = "PC"`. `UTPersonaEntity.platform`
and `isPC` are getters derived from the current club in `compiled_2.js`. The
native representation requires both uppercase `PC`, boolean `isPC === true`,
and the matching public enum. Canonical lowercase `pc` and the previously
supported missing/null platform plus true flag remain valid alternatives.
Unknown explicit platforms, console platforms, conflicting or malformed flags,
arrays, boxed primitives and throwing getters fail closed.

## Attach and validate

1. Load `C:\hustle\fc-hustle\experiments\market_discovery_followup_v1\browser`
   using Edge's existing developer-mode extension manager. This is an additive
   package; do not replace or reload the sealed original package from edited code.
2. From the repository root start the server with the exact ID shown in Edge:

   ```powershell
   python -m experiments.market_discovery_followup_v1 serve --extension-id efjplmigngambdonapdohhbofhomlfim
   ```

   That ID is derived from this workspace's exact unpacked path using Chromium's
   path-ID algorithm, checked against the installed original package's ID. If
   Edge shows a different ID, use the ID it shows. It is public, not a credential.
3. On the existing official signed-in EA Web App tab click **FC discovery
   integration follow-up READ ONLY**. `READ` indicates local attachment only.
   The server's `/persona` endpoint contains only an allowlisted public projection;
   it never receives persona IDs, account objects or authentication material.
4. Close other research callers. Leave at least 30 seconds since any preceding
   EA submission. Run exactly one search, choosing a new timestamped output:

   ```powershell
   python -m experiments.market_discovery_followup_v1 search --output experiments/market_discovery_followup_v1/runs/NEW-UTC/search.json
   ```

   Each invocation performs at most one search and never retries it. The page
   also enforces at least 30 seconds between native submissions, including failed
   searches. Local 20-second long polls are independent of EA pacing. Reloading
   the page resets its local pacing history, so retain the initial manual gap.

## Timing and evidence

The inherited queue measures enqueue-to-delivery with server monotonic time.
The page measures worker-to-native dispatch and native observable duration with
normalized browser Performance clocks. `result_return_ms` is the measured server
round trip less those browser durations (a residual, not EA server latency).
Independent worker telemetry measures page-return duration and the `/result`
POST round trip. Python measures `/run` end to end. No assumed alarm delay is
subtracted. One sample establishes neither p95 nor sustained throughput.

Only a successful projected response plus a fresh authenticated FC27
`transfermarket` HTTP 200, PC persona validation and exact definition/item/auction
identities constitutes live success. Attachment, a rendered market screen and
offline fixtures do not. A failed 401 stops the check; use normal EA login rather
than copying headers or session values. Reattach after a full page navigation.

Regression commands:

```powershell
node tests/market_discovery_followup_v1_checks.cjs
python tests/test_market_discovery_followup_v1.py
python -m experiments.market_discovery_followup_v1 validate --input experiments/market_discovery_followup_v1/runs/NEW-UTC/search.json
python -m unittest discover -s tests -p "test_*.py"
python tests/validate_001b.py --precommit
```

The original validators' exact historical commit/deliverable-set gates are not
new follow-up acceptance gates. The Objective 001B precommit artifact audit
passes. Its original commit gate already reports that the task-entry commit
included an observer file excluded by the T7 policy. Objective 001's original
exact-set validator also predates the added Objective 001B files. Their results
are recorded in the follow-up check log; no sealed audit is rewritten to hide
these historical limitations. The new capture has its own independent validator.
