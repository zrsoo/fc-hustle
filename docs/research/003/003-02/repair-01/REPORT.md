# Repair 01: baseline scope after production publication

The supervisor's post-publication recheck of `b899ab4` failed one of 799 Python
tests and the independent 003-01 validator. Both reported
`unrelated_baseline_changes`. All 27 Node suites passed. The failed recheck is
retained here, rather than reinterpreted as a production or interpreter failure.

The 003-01 preservation validator applied its task-only changed-path allowance to
`BASELINE..HEAD`. After committing 003-02, HEAD legitimately included production
files outside the earlier baseline-review task. Prepublication runs could not
expose this because uncommitted changes are outside that Git range.

The corrected check audits `BASELINE..BASELINE_REVIEW`, the actual completed
003-01 review commit `fd43ec1b051611377d66735f67813d69c3c77338`. It requires both
baseline-to-review and review-to-current-HEAD ancestry. The review's original
allowed paths are still checked, and all immutable evidence, backups, consumed
state, account reconciliation and Objective 002 checks remain enforced.
No current implementation hash or source byte identity check was introduced.

Four regressions cover later production commits, rejection of unrelated changes
inside the original review, rejection of either broken ancestry boundary, and the
actual published baseline/review/production history. The targeted baseline suite
passed all 17 tests under the supervisor's Python 3.13.17. The independent 003-01
assessment also passed all six criteria under that executable.

Captured failure files retain the supervisor's original outputs/receipts. In
`failed-python-suites.json`, the original `python-00-stderr.txt` and
`python-00-stdout.txt` references map to `failed-python-stderr.txt` and
`failed-python-stdout.txt` here. In `failed-independent-suites.json`, the relevant
`independent-04-stdout.txt` maps to `failed-baseline-stdout.txt`. These are failure
records, separate from the current receipts in the parent directory.

The complete Python, Node and independent inventories are rerun with
`C:\hustle\agent-orchestrator\.venv\Scripts\python.exe`; final results are in the
parent receipts and updated 003-02 report. This repair changes validation scope
only. It makes no EA requests, changes no production runtime or historical
checkpoint, and does not launch live production.

The supervisor-Python rerun completed successfully: 803 Python tests in 320.848
seconds, all 27 Node suites, and all five independent validators. Current receipts
retain the actual commands and outputs. The acceptance check passed criteria 0–8
before publication and kept criterion 9 PUBLICATION_PENDING until commit/push.
The baseline and complete acceptance checks are run again after publication.
