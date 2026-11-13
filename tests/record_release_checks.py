"""Record independent offline reproduction; never update previous evidence."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/001c/001c-07"


def main():
    jobs = [["tests/" + name] for name in (
        "test_001c01_audit.py", "test_bidding_v1.py", "check_bidding_v1_artifacts.py",
        "test_watched_bulk_artifacts.py", "test_search_validation_artifacts.py",
        "test_durability_v1.py", "test_durability_artifacts.py", "test_e2e_v1.py",
        "test_e2e_artifacts.py", "test_e2e_live_v2.py", "test_e2e_reconcile_v1.py",
        "test_e2e_complete_artifacts.py", "validate_001c06_complete.py", "test_market_pricing.py",
        "test_transaction.py")]
    jobs += [["tests/run_offline_suite.py", "tests/" + n] for n in (
        "test_watched_bulk_v1.py", "test_search_validation_v1.py", "test_readiness_regressions.py")]
    jobs += [["tests/check_e2e_v1_acceptance.py"],
             ["-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]]
    records = []
    for i, args in enumerate(jobs):
        started = datetime.now(timezone.utc)
        result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, timeout=600)
        raw = result.stdout + result.stderr
        name = f"check-{i:02d}.txt"
        (OUT / name).write_bytes(raw)
        records.append({"command": ["{python}", *args], "exit_code": result.returncode,
                        "started_at": started.isoformat(), "ended_at": datetime.now(timezone.utc).isoformat(),
                        "output": name, "output_sha256": hashlib.sha256(raw).hexdigest()})
        print(json.dumps({"command": args, "exit_code": result.returncode}), flush=True)
    (OUT / "checks.json").write_text(json.dumps({"checks": records}, indent=2) + "\n")


if __name__ == "__main__":
    main()
