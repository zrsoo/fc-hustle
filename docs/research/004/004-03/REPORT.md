# 004-03: encapsulated sequential controller

Implemented and validated offline. Full controller E2E remains pending. No EA
requests, browser recovery, live state migration, account mutations, controller
service, legacy actor, scheduler or production cutover was started by this task.
The pre-change controller/browser files were backed up under
`C:/hustle/backups/004-03-20261116-200540.zip`; unrelated workspace changes and
004-01/004-02 evidence remain intact. The initial read-only process inspection
found no matching controller/actor/continuous Python or Node worker.

## Composition and reuse

`fc_access/controller_v1/controller.py` owns finite sequential steps and an
explicit optional run loop. `config.py` validates the configurable 40000 entry
threshold, two-second request spacing and five-second management target.
`journal.py` adds isolated controller, batch, selected candidate, attempt,
membership, inventory validity and metric tables to ControllerStore. Selection
and attempt bodies are immutable. Intent commits before native delivery; SQLite
write transactions do not span I/O. The executor is shared with all read and
native price helper work. Local helper calls consume zero EA pacing slots.

Imported production components: `PricingService`, `QuoteCache`, `PriceService`,
`CardKey`, native minimum/increment/floor rules, `Search`, strict legacy read
parsers and bid receipts. Completed observations retain TTL 86400; completed
hits perform zero searches. Misses keep the two-search minimum valid BIN method,
inclusive second maxb=first_min, 600/10000 template/candidate/identity exclusions,
early rejection, diagnostic-only comparable last_sale_price, 5% tax and X=500.
The cheapest legal representative is priced first within a version to avoid an
illegal or expensive first discovery row excluding every cheaper auction. Each
candidate uses the completed cache API so its own trade/item is still excluded.

The narrow shared seam accepts schema 2 reads only. It cannot dispatch a legacy
mutation or credits read. Schema 4 remains the one-shot bid/status/balance
authority. ControllerStore records both schemas and links genuine lite results
to retained full search/watched evidence. The browser retains the original full
observation timestamp, separately attaches genuine current auction entities and
permits a fresh exact terminal link to select the existing read-only owned-item
GET. The controller service identifies its shared read seam explicitly in the
worker handshake. Those reads quarantine late callbacks, disable native retries,
abort/remove abandoned queued requests, restore temporary hooks and do not poison
later writes. The seam accepts reads only. Legacy write admission and uncertainty
policies remain unchanged.

## Batch policy and inventory validity contract

One genuine credits GET belongs exclusively to each acquisition batch. At or
below the configured threshold, the controller durably HALTs with
ENTRY_CREDITS_AT_OR_BELOW_THRESHOLD. Failed credits reads have no admission
authority. The sole entry observation remains batch authority even when pricing
takes more than 30 seconds; it is never restamped or reused for another batch.
There are no credits GETs during bid bursts or management.

Discovery is exactly one page 1 PC player GET, count 21, maxBid=1000 and
minBuy=11000. All public identities, bid/BIN/expiry fields and original network
times are retained. Candidates need strictly more than 60 seconds remaining at
selection after real observation age, exact tradeability, legal minimum bid at
or below their stored cap, no prior attempted initial action and no existing
known participation. At most ten distinct candidates are selected and attempted.
Selected candidates and individual intent are committed before sequential bids.
The controller neither raises a submitted amount nor retries that mutation.

One successful watched read establishes known other participations; one complete
Transfer List read establishes physical capacity near selection. Manual, sold,
expired and inactive physical entries count. Active highest/outbid and possible
won watched items, plus durable confirmed/pending members, count toward the
known combined 50 pipeline. Physical item IDs are unioned to prevent double
counting. Each selected possible win consumes a known prospective slot.

The complete inventory snapshot can be shared only in the same account/context
and document generation, at most 30 seconds from its genuine network timestamp.
Invalidate it on known inventory mutation, mapping loss, observed external
account change or identity conflict. Call `journal.invalidate_inventory()` when
an external integration establishes such a change. Invalidity skips remaining
initial actions; it does not cause per-candidate inventory GETs. Unknown or
incomplete inventory is never zero capacity. Existing EA effects which were
discarded as uncertain are exposed separately and are not hidden reservations.
This bounds known capacity; the policy cannot bound unobserved external effects.

## Confirmation, management and recovery

One exact-target status GET confirms each submitted initial target separately.
HTTP success and service itemIds are not participation proof. Only an independent
later highest/outbid observation admits active membership; independently observed
closed/outbid results settle LOST. A possible win stays PENDING_WIN until an
independent exact physical owned item and dispatched paid amount agree. The
verified win-handler seam must account for required resale work before settling
WON_ACCOUNTED. The production resale/maintenance integration and operational
run/pause/stop launcher are the separate 004-04 task; no default handler invents
a completed listing. Pending wins remain exact observed targets and count toward
known capacity.

Management observes only confirmed exact targets, orders outbid actions by
deadline, HOLDS highest and cap-exhausted auctions, and submits minimum capped
rebids sequentially. Independent correlated readbacks follow the burst. Missing
rows and expired local countdowns never establish loss. Cycle pacing targets five
seconds from actual cycle start; a slow cycle emits missed-target metrics and
cannot spawn catch-up work. When known management settles, acquisition begins
in the same step. Empty/rejected/uncertain acquisition batches immediately permit
the next step/batch with central pacing and a new entry read; no retry timer exists.

Uncertainty is persisted as UNKNOWN, consumed and abandoned. Initial action keys
exclude batch and read IDs; rebids additionally bind amount and originating
observation. Restart abandons unfinished intentions, retains prior membership and
permanent command tombstones, and never dispatches old commands. Late receipts
are audit-only. New document generations reacquire full watched mappings once,
require a genuine current exact status/full-version link, and then allow a new
fenced decision using the original stored quote/cap. Missing mappings grant no
write authority. Old commands remain fenced out.

`Controller.status()` includes potentially_untracked_effects and explicitly
sets global_ten_participation_guarantee=false. Ten is a per-batch attempt and
confirmed-membership bound, not a guarantee of ten real account participations
across batches after uncertain submissions. Unknown rebids retain prior confirmed
membership; an unrelated later write or a new decision from a fresh status can
proceed. The host remains responsible for the canonical account/native process
ownership guards when integrating the operational launcher in 004-04.

No actor loop, acquisition interval/backoff, DRAINING, one-bid exit, sum-of-caps
funding rule or per-auction budget allocator is imported or implemented.

## Executable evidence and limitations

`acceptance.json` maps all eleven criteria to executable tests.

* `python tests/test_00403_controller.py`: complete controller over real SQLite
  admission, parsers, receipts and pricing, with a synthetic EA boundary. Covers
  request counts, thresholds, failures, cache/version/tax/caps, 60-second edges,
  invalid/expired/changed-price candidates, attempt/membership/capacity limits,
  empty/mixed/rejected/uncertain batches, terminal lifecycles, immediate
  reacquisition, funds rejection, holds, ordering, restart and later writes.
* `python tests/test_00403_artifacts.py`: executes shipped JavaScript for full
  discovery to bid to lite to owned read, verifies unchanged original timestamps,
  local price-change rejection, and replays the ten-auction offline artifact.
* `python tests/test_00402_controller.py`: transport/authority/actual loopback
  regression, native request ownership, late results, cleanup, and compatibility.
* `python tests/test_001d04_pricing.py` and
  `python tests/test_001d03_native_prices.py`: imported pricing/native rules.

`offline.json` is explicitly SYNTHETIC_OFFLINE_ONLY. Its reproducible trace
acquires ten, rebids ten in deadline order, independently settles ten LOST and
immediately reads the next batch's threshold-equal balance. Counts: two credits,
three market searches (one discovery/two pricing), one caps, one watched, one
complete inventory, twenty bids, four exact-target status requests. The separate
local helpers are not EA requests. Acquisition/burst/handoff durations, expiry
misses, cycle elapsed time and missed targets are recorded; these are synthetic
clock measurements, not EA performance claims. The one-minute eligibility window
still permits expiry misses, which are exercised and reported by the tests.

Implementation defects found during verification were repaired: an illegal first
candidate poisoned same-version pricing; restart erased a HALTED reason; lite
updates did not initially supply fresh terminal authority for owned-item lookup;
shared legacy reads initially inherited page-wide timeout poisoning.
No mutable source/configuration/test hashes are asserted. Existing immutable
captured EA evidence integrity checks remain unchanged. No new live verification
or full integrated autonomous lifecycle is claimed by this task.

Final independent command results: 25 controller tests, 3 artifact/native seam
tests, 12 controller transport regressions, 17 imported pricing tests and 10 native
price tests passed (67 Python tests total, including their invoked Node checks).
The shipped worker and legacy page checks also passed directly. All use isolated
fixture state and require no production browser/session prerequisites.
