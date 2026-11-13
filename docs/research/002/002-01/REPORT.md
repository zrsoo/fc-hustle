# Objective 002 task 002-01

Production native status validation now uses function availability and observed
behavior. `status_support` reports `function_available` and retained mapping count
without an EA request. It establishes neither authentication nor market support.
`status` requires a retained same-context trade/item/full-definition mapping,
then validates exactly one authenticated successful GET to
`/ut/game/fc27/trade/status/lite`, its exact retained trade selector, native items
schema, matching trade/item identity and any observed full definition. Unknown
native states, malformed prices, duplicate rows, mismatched identities, stale or
future observations and ambiguous network activity fail closed.

Request selectors are private snapshots of native trade IDs. Mutable native
repository objects cannot redirect a status request. Conflicting fresh full
identity reads cannot overwrite a retained mapping. Lite zero/absent definitions
remain unobserved and do not overwrite the retained full definition. Empty status
coverage remains inconclusive. A retained mapping can select an older known trade;
each returned status requires a new authenticated observation within 30 seconds,
including time spent projecting the response. A changed owner/host/worker epoch
clears mappings, and a new document requires fresh full-identity reacquisition.

The hardcoded function digest and function-byte hashing are removed from the
production page and current Python parser. Identity pseudonym hashing remains.
The current support schema rejects the old fingerprint envelope. Offline
historical validators use `tests/historical_contracts.py` to project sealed local
metadata into availability without enforcing its source digest or old match
conclusion. Captured EA response hashes and sealed evidence integrity remain
enforced. No historical file was migrated or rewritten.

Verification commands, run independently from the workspace:

- `python tests/test_00201_native_status.py`: six acceptance tests, including
  executed production JavaScript, parser forgery negatives, mutable-source
  evolution through the real auditor, and evidence preservation/tamper negatives.
- `node tests/native_status_checks.cjs`: unavailable and independently implemented
  native functions, authenticated GET, malformed/schema/state cases, freshness
  during network and projection, identity conflicts, lite omissions and reconnect
  epochs. Runtime digest instrumentation permits identity inputs only.
- `python -m unittest discover -s tests -q`: complete Python regression suite,
  including production page/inventory behavior and historical audit checks.
- `python tests/validate_remediation_live.py`: offline validation of retained live
  records, including actual historical reconnect and request-budget evidence.

Observed results: the focused six-test acceptance suite passed; the complete
suite passed all 488 tests in 58.659 seconds; retained live-record validation and
`python -m fc_access.release_audit_v1` both returned PASS. `git diff --check`
passed. All commands were offline checks of implementations or captured evidence.

`preservation.json` records integrity checks for 754 pre-existing tracked
immutable evidence files selected by the repository evidence policy. It excludes
mutable implementations, tests, configuration and instructions. Acceptance tests
verify all recorded evidence, plus changed/deleted capture negatives and refusal
to enforce a mutable-file digest.

AGENTS.md and the final-remediation report were read before implementation. This
task performed no browser recovery, live EA requests, account operations, window
replays, checkpoint resets or task/session replacement. Existing 001C/001D and
completed research windows are preserved. New behavior is verified offline; no
new live-market verification is claimed.
