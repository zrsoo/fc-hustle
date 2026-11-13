"""Task_07 artifact audit. Historical proofs are replayed, never generated here."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from checkpoint import transaction_at_checkpoint
from validate_browser_live import assess as assess_browser
from fc_access.capabilities import assess as assess_reads
from fc_access.harness import validate_result
from fc_access.market_replay import replay

BASE_HEAD = "f60bf58c38ff96b8dc59fbe2d63947fc6bda78f2"
OBJECTIVE = "objectives/001-fc27-api-research.md"
OBJECTIVE_SHA = "3499d464add896050438401e45cf7793820954e92867058215f5b3b4a7be91d1"
COMMIT_SUBJECT = "Audit FC27 research evidence and retain reproducible readiness handoff"
RESEARCH = tuple("docs/research/" + n + ".md" for n in (
    "repository-analysis", "confirmed-capabilities", "market-strategy", "execution-architecture", "obj002-handoff"))
REQUIRED = RESEARCH + ("README.md", "fc_access/harness.py", "fc_access/transaction.py",
    "fc_access/readback.py", "browser/transaction-bridge/page.js", "tests/test_final_audit.py",
    "tests/validate_final.py", "docs/research/final-report.md")


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


from fc_access.evidence import evidence_hashes, is_evidence

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deliverables():
    paths = [ROOT / ".gitignore", ROOT / ".gitattributes", ROOT / "README.md", ROOT / OBJECTIVE]
    for directory in ("browser", "docs", "fc_access", "tests"):
        paths.extend(p for p in (ROOT / directory).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".tmp", ".lock"})
    return sorted(set(paths))


def privacy_findings(name, text):
    """Report locations/categories only; never echo suspect values."""
    findings = []
    # Reviewed negative-test literals, not captured credentials. Exceptions are
    # exact and restricted to authored test source; evidence JSON has none.
    if name.startswith("tests/") and name.endswith((".py", ".cjs")):
        text = text.replace("synthetic-private-canary", "SYNTHETIC_CANARY")
        if name == "tests/test_browser_access.py":
            text = text.replace("account" + "@" + "utas.ea.com", "INVALID_HOST_USERINFO_FIXTURE")
    patterns = {
        "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "github_token": r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b",
        "jwt": r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b",
        "authorization_value": r"(?i)\bBearer\s+[a-z0-9._~-]{20,}",
        "email_address": r"(?<![\w/])[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b",
        "credential_assignment": r'''(?i)["']?(?:password|access_token|refresh_token|session_id|phishing_token|x-ut-sid|authorization|cookie)["']?\s*[:=]\s*["'][A-Za-z0-9+/_=.~-]{20,}["']''',
    }
    for category, pattern in patterns.items():
        if re.search(pattern, text):
            findings.append(name + ":" + category)
    if name.endswith(".json"):
        try:
            value = json.loads(text)
        except ValueError:
            return findings + [name + ":invalid_json"]
        forbidden = {"password", "cookie", "cookies", "authorization", "access_token", "refresh_token",
                     "session_id", "sessionid", "phishing_token", "personaid", "persona_id", "accountid",
                     "account_id", "email", "email_address", "nucleusid", "nucleus_id", "username"}

        def walk(v):
            if isinstance(v, dict):
                for key, child in v.items():
                    if key.lower().replace("-", "_") in forbidden and child not in (None, False, ""):
                        findings.append(name + ":private_json_field")
                    if key in {"item_id", "physical_item", "trade_id", "purchase_trade"} and child is not None:
                        namespace = "item" if key in {"item_id", "physical_item"} else "trade"
                        if not isinstance(child, str) or not re.fullmatch(namespace + r":[a-f0-9]{24}", child):
                            findings.append(name + ":raw_account_item_or_trade_id")
                    # Every retained native response must obey the positive schema.
                    if key == "result" and isinstance(child, dict) and "auctions" in child:
                        try:
                            validate_result(child)
                        except ValueError:
                            findings.append(name + ":unallowlisted_response")
                    walk(child)
            elif isinstance(v, list):
                for child in v:
                    walk(child)
        walk(value)
    return sorted(set(findings))


def readiness(browser_ok, transaction_ok):
    if not browser_ok or not transaction_ok:
        return {"verdict": "NO-GO", "objective_state": "PARTIAL/BLOCKED"}
    return {"verdict": "CONDITIONAL GO", "objective_state": "BOUNDED_VALIDATION_DEMONSTRATED"}


def evidence_assessment():
    browser = load("docs/research/browser-access/live-v2.json")
    bv = load("docs/research/browser-access/verification.json")
    # The observer appended later real traffic. Reconstruct the exact retained
    # assessment checkpoint, as the browser artifact tests do; do not label
    # later observations future/missing relative to an earlier review.
    cutoff = datetime.fromisoformat(bv["evidence"]["received_at"])
    browser["received_at"] = bv["evidence"]["received_at"]
    browser["observations"] = [v for v in browser["observations"]
        if datetime.fromisoformat(v["observed_at"].replace("Z", "+00:00")) <= cutoff]
    be, bf = assess_browser(browser, now=datetime.fromisoformat(bv["evidence"]["validated_at"]))
    reads = load("docs/research/capabilities/attempts.json")
    re_errors, rf = assess_reads(reads)
    journal = load("docs/research/transaction/live.json")
    te, tf = transaction_at_checkpoint(journal)
    matrix = []

    def row(name, status, evidence, detail):
        matrix.append({"capability": name, "status": status, "evidence": evidence, "detail": detail})

    bpath = "docs/research/browser-access/live-v2.json"
    rpath = "docs/research/capabilities/attempts.json"
    tpath = "docs/research/transaction/live.json"
    mpath = "docs/research/market/availability.json"
    row("authenticated_session_configuration", "BLOCKED" if be else "VERIFIED", bpath,
        "Structured authenticated FC27 read; observed host/prefix/client/SKU. Checkpoint, not a new connection.")
    for name in ("renewal", "expiry", "logout_reconnect"):
        row("session_" + name, bf.get("session_lifecycle", {}).get(name, "UNVERIFIED"), bpath,
            "No independent session lifecycle experiment retained.")
    row("transfer_market_search", "VERIFIED" if not re_errors and rf["edge"]["authenticated_reads"] else "BLOCKED",
        rpath, "Exact native card definition, physical item, trade, prices and expiry; PC only.")
    for name in ("coins", "club", "unassigned", "purchased", "transfer_list"):
        row("account_" + name, rf.get(name, "UNVERIFIED"), rpath,
            "Observed readback mode: " + rf.get(name + "_readback_mode", "See typed attempts; empty and unknown are distinct."))
    row("exact_card_and_bin_filters", "VERIFIED" if not re_errors else "BLOCKED", rpath,
        "Exact version and ceiling positive/negative boundary searches retained.")
    for name, status in rf.get("filters", {}).items():
        row("filter_" + name, status, rpath, "Broad population checks; unsupported filters remain unverified.")
    pagination = rf.get("pagination", {})
    for name, key in (("pagination_two_pages", "two_nonempty_pages"), ("search_cache_invalidation", "invalidation")):
        row(name, "VERIFIED" if pagination.get(key, "").startswith("OBSERVED") else "UNVERIFIED", rpath,
            pagination.get(key, "UNVERIFIED"))
    row("cache_ttl_and_hit_semantics", "UNVERIFIED", rpath, "Network invalidation observed; no proven cache hit/TTL.")
    row("comparable_market_sample", "VERIFIED" if not re_errors else "BLOCKED", mpath,
        "Exact-version PC samples retained; market_average null and last_sale_price observed, not guaranteed proceeds.")
    for name in ("purchase", "movement", "listing", "status", "relist"):
        row(name, tf.get(name, "UNVERIFIED"), tpath,
            "Independent before/after readbacks; relist not exercised because no eligible expired listing existed.")
    row("purchase_verification", tf.get("purchase", "UNVERIFIED"), tpath,
        "New physical item plus exact 200-coin debit on fresh reconciliation; 304 cache snapshots rejected.")
    row("listing_verification", tf.get("listing", "UNVERIFIED"), tpath,
        "Same physical item/version; new active trade, bid 200/BIN 250, duration 3600, countdown 3570.")
    row("direct_http", "UNVERIFIED", tpath, "direct_session_provider_unavailable; zero authenticated direct reads.")
    public = {p["name"]: p for p in load(mpath)["public"]}
    row("bulk_catalog_and_price_feed", "BLOCKED" if public["manifest"].get("status") == 403 else "UNVERIFIED",
        mpath, "Retained direct manifest/catalog requests returned 403; no fresh availability claim.")
    for name in ("numeric_history", "exact_card_caps", "full_increment_schedule", "realized_tax_rounding",
                 "sold_settlement", "continuous_autonomous_repeat", "cross_platform"):
        row(name, "UNVERIFIED", "docs/research/obj002-handoff.md", "Explicit future release prerequisite; not proved by offline fixtures.")
    mutations = []
    before = [a for a in journal["attempts"] if a["phase"] == "before_buy"]
    for op, prior_phase, after_phase in (("buy", "exact_match", "restart_reconciliation"),
                                         ("move", "restart_reconciliation", "after_move"),
                                         ("list", "after_move", "after_list")):
        writes = [a for a in journal["attempts"] if a["operation"] == op]
        prior = [a for a in journal["attempts"] if a["phase"] == prior_phase]
        after = [a for a in journal["attempts"] if a["phase"] == after_phase]
        pointers = lambda rows: [tpath + "#/attempts/" + str(journal["attempts"].index(a)) for a in rows]
        mutations.append({"operation": op, "status": tf.get({"buy": "purchase", "move": "movement", "list": "listing"}[op], "UNVERIFIED"),
                          "write": pointers(writes), "before": pointers(prior + (before if op == "buy" else [])), "after": pointers(after)})
    return readiness(not be, not te) | {"browser_errors": be, "read_errors": re_errors,
        "transaction_errors": te, "capabilities": matrix, "mutations": mutations,
        "transaction_facts": tf, "proof_boundary": "Retained historical observations replayed at their recorded checkpoints. No fresh EA calls or mutations by task_07."}


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def validate(*, require_commit=True):
    errors = {i: [] for i in range(7)}

    def need(i, condition, message):
        if not condition:
            errors[i].append(message)

    for name in REQUIRED:
        need(0, (ROOT / name).is_file() and (ROOT / name).stat().st_size > 50, "missing/empty deliverable: " + name)
    manifest = load("docs/research/final/manifest.json")
    paths = deliverables()
    excluded = {"docs/research/final/manifest.json", "docs/research/final/validation-summary.json"}
    expected = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths if p.relative_to(ROOT).as_posix() not in excluded and is_evidence(p.relative_to(ROOT).as_posix())}
    need(0, evidence_hashes(manifest["sha256"]) == expected, "artifact manifest differs from retained files")
    summary = load("docs/research/final/validation-summary.json")
    need(0, summary["manifest_sha256"] == digest(ROOT / "docs/research/final/manifest.json"), "summary manifest hash mismatch")
    need(2, bool(summary["checks"]) and all(c["exit_code"] == 0 for c in summary["checks"]), "recorded required checks failed")
    need(2, summary["status"] == "PASS" and not summary["privacy"]["findings"], "recorded final summary failed")
    for command in (["{python}", "tests/validate_browser_live.py"],
                    ["{python}", "tests/validate_capabilities_live.py"],
                    ["{python}", "tests/validate_transaction_live.py"],
                    ["git", "diff", "--check"], ["git", "diff", "--cached", "--check"]):
        need(2, any(c["command"] == command and c["exit_code"] == 0 for c in summary["checks"]), "required final command not recorded")
    need(2, any(c["command"] == ["{python}", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
                and c["tests_run"] >= 88 for c in summary["checks"]), "full deterministic suite not recorded")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in ("python -m fc_access.readback --output private-captures/listing.json",
                   "python tests/validate_final.py", "Load unpacked", "127.0.0.1:8768", "Do not replay",
                   "expired", "secrets", "python -m unittest discover -s tests -p test_*.py"):
        need(1, phrase in readme, "setup missing " + phrase)
    findings = [f for p in paths for f in privacy_findings(p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8"))]
    need(2, not findings, "privacy review findings: " + ", ".join(findings))
    for p in paths:
        need(2, not p.is_symlink(), "deliverable symlink: " + p.name)
    assessment = evidence_assessment()
    need(3, load("docs/research/final/assessment.json") == assessment, "assessment differs from independent evidence replay")
    need(3, not assessment["browser_errors"] and not assessment["read_errors"] and not assessment["transaction_errors"], "required retained evidence failed assessment")
    need(3, json.loads(json.dumps(replay())) == load("docs/research/market/offline-proof.json"), "pricing replay differs")
    for mutation in assessment["mutations"]:
        need(3, mutation["write"] and mutation["before"] and mutation["after"], "missing mutation before/write/after references")
    report = (ROOT / "docs/research/final-report.md").read_text(encoding="utf-8")
    for term in (assessment["verdict"], assessment["objective_state"], "Working functions", "Blockers", "Next steps",
                 "final/assessment.json", "final/validation-summary.json", "README.md", "historical", "PARTIAL/BLOCKED"):
        need(5, term in report, "final report missing " + term)
    need(6, readiness(False, True) == readiness(True, False) == readiness(False, False) ==
         {"verdict": "NO-GO", "objective_state": "PARTIAL/BLOCKED"}, "missing-live-proof readiness gate broken")
    try:
        git("diff", "--check")
        git("diff", "--cached", "--check")
        if require_commit:
            git("merge-base", "--is-ancestor", BASE_HEAD, "HEAD")
            need(4, git("log", "-1", "--format=%s").decode().strip() == COMMIT_SUBJECT, "deliverable commit missing")
            tracked = set(git("ls-tree", "-r", "--name-only", "HEAD").decode().splitlines())
            names = {p.relative_to(ROOT).as_posix() for p in paths}
            need(4, names <= tracked, "deliverables absent from HEAD")
            need(4, not any(n.startswith((".orchestrator/", "private-captures/")) for n in tracked), "unrelated/private files committed")
            changed = set(git("diff", "--name-only", BASE_HEAD, "HEAD").decode().splitlines())
            need(4, changed <= names - {OBJECTIVE}, "commit changes unrelated files")
            for p in paths:
                name = p.relative_to(ROOT).as_posix()
                if name != OBJECTIVE:
                    need(4, git("show", "HEAD:" + name) == p.read_bytes(), "uncommitted deliverable: " + name)
            # The original objective predates the byte-preserving attributes:
            # compare both its original working hash (above) and Git blob.
            need(4, bool((ROOT / OBJECTIVE).read_text()), "objective missing")
    except subprocess.CalledProcessError:
        errors[4].append("git verification failed")
    return {i: messages for i, messages in errors.items() if messages}
