"""Separate loopback read command queue; leaves the task_02 observer untouched."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import secrets
import threading
import time

from .harness import command, empty_result, validate_result

HOST, PORT = "127.0.0.1", 8767


class ReadServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=PORT, wait_seconds=60):
        self.condition = threading.Condition()
        self.pending = None
        self.last_attached = 0
        self.wait_seconds = wait_seconds
        super().__init__((HOST, port), Handler)

    def handle_error(self, *args):
        pass


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = "FCReadBridge/1", ""

    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, *args):
        pass

    def reply(self, code, value):
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def origin_ok(self, extension=False):
        if self.headers.get("Host") != f"{HOST}:{self.server.server_port}":
            return False
        origin = self.headers.get("Origin")
        if extension:
            return bool(re.fullmatch(r"chrome-extension://[a-p]{32}", origin or ""))
        return origin is None and self.headers.get("Sec-Fetch-Site") is None

    def payload(self):
        if self.headers.get("Content-Type") != "application/json" or self.headers.get("Transfer-Encoding"):
            raise ValueError("encoding_denied")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 262144:
            raise ValueError("size_denied")
        def unique(pairs):
            result = {}
            for k, v in pairs:
                if k in result:
                    raise ValueError("duplicate_field")
                result[k] = v
            return result
        return json.loads(self.rfile.read(length), object_pairs_hook=unique)

    def do_GET(self):
        if not self.origin_ok(extension=self.path == "/next"):
            return self.reply(403, {"error": "origin_denied"})
        if self.path == "/health":
            return self.reply(200, {"service": "fc-read-bridge-v1", "protocol": 1,
                                    "bind": HOST, "attached": time.monotonic()-self.server.last_attached < 90})
        if self.path == "/next":
            return self.next_command()
        return self.reply(404, {"error": "not_found"})

    def next_command(self):
        with self.server.condition:
            self.server.last_attached = time.monotonic()
            pending = self.server.pending
            if pending and pending["deadline"] > time.monotonic() and not pending["delivered"]:
                pending["delivered"] = True
                return self.reply(200, pending["command"])
        return self.reply(200, None)

    def do_POST(self):
        if self.path not in {"/run", "/result", "/next"}:
            return self.reply(404, {"error": "not_found"})
        if not self.origin_ok(extension=self.path in {"/result", "/next"}):
            return self.reply(403, {"error": "origin_denied"})
        try:
            value = self.payload()
            if self.path == "/next":
                if not isinstance(value, dict) or value:
                    raise ValueError("invalid_fields")
                return self.next_command()
            if self.path == "/result":
                if not isinstance(value, dict) or set(value) != {"id", "result"}:
                    raise ValueError("invalid_fields")
                result = validate_result(value["result"])
                with self.server.condition:
                    pending = self.server.pending
                    if not pending or not pending["delivered"] or pending["result"] is not None or pending["command"]["id"] != value["id"] or pending["deadline"] <= time.monotonic():
                        return self.reply(409, {"error": "unknown_or_expired_command"})
                    pending["result"] = result
                    self.server.condition.notify_all()
                return self.reply(200, {"accepted": True})
            if not isinstance(value, dict) or set(value) != {"operation", "params", "evidence_key"}:
                raise ValueError("invalid_fields")
            request = command(value["operation"], value["params"])
            if not isinstance(value["evidence_key"], str) or not re.fullmatch(r"[a-f0-9]{32}", value["evidence_key"]):
                raise ValueError("invalid_key")
            with self.server.condition:
                if self.server.pending is not None:
                    return self.reply(409, {"error": "bridge_busy"})
                if time.monotonic()-self.server.last_attached >= 90:
                    return self.reply(200, empty_result("bridge_not_attached"))
                pending = {"command": request | {"id": secrets.token_hex(16), "evidence_key": value["evidence_key"]},
                           "deadline": time.monotonic()+self.server.wait_seconds, "delivered": False, "result": None}
                self.server.pending = pending
                try:
                    self.server.condition.wait_for(lambda: pending["result"] is not None, timeout=self.server.wait_seconds)
                    result = pending["result"] or empty_result("bridge_timeout")
                finally:
                    self.server.pending = None
            return self.reply(200, result)
        except (OSError, ValueError, TypeError, OverflowError):
            return self.reply(400, {"error": "invalid_payload"})


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    server = ReadServer()
    print("FC read bridge on http://127.0.0.1:8767 (finite read commands only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
