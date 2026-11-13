"""Offline artifact checks for task_01; does not execute or import upstream code.

Run independently from the workspace with: python tests/test_repository_research.py
The retained GitHub observations are evidence records, not cryptographic proof of
remote authenticity or an OS execution trace. Live FC27 validation is out of scope.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import unittest
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/research/repository-analysis.md"
LEDGER = ROOT / "docs/research/evidence/repositories.json"
AUDIT = ROOT / "docs/research/evidence/review-audit.json"
OBJECTIVE = ROOT / "objectives/001-fc27-api-research.md"
EXPECTED = (
    "liusihang/fc27-copilot",
    "jgor80/11-lab",
    "Vladisllavy/FC27-Autobuyer",
    "RanuK12/fc27-gallery-bot",
    "puredan824-hub/fc27-sniffer",
    "marchiartur/sp-tool",
    "FrancescoPalasciano/Bot-Fc27",
    "sauravhiremath/fut-25-market",
    "AbdoD97/fut-web-app-api",
)
FACTORS = ("Compatibility", "Completeness", "Dependencies", "Security", "Maintenance", "License")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
BLOB = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/blob/([^/\s]+)/([^\s)#]+)(?:#L(\d+))?")
SECTIONS = re.compile(r"^## ([1-9])\. ([^\n]+)\n(.*?)(?=^## |\Z)", re.M | re.S)
# These anchors were chosen from actual implementation review, not README claims.
# The historical documentation-only repository explicitly has no functions.
FUNCTIONS = {
    EXPECTED[0]: [("extension/content/page-inject.js", 1596, "searchTransferMarket"),
                  ("fc27/actions.py", 32, "_buy_now"), ("fc27/actions.py", 138, "_list_item")],
    EXPECTED[1]: [("src/market/capture.ts", 91, "summarizeSearch"),
                  ("extension/src/hook.ts", 123, "run")],
    EXPECTED[2]: [("fc27-autobuyer.user.js", 159, "searchFutMarket"),
                  ("fc27-autobuyer.user.js", 501, "buyItem")],
    EXPECTED[3]: [("fc27_gallery_worker.py", 88, "eval_js"),
                  ("fc27_gallery_worker.py", 235, "execute_buy_and_flip_cycle")],
    EXPECTED[4]: [("r2_prices.py", 53, "decode_ids"), ("r2_prices.py", 63, "fetch_market"),
                  ("pricedb.py", 43, "insert_samples")],
    EXPECTED[5]: [("extension-static/ea-main.js", 112, "openInMarket"),
                  ("src/lib/price.ts", 25, "parseAmount")],
    EXPECTED[6]: [("src/market.js", 13, "calculateTrade"), ("src/market.js", 93, "summarizePrices")],
    EXPECTED[7]: [("auth_api/services.py", 256, "buy_now"),
                  ("market/services.py", 30, "get_trade_status")],
    EXPECTED[8]: [("README.md", 1, "FC 26")],
}


def validate(report: str, ledger: dict, audit: dict) -> list[str]:
    """Return concrete defects; usable against mutated artifacts without file writes."""
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    check(ledger.get("task") == audit.get("task") == "task_01", "wrong task identity")
    records = ledger.get("repositories", [])
    by_repo = {r.get("repository"): r for r in records}
    check(len(records) == 9 and set(by_repo) == set(EXPECTED), "ledger must cover exactly nine named repositories")
    sections_list = SECTIONS.findall(report)
    sections = {repo.strip(): body for _, repo, body in sections_list}
    check(len(sections_list) == 9 and set(sections) == set(EXPECTED), "report must assess every named repository once")
    if set(by_repo) != set(EXPECTED) or set(sections) != set(EXPECTED):
        return errors

    cited = {repo: set() for repo in EXPECTED}
    for repo, rev, path, line_text in BLOB.findall(report):
        check(repo in by_repo, f"unexpected source repository: {repo}")
        if repo not in by_repo:
            continue
        record = by_repo[repo]
        check(rev == record.get("revision") and bool(HEX40.fullmatch(rev)), f"unpinned or wrong revision: {repo}/{path}")
        reviewed = {f["path"]: f for f in record.get("reviewed_files", [])}
        check(path in reviewed, f"source citation was not reviewed: {repo}/{path}")
        check(bool(line_text), f"source citation lacks line: {repo}/{path}")
        if path not in reviewed or not line_text:
            continue
        file = reviewed[path]
        line = int(line_text)
        anchors = {a["line"]: a["text"] for a in file.get("excerpts", [])}
        check(1 <= line <= file["line_count"], f"line outside source: {repo}/{path}:{line}")
        check(line in anchors and bool(anchors.get(line, "").strip()), f"missing source anchor: {repo}/{path}:{line}")
        cited[repo].add((path, line))

    for repo, record in by_repo.items():
        section = sections[repo]
        rev = record.get("revision", "")
        check(bool(HEX40.fullmatch(rev)), f"invalid revision: {repo}")
        check(rev in report and f"https://github.com/{repo}" in report, f"missing exact repository/revision: {repo}")
        check(record.get("tree_truncated") is False, f"incomplete tree: {repo}")
        check(record.get("access") == {"status": "accessible", "blockers": []}, f"access observation changed: {repo}")
        check("Access blockers: none." in section, f"missing explicit access finding: {repo}")
        check(bool(re.fullmatch(r"\d{4}-\d\d-\d\dT[^\s]+Z", record.get("commit_date", ""))), f"missing maintenance date: {repo}")
        check(len(cited[repo]) >= (1 if repo == EXPECTED[8] else 3), f"insufficient concrete citations: {repo}")

        tree = {entry["path"]: entry["sha"] for entry in record.get("tree", [])}
        files = {f["path"]: f for f in record.get("reviewed_files", [])}
        check("README.md" in files, f"README not reviewed: {repo}")
        for path, file in files.items():
            check(file.get("blob_sha") == tree.get(path) and bool(HEX40.fullmatch(file.get("blob_sha", ""))), f"blob/tree mismatch: {repo}/{path}")
            check(file.get("url") == f"https://github.com/{repo}/blob/{rev}/{path}", f"file URL mismatch: {repo}/{path}")
            check(isinstance(file.get("line_count"), int) and file["line_count"] > 0, f"invalid source length: {repo}/{path}")
            anchors = file.get("excerpts", [])
            check(bool(anchors) and len({a["line"] for a in anchors}) == len(anchors), f"missing/duplicate anchors: {repo}/{path}")
            check(all(1 <= a["line"] <= file["line_count"] and isinstance(a["text"], str) for a in anchors), f"invalid excerpt: {repo}/{path}")
        for path, line, symbol in FUNCTIONS[repo]:
            anchor = {a["line"]: a["text"] for a in files.get(path, {}).get("excerpts", [])}.get(line, "")
            check(symbol in anchor, f"function lacks source corroboration: {repo}/{path}::{symbol}")
            if repo != EXPECTED[8]:
                check(symbol in section, f"function omitted from report: {repo}::{symbol}")

        decision = re.search(r"\*\*Decision: (reuse|adapt|reference-only|discard)\. Access blockers:", section)
        check(decision is not None, f"missing supported decision: {repo}")
        findings = dict(re.findall(r"^- \*\*([^:*]+):\*\* (.+)$", section, re.M))
        check(set(findings) == set(FACTORS), f"missing decision factor: {repo}")
        for factor in FACTORS:
            value = findings.get(factor, "")
            check(len(value) >= 80 and not re.search(r"\b(TODO|TBD|placeholder)\b", value, re.I), f"unsupported {factor} finding: {repo}")
        check("README" in section, f"README claims not distinguished: {repo}")
        license_id = record.get("declared_license")
        if license_id is None:
            check("license" in findings.get("License", "").lower() and "no license" in findings.get("License", "").lower(), f"missing license blocker: {repo}")
            check(not any(Path(p).name.upper().startswith(("LICENSE", "COPYING")) for p in tree), f"license absence contradicted by tree: {repo}")
            check(decision is not None and decision.group(1) in {"reference-only", "discard"}, f"unlicensed code selected for reuse: {repo}")
        else:
            check("LICENSE" in files and license_id in findings.get("License", ""), f"license grant not reviewed: {repo}")
        check(isinstance(record.get("releases"), list) and isinstance(record.get("latest_workflow_runs"), list), f"maintenance queries not recorded: {repo}")
        check("reviewed commit" in findings.get("Maintenance", ""), f"maintenance claim missing date context: {repo}")

    for phrase in ("README claim", "Source implementation", "Upstream FC27 observation", "Historical FC25/26 reference",
                   "Independently observed FC27 behavior: UNVERIFIED", "zero EA", "No repository was cloned",
                   "No upstream code", "Source review preceded", "Clone only if integration or testing",
                   "not live trading", "not a complete security or dependency audit"):
        check(phrase in report, f"missing evidence/process boundary: {phrase}")
    check("FC25" in sections[EXPECTED[7]] and "FC26" in sections[EXPECTED[8]], "historical versions conflated")
    check("implementation functions: none" in sections[EXPECTED[8]], "docs-only repository presented as implementation")
    check("upstream observations, not independently checked" in sections[EXPECTED[1]], "upstream capture presented as independent observation")
    check("source contract, not an independently fetched working feed" in sections[EXPECTED[4]], "feed availability claimed from source alone")
    check("function" not in sections[EXPECTED[8]].split("implementation functions: none")[0].lower() or "documented JS/HTTP contracts" in sections[EXPECTED[8]], "invented documentation functions")
    check(not re.search(r"independently (verified|observed|confirmed|demonstrated) (?:live )?FC27 (?:buy|purchase|listing|search) (?:succeeded|works|passed)", report, re.I), "unsupported independent live success claim")
    live = audit.get("independent_fc27", {})
    check(live == {"status": "UNVERIFIED", "observations": [], "network_calls": 0, "browser_actions": 0, "trades": 0}, "unsupported independent FC27 evidence")

    activity = audit.get("activity", [])
    check([e.get("order") for e in activity] == list(range(1, len(activity) + 1)), "activity order invalid")
    stages = [e.get("type") for e in activity]
    required_stages = ["instructions_read", "remote_metadata", "remote_revision_and_tree", "remote_source_review", "remote_release_and_ci_read", "assessment_written", "local_artifact_validation"]
    check(stages == required_stages, "missing or unsafe source-review stage")
    reviews = next((e.get("reviews", []) for e in activity if e.get("type") == "remote_source_review"), [])
    review_map = {r["repository"]: r for r in reviews}
    check(set(review_map) == set(EXPECTED), "source review not recorded for all repositories")
    for repo, record in by_repo.items():
        review = review_map.get(repo, {})
        check(review.get("revision") == record["revision"] and set(review.get("paths", [])) == {f["path"] for f in record["reviewed_files"]}, f"source review record mismatch: {repo}")
    for key in ("third_party_executions", "clone_operations", "installations", "copied_implementation_files"):
        check(audit.get(key) == [], f"unexpected third-party activity: {key}")
    future = audit.get("policy_for_future_execution", {})
    check(all(future.get(k) is True for k in ("review_first", "pin_revision", "review_transitive_dependencies", "record_clone_purpose_before_clone")), "review-before-execution gate missing")
    check(set(future.get("clone_purposes", [])) == {"integration", "testing"}, "cloning not limited to integration/testing")
    for e in activity:
        for command in e.get("commands", []):
            check(command == ["python", "tests/test_repository_research.py"], f"unexpected executable in audit: {command}")
    check("not an OS-level execution trace" in audit.get("limitations", ""), "audit overstates historical proof")
    return errors


class RepositoryResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = REPORT.read_text(encoding="utf-8")
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.audit = json.loads(AUDIT.read_text(encoding="utf-8"))

    def test_all_acceptance_artifacts(self):
        self.assertEqual(validate(self.report, self.ledger, self.audit), [])

    def test_criterion_0_named_repositories_match_original_instructions(self):
        objective_repos = set(re.findall(r"https://github\.com/([\w-]+/[\w.-]+)", OBJECTIVE.read_text(encoding="utf-8")))
        self.assertEqual(objective_repos, set(EXPECTED))
        self.assertTrue(objective_repos)
        self.assertEqual(self.audit["instructions"]["agents_search"]["found"], [])
        self.assertIn("C:/hustle/fc-hustle", self.audit["instructions"]["agents_search"]["checked_directories"])

    def test_criterion_0_reject_missing_repository_and_broken_citations(self):
        mutated = copy.deepcopy(self.ledger)
        mutated["repositories"].pop()
        self.assertTrue(validate(self.report, mutated, self.audit))
        first = self.ledger["repositories"][0]
        for old, new in ((first["revision"], "main"), ("/fc27/actions.py#L32", "/fc27/not-a-file.py#L32"), ("/fc27/actions.py#L32", "/fc27/actions.py#L99999")):
            with self.subTest(new=new):
                self.assertNotEqual(self.report, self.report.replace(old, new))
                self.assertTrue(validate(self.report.replace(old, new), self.ledger, self.audit))
        mutated = copy.deepcopy(self.ledger)
        mutated["repositories"][0]["reviewed_files"][0]["blob_sha"] = "0" * 40
        self.assertTrue(validate(self.report, mutated, self.audit))

    def test_criterion_1_reject_every_missing_factor_for_every_repository(self):
        for _, repo, section in SECTIONS.findall(self.report):
            for factor in FACTORS:
                with self.subTest(repository=repo, factor=factor):
                    damaged = re.sub(rf"^- \*\*{factor}:\*\* .+\n", "", section, flags=re.M)
                    self.assertNotEqual(damaged, section)
                    self.assertTrue(validate(self.report.replace(section, damaged), self.ledger, self.audit))

    def test_criterion_1_reject_unlicensed_adaptation_and_missing_decision(self):
        for index in (1, 2, 8):
            section = dict((r, b) for _, r, b in SECTIONS.findall(self.report))[EXPECTED[index]]
            damaged = re.sub(r"Decision: (reference-only|discard)", "Decision: reuse", section)
            with self.subTest(repository=EXPECTED[index]):
                self.assertTrue(validate(self.report.replace(section, damaged), self.ledger, self.audit))
        self.assertTrue(validate(self.report.replace("**Decision: adapt.", "**Choice: maybe."), self.ledger, self.audit))

    def test_criterion_2_reject_conflated_live_and_historical_evidence(self):
        for phrase in ("Independently observed FC27 behavior: UNVERIFIED", "Historical FC25/26 reference", "upstream observations, not independently checked", "implementation functions: none"):
            with self.subTest(phrase=phrase):
                self.assertTrue(validate(self.report.replace(phrase, "evidence checked"), self.ledger, self.audit))
        damaged = copy.deepcopy(self.audit)
        damaged["independent_fc27"]["status"] = "VERIFIED"
        self.assertTrue(validate(self.report, self.ledger, damaged))
        self.assertTrue(validate(self.report + "\nIndependently verified FC27 purchase succeeded.\n", self.ledger, self.audit))

    def test_criterion_3_reject_execution_cloning_and_missing_source_review(self):
        for key in ("third_party_executions", "clone_operations", "installations"):
            with self.subTest(activity=key):
                damaged = copy.deepcopy(self.audit)
                damaged[key].append({"repository": EXPECTED[0], "purpose": "research"})
                self.assertTrue(validate(self.report, self.ledger, damaged))
        damaged = copy.deepcopy(self.audit)
        damaged["activity"] = [e for e in damaged["activity"] if e["type"] != "remote_source_review"]
        self.assertTrue(validate(self.report, self.ledger, damaged))
        damaged = copy.deepcopy(self.audit)
        damaged["policy_for_future_execution"]["clone_purposes"].append("browsing")
        self.assertTrue(validate(self.report, self.ledger, damaged))

    def test_criterion_3_retained_evidence_contains_no_executable_upstream_payload(self):
        evidence_files = list(LEDGER.parent.rglob("*"))
        self.assertEqual({p.name for p in evidence_files if p.is_file()}, {"repositories.json", "review-audit.json"})
        self.assertFalse((ROOT / ".gitmodules").exists(), "research must not add source submodules")
        # No nested checkout can be disguised as a source excerpt under research.
        self.assertFalse(any(p.name == ".git" for p in (ROOT / "docs/research").rglob("*")))
        for record in self.ledger["repositories"]:
            self.assertEqual(urlparse(record["url"]).netloc, "github.com")
            for file in record["reviewed_files"]:
                self.assertNotIn("content", file, "ledger must not retain runnable source files")


if __name__ == "__main__":
    unittest.main(verbosity=2)
