"""Criterion 7: verify actual normal-Git publication, not a claimed receipt.

Read-only; requires network access to query the repository's advertised main.
No credentials, authentication configuration or remote URLs are printed.
"""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fc_access import release_audit_v1 as a
from fc_access.evidence import is_evidence


def git(*args):
    return subprocess.check_output(["git", *args], cwd=a.ROOT, stderr=subprocess.PIPE)


def validate():
    entry = a.load(a.OUT + "entry.json")
    manifest = a.load(a.OUT + "payload-manifest.json")
    a.preserve()
    a.require(git("branch", "--show-current").decode().strip() == "main", "not_main")
    a.require(subprocess.run(["git", "merge-base", "--is-ancestor", entry["baseline_head"], "HEAD"],
                             cwd=a.ROOT, capture_output=True).returncode == 0, "history_rewritten")
    head = git("rev-parse", "HEAD").decode().strip()
    a.require(head != entry["baseline_head"], "work_not_committed")
    remote = git("ls-remote", "--exit-code", "origin", "refs/heads/main").decode().split()
    a.require(len(remote) == 2 and remote[0] == head, "main_not_published")
    a.require(git("rev-parse", "origin/main").decode().strip() == head, "upstream_not_updated")
    a.require(not git("diff", "HEAD", "--name-only").strip(), "uncommitted_tracked_change")
    changed = set(filter(None, git("diff", "--name-only", entry["baseline_head"], "HEAD").decode().splitlines()))
    expected = set(manifest["files"]) | set(manifest["git_sealed_control_files"])
    a.require(changed == expected, "publication_scope_mismatch")
    for path in sorted(expected):
        a.require(path != "AGENTS.md" and not any(p in path for p in (".orchestrator/", "private-captures/", "__pycache__"))
                  and not a.mutable_artifact(path), "excluded_or_unrelated_file_published")
        raw = a.read(path)
        a.require(git("show", "HEAD:" + path) == raw, "committed_bytes_differ:" + path)
        if is_evidence(path) and path in manifest["files"]:
            a.require(hashlib.sha256(raw).hexdigest() == manifest["files"][path], "payload_hash_mismatch:" + path)
        if path.endswith(".json"):
            a.private_fields(json.loads(raw))
        if path.endswith(".py"):
            tree = ast.parse(raw)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    a.require(node.name not in {"acquirer_loop", "bidder_loop", "run_actors", "auto_enroll"}, "autonomous_actor_entrypoint")
    # Historical base paths were not staged, deleted or modified. Only additions.
    statuses = git("diff", "--name-status", entry["baseline_head"], "HEAD").decode().splitlines()
    a.require(all(s.startswith("A\t") for s in statuses), "preexisting_tracked_content_modified")
    a.require(not git("ls-files", "AGENTS.md").strip(), "unrelated_agents_file_staged")
    receipts = a.load(a.OUT + "release-checks.json")
    a.require(receipts["command"] == ["{python}", "tests/test_release_audit.py"] and receipts["exit_code"] == 0,
              "release_tests_not_recorded_passing")
    a.require(a.sha(a.read(a.OUT + receipts["output"])) == receipts["output_sha256"], "release_test_output_changed")
    return {"status": "PASS", "branch": "main", "commit": head, "published_paths": len(expected),
            "normal_history": True, "remote_main_matches": True, "unrelated_state_preserved": True}


if __name__ == "__main__":
    try:
        print(json.dumps(validate(), indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        # Avoid logging arbitrary git stderr (which can include auth details).
        reason = str(error) if isinstance(error, ValueError) else type(error).__name__
        print(json.dumps({"status": "FAIL", "reason": reason}))
        sys.exit(1)
