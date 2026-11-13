"""Build an explicit sanitized publication file list; does not stage or commit."""
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fc_access import release_audit_v1 as a


def main():
    a.preserve()
    entry = a.load(a.OUT + "entry.json")
    controls = [a.OUT + p for p in ("payload-manifest.json", "release-checks.json", "release-checks.txt")]
    candidates = set(subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=a.ROOT).decode().split("\0"))
    candidates.update(subprocess.check_output(["git", "diff", "--name-only", entry["baseline_head"]], cwd=a.ROOT).decode().splitlines())
    included = []
    excluded = []
    for path in sorted(candidates - {""}):
        if path == "AGENTS.md" or any(x in path for x in ("__pycache__", ".orchestrator/", "private-captures/")) or a.mutable_artifact(path):
            excluded.append(path)
            continue
        a.require(path.startswith(("browser/", "fc_access/", "experiments/", "docs/research/", "tests/")), "unreviewed_publication_scope")
        if path not in controls:
            raw = a.read(path)
            if path.endswith(".json"):
                a.private_fields(json.loads(raw))
            included.append(path)
    manifest = {"schema": 1, "task": "001c-07", "baseline_head": entry["baseline_head"],
                "files": {p: a.sha(a.read(p)) for p in included}, "git_sealed_control_files": controls,
                "control_policy": "Manifest and final test receipt are sealed by the normal Git commit; self-hashing test output would be circular.",
                "excluded_preexisting": excluded, "secret_policy": "Positive projected native schemas, presence-only authentication, local trade/item/owner/epoch IDs. No authentication/session values.",
                "no_autonomous_actor_loops": True}
    (a.ROOT / a.OUT / "payload-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"files": len(included), "excluded": len(excluded)}))


if __name__ == "__main__":
    main()
