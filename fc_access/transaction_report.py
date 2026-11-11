"""Render the current transaction checkpoint; offline tests are never live proof."""
import hashlib
import json
from pathlib import Path

from .transaction import DIRECTORY, JOURNAL, ROOT
from .transaction_checks import assess


CRITERIA = [
    "Exactly one inexpensive tradeable player, exact card/version and auction; no trading loop",
    "Fresh owned-item inventory and exact acquisition coin delta after Buy Now",
    "Move acquired physical item where required and independently read its destination",
    "Fresh active listing with physical item, new live trade ID, bid/BIN and one-hour duration",
    "Fresh status; eligible expired item relisted only if present; otherwise relist UNVERIFIED",
    "Timeout/ambiguous writes reconciled before any retry; duplicate dispatch prevented",
    "Observed transport comparison; direct HTTP only when all essential operations work",
    "Failure reported PARTIAL/BLOCKED with exact errors and recovery; no source/mock/HTTP-only proof",
]


def write_report(record, journal=JOURNAL, destination=None):
    journal = Path(journal)
    destination = Path(destination) if destination else ROOT / "docs/research/purchase-to-list.md"
    errors, summary = assess(record)
    verification = {"task": "task_04", "status": "VERIFIED" if not errors else "PARTIAL/BLOCKED",
                    "evidence_sha256": hashlib.sha256(journal.read_bytes()).hexdigest(),
                    "checked_at": record["updated_at"], "criteria_errors": errors, "facts": summary,
                    "proof_boundary": "Only the recorded independent live reads can satisfy transaction criteria. Offline tests exercise guards and validation only."}
    verification_path = journal.parent / "verification.json"
    verification_path.write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    lines = ["# Purchase-to-list validation — task_04", "",
             f"Status: **{verification['status']}** at `{record['updated_at']}`. "
             f"Actual write intents: `{', '.join(record['intents']) or 'none'}`. "
             "The journal is [transaction/live.json](transaction/live.json); the independent assessment is "
             "[transaction/verification.json](transaction/verification.json).", "",
             "No completed transaction is inferred from native/HTTP success, prior task read access, source review, "
             "or synthetic tests. An empty write-intent map means no purchase, move, listing or relist was dispatched by this experiment.", "",
             "| Index | Acceptance criterion | Current evidence result |", "| --- | --- | --- |"]
    for i, description in enumerate(CRITERIA):
        lines.append(f"| {i} | {description} | {'; '.join(errors[i]) if i in errors else 'VERIFIED'} |")
    lines += ["", f"Purchase: `{summary['purchase']}`; movement: `{summary['movement']}`; listing: `{summary['listing']}`; "
              f"status reads: `{summary['status']}`; relist: **{summary['relist']}**.", "",
              "Retained identity, acquisition and listing readback fields (IDs are stable per-run pseudonyms):", "", "```json",
              json.dumps({k: v for k, v in summary.items() if k in {"identity", "acquisition_readback", "listing_readback", "eligible_expired_listing_present"}}, indent=2),
              "```", "",
              "The selected transport is **Edge native services**. The observed direct adapter result is "
              f"`{record.get('direct_probe', {}).get('error', 'UNVERIFIED')}`. "
              "There is no trusted in-memory direct HTTP session provider. The existing read-only bridge previously "
              "produced authenticated reads in task_03, but cannot perform writes. Its subsequent coin preflight returned "
              "`bridge_not_attached` ([preflight-coins.json](transaction/preflight-coins.json)). This final fallback decision "
              f"does not itself prove writes. Native purchase/listing proof is currently **{summary['purchase']}** / **{summary['listing']}**. Direct HTTP remains **UNVERIFIED**. "
              "No second purchase is authorized merely to compare transports. Reconsider the transport only if an "
              "independent trusted session provider and all essential-operation readbacks become available.", "",
              "Each row below is an actual command attempt. Null status/code means no such response was observed. "
              "Methods are dispatch contracts; they do not imply that a detached page executed them.", "",
              "| UTC | Phase / operation | Native dispatch contract | Request | Status | Exact error | EA code |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for a in record["attempts"]:
        r = a["result"]
        lines.append(f"| {a['at']} | {a['phase']} / {a['operation']} | `{a['method']}` | `{json.dumps(a['request'], sort_keys=True)}` | {r['status']} | `{r['error']}` | {r['ea_error_code']} |")
    lines += ["", "Historical experiment errors (preserved for reconciliation; current status is the assessment above): " + ("; ".join("`" + e["error"] + "`" for e in record["errors"]) or "none") + ".", "",
              "A successful fresh reconciliation can resolve a historical cached-read failure without repeating its write. "
              "The original cached snapshots and error remain in the journal alongside the later network readbacks.", "",
              "Write contracts were reviewed against the pinned upstream "
              "[page-inject.js](https://github.com/liusihang/fc27-copilot/blob/fa0fdde132715b2c09a4cff1e51736a1794d635e/extension/content/page-inject.js). "
              "`Item.bid(item, price)`, `Item.move([item], ItemPile.TRANSFER, false)` and "
              "`Item.list(item, startingBid, buyNowPrice, duration)` were initially source-level contracts; "
              "the current evidence result comes from independent live readback. "
              "Status is independently read from `requestTransferItems()`. Relist uses `Item.list` on exactly one "
              "eligible expired item, rather than a bulk relist operation. An expired item is eligible only if its "
              "physical/version IDs, unsold/tradeable state and prices satisfy the bounded command contract. "
              "No expiry is awaited, no listing is cancelled, and no expiry is fabricated just to test relisting.", "",
              "The new extension [browser/transaction-bridge](../../browser/transaction-bridge) is separate from the installed "
              "read-only and observer extensions. It contains locally authored code, no upstream executable code. "
              "The [source review](transaction/source-review.json) records exact file hashes. "
              "The inspection in [access-inspection.json](transaction/access-inspection.json) found no Edge debug port/pipe, "
              "Edge-owned listener or DevToolsActivePort marker; localhost CDP probes failed. Document Control returned "
              "no connected sessions. No browser restart, profile change, login navigation or credential export was attempted.", "",
              "The transaction server listens only on **127.0.0.1:8768** and exposes no arbitrary evaluation. "
              "Commands have strict fields and numeric/identity bounds. Native physical/trade IDs remain in the page; "
              "the journal contains stable per-run hashes. The journal's `evidence_key` is a random correlation key, "
              "not authentication material. Unknown response properties and exception messages are excluded. "
              "This is local engineering evidence, not tamper-proof attestation against a malicious local process.", "",
              "Reproduction and recovery if attachment is lost; completed mutations must never be repeated:", "",
              "1. The task started `python -m fc_access.transaction_server` in a hidden background process. "
              "If it has stopped, start that command from this workspace. Preserve unrelated services if port 8768 is occupied.",
              "2. In the existing signed-in Edge profile, open `edge://extensions`, enable Developer mode, "
              "choose **Load unpacked**, and select `C:\\hustle\\fc-hustle\\browser\\transaction-bridge`. "
              "Return to the existing official HTTPS EA Ultimate Team Web App tab and click **FC one-shot transaction bridge**. "
              "The reviewed version is 0.3.0 (protocol 3); legacy polling cannot attest the updated bridge. "
              "`TXN` means attached, not authenticated or transaction-verified. Do not restart Edge or export any session values.",
              "3. Run `python tests/check_transaction_prerequisite.py`. It checks only local extension attachment and "
              "does not depend on generated evidence, balances, market results, or transaction success. If a normal login/challenge "
              "is visible, complete it directly in EA; do not send account data to the harness.",
              "4. Run `python -m fc_access.transaction` **once**. No new permission is required: the objective already "
              "authorizes the single inexpensive experiment. Preflight must have fresh authenticated inventory, transfer-list "
              "and coin reads before any buy. One bounded 200–500 coin search seeds one exact card-version search; "
              "the runner selects a cheap matching auction with sufficient time remaining, revalidates its exact physical "
              "item/version/auction, and buys at most once. Native `tradable` is mapped to the retained `untradeable` "
              "boolean using the official factory contract in [native-tradability-contract.json](transaction/native-tradability-contract.json). "
              "Unknown tradability remains unknown. It verifies the exact coin debit "
              "and newly owned physical item before moving/listing. Listing uses the acquisition price as starting bid, "
              "50 coins higher as BIN, and 3600 seconds; EA acceptance and independently read active state determine validity. "
              "A rejected price band is a failure, not grounds for an automatic retry.",
              "5. The runner writes an intent to disk before each mutation, flushes it, and holds an OS lock for the whole run. "
              "Both journal and page suppress duplicate writes. It reads back state after errors/timeouts. "
              "After any persisted intent, restart first reads fresh inventory, transfer list, coins and status. "
              "An acknowledged purchase with the exact physical item and original coin debit can continue only the "
              "unwritten move/list stages; it never buys again. Missing buy responses or prior move/list intents remain "
              "reconciliation-only and stop PARTIAL/BLOCKED for inspection. "
              "**Preserve the journal after any intent; never delete it to retry.** "
              "If purchased but unlisted, identify the exact physical item and finish recovery in EA only after confirming "
              "no active listing exists. If there is no write intent, a new preflight archives the failed checkpoint and can "
              "proceed safely. Concurrent account mutations can invalidate the exact coin delta; such cases stop for reconciliation.",
              "6. Re-run the live validator and retain the generated report. A fresh transfer-list GET proves destination "
              "and listing; a later GET proves status. The requested one-hour duration is checked against the fresh expiry "
              "countdown with a bounded dispatch/read delay tolerance. Cached native snapshots without network freshness "
              "are rejected. The native repository cache is expired using `repositories.Item.setDirty` before purchased/transfer "
              "reads; the official contract is retained in [native-cache-contract.json](transaction/native-cache-contract.json). "
              "Historical cached reads remain in the journal and cannot themselves satisfy purchase proof. "
              "Relist remains UNVERIFIED when no eligible expired listing exists.", "",
              "Independent commands from the workspace:", "", "```text", "python tests/test_transaction.py",
              "python tests/test_transaction_bridge.py", "python tests/test_transaction_artifacts.py",
              "python tests/validate_transaction_live.py", "```", "",
              "The first two execute synthetic fault injection and actual authored JavaScript/loopback-server behavior; "
              "fixtures are written only to temporary directories. The artifact check compares this report, review hashes "
              "and retained assessment with the real journal. The live validator is read-only and must fail while any required "
              "live proof is absent; it never generates transaction evidence. Its 24-hour checkpoint freshness requirement "
              "does not authorize repeating a purchase when evidence ages out. " +
              ("The required live proof remains absent; the task is PARTIAL/BLOCKED." if errors else "The retained independent live proof satisfies this bounded experiment."), ""]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")
    return verification
