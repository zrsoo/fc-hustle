"""Record real final-check outcomes; no trading runner or capture generator is invoked.

This maintainer command refreshes the audit artifacts and then runs checks. The
ordinary reproduction entry points (unittest/validate_final) are read-only.
"""
from datetime import datetime, timezone
import json
import re
import shutil
import subprocess
import sys

from final_audit import (ROOT, BASE_HEAD, COMMIT_SUBJECT, OBJECTIVE, OBJECTIVE_SHA,
                         deliverables, digest, evidence_assessment, privacy_findings)


def write(name, value):
    path = ROOT / "docs/research/final" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    if not shutil.which("node"):
        raise SystemExit("Node is required; do not accept skipped JavaScript checks")
    write("assessment.json", evidence_assessment())
    write("validation-summary.json", {"status": "RUNNING", "checks": []})
    excluded = {"docs/research/final/manifest.json", "docs/research/final/validation-summary.json"}
    manifest = {"schema": 1, "baseline_head": BASE_HEAD, "expected_commit_subject": COMMIT_SUBJECT,
                "unchanged_tracked_objective": {"path": OBJECTIVE, "sha256": OBJECTIVE_SHA},
                "excluded_unrelated_state": [".orchestrator/", "private-captures/"],
                "sha256": {p.relative_to(ROOT).as_posix(): digest(p) for p in deliverables()
                           if p.relative_to(ROOT).as_posix() not in excluded}}
    write("manifest.json", manifest)
    commands = [
        ["{python}", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        ["{python}", "tests/validate_browser_live.py"],
        ["{python}", "tests/validate_capabilities_live.py"],
        ["{python}", "tests/validate_transaction_live.py"],
        ["git", "diff", "--check"],
        ["git", "diff", "--cached", "--check"],
    ]
    checks = []
    for command in commands:
        argv = [sys.executable if part == "{python}" else part for part in command]
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=120)
        combined = result.stdout + result.stderr
        match = re.search(r"Ran (\d+) tests?", combined)
        check = {"command": command, "exit_code": result.returncode,
                 "tests_run": int(match[1]) if match else 0}
        if "unittest" in command:
            check["skipped_tests"] = bool(re.search(r"skipped=|skipped '|\.\.\. skipped", combined))
            if check["skipped_tests"]:
                check["exit_code"] = 1
        if len(command) == 2 and command[1].startswith("tests/validate_"):
            data = json.loads(result.stdout)
            check["reported_status"] = data["status"]
            check["errors"] = data.get("errors", [])
        checks.append(check)
        print(json.dumps(check), flush=True)
        if result.returncode:
            # Failure output stays local; the committed summary contains only
            # allowlisted status/errors. Never save arbitrary browser messages.
            print(combined, file=sys.stderr)
    paths = deliverables()
    findings = [f for p in paths for f in privacy_findings(p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8"))]
    summary = {"task": "task_07", "checked_at": datetime.now(timezone.utc).isoformat(),
               "status": "PASS" if all(c["exit_code"] == 0 for c in checks) and not findings else "FAIL",
               "checks": checks, "privacy": {"files_reviewed": len(paths), "findings": findings,
                   "scope": "All retained deliverables; allowlisted native schemas, pseudonymous IDs and concrete secret/account-field signatures."},
               "manifest_sha256": digest(ROOT / "docs/research/final/manifest.json"),
               "proof_boundary": "Actual offline/checkpoint validations and freshness checks on existing captures; no new EA request, browser action or mutation.",
               "git_review": "Final validate_final.py requires committed byte equality, preserved baseline objective and exclusion of unrelated runtime/private files."}
    write("validation-summary.json", summary)
    print(json.dumps({"status": summary["status"], "privacy_findings": findings}))
    return int(summary["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
