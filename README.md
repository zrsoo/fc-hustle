# FC27 integration research and retained harness

Read [the final readiness report](docs/research/final-report.md) first. The bounded
authenticated purchase-to-list experiment was demonstrated on 2026-11-11. The
verdict is **CONDITIONAL GO** for implementing Objective 002, with outstanding
release prerequisites. This repository contains research and a finite harness;
the autonomous executor is a future implementation.

## Setup

Run from the repository root in PowerShell. Python 3.10+ and Node 22+ are required
for all offline checks; this audit used Python 3.13.17 and Node 26.13.0. Node only
runs the authored JavaScript fixture tests. Python uses its standard library:
there are no pip packages or upstream executables to install. Microsoft Edge and
a normally authenticated official FC27 Ultimate Team Web App tab are required
only for fresh readback. No remote debugger or exported credentials are needed.

```text
python --version
node --version
python -m unittest discover -s tests -p test_*.py
python tests/validate_final.py
python -m fc_access.market_replay
```

The unit suite includes actual Node bridge tests, loopback HTTP behavior,
transaction fault/restart/duplicate prevention, pricing edge cases, source
provenance and artifact checks. Missing Node is an error. The final validator
also verifies all seven task_07 criteria, file hashes, privacy and committed
bytes against Git. It requires the final deliverable commit.

Historical artifact tests replay each retained checkpoint at its recorded time.
That is deterministic evidence review, not proof of a currently attached browser.
These additional **read-only** commands evaluate the retained evidence using the
live validators' original freshness rules (browser and transaction evidence age
out after 24 hours):

```text
python tests/validate_browser_live.py
python tests/validate_capabilities_live.py
python tests/validate_transaction_live.py
```

An aged checkpoint must not trigger a new purchase. The frozen independent
assessment and evidence hashes remain in
[final/assessment.json](docs/research/final/assessment.json) and
[final/manifest.json](docs/research/final/manifest.json).

## Fresh authenticated readback without a purchase

1. Start `python -m fc_access.transaction_server` in one terminal. It binds only
   to **127.0.0.1:8768**. If another process already owns that port, identify it;
   preserve unrelated services. Do not restart an existing working bridge.
2. In the signed-in Edge profile, open `edge://extensions`, enable Developer
   mode, select **Load unpacked**, and choose this repository's
   `browser/transaction-bridge` directory (version 0.3.0, protocol 3). Return to
   the existing official HTTPS EA Ultimate Team Web App tab and click
   **FC one-shot transaction bridge**. Its `TXN` badge proves attachment only.
   Finish any normal EA login/challenge directly in Edge. Never copy cookies,
   tokens, passwords or account identifiers into a terminal or report.
3. In another terminal run the attachment-only prerequisite:

   ```text
   python tests/check_transaction_prerequisite.py
   ```

4. Read and independently assess the original acquired card's current listing:

   ```text
   python -m fc_access.readback --output private-captures/listing.json
   ```

   Use a new output filename for each read. This command dispatches exactly one
   `transfer_list` read, requests native cache invalidation through protocol 3,
   and requires a fresh authenticated FC27 tradepile response. It uses the
   original public correlation key from `transaction/live.json` to match the
   physical-item pseudonym, exact card version, PC platform, original listing
   trade, bid 200, BIN 250 and active state with positive remaining expiry.
   It exits nonzero with UNVERIFIED if the bridge is detached, the snapshot is
   cached, the listing is expired/sold/absent, identity differs or evidence is
   older than 120 seconds. A later expired/sold state does not invalidate the
   historical acquisition/listing demonstration. This command does not prove a
   sale or realized profit. Independent **acquisition** proof remains the new
   owned item and exact 200-coin debit in the original journal.

Do not replay `python -m fc_access.transaction`, delete/reset its journal, or
buy/list/relist another card to reproduce this audit. That write runner is
retained for source review and the original bounded experiment, not required by
the reproduction commands above. Preserve all intents after any timeout. The
readback tool cannot overwrite retained evidence and never dispatches writes.

The read-only research adapter can also reproduce one authenticated read with
the separate `browser/read-bridge` extension and `python -m fc_access.read_server`
on 127.0.0.1:8767. Attach it by its own extension button, then run:

```text
python tests/check_read_prerequisite.py
python -m fc_access.harness --output private-captures/coins.json read edge coins
python -m fc_access.harness --output private-captures/transfer-list.json read edge transfer_list
```

Space reads by at least 30 seconds. These adapter calls use a new correlation
key; use `fc_access.readback` for original-card identity verification. The older
read bridge's native cache freshness is limited; a cache-only response is not
new transaction proof. Direct HTTP remains UNVERIFIED because no trusted
in-memory session provider was available.

## Evidence and privacy

All five required documents are under `docs/research/`: repository-analysis,
confirmed-capabilities, market-strategy, execution-architecture and
obj002-handoff. The final report links each working function and remaining gap.
The sanitized validation summary records exact argv, exit codes, test counts
and proof boundaries. `{python}` in JSON command records means the Python
interpreter running the checks; the shell examples above use `python`.

Keep secrets and personal account identifiers out of every artifact. The
positive response schema retains only task-required game telemetry, coin
readbacks/deltas, public card definitions and per-run hashed item/trade IDs.
No names, email addresses, account/persona IDs, session values or arbitrary
service error text are retained. `session_header_present` is a boolean, and
`evidence_key` is a non-authenticating correlation salt, not a login secret.
The retained native responses are local engineering observations, not
tamper-proof attestation. Ignore `private-captures/` for fresh local results and
review any future exports before committing them. Never retain a browser
profile, raw HAR, cookie jar or login dump.

Git excludes existing `.orchestrator/` runtime state and fresh private captures.
The original tracked objective is preserved byte-for-byte. `.gitattributes`
disables newline conversion so pinned evidence/source hashes survive checkout.

To repeat the complete deterministic audit after the deliverable commit:

```text
python -m unittest discover -s tests -p test_*.py
python tests/validate_final.py
git diff --check
git diff --cached --check
```
