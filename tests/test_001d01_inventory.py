"""Independent 001d-01 artifact acceptance; no browser, server or EA requests.

Checks audit delivery, not implementation of future D1-D5 work. Negative cases
use in-memory readers and never rewrite the historical artifacts under test.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import unittest
from migration_001d03 import historical_reader

ROOT = Path(__file__).resolve().parents[1]
BASE = "docs/research/001d/"
REPORT = BASE + "REPORT.md"

AREAS = {
    "bridge-dialects": ("REPLACE", ["browser/bidding-v1/page.js", "browser/durability-v1/page.js", "browser/e2e-live-v2/page.js"], ["incompatible", "schema", "timeout", "1000"]),
    "contracts-adapters": ("REUSE", ["fc_access/bidding_v1/contracts.py", "fc_access/bidding_v1/adapter.py", "fc_access/durability_v1/adapter.py"], ["/user/credits", "freshness", "unrelated evidence keys"]),
    "executor-transport": ("IMPLEMENT", ["fc_access/durability_v1/executor.py", "fc_access/durability_v1/server.py", "browser/durability-v1/worker.js", "browser/durability-v1/persona.js", "browser/durability-v1/manifest.json"], ["8779", "concurrency=1", "separately running local server"]),
    "runtime-rules": ("REPLACE", ["fc_access/bidding_v1/rules.py", "browser/e2e-live-v2/page.js"], ["300", "getIncrementAboveVal", "getIncrementBelowVal", "750 -> 800", "rounding"]),
    "pricing": ("REPLACE", ["fc_access/pricing.py", "fc_access/bidding_v1/rules.py", "fc_access/bidding_v1/adapter.py", "experiments/search_validation_v1/economics.py"], ["1500", "2800", "maxBuy=first_min", "maxb", "last_sale_price", "Failed/ambiguous second"]),
    "price-cache": ("IMPLEMENT", ["fc_access/pricing.py", "fc_access/bidding_v1/adapter.py"], ["86400", "account/game/platform", "restart", "never cache as completed"]),
    "fresh-reads": ("IMPLEMENT", ["browser/e2e-live-v2/page.js", "browser/bidding-v1/page.js", "fc_access/bidding_v1/adapter.py", "fc_access/bidding_v1/core.py"], ["INBOX/PURCHASED/TRANSFER", "missing -> UNKNOWN", "closed/highest -> PENDING", "cache-only"]),
    "journal-registry": ("REUSE", ["fc_access/bidding_v1/journal.py", "fc_access/bidding_v1/core.py"], ["WAL/FULL", "UNKNOWN", "adapter -> quote -> admission -> scheduler -> journal", "5000"]),
    "scheduler-store": ("REUSE", ["fc_access/bidding_v1/scheduler.py", "fc_access/durability_v1/store.py", "fc_access/durability_v1/harness.py"], ["concurrency=1", "deadline", "consumed", "30-second"]),
    "S1-status": ("INVESTIGATE", ["browser/e2e-resolution-v2/page.js", "fc_access/e2e_resolution_v2/server.py"], ["performance resource", "definition_id=0", "not implemented/proven", "Never invent an auction"]),
    "S2-list-prices": ("INVESTIGATE", ["browser/e2e-live-v2/page.js", "fc_access/e2e_live_v2/policy.py"], ["1500 -> 1400", "getIncrementBelowVal", "UNLISTABLE/NEEDS_RECONCILIATION", "no listing"]),
    "actor-outcomes": ("DEFER-TO-002", ["fc_access/transaction.py", "fc_access/e2e_live_v2/policy.py", "fc_access/durability_v1/harness.py"], ["personal outbid/rebid", "actual paid cost", "settled proceeds", "25-second", "50-slot", "TBD"]),
}
TARGETS = {
    "fc_access/production_v1/" + p + ".py"
    for p in ("contracts", "adapter", "native_prices", "pricing", "price_cache", "core", "journal", "scheduler", "store", "executor")
} | {"browser/production-v1/page.js", "browser/production-v1/worker.js"}
ROUTES = dict(zip(
    ("watched", "balance", "unassigned", "transfer_list", "search", "caps", "status"),
    ("watchlist", "user/credits", "purchased/items", "tradepile", "transfermarket", "marketdata/pricelimits", "trade/status/lite"),
))
RECOVERY = {
    "reread_AGENTS", "same_task_checkpoints", "own_desktop_access", "verified_Edge_tab_and_foreground",
    "localhost_service", "reviewed_extension", "normal_UI_saved_autofill_only",
    "no_credential_or_session_extraction", "separate_attachment_persona_auth_native_gates",
}
STOPS = {
    "CAPTCHA_2FA_security_or_missing_credentials", "desktop_control_failure", "wrong_tab_persona_account_game_platform",
    "attachment_absent", "changed_unreviewed_source", "known_trade_mapping_absent",
    "cache_only_stale_mismatched_malformed_ambiguous", "failed_or_timeout", "401_403_429_Retry_After",
    "unexpected_route_method_fanout", "budget_or_deadline_exhausted",
}
INVARIANTS = {
    "reserve_before_delivery": True, "count_actual_fanout": True, "count_uncertain_attempts": True,
    "preserve_counts_and_deadlines": True, "retry_ambiguous_commands": False, "reset_budget_on_recovery": False,
    "replay_completed_windows": False, "account_background_or_stop": True, "direct_authenticated_python_http": False,
    "invent_auctions": False, "live_writes": False, "recurring_actors": False, "modify_sealed_evidence": False,
}
DEFERRED = {
    "active_personal_outbid_rebid", "competitive_WON_owned_paid_move_list", "settled_sale_profit",
    "sustained_25s_under_Acquirer_load", "live_50_slot_completeness", "natural_expiry_refund_timing",
    "listing_duration_unsold_relisting_decisions",
}


def read(path):
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT):
        raise AssertionError("path outside workspace: " + path)
    return resolved.read_bytes()


def load(path, reader=read):
    return json.loads(reader(path))


def need(ok, reason):
    if not ok:
        raise AssertionError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def rows(doc):
    table = doc.split("## Pre-change inventory\n", 1)[1].split("## Proposed authoritative production modules", 1)[0]
    result = {}
    for line in table.splitlines():
        if not line.startswith("| "):
            continue
        cells = [s.strip() for s in line.strip("|").split("|")]
        if cells[0] == "Area":
            continue
        need(len(cells) == 6 and cells[0] not in result, "malformed/duplicate inventory row")
        result[cells[0]] = cells
    return result


def check_map(doc, reader=read):
    table = rows(doc)
    need(set(table) == set(AREAS), "missing/extra inventory area")
    need({r[1] for r in table.values()} == {"REUSE", "REPLACE", "IMPLEMENT", "INVESTIGATE", "DEFER-TO-002"}, "missing disposition")
    for area, (action, paths, terms) in AREAS.items():
        row = table[area]
        need(row[1] == action, "wrong decision: " + area)
        for p in paths:
            need("`" + p + "`" in row[2], "missing implementation: " + p)
            need(len(reader(p)) > 20, "empty implementation")
        for cell in (row[3], row[4]):
            refs = re.findall(r"`([^`]+)`", cell)
            need(bool(refs), "missing evidence/test citation: " + area)
            for p in refs:
                need(len(reader(p)) > 0, "empty evidence/test")
        need("tests/" in row[4] and len(row[5]) >= 140, "missing test or actionable validation gap")
        for term in terms:
            need(term in " ".join(row), "missing scoped finding: " + area + ":" + term)
    need("tests/fixtures/market-pricing.json" in doc and "experiments/watched_bulk_v1/fixtures/watched-50.json" in doc,
         "relevant fixtures omitted")


def check_authority(doc):
    section = doc.split("## Proposed authoritative production modules\n", 1)[1].split("## Baseline and preservation", 1)[0]
    targets = re.findall(r"^\| `(fc_access/production_v1/[^`]+|browser/production-v1/[^`]+)` \|", section, re.M)
    need(len(targets) == len(TARGETS) and set(targets) == TARGETS, "missing/duplicate production authority")
    for line in section.splitlines():
        if line.startswith("| `"):
            need(bool(re.search(r"`(?:fc_access|browser)/[^`]+`", line.split(" | ", 1)[1])) or "New completed-only durable" in line,
                 "migration has no existing primitive or explicit new gap")
    for phrase in ("Proposal only", "do not exist yet", "Historical", "historical release audits pin original implementation bytes",
                   "one production dialect", "Keep `browser/bidding-v1/`", "existing fixtures", "unchanged", "historical harnesses only",
                   "one production schema", "No production migration", "PARTIAL", "not a FULL GO"):
        need(phrase.lower() in doc.lower(), "migration or readiness boundary missing: " + phrase)
    for phrase in ("one-shot caller -> adapter", "serialized executor", "durable intent/journal", "independent fresh readbacks", "reconciliation or UNKNOWN"):
        need(phrase in section, "integration call graph missing: " + phrase)


def check_plan(p, doc):
    need(p["task"] == "001d-01" and p["schema"] == 1 and p["future_probe_only"] is True, "probe scope")
    need(p["executed"] == {"native_requests": 0, "mutations": 0, "actors": 0, "browser_recovery": False}, "audit performed live work")
    for key, value in (("max_native_requests", 10), ("max_seconds", 300), ("max_mutations", 0), ("native_concurrency", 1), ("max_local_helper_evaluations", 8)):
        need(type(p[key]) is int and p[key] == value, "nonfinite/increased budget: " + key)
    expected = [
        ("R1-fresh-reads", 4, 60, ["watched", "balance", "unassigned", "transfer_list"]),
        ("R2-pricing-wire", 3, 90, ["caps", "search", "search"]),
        ("S1-known-status", 2, 60, ["status", "watched"]),
        ("S2-list-pair", 1, 90, ["caps"]),
    ]
    need(len(p["windows"]) == len(expected), "extra/replayed window")
    for w, (name, n, seconds, operations) in zip(p["windows"], expected):
        need(w == dict(id=name, max_native_requests=n, seconds=seconds, operations=operations), "unbounded/expanded window")
        need(f"| {name} | {n} | {seconds} |" in doc, "report/plan budget divergence")
    need(sum(w["seconds"] for w in p["windows"]) == p["max_seconds"], "wall budget undercount")
    need(sum(w["max_native_requests"] for w in p["windows"]) == p["max_native_requests"], "request budget undercount")
    need(p["routes"] == {op: {"method": "GET", "path": "/ut/game/fc27/" + path} for op, path in ROUTES.items()}, "route/method expansion")
    for route in p["routes"].values():
        need("`" + route["path"] + "`" in doc, "route absent from report")
    need(p["pricing"] == dict(page=1, count=21, max_searches=2, second_criterion="maxBuy", wire_criterion="maxb", inclusive=True,
         max_buy="first_min", discovery_filters_allowed=False, early_reject_requests=1, completed_cache_hit_requests=0, ttl_seconds=86400), "pricing budget/criteria changed")
    need(p["helpers"] == {"above": [750, 950, 1000, 9900], "below": [1500, 1000, 10000, "card_minimum"]}, "helper probe expansion")
    need(sum(map(len, p["helpers"].values())) == p["max_local_helper_evaluations"], "helper count inconsistent")
    need(set(p["required_recovery"]) == RECOVERY and set(p["required_stops"]) == STOPS, "recovery prerequisite/stop missing")
    need(p["invariants"] == INVARIANTS and set(p["deferred"]) == DEFERRED, "scope or budget invariant weakened")
    for phrase in ("actual EA requests=0", "live mutations=0", "recurring actors=0", "10 authenticated EA GET requests, 300 seconds, zero mutations",
                   "count actual service fanout", "uncertain attempts", "eight client helper evaluations", "background traffic", "never retry an ambiguous command",
                   "No PUT/POST/DELETE to EA", "No endpoint emulation/direct authenticated Python HTTP", "no new auction", "invented auction",
                   "reread `AGENTS.md`", "worker's own desktop access", "tab/window/foreground", "correct reviewed extension", "normal UI and saved autofill",
                   "tokens or session identifiers", "four separate gates", "CAPTCHA", "two-factor/security challenge", "minimal user action",
                   "exact failed control", "Retry-After", "original deadlines", "never replay completed windows", "reset budgets", "UNKNOWN"):
        need(phrase.lower() in doc.lower(), "missing concrete execution boundary: " + phrase)


def check_publication(reader=read):
    pub = load(BASE + "publication.json", reader)
    need(pub["phase"] == "PRE_CHANGE_GAP_MAP" and pub["existing_files_changed"] == [] and pub["new_code_files_at_publication"] == [], "not pre-change publication")
    need(pub["production_migrations_implemented"] is False, "audit claims implemented migrations")
    required = {REPORT, BASE + "entry.json", BASE + "baseline.json", BASE + "seal-audit.json", BASE + "execution-plan.json"}
    required |= {BASE + f"baseline-{i:02}.txt" for i in range(12)}
    need(set(pub["sha256"]) == required, "publication omits supporting artifacts")
    for p, digest in pub["sha256"].items():
        need(sha(reader(p)) == digest, "changed pre-change artifact: " + p)
    entry = load(BASE + "entry.json", reader)
    baseline = load(BASE + "baseline.json", reader)
    published = datetime.fromisoformat(pub["published_utc"])
    need(datetime.fromisoformat(entry["captured_utc"]) <= datetime.fromisoformat(baseline["checks"][0]["started_utc"]), "entry after tests")
    need(all(datetime.fromisoformat(c["ended_utc"]) <= published for c in baseline["checks"]), "baseline after publication")


def check_preservation(reader=read):
    reader = historical_reader(reader)
    entry = load(BASE + "entry.json", reader)
    need(entry["initial_status"] == [] and len(entry["sha256"]) == 686, "task entry missing/dirty")
    need(entry["head"] == "82846498e48a88ada592bba8a67d664e8671ad13", "task-entry revision changed")
    for p, digest in entry["sha256"].items():
        need(sha(reader(p)) == digest, "existing file changed: " + p)
    audit = load(BASE + "seal-audit.json", reader)
    expected_drift = {
        "docs/research/final/manifest.json": ["docs/research/browser-access/live-v2.json"],
        "docs/research/001b/preservation.json": [], "docs/research/001b/t7/manifest.json": [],
        "docs/research/001c/001c-06-complete/manifest.json": [],
        "docs/research/001c/001c-01/preservation.json": ["objectives/002-two-actor-competitive-bidding.md"],
        "docs/research/001c/001c-07/entry.json": ["objectives/002-two-actor-competitive-bidding.md"],
    }
    need({s["path"] for s in audit["seals"]} == set(expected_drift), "historical seal inventory incomplete")
    for seal in audit["seals"]:
        mapping = load(seal["path"], reader)[seal["key"]]
        need(len(mapping) == seal["files"], "seal count changed")
        actual = [{"path": p, "expected": h, "actual": sha(reader(p))} for p, h in mapping.items() if sha(reader(p)) != h]
        need(actual == seal["mismatches"], "historical mismatch concealed/introduced")
        need([m["path"] for m in actual] == expected_drift[seal["path"]], "unexpected historical drift")


def check_baselines(reader=read):
    b = load(BASE + "baseline.json", reader)
    targets = ["bidding_v1", "durability_v1", "market_pricing", "search_validation_v1", "watched_bulk_v1", "e2e_live_v2", "e2e_reconcile_v1", "e2e_complete_artifacts", "release_audit"]
    commands = [["{python}", "tests/run_offline_suite.py", "tests/test_" + t + ".py"] for t in targets]
    commands += [["{python}", "tests/validate_001c06_complete.py"], ["{python}", "tests/check_e2e_v1_acceptance.py"], ["{python}", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]]
    need([c["command"] for c in b["checks"]] == commands, "missing/replaced baseline invocation")
    counts = [25, 21, 11, 10, 7, 22, 6, 11, 22, None, None, 383]
    codes = [0] * 8 + [1, 0, 1, 1]
    for i, (c, count, code) in enumerate(zip(b["checks"], counts, codes)):
        need(c["exit_code"] == code and c["output"] == f"baseline-{i:02}.txt", "failure hidden or baseline reordered")
        raw = reader(BASE + c["output"])
        need(sha(raw) == c["output_sha256"], "baseline output changed")
        text = raw.decode("utf-8")
        need(datetime.fromisoformat(c["started_utc"]) <= datetime.fromisoformat(c["ended_utc"]) and c["duration_seconds"] > 0, "baseline timing missing")
        if count is not None:
            need(bool(re.search(rf"Ran {count} tests? in", text)), "baseline test count unsupported")
        if code == 0 and count is not None:
            need("\nOK\n" in text.replace("\r\n", "\n"), "passing baseline lacks test success")
        if i == 8:
            need("FAILED (failures=1, errors=2)" in text and "preexisting_bytes_changed:objectives/002-two-actor-competitive-bidding.md" in text, "release drift hidden")
        if i in (9, 10):
            result = json.loads(text.split("--- STDERR ---")[0])
            need(result["status"] == ("PASS" if i == 9 else "UNRESOLVED") and len(result["checks"]) == 8, "historical scope relabeled")
        if i == 11:
            for term in ("FAILED (failures=5, errors=3)", "stale_live_evidence", "WinError 10053", "test_criterion_2_required_reads_hashes", "preexisting_bytes_changed:objectives/002-two-actor-competitive-bidding.md"):
                need(term in text, "discovery failure not retained: " + term)


def check_findings(reader=read):
    reader = historical_reader(reader)
    anchors = {
        "browser/bidding-v1/page.js": ["__fcBiddingV1", 'balance:["GET","user/currencies"]', 'else if (c.operation === "watched") invoke'],
        "browser/durability-v1/page.js": ["__fcDurablePageV1", 'c.operation === "bid") {out.result.error', "repositories.Item.setDirty(ItemPile.INBOX)"],
        "browser/e2e-live-v2/page.js": ["__fcE2ELiveV2", "boot:h.boot,owner:h.owner", "wire_rows:null", "getIncrementAboveVal(a.current_bid)", "getItemMarketDataByDefId", "max_buy:'maxBuy'", "'maxb'", "ItemPile.PURCHASED", "ItemPile.TRANSFER"],
        "fc_access/bidding_v1/contracts.py": ["class Identity:", "class BidIntent:", 'game: str = "fc27"', "class Freshness:"],
        "fc_access/bidding_v1/adapter.py": ['"balance": {"/ut/game/fc27/user/currencies"}', '"result", "freshness", "coverage", "timing"', "state = State.PENDING", "estimate_cap"],
        "fc_access/durability_v1/adapter.py": ["/ut/game/fc27/user/credits", "return value['result'],f,c"],
        "fc_access/durability_v1/executor.py": ["port=8779", "('search','watched','balance')", "return False"],
        "fc_access/bidding_v1/rules.py": ["reviewed_hashes", "max_age=300", '"LIVE_VERIFIED"', "unsupported_increment_coverage"],
        "fc_access/pricing.py": ["min_samples: int = 5", "3*mad", "robust[(len(robust)-1)//4]", "undercut", "target_sale_price//20"],
        "fc_access/bidding_v1/journal.py": ["synchronous=FULL", "journal_mode=WAL", "append_only", "UNKNOWN"],
        "fc_access/bidding_v1/core.py": ['Decision("HOLD")', "State.UNKNOWN", "self.draining", "capacity=50, reserve=5000"],
        "fc_access/bidding_v1/scheduler.py": ["concurrency=1", "DEADLINE_SKIPPED", "local_delivery_ms", "native_service_ms"],
        "fc_access/durability_v1/store.py": ["synchronous=FULL", "UPDATE owner SET epoch=epoch+1", "state='UNKNOWN'", "never a retry queue"],
        "browser/e2e-resolution-v2/page.js": ["performance.getEntriesByType('resource')", "sourceMatch", "getAuctionData([{getAuctionData:()=>query}])", "TRADE='trade:d59ab1cf05df393676e66e4e'"],
        "fc_access/e2e_resolution_v2/server.py": ["127.0.0.1',8783", "'command_limit':4", "'seconds_limit':120"],
    }
    for path, terms in anchors.items():
        source = reader(path).decode("utf-8")
        for term in terms:
            need(term in source, "inventory finding unsupported: " + path + ":" + term)
    capture = load("docs/research/001c/001c-06-resume-02/comparables-2.json", reader)
    response = capture["response"]
    need(response["success"] and response["persona"]["accepted"] and response["rows"] == response["wire_rows"], "comparable proof mismatch")
    candidates = [r for r in response["rows"] if r["definition_id"] == 261855 and r["trade_state"] == "active" and r["expires"] > 0
                  and r["buy_now_price"] > 0 and not (r["starting_bid"] == 600 and r["buy_now_price"] == 10000)]
    need(min(r["buy_now_price"] for r in candidates) == 1500 and any(r["buy_now_price"] == 1700 for r in candidates), "cheap retained asks missing")
    need(len({r["trade_id"] for r in candidates}) == len(candidates), "unexpected duplicate fixture")
    old = load("docs/research/001c/001c-06-resume-02/pricing-plan.json", reader)
    need(old["target"] == 2800 and old["estimate"]["sample_count"] == 12, "historical estimator result relabeled")
    status = load("docs/research/001c/001c-06-resume-03/status.json", reader)["response"]["rows"][0]
    watched = load("docs/research/001c/001c-06-resume-03/watched.json", reader)["response"]["rows"][0]
    need(status["definition_id"] == 0 and watched["definition_id"] == 261855, "lite omission claim unsupported")
    need(all(status[k] == watched[k] for k in ("trade_id", "item_id", "current_bid", "trade_state", "bid_state")), "independent status identity mismatch")
    need(status["trade_state"] == "closed" and status["bid_state"] == "outbid" and status["current_bid"] == 1200, "terminal loss claim unsupported")


class InventoryAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = read(REPORT).decode("utf-8")

    def test_criterion_0_prechange_map_published_before_validator_code(self):
        check_publication()
        check_map(self.doc)

    def test_criterion_0_every_missing_row_decision_or_gap_is_rejected(self):
        for area in AREAS:
            line = next(s for s in self.doc.splitlines() if s.startswith("| " + area + " |"))
            for replacement in ("", line.replace(AREAS[area][0], "LIVE_VERIFIED", 1), " | ".join(line.split(" | ")[:-1]) + " | TBD |"):
                with self.subTest(area=area, replacement=replacement[:30]), self.assertRaises((AssertionError, IndexError)):
                    check_map(self.doc.replace(line, replacement))

    def test_criterion_1_inventory_citations_and_actual_findings(self):
        check_map(self.doc)
        check_findings()

    def test_criterion_1_wrong_route_or_fabricated_evidence_is_rejected(self):
        changes = {
            "fc_access/bidding_v1/adapter.py": lambda b: b.replace(b"/user/currencies", b"/user/credits"),
            "docs/research/001c/001c-06-resume-02/comparables-2.json": lambda b: b.replace(b'"buy_now_price": 1500', b'"buy_now_price": 2900'),
            "docs/research/001c/001c-06-resume-03/status.json": lambda b: b.replace(b'"definition_id": 0', b'"definition_id": 999'),
        }
        for target, change in changes.items():
            with self.subTest(target=target), self.assertRaises(AssertionError):
                check_findings(lambda p: change(read(p)) if p == target else read(p))

    def test_criterion_2_exact_baselines_and_all_existing_bytes_preserved(self):
        check_baselines()
        check_preservation()

    def test_criterion_2_changed_or_deleted_evidence_source_seal_and_log_rejected(self):
        for target in ("docs/research/001c/001c-06-resume-02/opening-1.json", "docs/research/001b/t7/manifest.json", "browser/e2e-live-v2/page.js", "objectives/002-two-actor-competitive-bidding.md", BASE + "baseline-11.txt"):
            for mode in ("change", "delete"):
                def altered(p):
                    if p == target:
                        if mode == "delete":
                            raise FileNotFoundError(p)
                        return read(p) + b"CHANGED"
                    return read(p)
                with self.subTest(target=target, mode=mode), self.assertRaises((AssertionError, FileNotFoundError)):
                    check_publication(altered)
                    check_preservation(altered)

    def test_criterion_2_failure_exit_or_output_hash_cannot_be_hidden(self):
        for mode in ("exit", "output", "delete"):
            bad = load(BASE + "baseline.json")
            if mode == "exit":
                bad["checks"][-1]["exit_code"] = 0
            elif mode == "output":
                bad["checks"][-1]["output_sha256"] = sha(b"PASS")
            else:
                bad["checks"].pop(8)
            with self.subTest(mode=mode), self.assertRaises(AssertionError):
                check_baselines(lambda p: json.dumps(bad).encode() if p == BASE + "baseline.json" else read(p))

    def test_criterion_3_read_only_numeric_budgets_routes_recovery_and_stops(self):
        check_plan(load(BASE + "execution-plan.json"), self.doc)

    def test_criterion_3_every_weakened_budget_route_and_invariant_is_rejected(self):
        original = load(BASE + "execution-plan.json")
        variants = []
        for key, value in (("max_native_requests", 11), ("max_seconds", None), ("max_mutations", 1), ("native_concurrency", 2), ("max_local_helper_evaluations", 9), ("native_concurrency", True)):
            bad = deepcopy(original); bad[key] = value; variants.append(bad)
        for key, value in INVARIANTS.items():
            bad = deepcopy(original); bad["invariants"][key] = not value; variants.append(bad)
        for key in ("required_stops", "required_recovery", "deferred"):
            for index in range(len(original[key])):
                bad = deepcopy(original); bad[key].pop(index); variants.append(bad)
        for operation in ROUTES:
            bad = deepcopy(original); bad["routes"][operation]["method"] = "POST"; variants.append(bad)
        bad = deepcopy(original); bad["routes"]["balance"]["path"] = "/ut/game/fc27/user/currencies"; variants.append(bad)
        bad = deepcopy(original); bad["windows"].append(deepcopy(bad["windows"][0])); variants.append(bad)
        bad = deepcopy(original); bad["pricing"]["max_searches"] = 3; variants.append(bad)
        bad = deepcopy(original); bad["pricing"]["discovery_filters_allowed"] = True; variants.append(bad)
        bad = deepcopy(original); bad["executed"]["native_requests"] = 1; variants.append(bad)
        for index, bad in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(AssertionError):
                check_plan(bad, self.doc)

    def test_criterion_4_authority_call_graph_and_historical_separation(self):
        check_authority(self.doc)
        check_preservation()
        # 001d-02 implements these destinations after this sealed inventory.
        # Assert their absence at inventory capture, not their future absence.
        entry_paths = load(BASE + "entry.json")["sha256"]
        for p in TARGETS:
            self.assertNotIn(p, entry_paths, "proposal existed before inventory: " + p)
        self.assertFalse(load(BASE + "publication.json")["production_migrations_implemented"])

    def test_criterion_4_missing_authority_or_historical_boundary_rejected(self):
        for term in ("fc_access/production_v1/executor.py", "browser/production-v1/page.js", "historical release audits pin original implementation bytes", "one production dialect"):
            with self.subTest(term=term), self.assertRaises(AssertionError):
                check_authority(self.doc.replace(term, "REMOVED"))

    def test_all_criteria_report_references_exist_and_scope_is_audit_only(self):
        references = set(re.findall(r"`((?:fc_access|browser|tests|experiments|docs|objectives)/[\w./-]+\.(?:py|js|cjs|md|json|sqlite))`", self.doc))
        self.assertGreater(len(references), 60)
        for p in references - TARGETS:
            self.assertTrue((ROOT / p).is_file(), p)
        for p in ("AGENTS.md", "objectives/001d-pre-actor-integration-readiness.md", "objectives/002-two-actor-competitive-bidding.md", "docs/research/001c-capability-matrix.md", "docs/research/001c-architecture-handoff.md", "docs/research/001c/001c-06-complete/REPORT.md"):
            self.assertIn("`" + p + "`", self.doc)
            self.assertIn(p, load(BASE + "entry.json")["sha256"])
        check_plan(load(BASE + "execution-plan.json"), self.doc)
        check_publication()


if __name__ == "__main__":
    unittest.main(verbosity=2)
