# 004-02 implementation and verification

Implemented and verified the new controller transport contract. The selected
final evidence is [status-array-06/result.json](status-array-06/result.json), with
the full acceptance mapping in [final-verification.json](final-verification.json).
No controller, legacy actor, account mutation or full lifecycle E2E was launched.

The shipped production extension now routes explicit schema 4 commands to a
private controller closure. Schema 2 retains its legacy validation, receipt and
poisoning behavior. The controller status adapter passes 1–10 retained native
DTOs to the official array DAO once and binds the sole GET to exactly those
private trade IDs. It does not search the market to confirm a command.

Requested pairs, returned pairs, duplicates, omissions, unexpected identities,
malformed states, version conflicts and lost document mappings are validated.
Lite 0/null versions remain unchanged in the original safe response projections.
Separate links reference the retained full-version read and its original time.
After validating the returned set, the native `setAuctionData` setter connects
the genuine returned auction entity to the retained full-version item DTO.
This supplies current bid state without inventing a full version or passing a
lite DTO as a full write target. Missing rows grant no authority or loss proof.

`ControllerStore` provides server-owned durable batch/decision/intent admission.
Its trusted APIs are absent from HTTP routes; request flags cannot enable writes.
An authenticated entry balance and complete current-scope inventory precede batch
admission. A decision binds the exact target, amount/minimum/cap, deadline and
independent read. Claims recheck authority and commit permanent action tombstones
before dispatch. Initial action keys survive changes of batch or decision ID;
rebids bind amount and originating independent observation. Restart abandons old
queued/claimed commands. No transaction spans native I/O. Unknown, duplicate and
expired commands do not gate unrelated subsequent work.

Request attribution follows the actual native queue request object to its
eventual send. Same-URL background requests remain sanitized diagnostics and
cannot replace a missing owned request. Owned writes require exact method,
endpoint, target, body and authenticated response binding. Existing receipts are
retained; ACKNOWLEDGED is separate from independent participation. Owned request
retry/reauth is disabled per finite request, without changing global EA policy.
Queue, request, observable, DAO and XHR hooks restore on every exit. Timeout and
interruption remove only owned queued work and abort owned in-flight work. Late
results remain audit evidence without replay or a new-mode global write gate.

## Actual authenticated read-only evidence

Normal Edge UI selected the unique saved zzorniss account suggestion, then
submitted the account and saved-autofilled password controls. No field values,
credentials, cookies, headers, tokens or session identifiers were extracted or
retained. [account-selection.json](account-selection.json) records only safe UI
booleans and actions. Attachment pins the actual native user and selected PC
persona objects; commands recheck them and the complete public scope/epoch fences.
Native persona display names are not saved sign-in identifiers.

Each successful window used this three-request recipe: fresh watched GET, one
exact-target status/lite GET, independent forced watched GET. The final window
retained **19 full watched rows**, requested **10 real retained targets**, and
returned **all 10** with **zero omissions**. All three HTTP statuses were **200**.
The exact batch request was **one GET /ut/game/fc27/trade/status/lite**. Private
wire trade IDs were checked in the page and never exported. The complete actual
requested/returned pseudonymized trade/item pairs and full definitions are in
the selected result and its append-only checkpoint, not reconstructed from old
artifacts. Every returned lite definition was **0**, every target was
**closed/outbid**, and the independent later full watched rows agreed on exact
identity, version, personal state and current bid. Original version 0 values and
all ten full-read/current-DTO links are retained.

| Window | Reserved requests | Actual EA GETs | Outcome |
| --- | ---: | ---: | --- |
| status-array-01 | 0 | 0 | Attachment expired while normal login recovery was needed |
| status-array-02 | 1 | 0 | Erroneous persona-display-name guard stopped before native traffic |
| status-array-03 | 1 | 0 | Case normalization did not resolve the invalid alias assumption |
| status-array-04 | 3 | 3 | Ten targets returned by one status GET after account-binding repair |
| status-array-05 | 3 | 3 | Ten-target retest after final admission/authentication checks |
| status-array-06 | 3 | 3 | Ten-target retest including genuine auction-entity/full-DTO linkage |
| Total | **11** | **9** | **Zero mutations** |

All windows were prepared exclusively and reservations fsynced before delivery.
Earlier windows and their budgets/checkpoints were never reset. The original
through-05 evidence index and seal remain intact; the final retest has a separate
index and supplemental seal. Hash checks cover only captured immutable experiment
evidence, never current implementation, tests, configuration or instructions.

## Verification and limits

`python tests/test_00402_controller.py` passes **12** behavioral tests. Its Node
fixture executes the shipped page, captured official array DAO, synthetic native
observables/queue/XHR, and actual worker callbacks. Python executes the actual
parser, adapter, durable store and loopback HTTP transport. Cases include ten
targets/one GET, private selector binding, partial/duplicate/wrong-item/version
results, 0/null lite rebids using current full DTOs, omissions without authority,
delayed owned requests, interleaved same-URL background traffic, zero owned sends,
late callbacks, timeout/interruption/rejection cleanup, receipt versus independent
confirmation, authenticated scope, failed persistence, restart, duplicate action
keys, expired intents and one mutation dispatch through real HTTP delivery.

[offline-03/results.json](offline-03/results.json) records **38 passing commands**:
seven relevant Python suites and all **31** current Node checks suites. This
includes legacy status, page, worker, receipt, inventory, diagnostic and routing
contracts. Earlier offline passes are retained separately. Final targeted
behavior/artifact checks were rerun after adding explicit function-restoration
and independent-confirmation assertions; their results are in `acceptance.json`.

`python tests/check_00402_artifacts.py` independently checks all captured commands
and envelopes, exact requested/returned sets, original lite versions/full evidence
links, independent comparisons, scope, timestamps, one-GET behavior, conservative
budgets, no replay, sealed experiment evidence and stopped-process projections.
Its negative cases reject fabricated identity, omission, version normalization,
extra requests, changed fences and unreported limits. Both validators make zero
EA calls. No source-code hash assertions were introduced.

The live account supplied ten closed/outbid targets; active auction/rebid effects
were not manufactured. No live null-version, malformed response, omission,
manual/background interleaving, timeout, rejection or uncertain mutation was
induced. Those paths are behaviorally verified offline. New authority mutation
effects remain offline-only under this task's read-only probe boundary. Full
pricing/phase/resale composition and the full integrated controller E2E belong to
later tasks. [final-verification.json](final-verification.json) gives the evidence
or precise live limitation for every acceptance criterion.

[final-cleanup.json](final-cleanup.json) independently confirms no production
worker or production-port listener remains. Every temporary service thread exited,
all native mailboxes had zero waiting/claimed work, and no mutations were enabled.
The pre-task service was absent and remains absent. Existing Objective 002/003
records and sealed historical evidence were preserved.
