"""Record task-entry bytes and actual offline baselines in a NEW audit directory.

This recorder never connects to Edge/EA or runs a live collector. It refuses to
overwrite its outputs. Public upstream inspection is a separate audit action.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/001c/001c-01"


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def save(name, value):
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    paths = git("ls-files").splitlines()
    # Git blob hashes and disk SHA-256 serve different purposes; Windows checkout
    # line endings must not be confused with a change to historical evidence.
    save("entry.json", {
        "schema": 1, "task": "001c-01", "recorded_utc": utc(),
        "head": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
        "upstream": git("rev-parse", "--abbrev-ref", "@{upstream}"),
        "status_porcelain": git("status", "--porcelain=v1", "--untracked-files=all").splitlines(),
        "initial_user_status": ["?? AGENTS.md"],
        "tracked_diff": git("diff", "--stat", "HEAD"),
        "python": platform.python_version(), "node": subprocess.check_output(["node", "--version"]).decode().strip(),
        "browser_attachment": "NOT_CHECKED", "authentication": "NOT_CHECKED",
        "new_EA_requests": 0, "account_mutations": 0,
    })
    save("preservation.json", {
        "schema": 1, "baseline_head": git("rev-parse", "HEAD"),
        "policy": "All task-entry tracked files and user AGENTS.md remain byte-identical; new audit files only.",
        "sha256": {p: digest((ROOT / p).read_bytes()) for p in paths + ["AGENTS.md"]},
        "git_blobs": {line.split("\t", 1)[1]: line.split()[1]
                      for line in git("ls-files", "--stage").splitlines()},
        "historical_seals": ["docs/research/final/manifest.json", "docs/research/001b/preservation.json",
                             "docs/research/001b/t7/manifest.json",
                             "experiments/market_discovery_followup_v1/runs/20261111T230544Z/preserved-seals.json"],
    })
    commands = [
        ("regression", ["{python}", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]),
        ("001b-precommit", ["{python}", "tests/validate_001b.py", "--precommit"]),
        ("001b-historical-commit", ["{python}", "tests/validate_001b.py"]),
        ("001-historical-final", ["{python}", "tests/validate_final.py"]),
        ("followup-retained", ["{python}", "-m", "experiments.market_discovery_followup_v1", "validate", "--input",
          "experiments/market_discovery_followup_v1/runs/20261112T062256Z/search.json"]),
        ("partial-benchmark-retained", ["{python}", "-m", "experiments.market_discovery_live_v1.validate", "--run-dir",
          "experiments/market_discovery_live_v1/runs/20261112T064306Z"]),
    ]
    checks = []
    for name, command in commands:
        start, mark = utc(), time.monotonic()
        result = subprocess.run([sys.executable if p == "{python}" else p for p in command],
                                cwd=ROOT, capture_output=True, timeout=120)
        output = result.stdout + result.stderr
        logfile = "baseline-" + name + ".txt"
        with (OUT / logfile).open("xb") as stream:
            stream.write(output)
        row = {"id": name, "command": command, "started_utc": start, "ended_utc": utc(),
               "duration_seconds": round(time.monotonic()-mark, 3), "exit_code": result.returncode,
               "output": logfile, "output_sha256": digest(output)}
        checks.append(row)
        print(json.dumps(row), flush=True)
    save("baseline.json", {"schema": 1, "checks": checks, "new_EA_requests": 0, "account_mutations": 0})


if __name__ == "__main__":
    main()
