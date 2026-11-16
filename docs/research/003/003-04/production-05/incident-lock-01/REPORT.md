# Idle resale work must not wait for a mutation lock

Run `2a8011d59307b4b1eabe0a2b49577abc`, epoch90, reached READY after three
fresh native startup reads. The published no-status read correction was deployed
to a genuinely new document/worker, and real successful GET diagnostics included
its new typed flag. The earlier 42-minute segment remained separately sealed.

The idle bidder entered its first cycle at 08:36:36 UTC. There was no acquisition
queue, pending acquisition/resale write, active resale or unseeded verified win,
but `Resale.cycle` nevertheless waited for the global `.bid.lock`. Maintenance's
real due relist used that lock while discovery occupied higher-priority native
slots. The relist and exact readback completed at 08:37:05. Acquisition's fresh
search and funds checks then used their protected section. At 08:37:11 the idle
bidder's 35-second wait failed with `process_already_running`, causing the
controlled stop. The timing and protected-command traces establish internal
contention; no competing controller was observed. Maintenance's later lock
failure followed the stop and the gated queued read.

The segment retained 33.74527 healthy monitored seconds. All five child exits
were awaited and RUN_STOPPED is sequence29707. The journal-backed service exited
before source changes. There were no new bid mutations or unresolved mutation
intents. The actual bulk relist is RECONCILED, with its native command and distinct
complete Transfer List readback retained. Read
`6e114044b10d7bd079e67d089e5a7b9c` had no start, dispatch claim or transport
command and was not an executed account action. No operation will be replayed.

The fix checks the current owner and whether any active resale, pending resale
write or unseeded verified win exists before attempting the mutation lock. When
none exists, resale returns without account work. Every positive path still
seeds/reconciles and rechecks under the unchanged original lock and all native
physical ownership, paid cost, stored-price, capacity and intent guards. Work
created concurrently remains durable for the next ordinary cycle. This adds no
retry, longer timeout, broad exception suppression or guard bypass. The separate
bidder role lock and stale-owner checks remain fatal.

Five new regressions include a real separate process holding the OS mutation
lock while the idle bidder completes normally. They also exercise unseeded wins,
active/pending writes, historical completed wins, duplicate roles and stale
owners. The first pending-write fixture accidentally allowed a successful move
effect, which the existing independent readback correctly reconciled; it now
explicitly models no effect plus timeout to test a genuinely pending write.
No production guard or old assertion was weakened. All account/native doubles
remain offline and contribute no live coverage or monitored time.

Final full discovery passed **953 Python tests**, zero failures/errors, and all
**29 Node suites** passed. Exact argv/times/stdout/stderr are in `offline-01/`.
The separately scoped export correction checker passed against genuine captured
files and rejects the invalid revision declaration. Source/test/instruction byte
identity is not an acceptance condition.

An independent operator metadata incident is recorded in
`../incident-export-label-01.json`. A placeholder exporter CLI revision produced
an invalid capture even though the launch receipt named intended HEAD. The
invalid output remains preserved and excluded. The replacement exporter used
the correct actual revision and retained the complete control stream. The
primary runtime lock stop preceded that replacement; the earlier statement of
uninterrupted runtime during replacement was premature and is corrected here.
Exporters sent no EA request or account mutation. No historical capture was
rewritten to repair its label.

No human prerequisite is known. Publication and new independent native startup
reconciliation must precede a fresh fenced owner. All stopped segments, including
their counters and incidents, remain sealed. Four consecutive healthy monitored
hours must begin again after this stop, and all required natural cases remain
mandatory. Missing events will not be manufactured or called a blocker.
