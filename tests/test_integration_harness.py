"""Deterministic transport, retention, read-plan and independent-assessor tests."""
import contextlib
import copy
import http.client
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.harness import (DirectHTTPTransport, EdgeTransport, Harness, Session, command,
                               empty_result, project_auction, project_item, pseudonym, validate_result)
from fc_access.read_server import ReadServer
from fc_access.capabilities import assess
from check_read_prerequisite import check

KEY = "a" * 32
PRIVATE = "synthetic-private-canary"


def raw_item():
    return {"id": "12345678901234567890", "resourceId": 90001, "definitionId": 90001,
            "assetId": 123, "rating": 83, "rareflag": 1, "nationId": 4, "leagueId": 13,
            "teamId": 23, "preferredPosition": "ST", "untradeable": False,
            "marketAverage": 800, "lastSalePrice": 650, "name": PRIVATE,
            "personaId": PRIVATE, "nested": {"cookie": PRIVATE}}


def raw_auction(trade="22222222222222222222"):
    return {"tradeId": trade, "startingBid": 500, "currentBid": 550, "buyNowPrice": 700,
            "expires": 100, "tradeState": "active", "bidState": "none", "itemData": raw_item(), "token": PRIVATE}


def result(op, key=KEY, trade="22222222222222222222"):
    r = empty_result("internal_error")
    path = {"coins": "user/credits", "club": "club", "unassigned": "unassigned", "purchased": "purchased/items", "transfer_list": "tradepile", "search": "transfermarket"}[op]
    r.update(status=200, success=True, error=None, platform="pc", network=[{"host": "utas.mob.v1.prd.futc-ext.gcp.ea.com", "path": "/ut/game/fc27/" + path, "status": 200, "session_header_present": True}])
    if op == "coins":
        r["credits"] = 12345
    elif op in {"search", "transfer_list"}:
        r["auctions"] = [project_auction(raw_auction(trade), key)]
    else:
        r["items"] = [project_item(raw_item(), key)]
    return r


class FakeTransport:
    name = "edge"
    def __init__(self):
        self.calls = []
    def read(self, op, params, key):
        self.calls.append((op, params.copy()))
        return result(op, key, "3" if params.get("page") == 2 else "2")


class Tests(unittest.TestCase):
    def test_read_only_command_filter_and_bounds_contract(self):
        for op in ["bid", "buy", "list", "relist", "move", "eval", "POST"]:
            with self.assertRaises(ValueError): command(op, {})
        invalid = [{"page": 3}, {"page": True}, {"count": 22}, {"definition_id": 0}, {"min_buy": 700, "max_buy": 500}, {"platform": "pc"}, {"headers": PRIVATE}, {"position": PRIVATE}, {"fresh": "yes"}]
        for p in invalid:
            with self.assertRaises(ValueError): command("search", p)
        for p in [False, [], "", 1]:
            with self.assertRaises(ValueError): command("search", p)
        self.assertEqual(command("search", {"page": 2, "count": 21, "fresh": False})["params"]["page"], 2)
        with self.assertRaises(ValueError): command("coins", {"count": 1})

    def test_three_identity_namespaces_no_float_loss_and_private_projection(self):
        a = project_auction(raw_auction(), KEY)
        self.assertNotEqual(a["trade_id"], a["item"]["item_id"])
        self.assertEqual(a["item"]["resource_id"], 90001)
        self.assertEqual(a["item"]["asset_id"], 123)
        self.assertNotIn(PRIVATE, json.dumps(a))
        self.assertNotIn("12345678901234567890", json.dumps(a))
        self.assertNotEqual(pseudonym("123", "item", KEY), pseudonym("123", "trade", KEY))
        self.assertNotEqual(pseudonym("123", "item", KEY), pseudonym("123", "item", "b"*32))
        for value in [2**53, float(123), True, PRIVATE]:
            with self.assertRaises(ValueError): pseudonym(value, "item", KEY)
        self.assertIsNone(project_item({"id": "1", "definitionId": 90001}, KEY)["resource_id"])

    def test_retention_boundary_rejects_sensitive_unknown_or_wrongly_typed_fields(self):
        good = result("search")
        self.assertEqual(validate_result(good), good)
        for path in [[], ["auctions", 0], ["auctions", 0, "item"], ["network", 0]]:
            bad = copy.deepcopy(good)
            obj = bad
            for k in path: obj = obj[k]
            obj["cookie"] = PRIVATE
            with self.assertRaises(ValueError): validate_result(bad)
        for k, v in [("platform", PRIVATE), ("error", PRIVATE), ("credits", True), ("status", 99), ("ea_error_code", PRIVATE), ("success", False)]:
            bad = copy.deepcopy(good); bad[k] = v
            with self.assertRaises(ValueError): validate_result(bad)
        bad = copy.deepcopy(good); bad["network"][0]["path"] += "?sid=" + PRIVATE
        with self.assertRaises(ValueError): validate_result(bad)
        bad = copy.deepcopy(good); bad["auctions"][0]["trade_id"] = "123"
        with self.assertRaises(ValueError): validate_result(bad)

    def test_authenticated_direct_http_request_and_sanitized_account_search_responses(self):
        http = MagicMock()
        response = http.open.return_value.__enter__.return_value
        response.status = 200
        transport = DirectHTTPTransport(lambda: Session("utas.mob.v1.prd.futc-ext.gcp.ea.com", PRIVATE, "pc"), http)
        response.read.return_value = json.dumps({"auctionInfo": [raw_auction()], "account": PRIVATE}).encode()
        r = transport.read("search", {"page": 2, "count": 21, "definition_id": 90001, "max_buy": 700}, KEY)
        self.assertTrue(r["success"])
        request = http.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("X-ut-sid"), PRIVATE)
        self.assertIn("start=20", request.full_url)
        self.assertIn("num=21", request.full_url)
        self.assertIn("definitionId=90001", request.full_url)
        self.assertNotIn("maskedDefId", request.full_url)
        self.assertIn("maxb=700", request.full_url)
        self.assertNotIn(PRIVATE, json.dumps(r))
        for op, body, field in [("coins", {"credits": 0, "name": PRIVATE}, "credits"), ("club", {"itemData": []}, "items"), ("unassigned", {"itemData": []}, "items"), ("purchased", {"itemData": []}, "items"), ("transfer_list", {"auctionInfo": []}, "auctions")]:
            response.read.return_value = json.dumps(body).encode()
            out = transport.read(op, {}, KEY)
            self.assertTrue(out["success"])
            self.assertIsNotNone(out[field])
        self.assertNotIn(PRIVATE, repr(Session("utas.mob.ea.com", PRIVATE)))

    def test_direct_unavailable_errors_and_no_redirect_or_false_http_200_proof(self):
        self.assertEqual(DirectHTTPTransport().read("coins", {}, KEY)["error"], "direct_session_provider_unavailable")
        http = MagicMock()
        transport = DirectHTTPTransport(lambda: Session("utas.mob.ea.com", PRIVATE), http)
        for status in [401, 403, 429, 500]:
            http.open.side_effect = urllib.error.HTTPError("https://utas.mob.ea.com/?"+PRIVATE, status, PRIVATE, {}, io.BytesIO(PRIVATE.encode()))
            r = transport.read("coins", {}, KEY)
            self.assertEqual(r["status"], status)
            self.assertFalse(r["success"])
            self.assertNotIn(PRIVATE, json.dumps(r))
        http.open.side_effect = None
        response = http.open.return_value.__enter__.return_value; response.status = 200
        for body in [{"account": PRIVATE}, {"credits": PRIVATE}, {"credits": True}]:
            response.read.return_value = json.dumps(body).encode()
            self.assertEqual(transport.read("coins", {}, KEY)["error"], "schema_unrecognized")
        invalid = DirectHTTPTransport(lambda: Session("utas.ea.com.attacker.invalid", PRIVATE), http)
        http.reset_mock()
        self.assertEqual(invalid.read("coins", {}, KEY)["error"], "schema_unrecognized")
        http.open.assert_not_called()
        from fc_access.harness import NoRedirect
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.invalid"))

    def test_finite_plan_relevant_pages_ceiling_filters_and_invalidation(self):
        fake = FakeTransport(); h = Harness({"edge": fake}, KEY); h.suite()
        calls = fake.calls
        self.assertEqual(len(calls), 16)
        targeted = [p for op, p in calls if op == "search" and "definition_id" in p]
        self.assertTrue(all(p["definition_id"] == 90001 and p["max_buy"] == 700 for p in targeted))
        self.assertEqual({p["page"] for p in targeted}, {1, 2})
        self.assertEqual([p["fresh"] for p in targeted[:4]], [True, False, False, True])
        filters = [p for op,p in calls if op == "search" and any(f in p for f in ["nation", "league", "club", "rarity", "position"])]
        self.assertEqual(len(filters), 5)
        self.assertTrue(all("definition_id" not in p for p in filters))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"capture.json"; record = h.save(path)
            self.assertNotIn(PRIVATE, path.read_text())
            self.assertEqual(len(record["attempts"]), 16)
        empty = FakeTransport(); empty.read = lambda *args: empty_result("bridge_not_attached")
        h = Harness({"edge": empty}, KEY); h.suite()
        self.assertEqual(len(h.attempts), 7)
        self.assertTrue(all(a["result"]["items"] is None for a in h.attempts))
        bad = FakeTransport(); bad.read = lambda *args: (_ for _ in ()).throw(RuntimeError(PRIVATE))
        h = Harness({"edge": bad}, KEY)
        self.assertEqual(h.read("edge", "coins")["result"]["error"], "internal_error")
        self.assertNotIn(PRIVATE, json.dumps(h.attempts))

    def test_live_assessor_rejects_wrong_variant_platform_ceiling_missing_account_and_untyped_200(self):
        h = Harness({"edge": FakeTransport(), "direct_http": FakeTransport()}, KEY); h.suite()
        with tempfile.TemporaryDirectory() as d:
            baseline = h.save(Path(d)/"synthetic-only.json")
        self.assertEqual(assess(baseline)[0], [])
        cases = [
            (lambda a: a["result"].update(network=[]), "criterion_3_live_listing_identity_prices_expiry_unverified"),
            (lambda a: a["result"].update(platform=None), "criterion_3_platform_separation_unverified"),
            (lambda a: [r["item"].update(definition_id=999) for r in a["result"]["auctions"] or []], "criterion_3_card_version_or_buy_now_ceiling_unverified"),
            (lambda a: [r.update(buy_now_price=900) for r in a["result"]["auctions"] or []], "criterion_3_card_version_or_buy_now_ceiling_unverified"),
            (lambda a: a["result"].update(credits=None), "criterion_5_live_coins_unverified"),
            (lambda a: [r.update(expires=None) for r in a["result"]["auctions"] or []], "criterion_3_live_listing_identity_prices_expiry_unverified")]
        for mutate, expected in cases:
            record = copy.deepcopy(baseline)
            for a in record["attempts"]: mutate(a)
            self.assertIn(expected, assess(record)[0])
        poisoned = copy.deepcopy(baseline); poisoned["attempts"][0]["result"]["cookie"] = PRIVATE
        self.assertEqual(assess(poisoned)[0], ["invalid_or_sensitive_attempt"])
        no_pages = copy.deepcopy(baseline)
        no_pages["attempts"] = [a for a in no_pages["attempts"] if a["request"].get("page") != 2]
        self.assertEqual(assess(no_pages)[1]["pagination"]["two_nonempty_pages"], "UNVERIFIED")
        for a in no_pages["attempts"]:
            a["result"] = empty_result("bridge_unavailable")
        self.assertTrue(assess(no_pages)[0], "recorded failures are not live success")

    def test_bridge_real_http_roundtrip_origin_duplicate_timeout_and_privacy(self):
        server = ReadServer(port=0, wait_seconds=0.3)
        self.assertEqual(server.server_address[0], "127.0.0.1")
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def request(method, path, value=None, extension=False, extra=None, raw=None):
            headers = {"Content-Type": "application/json"}
            if extension: headers["Origin"] = "chrome-extension://" + "a"*32
            headers.update(extra or {})
            con = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            con.request(method, path, body=raw if raw is not None else json.dumps(value) if value is not None else None, headers=headers)
            response = con.getresponse()
            self.assertIsNone(response.getheader("Access-Control-Allow-Origin"))
            status, body = response.status, json.loads(response.read()); con.close(); return status, body
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.assertFalse(request("GET", "/health")[1]["attached"])
                self.assertEqual(request("GET", "/next")[0], 403)
                # An ordinary extension GET may omit Origin. The POST poll must
                # supply an extension origin; never relax the server check.
                for extra in [{}, {"Origin": "https://attacker.invalid"}, {"Origin": "null"}]:
                    self.assertEqual(request("POST", "/next", {}, extra=extra)[0], 403)
                self.assertFalse(request("GET", "/health")[1]["attached"])
                self.assertEqual(request("POST", "/next", {"unexpected": True}, extension=True)[0], 400)
                self.assertEqual(request("POST", "/next", [], extension=True)[0], 400)
                self.assertFalse(request("GET", "/health")[1]["attached"])
                # Retain the earlier authenticated GET protocol for compatibility.
                self.assertEqual(request("GET", "/next", extension=True)[0], 200)
                server.last_attached = 0
                self.assertEqual(request("POST", "/next", {}, extension=True)[0], 200)
                self.assertTrue(request("GET", "/health")[1]["attached"])
                for extra in [{"Origin": "https://attacker.invalid"}, {"Host": "attacker.invalid"}, {"Sec-Fetch-Site": "cross-site"}]:
                    self.assertEqual(request("POST", "/run", {}, extra=extra)[0], 403)
                self.assertEqual(request("POST", "/execute", {})[0], 404)
                self.assertEqual(request("POST", "/run", {"operation": "bid", "params": {}, "evidence_key": KEY})[0], 400)
                self.assertEqual(request("POST", "/run", raw='{"x":1,"x":2}')[0], 400)
                transport = EdgeTransport(server.server_port)
                received = []
                caller = threading.Thread(target=lambda: received.append(transport.read("coins", {}, KEY))); caller.start()
                deadline = time.monotonic()+2; pending = None
                while time.monotonic() < deadline:
                    pending = request("POST", "/next", {}, extension=True)[1]
                    if pending: break
                    time.sleep(0.005)
                self.assertIsNotNone(pending)
                self.assertEqual(pending["operation"], "coins")
                self.assertIsNone(request("POST", "/next", {}, extension=True)[1], "dispatch at most once")
                self.assertEqual(request("POST", "/run", {"operation": "coins", "params": {}, "evidence_key": KEY})[0], 409)
                bad = result("coins"); bad["cookie"] = PRIVATE
                self.assertEqual(request("POST", "/result", {"id": pending["id"], "result": bad}, extension=True)[0], 400)
                self.assertEqual(request("POST", "/result", {"id": "bad", "result": result("coins")}, extension=True)[0], 409)
                self.assertEqual(request("POST", "/result", {"id": pending["id"], "result": result("coins")}, extension=True)[0], 200)
                caller.join(timeout=3); self.assertEqual(received[0]["credits"], 12345)
                self.assertEqual(request("POST", "/result", {"id": pending["id"], "result": result("coins")}, extension=True)[0], 409)
                self.assertEqual(transport.read("coins", {}, KEY)["error"], "bridge_timeout")
                self.assertIsNone(server.pending)
                server.last_attached = 0
                self.assertEqual(transport.read("coins", {}, KEY)["error"], "bridge_not_attached")
            self.assertEqual(output.getvalue(), "")
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)

    def test_human_blocker_check_depends_only_on_attachment_health(self):
        src = (ROOT/"tests/check_read_prerequisite.py").read_text()
        for forbidden in ["read_text", "attempts.json", "assess(", "credits", "auctionInfo"]:
            self.assertNotIn(forbidden, src)
        for attached in [True, False]:
            http = MagicMock()
            http.open.return_value.__enter__.return_value.read.return_value = json.dumps({"service": "fc-read-bridge-v1", "protocol": 1, "bind": "127.0.0.1", "attached": attached}).encode()
            with patch("urllib.request.build_opener", return_value=http):
                self.assertEqual(check()["status"], "READY" if attached else "BLOCKED")

    def test_native_snapshot_and_purchased_alias_need_independent_authentication(self):
        h = Harness({"edge": FakeTransport(), "direct_http": FakeTransport()}, KEY); h.suite()
        with tempfile.TemporaryDirectory() as directory:
            baseline = h.save(Path(directory)/"synthetic-only.json")
        for a in baseline["attempts"]:
            if a["operation"] == "purchased":
                a["result"] = empty_result("service_unavailable")
            if a["operation"] == "unassigned":
                a["result"]["items"] = []
                a["result"]["network"][0]["path"] = "/ut/game/fc27/purchased/items"
            if a["operation"] == "club":
                a["result"]["network"] = []
        errors, facts = assess(baseline)
        self.assertNotIn("criterion_5_live_club_unverified", errors)
        self.assertNotIn("criterion_5_live_purchased_unverified", errors)
        self.assertEqual(facts["club_readback_mode"], "NATIVE_SNAPSHOT_NETWORK_FRESHNESS_UNVERIFIED")
        self.assertEqual(facts["purchased_readback_mode"], "SHARED_PURCHASED_UNASSIGNED_ENDPOINT")
        wrong_endpoint = copy.deepcopy(baseline)
        for a in wrong_endpoint["attempts"]:
            if a["operation"] == "unassigned":
                a["result"]["network"][0]["path"] = "/ut/game/fc27/unassigned"
        self.assertIn("criterion_5_live_purchased_unverified", assess(wrong_endpoint)[0])
        no_anchor = copy.deepcopy(baseline)
        for a in no_anchor["attempts"]:
            if a["operation"] == "coins":
                a["result"]["network"] = []
        self.assertIn("criterion_5_live_club_unverified", assess(no_anchor)[0])
        wrong_platform = copy.deepcopy(baseline)
        for a in wrong_platform["attempts"]:
            if a["operation"] == "club":
                a["result"]["platform"] = "ps5"
        self.assertIn("criterion_5_live_club_unverified", assess(wrong_platform)[0])

    def test_exact_definition_survives_absent_wire_properties_and_platform_groups_stay_separate(self):
        h = Harness({"edge": FakeTransport(), "direct_http": FakeTransport()}, KEY); h.suite()
        with tempfile.TemporaryDirectory() as directory:
            record = h.save(Path(directory)/"synthetic-only.json")
        for a in record["attempts"]:
            if a["transport"] == "direct_http": a["result"]["platform"] = "ps5"
            for row in a["result"]["auctions"] or []:
                row["item"].update(resource_id=None, asset_id=None)
        errors, facts = assess(record)
        self.assertNotIn("criterion_3_live_listing_identity_prices_expiry_unverified", errors)
        self.assertEqual(set(facts["comparable_groups"]), {"pc:90001", "ps5:90001"})
        self.assertEqual(facts["comparable_groups"]["pc:90001"]["platform"], "pc")
        self.assertEqual(facts["comparable_groups"]["ps5:90001"]["platform"], "ps5")
        for a in record["attempts"]:
            for row in a["result"]["auctions"] or []: row["item"]["definition_id"] = None
        self.assertIn("criterion_3_live_listing_identity_prices_expiry_unverified", assess(record)[0])

    def test_javascript_runtime_and_cli_explicit_commands(self):
        self.assertIsNotNone(shutil.which("node"))
        process = subprocess.run(["node", str(ROOT/"tests/read_bridge_checks.cjs")], capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stdout+process.stderr)
        for module in ["fc_access.harness", "fc_access.read_server"]:
            process = subprocess.run([sys.executable, "-m", module, "--help"], cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
