# 001c-03 bounded watched reads

Results, limitations and acceptance mapping are in
[`REPORT.md`](../../docs/research/001c/001c-03/REPORT.md).
This package has no account-write command or actor loop.

The reviewed unpacked extension is `browser/`, version 0.2.0. Its Windows-path
ID, verified in Edge, is `bbdmlnhehokodegoodepjkoebhbhdhbc`. It attaches only on
the official HTTPS EA Ultimate Team Web App. The loopback endpoint is 8775.
Attachment polls locally; only an explicit `watched` CLI command invokes EA.

Check the existing service before starting another:

```powershell
Invoke-RestMethod http://127.0.0.1:8775/health
python -m experiments.watched_bulk_v1.server
```

Start only when absent. Preserve `docs/research/001c/001c-03/budget.json`:
four of six watched invocations are already consumed. Restart does not authorize
resetting that checkpoint. Reattach by clicking **FC27 watched bulk READ ONLY
001c-03** on the verified EA tab. `READ`/health establish attachment only.
`inspect` projects public PC/capacity/feature metadata without requesting EA.

For a remaining explicitly scoped read, use a new filename; never overwrite:

```powershell
python -m experiments.watched_bulk_v1 inspect --output docs/research/001c/001c-03/NEW-inspect.json
python -m experiments.watched_bulk_v1 watched --output docs/research/001c/001c-03/NEW-watched.json
```

Leave 30 seconds between native invocations. This is the experiment guard,
not an EA requirement. Commands are delivered once, without retries; a delivered
ambiguous read consumes budget. Do not replay completed capture files/windows.
No additional live calls are needed to run the acceptance validators.

`contract.to_snapshot` reuses the 001c-02 typed status/coverage seam. It separates
network freshness from cached success, reported capacity from queue configuration,
and pending/unknown outcomes from independently confirmed terminal outcomes.
The persistent 50-row fixture is explicitly synthetic. The public source decoder
performs static string substitutions and checksum arithmetic, never JS execution.
