"""Execute authored JS and loopback HTTP queue, without using the live browser."""
import http.client
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.transaction_server import TransactionServer
from fc_access.harness import empty_result
from check_transaction_prerequisite import check


class BridgeTests(unittest.TestCase):
    def test_actual_javascript_with_synthetic_native_observables(self):
        p = subprocess.run(["node", "tests/transaction_bridge_checks.cjs"], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("synthetic only", p.stdout)

    def test_real_loopback_protocol_at_most_once_dispatch_and_late_reply(self):
        server = TransactionServer(port=0, wait_seconds=.3)
        self.assertEqual(server.server_address[0], "127.0.0.1")
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        def request(method, path, value=None, extension=False, extra=None):
            h = {"Content-Type": "application/json"}
            if extension:
                h["Origin"] = "chrome-extension://" + "a" * 32
            h.update(extra or {})
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            conn.request(method, path, json.dumps(value) if value is not None else None, h)
            r = conn.getresponse()
            self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))
            result = r.status, json.loads(r.read())
            conn.close()
            return result
        body = {"operation": "buy", "params": {"item_id": "item:" + "a" * 24, "definition_id": 90001,
                "trade_id": "trade:" + "b" * 24, "buy_now_price": 200}, "evidence_key": "c" * 32}
        try:
            self.assertEqual(request("GET", "/health")[1]["service"], "fc-transaction-bridge-v3")
            for headers in ({"Origin": "https://attacker.invalid"}, {"Host": "attacker.invalid"}, {"Sec-Fetch-Site": "cross-site"}):
                self.assertEqual(request("POST", "/run", body, extra=headers)[0], 403)
            self.assertEqual(request("POST", "/next", {})[0], 403)
            self.assertFalse(request("GET", "/health")[1]["attached"])
            self.assertEqual(request("POST", "/next", {"bridge_version": 3}, extension=True)[0], 200)
            self.assertTrue(request("GET", "/health")[1]["attached"])
            self.assertEqual(request("POST", "/next", {}, extension=True)[0], 400, "legacy extension cannot claim current attachment")
            self.assertEqual(request("POST", "/run", body | {"operation": "eval"})[0], 400)
            self.assertEqual(request("POST", "/run", body | {"params": body["params"] | {"buy_now_price": 10000}})[0], 400)
            results = []
            caller = threading.Thread(target=lambda: results.append(request("POST", "/run", body)))
            caller.start()
            deadline, pending = time.monotonic() + 2, None
            while pending is None and time.monotonic() < deadline:
                pending = request("POST", "/next", {"bridge_version": 3}, extension=True)[1]
                if pending is None:
                    time.sleep(.005)
            self.assertIsNotNone(pending)
            self.assertEqual(pending["operation"], "buy")
            self.assertIsNone(request("POST", "/next", {"bridge_version": 3}, extension=True)[1])
            self.assertEqual(request("POST", "/run", body)[0], 409)
            bad = empty_result("service_timeout") | {"cookie": "synthetic-private-canary"}
            self.assertEqual(request("POST", "/result", {"id": pending["id"], "result": bad}, extension=True)[0], 400)
            caller.join(3)
            self.assertEqual(results[0][1]["error"], "bridge_timeout")
            self.assertEqual(request("POST", "/result", {"id": pending["id"], "result": empty_result("service_timeout")}, extension=True)[0], 409)
            self.assertIsNone(request("POST", "/next", {"bridge_version": 3}, extension=True)[1], "timed-out write is never requeued")
        finally:
            server.shutdown()
            server.server_close()
            t.join(3)

    def test_prerequisite_only_checks_human_attachment(self):
        for attached in (True, False):
            http = MagicMock()
            http.open.return_value.__enter__.return_value.read.return_value = json.dumps({"service": "fc-transaction-bridge-v3", "protocol": 3, "bind": "127.0.0.1", "attached": attached}).encode()
            with patch("urllib.request.build_opener", return_value=http):
                self.assertEqual(check()["status"], "READY" if attached else "BLOCKED")
        source = (ROOT / "tests/check_transaction_prerequisite.py").read_text()
        for forbidden in ("live.json", "read_text", "assess(", "/run", "coins", "auctionInfo"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
