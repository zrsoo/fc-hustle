# Bulk blocker repair and verified read-only recovery

**BLOCKER FIXED; READY FOR ORCHESTRATOR RECHECK OF 002-12.** This is not a full
item-12 E2E PASS. The remaining unobserved branches in the sealed review-03
report remain unverified.

The user explicitly authorized fixing the blocker, confirming the fix, and
requesting orchestrator recheck. They also reported navigating the Web App and
clearing lost watched auctions. That activity is preserved; no account mutation
was performed by this remediation.

## Backup and scope

Before changes, local `main` was at `880ca4914f648ef337435013d1fb4752704ace48`.
An annotated backup tag `backup/bulk-blocker-20261114T124422Z`, a complete Git
bundle and consistent SQLite backups preserve the journal, native mailbox,
completed quotes, transport and orchestrator state. All five database integrity
checks passed. See [backup-receipt.json](backup-receipt.json). Private backups are
under `private-captures/bulk-blocker-repair/20261114T124422Z/`.

All original item-12 windows, budgets, journal snapshots, failed callbacks and
review-03 PARTIAL verdict remain unchanged. This repair never repeated the
already-executed relist. It used two separately consumed, read-only recovery
windows, with one fresh Transfer List GET each and zero EA mutations.

## Root cause

The original `relist_all` command `869ed95434e70ea0d7ba599945751fd2` dispatched one
authenticated `PUT /ut/game/fc27/auctionhouse/relist`, with no query or body.
EA returned HTTP200 and the native callback reported success. Independent native
reads later proved both physical targets relisted with new trades, unchanged
prices and one-hour duration.

The production bulk XHR guard nevertheless treated any concurrent request as part
of the bulk operation. It even fabricated an invalid request record for traffic
outside the FC27 namespace. An unrelated read or telemetry request could therefore
set `bulkViolation`, throw `bulk_contract_changed`, and turn the successful native
callback into a failed command. Rejected requests were thrown before being added
to the recorded wire list. The historical second request's exact identity is
therefore unavailable. The user's browser activity is a plausible trigger, not a
retrospectively proven endpoint or cause attributed to the user.

The Python layer made that generic callback error a persistent incompatibility.
Normal reconciliation preserved it even after complete independent reads proved
the actual effect. The supervisor also lacked a continuation branch for reconciled
bulk commands: its existing branches covered bids and resale mutations.

## Changes

- The bulk page wrapper distinguishes unrelated native GETs and non-UT browser
  traffic from the intended mutation. Background traffic passes through and emits
  bounded diagnostic metadata, without exporting URL/query/body/header values.
  It is not presented as an additional bulk mutation or an operation-owned request.
- Unexpected FC27 mutations, duplicate writes, wrong host/route, nonempty body,
  query changes and existing context/freshness/precondition failures still fail
  closed. Blocked attempts now record an enumerated reason before throwing.
  Diagnostic stages distinguish background requests/responses and blocked writes;
  the `bulk_contract_changed` error is retained explicitly.
- `production_v1/bulk_recovery.py` adds an explicit recovery procedure. It requires
  the immutable intent, the original recorded failed result, matching native
  mailbox response and dispatch interval, a distinct recorded complete post-read,
  exact physical/version/trade identities, unchanged prices, anchored one-hour
  duration, complete account membership and unchanged unrelated entries at the
  time of that historical effect. HTTP200 alone is insufficient.
- A new complete fresh production inventory read is also mandatory. Physical
  identities and prices must still match. Native sale-status observations such
  as `untradeable` and `lastSalePrice` may evolve; they are not physical identities.
  Current sold/expired/active state is independently classified by the existing
  native inventory contract.
- Verified recovery inserts an immutable `bulk_recoveries_v1` proof and appends
  `OBSERVED_EFFECT_RECOVERED`. It changes the operational intent state to
  `RECONCILED` while preserving **`incompatible=1`**, the original error and the
  original failed native/mailbox response. This is an audited state transition,
  not an unconditional flag reset. Ordinary reconciliation still leaves a
  contract-change error blocked without this explicit proof.
- Journal authority accepts that proof solely for reconciliation. It rejects
  redispatch of the consumed command. The supervisor now checks reconciled bulk
  authority and an independent readback event before accepting continuation.
- `actors_v1/recover_bulk_blocker.py` is a finite, explicit read-only harness.
  Each fixed window is exclusively created and permits one Transfer List read;
  it cannot issue bids, relists, clears, helpers, prices or actor work.

No trading strategy, prices, duration, reserve, freshness, login, persona or
authentication requirement was relaxed. The reviewed extension and normal
read-only localhost service were reloaded, and Edge's official tab was verified
through the existing UI helpers. No credential was inspected or exported.

## Consumed first recovery window

`blocker-repair-01/recovery.jsonl` records a genuine authenticated fresh native
Transfer List read at **2026-11-14T13:00:57.582Z**. It returned all six physical
items with the same trades and prices. Recovery stopped before changing the
intent because it compared the entire item projection as identity.

The acquired/listed exact card, version 246420, had genuinely sold at BIN 2000.
Its native `untradeable` changed from false to true and `lastSalePrice` from 1200
to 0, alongside `trade_state=closed/current_bid=2000/expires=-1`. Those sale-status
fields are mutable. Physical item/version, auction and listing prices were
unchanged. The correction compares actual physical identity and prices, while
retaining native state validation. A regression covers this real observed
transition and still rejects a changed exact version.

The failed first recovery checkpoint and budget are preserved. There was no
mutation, no intent-state change and no reset/reuse of that window.

## Successful live recovery

Command:

```text
python -m fc_access.actors_v1.recover_bulk_blocker --window blocker-repair-02
```

One actual authenticated GET `/ut/game/fc27/tradepile` returned HTTP200 at
**2026-11-14T13:03:27.563Z** through the production Foundation/adapter/service.
The fresh read ID is `73ae2808d236825440ce391345a26cf0`; complete occupancy is six.

| Physical target | Exact version | Original relisted trade | Start / BIN | Fresh state |
| --- | ---: | --- | --- | --- |
| `item:6c1821fd50efcf26deca9cb1` | 239085 | `trade:834fa628321887f7f200dd37` | 45000 / 46000 | active, current bid 0, expires 997 |
| `item:baedbe1a7c161538497cdc85` | 236772 | `trade:9435144d1f61a0df7e80a21f` | 6000 / 6200 | active, current bid 0, expires 997 |

The earlier independent post-read anchored the original 3600-second duration to
the original native dispatch interval. The fresh 997-second countdown is elapsed
time on those same auctions, not a newly created listing. Both existing prices
remain unchanged. The sold version-246420 item remains on the Transfer List;
this remediation did not clear it or move anything.

The result is **RECONCILED**, with no pending bulk intents. The original
incompatibility diagnostic remains 1, and its failed response still says
`bulk_contract_changed`. Journal authority returns true for reconciliation and
false for dispatch. The actual supervisor `review_resume` succeeds against the
preserved live mailbox and journal, with cumulative prior active time
**823.255405 seconds** retained. It starts no process and resets no budget.

See [recovery.jsonl](recovery.jsonl), [summary.json](summary.json) and
[independent-check.json](independent-check.json). The service remains attached
with mutations disabled. No actors were started here.

## Verification

The complete Python suite passes **734 tests, zero failures and zero errors**.
All **26 Node suites** pass. Exact commands and outputs are retained in this
directory and `../blocker-repair-01/`.

```text
python -m unittest discover -s tests -v
node tests/bulk_background_checks.cjs
node tests/production_bulk_checks.cjs
# Every other tests/*checks.cjs script was also executed; see node-final.json.
python tests/test_bulk_blocker_recovery.py
python tests/check_bulk_blocker_recovery.py
```

Regression coverage includes unrelated UI reads and telemetry, one native bulk
invocation, duplicate/write/body/query/host/route rejection, safe diagnostics,
incorrect identities/prices/duration, missing targets, unrelated inventory
changes, failed fresh reads, immutable recovery proofs, no duplicate read or
redispatch, natural sale-status changes, and the supervisor's bulk continuation.

The initial full run exposed one architectural-import failure: the new production
helper imported actor locking directly. The production bulk component now owns
its shared lock, and the finite recovery harness resides in the actors package.
The import-boundary test was preserved. The corrected full run passed; the final
full run after the sale-status correction is retained separately. No tests were
deleted or skipped, and no source-code hash assertions were added.

`tests/check_bulk_blocker_recovery.py` independently rechecks retained native
proof, the one fresh inventory read, the real durable transition and no-redispatch
authority. It performs no native operation. Historical item-12 strict acceptance
still remains PARTIAL; this repair does not manufacture the missing branches.

## Handoff

The local snapshot had been amended from published `009f7a7` to `880ca49` before
this task. Preserve the tested amended snapshot and all sealed continuation
evidence when joining the Git histories; do not force-push or restore older code.

Commit and push the fix, report and evidence before requesting recheck of the
existing task `obj-29bea3b74eb3/002-12`. The orchestrator can create a new bounded
continuation under the original cumulative limits and independently verify the
remaining branches. Do not replay the consumed relist or either recovery window.
After the recheck acknowledgement, this remediation stops and leaves execution
to the orchestrator. No full Objective 002 completion is claimed here.
