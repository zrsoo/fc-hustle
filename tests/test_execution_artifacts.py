"""Task_06 acceptance checks: specification, provenance, and negative mutations.

Offline, standard library only. Never attaches to a browser or creates trading
evidence. Historical captures are assessed at their checkpoint, not today's age.
Planned Objective 002 files are deliberately not required to exist yet.
"""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.capabilities import assess as assess_reads
from fc_access.market_replay import replay
from checkpoint import transaction_at_checkpoint as assess_transaction

ARCH_PATH = ROOT / "docs/research/execution-architecture.md"
HANDOFF_PATH = ROOT / "docs/research/obj002-handoff.md"


def read_json(relative):
    return json.loads((ROOT / "docs/research" / relative).read_text(encoding="utf-8"))


def section(document, title):
    match = re.search(r"^## " + re.escape(title) + r"\n(.*?)(?=^## |\Z)", document, re.M | re.S)
    return match.group(1) if match else ""


def table(body):
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in body.splitlines() if line.startswith("| ")]
    def separator(row):
        return all(re.fullmatch(r"[-: ]+", c) for c in row)
    return [row for i, row in enumerate(rows) if not separator(row)
            and not (i + 1 < len(rows) and separator(rows[i + 1]))]


def normative(document):
    blocks = re.findall(r"```json\n(.*?)\n```", document, re.S)
    if len(blocks) != 1:
        raise ValueError("exactly one normative JSON block required")
    return json.loads(blocks[0])


INTERFACES = {
    "CatalogPrices.catalog": ("game", "publication", "UNVERIFIED"),
    "CatalogPrices.quotes": ("MarketKey", "publication", "403"),
    "CatalogPrices.rules": ("MarketKey", "increment", "NOT_READY"),
    "Profitability.evaluate": ("X", "Estimate", "fc_access.pricing.evaluate"),
    "Market.search": ("page", "trade_id", "searchTransferMarket"),
    "Trading.buy_now": ("command_id", "session_epoch", "trade_id", "item_id", "buyNowPrice", "Persist intent first"),
    "Inventory.snapshot": ("force_network", "complete", "requestUnassignedItems", "service_unavailable"),
    "Movement.to_transfer": ("command_id", "item_id", "ItemPile.TRANSFER", "independently"),
    "Listing.create": ("listing_generation", "rules_revision", "startingBid", "new active trade ID"),
    "Status.read": ("force_network", "sold/unknown", "UNKNOWN", "UNVERIFIED"),
    "Session.ensure_ready": ("epoch", "AUTH_REQUIRED", "Authenticated reads"),
}

STATE_EDGES = {
    ("SCANNING", "EVALUATED"), ("EVALUATED", "BUY_INTENT"), ("BUY_INTENT", "OWNED"),
    ("OWNED", "MOVE_INTENT"), ("OWNED", "IN_TRANSFER"), ("MOVE_INTENT", "IN_TRANSFER"),
    ("IN_TRANSFER", "LIST_INTENT"), ("LIST_INTENT", "ACTIVE"), ("ACTIVE", "EXPIRED"),
    ("EXPIRED", "LIST_INTENT"), ("ACTIVE", "SETTLEMENT_PENDING"),
    ("SETTLEMENT_PENDING", "SOLD"), ("ACTIVE", "SCANNING"),
}

MODULES = {name: "tests/test_execution_" + name + ".py" for name in (
    "models", "store", "identity", "transport", "session", "providers", "rules",
    "strategy", "scheduler", "reconcile", "executor", "settlements")}


def defects(arch, handoff, spec=None):
    """Return defects by acceptance index; negative tests call this on mutations."""
    errors = {i: [] for i in range(6)}

    def check(index, condition, message):
        if not condition:
            errors[index].append(message)

    def require(index, body, terms, label):
        for term in terms:
            check(index, term in body, f"{label}: missing {term}")

    if spec is None:
        try:
            spec = normative(arch)
        except (ValueError, TypeError) as error:
            errors[0].append(str(error))
            spec = {}

    # Criterion 0: actual measurement, typed interfaces, and replaceability.
    transport = section(arch, "Transport decision and proof boundary")
    require(0, transport, ("14 authenticated network readbacks", "0 through direct HTTP",
            "direct_session_provider_unavailable", "UNVERIFIED", "in-memory session provider",
            "independent search", "replaceable", "not a future constant"), "transport")
    check(0, spec.get("transport") == "edge_native", "selected transport must be measured native path")
    rows = table(section(arch, "Interface contracts"))
    by_name = {r[0]: r for r in rows}
    check(0, set(by_name) == set(INTERFACES) and len(rows) == len(INTERFACES), "interface matrix incomplete/duplicated")
    for name, terms in INTERFACES.items():
        row = by_name.get(name, [])
        check(0, len(row) == 4 and all(row), f"{name}: needs input/output/dispatch contract")
        require(0, " ".join(row), terms, name)
    require(0, section(arch, "Interface contracts"), ("Result[T]", "UNKNOWN", "network_fresh",
            "complete", "definitionId", "resourceId", "physical item ID", "auction trade ID", "null"), "models")

    # Criterion 1: locked autonomous scope and executable decision sequence.
    check(1, spec.get("pipeline") == ["scan", "evaluate", "buy", "list", "repeat"], "pipeline changed")
    check(1, spec.get("per_transaction_approval") is False, "per-transaction approval introduced")
    check(1, spec.get("additional_portfolio_spend_policies") == [], "additional capital policies introduced")
    loop = section(arch, "Autonomous sequence")
    require(1, loop, ("scan → evaluate → buy → list → repeat", "without per-transaction approval",
            "without per-transaction approval or additional portfolio/spend policies",
            "expected_profit = target_sale_price - floor(target_sale_price * 0.05) - acquisition_price",
            "expected_profit >= X", "equality accepted", "same physical item", "returning to scan",
            "Recompute", "page", "HELD"), "autonomous loop")

    # Criterion 2: lifecycle, persistence, accounting, recovery for every write.
    durable = section(arch, "Durable state and accounting")
    tables = table(durable)
    check(2, {r[0] for r in tables} == {"account_scopes", "acquisitions", "operations", "listings", "observations", "settlements"}, "persistent entities missing")
    require(2, durable, ("WAL", "synchronous=FULL", "single OS process lock", "Commit the operation intent before",
            "semantic_key UNIQUE", "payload_hash", "actual_cost nullable", "listing", "generation",
            "sale_trade_id UNIQUE", "realized_profit nullable", "same key", "raw native IDs",
            "UNKNOWN_COST", "net_received - actual_cost", "SETTLEMENT_PENDING", "null", "Back up",
            "no verified idempotency-key", "not promise exactly-once"), "durability/accounting")
    matrix = table(section(arch, "State transitions and crash reconciliation"))
    state_rows = [r for r in matrix if len(r) == 4]
    edges = {(r[0], r[2]) for r in state_rows}
    check(2, edges == STATE_EDGES and len(state_rows) == len(STATE_EDGES), "state transitions incomplete")
    for r in state_rows:
        check(2, bool(r[1]) and bool(r[3]), f"{r[0]} lacks guard/action")
        if r[3].startswith(("buy", "move", "list")):
            check(2, "intent" in r[1] or "reconciled" in r[1], "remote action missing intent/reconciliation guard")
    recoveries = {r[0]: r for r in matrix if len(r) == 3}
    check(2, set(recoveries) == {"buy", "move", "list", "relist", "settlement"}, "crash recovery matrix incomplete")
    for operation, row in recoveries.items():
        check(2, len(row[1]) > 50 and len(row[2]) > 50, f"{operation}: non-actionable recovery")
    recovery = section(arch, "State transitions and crash reconciliation")
    require(2, recovery, ("before new writes", "UNKNOWN", "intent commit and send", "readback", "never deleting the intent",
            "Late results", "deadline", "no atomic commit", "Graceful shutdown"), "restart")
    lifecycle = section(arch, "Session lifecycle and bridge reconnection")
    require(2, lifecycle, ("UNVERIFIED", "401", "official Web App", "session_epoch", "AUTH_REQUIRED",
            "DETACHED", "chrome.storage.session", "90 seconds", "same official tab", "scope",
            "reconcile", "protocol/version", "Host/Origin", "pairing capability", "never proves authentication"), "lifecycle")
    check(2, spec.get("idempotency") == "durable_semantic_key_no_blind_write_retry", "unsafe retry contract")
    check(2, spec.get("realized_profit") == "net_received - actual_cost" and
          "unknown_realized_profit" in spec and spec["unknown_realized_profit"] is None, "unknown or modeled profit reported as realized")

    # Criterion 3: observed facts separated from proposed budgets/backoff.
    pacing = section(arch, "Measurement, pacing and errors")
    require(3, pacing, ("EA-only latency", "Background Web App polling frequency remains **UNVERIFIED**",
            "not measured service limits", "1.73/minute", "2 commands/minute", "Skip missed scan slots",
            "actual native network calls", "304", "repositories.Item.setDirty", "Retry-After",
            "429", "5xx", "401", "403", "RESTRICTED", "schema drift", "service_unavailable",
            "never refresh freshness", "No numerical EA rate limit", "empty authenticated search"), "pacing")
    expected = {
        "minimum_command_gap_seconds": 30, "scan_seconds": 90, "page2_seconds": 300,
        "manifest_seconds": 300, "quote_max_age_seconds": 600, "sample_max_age_seconds": 120,
        "candidate_max_age_seconds": 30, "minimum_remaining_seconds": 60,
        "caps_max_age_seconds": 300, "minimum_comparables": 5,
        "backoff_seconds": [30, 60, 120, 240, 300], "reconnect_seconds": [5, 10, 20, 40, 60],
    }
    for key, value in expected.items():
        check(3, spec.get(key) == value, f"incorrect pacing/freshness default: {key}")

    # Criterion 4: factual primary sources and explicit exclusion, no evasion implementation.
    enforcement = section(arch, "Enforcement facts and boundary")
    require(4, enforcement, ("EA's FC rules", "prohibit bots, automation and auto-buyers", "account bans",
            "does not establish permission", "normal access/support/appeal", "no detection-avoidance claims",
            "proxy rotation", "fingerprint spoofing", "CAPTCHA bypass", "restriction circumvention",
            "no detection immunity"), "enforcement")
    for url in ("https://help.ea.com/en/articles/ea-sports-fc/fc-rules/",
                "https://help.ea.com/en/articles/ea-sports-fc/transfer-market-web-and-companion-apps/"):
        check(4, f"]({url})" in enforcement, "primary enforcement citation missing")
    for claim in ("automation is permitted", "undetectable", "avoids detection", "rotate proxies to", "bypass challenges using"):
        check(4, claim not in (arch + handoff).lower(), f"unsupported enforcement/evasion claim: {claim}")

    # Criterion 5: reviewable implementation plan, dependency DAG, real source/license refs.
    for title in ("Stack and boundaries", "Module and file plan", "Reusable sources and license obligations",
                  "Dependency order", "Tests and artifact checks", "Live acceptance conditions",
                  "Unresolved prerequisites and disposition"):
        check(5, bool(section(handoff, title)), f"handoff missing {title}")
    require(5, section(handoff, "Stack and boundaries"), ("3.13", "sqlite3", "Edge Manifest V3", "Node **22+**",
            "one OS lock", "without per-transaction approval or additional portfolio/spend policies"), "stack")
    module_rows = table(section(handoff, "Module and file plan"))
    paths = {r[0]: r for r in module_rows}
    for name, test in MODULES.items():
        row = paths.get(f"fc_execution/{name}.py", [])
        check(5, len(row) == 3 and row[2] == test and len(row[1]) > 30, f"{name}: missing module responsibility/test")
    for path in ("fc_execution/__main__.py", "browser/execution-bridge/manifest.json",
                 "browser/execution-bridge/worker.js", "browser/execution-bridge/page.js",
                 "docs/obj002/setup.md", "tests/validate_execution_live.py"):
        check(5, path in paths, f"missing planned file {path}")
    dependency_rows = table(section(handoff, "Dependency order"))
    seen = set()
    for row in dependency_rows:
        check(5, len(row) == 3, "invalid dependency row")
        if len(row) != 3:
            continue
        deps = [] if row[1] == "none" else [d.strip() for d in row[1].split(",")]
        check(5, all(dep in seen for dep in deps) and row[0] not in seen, "cycle/forward/duplicate stage dependency")
        seen.add(row[0])
    check(5, seen == {f"S{i}" for i in range(1, 7)}, "missing dependency stage")
    acceptance = table(section(handoff, "Live acceptance conditions"))
    check(5, {r[0] for r in acceptance} == {f"L{i}" for i in range(1, 9)}, "missing live acceptance condition")
    require(5, section(handoff, "Live acceptance conditions"), ("two independent qualifying cycles", "normal reauthentication",
            "odd 5% boundary", "NOT_OBSERVED", "no duplicate mutation", "independent", "naturally expired"), "live release")
    require(5, section(handoff, "Tests and artifact checks"), ("after commit before send", "after native dispatch before response",
            "after readback before commit", "Two distinct qualifying", "wrong epoch/account", "Retry-After longer than 300",
            "unknown proceeds/cost", "fixtures never write retained live files"), "test plan")
    gaps = table(section(handoff, "Unresolved prerequisites and disposition"))
    check(5, len(gaps) == 10 and all(len(r) == 3 and len(r[2]) > 40 for r in gaps), "prerequisites missing resolution/impact")
    require(5, handoff, ("CONDITIONAL GO", "**planned**", "No upstream code is copied", "MIT: preserve copyright and permission notice",
            "no reviewed license grant", "Apache-2.0", "NOTICE", "marked modifications", "data or service rights",
            "No current human intervention"), "handoff scope/license")
    return {i: messages for i, messages in errors.items() if messages}


class ExecutionArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arch = ARCH_PATH.read_text(encoding="utf-8")
        cls.handoff = HANDOFF_PATH.read_text(encoding="utf-8")
        cls.spec = normative(cls.arch)

    def test_all_six_acceptance_contracts(self):
        self.assertEqual(defects(self.arch, self.handoff), {})

    def test_measured_transport_recomputed_from_retained_attempts(self):
        record = read_json("capabilities/attempts.json")
        facts = assess_reads(record)
        # assess returns (errors, summary); recompute rather than trusting report totals.
        errors, summary = facts
        self.assertFalse(errors)
        for transport in ("edge", "direct_http"):
            self.assertEqual(summary[transport]["authenticated_reads"], self.spec["authenticated_reads"][transport])
        self.assertEqual(summary["direct_http"]["unavailable_reasons"], [self.spec["direct_error"]])
        verification = read_json("capabilities/verification.json")
        self.assertEqual(verification["capture_sha256"], hashlib.sha256((ROOT / verification["capture"]).read_bytes()).hexdigest())

    def test_native_write_claims_recomputed_without_new_trade(self):
        journal = read_json("transaction/live.json")
        errors, facts = assess_transaction(journal)
        self.assertFalse(errors)
        for operation in ("purchase", "movement", "listing", "status", "relist"):
            self.assertEqual(facts[operation], self.spec["capabilities"][operation])
        for field in ("acquisition_price",):
            self.assertIn(f"**{facts['identity'][field]}**", self.arch)
        for field in ("starting_bid", "buy_now_price", "requested_duration", "observed_seconds_remaining"):
            self.assertIn(f"**{facts['listing_readback'][field]}**", self.arch)
        self.assertEqual(facts["acquisition_readback"]["coin_debit"], facts["identity"]["acquisition_price"])
        cached = [a for a in journal["attempts"] if a["phase"] == "after_buy" and a["result"]["status"] == 304]
        self.assertEqual({a["operation"] for a in cached}, {"unassigned", "transfer_list"})
        self.assertEqual(len([a for a in journal["attempts"] if a["operation"] == "buy"]), 1)

    def test_pacing_observations_and_capacity_arithmetic(self):
        capture = read_json("market/availability.json")
        for a in capture["attempts"]:
            self.assertIn(str(a["elapsed_ms"]), self.arch)
        self.assertEqual(sorted({a["request"]["definition_id"] for a in capture["attempts"]}), sorted(self.spec["watchlist"]))
        public = {r["name"]: r for r in capture["public"]}
        for key in ("manifest", "catalog", "history_ui", "price_ranges"):
            self.assertEqual(public[key]["status"], 403)
        observer = read_json("browser-access/verification.json")["live_configuration"]["observations"]
        self.assertEqual(len(observer), 8)
        elapsed = (datetime.fromisoformat(observer[-1]["observed_at"]) - datetime.fromisoformat(observer[0]["observed_at"])).total_seconds()
        self.assertIn(f"**{elapsed:.3f} seconds**", self.arch)
        worker = (ROOT / "browser/transaction-bridge/worker.js").read_text(encoding="utf-8")
        self.assertIn("periodInMinutes: 0.5", worker)
        load = len(self.spec["watchlist"]) * (60/self.spec["scan_seconds"] + 60/self.spec["page2_seconds"])
        self.assertIn(f"{load:.2f}/minute", self.arch)
        self.assertLess(load, 60/self.spec["minimum_command_gap_seconds"])
        self.assertEqual(self.spec["capabilities"]["web_app_poll_interval"], "UNVERIFIED")

    def test_dependency_market_proof_is_still_negative_and_missing_caps(self):
        calculated = replay()
        retained = read_json("market/offline-proof.json")
        self.assertEqual(json.loads(json.dumps(calculated)), retained)
        for market in calculated["markets"]:
            self.assertEqual(market["without_observed_caps"]["status"], "MISSING_CAPS")
        self.assertEqual(self.spec["capabilities"]["card_caps"], "UNVERIFIED")
        for capability in ("full_increment_schedule", "realized_tax_rounding", "session_renewal", "bulk_pc_catalog", "numeric_history"):
            self.assertEqual(self.spec["capabilities"][capability], "UNVERIFIED")

    def test_existing_local_links_and_anchors_resolve(self):
        for path, document in ((ARCH_PATH, self.arch), (HANDOFF_PATH, self.handoff)):
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document):
                if target.startswith("https://"):
                    continue
                name, _, anchor = target.partition("#")
                resolved = (path.parent / unquote(name)).resolve() if name else path
                self.assertTrue(resolved.is_relative_to(ROOT), target)
                self.assertTrue(resolved.is_file(), target)
                if anchor:
                    headings = re.findall(r"^#{1,6} (.*)$", resolved.read_text(encoding="utf-8"), re.M)
                    slugs = [re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in headings]
                    self.assertIn(anchor, slugs, target)

    def test_upstream_paths_revisions_and_licenses_match_reviewed_trees(self):
        repos = {r["repository"]: r for r in read_json("evidence/repositories.json")["repositories"]}
        links = re.findall(r"https://github.com/([^/]+/[^/]+)/blob/([a-f0-9]{40})/([^\s)#]+)", self.handoff)
        self.assertGreaterEqual(len(links), 7)
        cited = set()
        for repo, revision, source_path in links:
            record = repos[repo]
            self.assertEqual(revision, record["revision"])
            self.assertIn(source_path, {entry["path"] for entry in record["tree"]})
            self.assertEqual(record["declared_license"], "MIT")
            cited.add(repo)
        self.assertEqual(cited, {"liusihang/fc27-copilot", "puredan824-hub/fc27-sniffer", "marchiartur/sp-tool", "FrancescoPalasciano/Bot-Fc27"})

    def test_each_interface_deletion_is_rejected(self):
        for name in INTERFACES:
            with self.subTest(interface=name):
                mutated = re.sub(r"^\| " + re.escape(name) + r" \|.*\n", "", self.arch, flags=re.M)
                self.assertIn(0, defects(mutated, self.handoff))

    def test_approval_and_policy_mutations_are_rejected(self):
        for key, value in (("pipeline", ["scan", "buy"]), ("per_transaction_approval", True),
                           ("additional_portfolio_spend_policies", ["daily_budget"])):
            spec = copy.deepcopy(self.spec)
            spec[key] = value
            self.assertIn(1, defects(self.arch, self.handoff, spec))

    def test_lifecycle_durability_and_each_recovery_deletion_are_rejected(self):
        for title in ("Durable state and accounting", "State transitions and crash reconciliation", "Session lifecycle and bridge reconnection"):
            with self.subTest(section=title):
                mutated = self.arch.replace(section(self.arch, title), "\n")
                self.assertIn(2, defects(mutated, self.handoff))
        for operation in ("buy", "move", "list", "relist", "settlement"):
            mutated = re.sub(r"^\| " + operation + r" \|.*\n", "", self.arch, flags=re.M)
            self.assertIn(2, defects(mutated, self.handoff))
        for value in (0, "modeled_profit"):
            spec = copy.deepcopy(self.spec)
            spec["unknown_realized_profit"] = value
            self.assertIn(2, defects(self.arch, self.handoff, spec))

    def test_each_state_transition_deletion_is_rejected(self):
        for source, destination in STATE_EDGES:
            mutated = "\n".join(line for line in self.arch.splitlines()
                                if not (line.startswith(f"| {source} |") and f"| {destination} |" in line))
            self.assertIn(2, defects(mutated, self.handoff), (source, destination))

    def test_every_pacing_default_mutation_is_rejected(self):
        for key in self.spec:
            if key.endswith("_seconds") or key == "minimum_comparables":
                mutated = copy.deepcopy(self.spec)
                mutated[key] = 1
                self.assertIn(3, defects(self.arch, self.handoff, mutated), key)
        for phrase in ("Background Web App polling frequency remains **UNVERIFIED**", "No numerical EA rate limit", "Retry-After"):
            self.assertIn(3, defects(self.arch.replace(phrase, ""), self.handoff))

    def test_enforcement_mutations_are_rejected(self):
        for phrase in ("prohibit bots, automation and auto-buyers", "no detection-avoidance claims", "CAPTCHA bypass", "account bans"):
            self.assertIn(4, defects(self.arch.replace(phrase, ""), self.handoff))
        self.assertIn(4, defects(self.arch + "\nThis is undetectable.\n", self.handoff))

    def test_handoff_module_stage_acceptance_and_license_mutations_are_rejected(self):
        for name in MODULES:
            mutated = re.sub(r"^\| fc_execution/" + name + r"\.py \|.*\n", "", self.handoff, flags=re.M)
            self.assertIn(5, defects(self.arch, mutated), name)
        for prefix in ("S1", "S4", "S6", "L1", "L5", "L7", "L8"):
            mutated = re.sub(r"^\| " + prefix + r" \|.*\n", "", self.handoff, flags=re.M)
            self.assertIn(5, defects(self.arch, mutated), prefix)
        for phrase in ("MIT: preserve copyright and permission notice", "no reviewed license grant", "Apache-2.0", "marked modifications"):
            self.assertIn(5, defects(self.arch, self.handoff.replace(phrase, "")))
        self.assertIn(5, defects(self.arch, self.handoff.replace("| S2 | S1 |", "| S2 | S6 |")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
