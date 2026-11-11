# T4 live discovery and latency attempt

Results are **BLOCKED**, with **0 seconds of authenticated FC27 observation**.
Normal Edge extension attachment succeeded. An independent read-only baseline
search then reached EA and returned **HTTP 401**, with a session header present.
This is a current authentication rejection, even though the rendered Web App
still showed the transfer-market screen. No session value was exported.

The retained [report](../../experiments/market_discovery/runs/t4-live-20261111T220200Z/report.json)
is an offline-replayable account of the blocker, not a successful throughput
benchmark. The required 30 minutes and alternating windows were not obtained.
No historical observations, synthetic auctions or T3 simulator timings count
as live evidence in this report.

The two preflight operations ran from **2026-11-11 22:00:49.736773 UTC** to
**22:04:49.887092 UTC**, a **240.150319-second span**, including diagnosis and idle
time. Actual command waits total **10.415546 seconds**. Neither duration is
authenticated market observation. There were two commands, one captured EA GET,
zero successful results, zero returned auctions and zero account mutations.

Normal setup used Edge's existing developer-mode extension manager, Load
unpacked for `experiments/market_discovery/browser`, the existing official EA
tab, and the extension's action to grant activeTab. The
[inspection](../../experiments/market_discovery/runs/t4-live-20261111T220200Z/access-inspection.json)
records running Edge, lack of a debugging connection, the selected package,
and the real search-only bridge's attached health. The separately started
research server was stopped after evidence collection. Existing evidence and
the original bridges were preserved.

The [long-poll preflight](../../experiments/market_discovery/runs/t4-live-20261111T220200Z/preflight.json)
failed with `schema_unrecognized` before native search. No cache reset, native
duration or EA request was recorded. Source inspection identifies the
selected-persona PC guard as the pre-native schema-failure branch. The guard
requires `persona.platform === 'pc'`, or a null platform with `isPC === true`.
The rejected raw platform/persona values were not captured; no particular
alternative value is claimed. The stored window `-1` is a preflight marker,
not a strategy window. An unsuccessful DevTools readiness inspection supplied
no platform diagnostics; it does not establish a schema mapping.

An independently paced
[baseline preflight](../../experiments/market_discovery/runs/t4-live-20261111T220200Z/baseline-preflight.json)
used the existing read-only bridge's 30-second alarm, with the same exact-version
filter and a separate one-request budget. Its native projection reported `pc`,
but the fresh GET was rejected with 401. That projection alone does not resolve
the stricter new guard. All live requests stopped after the 401. Later
[health-only checks](../../experiments/market_discovery/runs/t4-live-20261111T220200Z/auth-stop-health.json)
are local attachment evidence and issue no EA requests.

| Arm | Failed round trips | Median round trip | Local queue delivery | Successful first result | p95 |
| --- | ---: | ---: | ---: | --- | --- |
| Existing alarm baseline | 1 | 10,397.478 ms | unknown | unobserved, n=0 | unsupported |
| Separate long-poll adapter | 1 | 18.068 ms | 0.043 ms, n=1 | unobserved, n=0 | unsupported |

These failure paths do not support a live speedup comparison. Baseline round
trip includes an unseparated alarm wait and the rejected native read. Alternative
round trip measures local delivery, injection and guard rejection. Both native
duration sample counts are zero. EA server latency is unknown. No assumed alarm
delay was subtracted. Every aggregate retains n and median; p95 is withheld for
n < 20. The raw runner's legacy `time_to_first_result_ms` field times receipt of
the error envelope; the report correctly excludes it from successful-result
latency. No prepared-intent timing exists.

The projected response sizes are **316 baseline bytes** and **311 alternative
bytes**, **627 total**. They are compact sanitized JSON sizes, not EA wire
payload sizes. Wire bytes, auction age, expiry distributions, duplicates,
exact-version yields and market coverage remain unavailable. The attempted
filter was definition 233731, BIN ceiling 7000, page 1/count 21; no successful
filter/page combination was observed. No auction was returned to revalidate.
Changed BIN, changed identity, expiry and unavailable-auction outcomes therefore
remain null, with zero attempts. A missing row in a bounded page would not
establish a sale or auction-wide absence.

Resumption requires a valid EA session restored through normal sign-in and any
normal challenge, selected FC27 PC persona, and normal extension reattachment.
If the stricter guard still rejects the selected PC persona, review its narrow
read-only platform projection before changing it. Do not force a platform value.
A fresh authenticated HTTP 200 market GET must pass before observation starts.
No credentials, remote-debugging restart or access-control bypass is needed or
proposed.

The frozen protocol remains the observation plan: nine alternating five-minute
A/B/C windows, eight foreground EA request slots each (six discovery and two
diagnostic revalidation), 24 maximum per strategy, one command in flight, at
least 30 seconds between submissions, multiple filters and pages 1/2. Compare
the reviewed instrumented `alarm_30s` and `long_poll` modes only with the same
EA caps and pacing, reloading and reattaching normally when changing modes.
The two preflights are outside those budgets. Actual matched blocks are zero.
Background EA traffic and coverage denominators were not measured. The
existing [harness instructions](../../experiments/market_discovery/README.md)
describe the finite observation and transport setup after prerequisites pass.

Reproduce the report without any live access, using a new output path:

```powershell
python -m experiments.market_discovery.t4_evidence --output private-captures/t4-report-replay.json
python tests/test_t4_live_evidence.py
```

The validator checks each acceptance criterion's blocker branch against raw
evidence: attachment and 401, planned versus actual budgets/windows/durations,
sanitized schema/byte counts/UTC/request accounting, failure-only latency and
unsupported p95, absence of fresh revalidation candidates, and exact unmet
prerequisites. It recomputes the report, pins input and browser/protocol source
hashes, verifies exclusive output creation, and rejects corrupted evidence that
would falsely establish an authentication blocker. These checks do not assert
that live access has recovered.
