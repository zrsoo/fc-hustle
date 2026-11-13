"""Offline acceptance artifacts plus runtime security checks. Never fake live access."""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fc_access.schema import validate_observation, utc_now
from fc_access.server import ObservationServer
from validate_browser_live import validate as validate_live, assess as assess_live
from check_browser_prerequisite import check as check_prerequisite




def observation(**changes):
    value = {"event": "authenticated_read", "observed_at": utc_now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
             "game_version": "fc27", "host": "utas.mob.v1.prd.futc-ext.gcp.ea.com",
             "request_prefix": "/ut/game/fc27/", "client_id": "FC27_JS_WEB_APP", "sku": "FUT27WEB",
             "method": "GET", "status": 200, "session_header_present": True, "response_shape": "credits"}
    value.update(changes)
    return value


class BrowserAccessTests(unittest.TestCase):
    def test_verified_report_and_lifecycle_are_grounded_in_real_retained_trace(self):
        directory = ROOT / "docs/research/browser-access"
        verification = json.loads((directory / "verification.json").read_text())
        report = (ROOT / "docs/research/browser-access.md").read_text(encoding="utf-8")
        self.assertEqual(verification["overall"], "VERIFIED")
        self.assertEqual(verification["remaining"], [])
        self.assertIn("Status: **VERIFIED**", report)
        source = json.loads((directory / "live-v2.json").read_text())
        # The observer keeps appending real traffic after the report checkpoint.
        # Replay historical access at the receipt, then compare the report with the
        # retained trace at its recorded receipt/validation time.
        self.assertEqual(assess_live(source, now=datetime.fromisoformat(source["received_at"]))[0], [])
        checkpoint = copy.deepcopy(source)
        cutoff = datetime.fromisoformat(verification["evidence"]["received_at"])
        checkpoint["received_at"] = verification["evidence"]["received_at"]
        checkpoint["observations"] = [v for v in source["observations"]
                                      if datetime.fromisoformat(v["observed_at"].replace("Z", "+00:00")) <= cutoff]
        errors, facts = assess_live(checkpoint, now=datetime.fromisoformat(verification["evidence"]["validated_at"]))
        self.assertEqual(errors, [])
        configuration = {k: facts[k] for k in ("game_version", "host", "request_prefix", "client_id", "sku")}
        self.assertEqual(verification["live_configuration"]["configuration"], configuration)
        self.assertEqual(verification["live_configuration"]["summary"], facts)
        self.assertEqual(verification["session_lifecycle"], facts["session_lifecycle"])
        for value in configuration.values():
            self.assertIn(value, report)
        for value in verification["live_configuration"]["observations"]:
            self.assertIn(validate_observation(value), source["observations"])
        for read in facts["authenticated_reads"]:
            self.assertIn(read["observed_at"], report)
            self.assertIn(read["response_shape"], report)
        self.assertIn(facts["session_lifecycle"]["last_later_successful_request_at"], report)
        self.assertIn("not counted as additional authenticated readbacks", report)
        self.assertEqual(hashlib.sha256((directory / "live.json").read_bytes()).hexdigest(),
                         verification["evidence"]["original_archive_sha256"])
        self.assertTrue((ROOT / "docs/research/browser-access-history.md").exists())
        self.assertEqual(verification["endpoint_checks"], [{"address": "127.0.0.1", "port": 8766,
                                                          "service": "fc-config-observer-v1"}])

    def test_review_matches_executed_bridge_sources_and_retained_metadata(self):
        directory = ROOT / "docs/research/browser-access"
        review = json.loads((directory / "review.json").read_text())
        expected = {"browser/observer/manifest.json", "browser/observer/page.js", "browser/observer/worker.js",
                    "browser/observer/native-read-probe.js", "fc_access/__init__.py", "fc_access/schema.py", "fc_access/server.py", "fc_access/inspect.py"}
        self.assertEqual(set(review["files"]), expected)
        from js_contract import check_js
        check_js(self, 'browser_observer_checks.cjs')
        self.assertEqual(review["third_party_code_executed"], False)
        verification = json.loads((directory / "verification.json").read_text())
        self.assertEqual(verification["task"], "task_02")
        self.assertIn(verification["overall"], {"PARTIAL/BLOCKED", "VERIFIED"})
        self.assertEqual(verification["document_control"], {"connected_sessions": 0})
        if verification["overall"] == "PARTIAL/BLOCKED":
            self.assertIn(verification["live_configuration"]["status"], {"UNVERIFIED", "PARTIAL"})
        else:
            self.assertEqual(assess_live(source := json.loads((directory / 'live-v2.json').read_text()), now=datetime.fromisoformat(source['received_at']))[0], [])
        self.assertEqual(verification["browser_mutations"], [])
        self.assertEqual(verification["listener"]["address"], "127.0.0.1")
        self.assertEqual(verification["listener"]["port"], 8766)
        self.assertIs(type(verification["listener"]["attached"]), bool)
        allowed_artifacts = {"inspection.json", "review.json", "verification.json", "live.json", "live-v2.json"}
        self.assertTrue({p.name for p in directory.iterdir() if p.is_file()}.issubset(allowed_artifacts))
        for artifact in directory.glob("*.json"):
            value = json.loads(artifact.read_text())
            def check_keys(obj):
                if isinstance(obj, dict):
                    for key, child in obj.items():
                        self.assertNotIn(key.lower(), {"password", "cookie", "cookies", "token", "sid", "session_id", "account_id", "email", "persona", "username", "headers", "body", "response_body"})
                        check_keys(child)
                elif isinstance(obj, list):
                    for item in obj: check_keys(item)
            check_keys(value)

    def test_criterion_0_inspection_is_current_and_does_not_assume_cdp(self):
        data = json.loads((ROOT / "docs/research/browser-access/inspection.json").read_text())
        self.assertEqual(data["task"], "task_02")
        self.assertLess(abs((datetime.fromisoformat(data['inspected_at']) - datetime.fromisoformat(json.loads((ROOT/'docs/research/browser-access/verification.json').read_text())['evidence']['validated_at'])).total_seconds()), 86400)
        process = data["edge_processes"]
        self.assertGreater(process["edge_process_count"], 0)
        self.assertIsInstance(process["debug_ports"], list)
        self.assertIsInstance(process["edge_listeners"], list)
        self.assertIsInstance(process["debug_pipe_process_count"], int)
        self.assertIsInstance(data["devtools_active_port_markers"], int)
        self.assertTrue({9222, 9223}.issubset({v["port"] for v in data["cdp_probes"]}))
        for probe in data["cdp_probes"]:
            self.assertEqual(probe["address"], "127.0.0.1")
            self.assertIs(type(probe["available"]), bool)
        self.assertGreater(data["extension_permissions"]["manifests"], 0)
        self.assertIn("Custom profile", data["limits"])
        source = (ROOT / "fc_access/inspect.py").read_text()
        self.assertNotIn("print(process", source)
        for filename in ["Cookies", "Login Data", "Preferences", "History"]:
            self.assertNotIn(' / "' + filename + '"', source)

    def test_criteria_1_2_reviewed_bridge_and_precise_operator_recovery(self):
        report = (ROOT / "docs/research/browser-access.md").read_text(encoding="utf-8")
        for required in ["PARTIAL/BLOCKED", "edge://extensions", "Developer mode", "Load unpacked",
                         "C:\\hustle\\fc-hustle\\browser\\observer", "same Edge profile", "No tab refresh",
                         "python -m fc_access.server", "FC configuration observer", "WAIT", "login screen",
                         "chrome.storage.session", "No Edge process was stopped", "no connected sessions",
                         "not supply default", "UNVERIFIED"]:
            self.assertIn(required, report)
        manifest = json.loads((ROOT / "browser/observer/manifest.json").read_text())
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(set(manifest["permissions"]), {"activeTab", "scripting", "alarms", "storage"})
        self.assertNotIn("content_scripts", manifest)
        worker = (ROOT / "browser/observer/worker.js").read_text()
        for forbidden in ["chrome.tabs.update", "chrome.tabs.remove", "chrome.tabs.reload", "chrome.cookies", "storage.local", "storage.sync", "console.log", "console.error"]:
            self.assertNotIn(forbidden, worker)
        self.assertIn('world: "MAIN"', worker)
        self.assertIn("chrome.storage.session", worker)
        self.assertIn('redirect: "error"', worker)

    def test_criterion_3_no_fixture_is_allowed_to_stand_for_live_evidence(self):
        self.assertIn("missing_live_evidence", validate_live(None))
        first = observation()
        second = observation(observed_at=(utc_now() - timedelta(seconds=10)).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
        record = {"schema": 1, "source": "edge-main-world-observer", "received_at": utc_now().isoformat(),
                  "observations": [first, second]}
        self.assertEqual(validate_live(record), [])  # Synthetic unit test only; never written to live.json.
        for field, value in [("game_version", "fc26"), ("client_id", None), ("sku", None),
                             ("session_header_present", False), ("response_shape", "none"), ("status", 401)]:
            mutated = copy.deepcopy(record)
            for item in mutated["observations"]:
                item[field] = value
            self.assertTrue(validate_live(mutated), field)
        for source in ["fixture", "historical", "mock"]:
            mutated = copy.deepcopy(record); mutated["source"] = source
            self.assertTrue(validate_live(mutated))
        mutated = copy.deepcopy(record); mutated["received_at"] = "2000-01-01T00:00:00+00:00"
        self.assertTrue(validate_live(mutated))
        mutated = copy.deepcopy(record); mutated["observations"] = [first]
        self.assertIn("criterion_3_request_lifecycle_unobserved", validate_live(mutated))
        mutated = copy.deepcopy(record); mutated["observations"][0]["observed_at"] = "2000-01-01T00:00:00.000Z"
        self.assertIn("criterion_3_request_lifecycle_unobserved", validate_live(mutated))
        v2 = copy.deepcopy(record)
        for item in v2["observations"]:
            item.update(observer_version=2, route="user/credits", response_type="arraybuffer")
        self.assertEqual(validate_live(v2), [])
        v2["observations"][0]["route"] = "other"
        self.assertIn("invalid_or_sensitive_observation", validate_live(v2))

    def test_archives_cannot_prove_current_access_or_poison_valid_current_evidence(self):
        recent = observation()
        prior = observation(observed_at=(utc_now() - timedelta(seconds=10)).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
        old = observation(observed_at="2000-01-01T00:00:00.000Z")
        record = {"schema": 1, "source": "edge-main-world-observer", "received_at": utc_now().isoformat(),
                  "observations": [old, prior, recent]}
        errors, facts = assess_live(record)
        self.assertEqual(errors, [])
        self.assertEqual(facts["archived_observation_count"], 1)
        self.assertEqual(facts["current_observation_count"], 2)
        archived_only = copy.deepcopy(record); archived_only["observations"] = [old, old]
        self.assertIn("criterion_1_authenticated_fc27_page_not_reached", validate_live(archived_only))
        archived_secret = copy.deepcopy(record); archived_secret["observations"][0]["cookie"] = "synthetic-private-canary"
        self.assertIn("invalid_or_sensitive_observation", validate_live(archived_secret))
        future = copy.deepcopy(record)
        future["observations"][0]["observed_at"] = (utc_now() + timedelta(hours=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        self.assertIn("future_page_observation", validate_live(future))

    def test_lifecycle_distinguishes_transport_activity_from_authenticated_readback(self):
        anchor = observation(observed_at=(utc_now() - timedelta(seconds=10)).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
        transport = observation(event="configured_request", response_shape="none")
        record = {"schema": 1, "source": "edge-main-world-observer", "received_at": utc_now().isoformat(),
                  "observations": [anchor, transport]}
        errors, facts = assess_live(record)
        self.assertEqual(errors, [])
        self.assertEqual(len(facts["authenticated_reads"]), 1)
        self.assertEqual(facts["session_lifecycle"]["transport_activity_after_authenticated_read"], "OBSERVED")
        for fact in ["repeat_authenticated_readback", "renewal", "expiry", "logout_reconnect"]:
            self.assertEqual(facts["session_lifecycle"][fact], "UNVERIFIED")
        no_auth = copy.deepcopy(record)
        no_auth["observations"][0].update(event="configured_request", response_shape="none")
        self.assertIn("criterion_1_authenticated_fc27_page_not_reached", validate_live(no_auth))
        for change in [{"session_header_present": False}, {"client_id": None}, {"status": 401}, {"observed_at": anchor["observed_at"]}]:
            mutated = copy.deepcopy(record); mutated["observations"][1].update(change)
            self.assertIn("criterion_3_request_lifecycle_unobserved", validate_live(mutated))

    def test_criterion_4_allowlist_rejects_sensitive_or_misleading_payloads(self):
        value = observation()
        self.assertEqual(validate_observation(value), value)
        v2 = observation(observer_version=2, route="user/credits", response_type="arraybuffer")
        self.assertEqual(validate_observation(v2), v2)
        for changes in [{"route": "club/123/private"}, {"response_type": "private"}, {"observer_version": True}, {"route": "other"}]:
            with self.assertRaises((TypeError, ValueError)):
                validate_observation({**v2, **changes})
        for key in ["password", "cookie", "token", "sid", "account", "coins", "full_url", "headers", "body", "personal_name"]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_observation(observation(**{key: "synthetic-private-canary"}))
        for field, values in {
            "host": ["0.0.0.0", "ea.com.attacker.invalid", "utas.ea.com?secret=synthetic", "account@utas.ea.com"],
            "request_prefix": ["/ut/game/fc27/club/123", "/ut/game/fc26/", "/ut/game/fc27/?secret=synthetic"],
            "client_id": ["private-client", "FC26_JS_WEB_APP"], "sku": ["private-sku", "FUT26WEB"],
            "event": ["account=synthetic"], "observed_at": ["2026-11-08T00:00:00.000Z?secret=synthetic"],
            "method": ["GET?private"], "status": [True, "200"], "response_shape": ["private"],
            "session_header_present": ["synthetic"]}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises((ValueError, TypeError)):
                    validate_observation(observation(**{field: value}))

    def test_criterion_4_localhost_sink_rejection_and_no_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "test-evidence.json"
            server = ObservationServer(port=0, evidence_path=evidence)
            self.assertEqual(server.server_address[0], "127.0.0.1")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            output = io.StringIO()
            def request(method, path, value=None, headers=None, raw=None):
                body = raw if raw is not None else json.dumps(value) if value is not None else None
                h = {"Content-Type": "application/json", "Origin": "chrome-extension://" + "a" * 32}
                h.update(headers or {})
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request(method, path, body=body, headers=h)
                response = connection.getresponse()
                result = response.status, json.loads(response.read())
                self.assertIsNone(response.getheader("Access-Control-Allow-Origin"))
                connection.close()
                return result
            try:
                with contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
                    self.assertFalse(request("GET", "/health")[1]["attached"])
                    for headers in [{"Origin": "https://attacker.invalid"}, {"Origin": "null"}, {"Host": "attacker.invalid"}]:
                        self.assertEqual(request("POST", "/observation", observation(), headers)[0], 403)
                    self.assertFalse(evidence.exists())
                    self.assertEqual(request("POST", "/observation", observation(password="synthetic-private-canary"))[0], 400)
                    self.assertFalse(evidence.exists())
                    self.assertEqual(request("POST", "/observation", raw='{"private":"synthetic-private-canary","private":1}')[0], 400)
                    self.assertEqual(request("POST", "/observation", raw="x" * 5000)[0], 413)
                    self.assertEqual(request("POST", "/observation", observation(), {"Content-Type": "text/plain"})[0], 415)
                    self.assertEqual(request("POST", "/execute", observation())[0], 404)
                    self.assertEqual(request("POST", "/attached", {"observer_installed": True})[0], 200)
                    self.assertTrue(request("GET", "/health")[1]["attached"])
                    self.assertEqual(request("GET", "/health")[1]["observer_version"], 1)
                    self.assertEqual(request("POST", "/attached", {"observer_installed": True, "observer_version": 2})[0], 200)
                    self.assertEqual(request("GET", "/health")[1]["observer_version"], 2)
                    self.assertFalse(evidence.exists(), "human attachment must not fabricate FC evidence")
                    self.assertEqual(request("POST", "/observation", observation())[0], 200)
                    saved = json.loads(evidence.read_text())
                    self.assertEqual(len(saved["observations"]), 1)
                    self.assertEqual(saved["source"], "edge-main-world-observer")
                    self.assertEqual(request("POST", "/observation", observation(observed_at="2000-01-01T00:00:00.000Z"))[0], 400)
                    self.assertEqual(request("POST", "/observation", observation(token="synthetic-private-canary"))[0], 400)
                    self.assertEqual(json.loads(evidence.read_text()), saved)
                    self.assertNotIn("synthetic-private-canary", evidence.read_text())
                self.assertEqual(output.getvalue(), "")
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5)
            restored = ObservationServer(port=0, evidence_path=evidence)
            try:
                self.assertEqual(restored.observations, saved["observations"], "sink upgrade must preserve sanitized evidence")
            finally:
                restored.server_close()

    def test_criteria_1_3_4_real_javascript_behavior_with_synthetic_browser(self):
        self.assertIsNotNone(shutil.which("node"), "Node is required to execute observer runtime checks")
        result = subprocess.run(["node", str(ROOT / "tests/browser_observer_checks.cjs")], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS:", result.stdout)
        manifest = json.loads((ROOT / "browser/observer/manifest.json").read_text())
        self.assertEqual(manifest["host_permissions"], ["http://127.0.0.1:8766/*"])
        for script in ["page.js", "worker.js", "native-read-probe.js"]:
            result = subprocess.run(["node", "--check", str(ROOT / "browser/observer" / script)], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0)

    def test_blocker_check_is_only_a_human_prerequisite(self):
        source = (ROOT / "tests/check_browser_prerequisite.py").read_text()
        self.assertNotIn("read_text", source)
        self.assertNotIn("validate_live", source)
        self.assertIn('"/health"', source.replace('"http://127.0.0.1:8766/health"', '"/health"'))
        self.assertNotIn("observations", source)
        for version, attached, expected in [(1, True, "BLOCKED"), (2, False, "BLOCKED"), (2, True, "READY")]:
            health = {"service": "fc-config-observer-v1", "bind": "127.0.0.1", "attached": attached, "observer_version": version}
            opener = MagicMock()
            opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(health).encode()
            with patch("urllib.request.build_opener", return_value=opener):
                self.assertEqual(check_prerequisite()["status"], expected)
                opener.open.assert_called_once_with("http://127.0.0.1:8766/health", timeout=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
