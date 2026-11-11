"""Local observation sink. No browser command execution or credential transport."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
import time

from .schema import utc_now, validate_observation

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "docs/research/browser-access/live-v2.json"
HOST = "127.0.0.1"
PORT = 8766


class ObservationServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=PORT, evidence_path=LIVE):
        self.evidence_path = Path(evidence_path)
        self.observations = []
        self.last_attached = 0.0
        self.observer_version = 0
        self.lock = threading.Lock()
        # Preserve already collected sanitized evidence when upgrading this local sink.
        try:
            previous_path = self.evidence_path
            if self.evidence_path == LIVE and not previous_path.exists():
                previous_path = LIVE.with_name("live.json")
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
            if previous.get("schema") == 1 and previous.get("source") == "edge-main-world-observer":
                self.observations = [validate_observation(v) for v in previous["observations"]][-200:]
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            self.observations = []
        super().__init__((HOST, port), Handler)

    def handle_error(self, request, client_address):
        # Base implementation prints exceptions and potentially unsanitized input.
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "FCObserver/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, *args):
        pass

    def valid_host(self):
        return self.headers.get("Host") == f"{HOST}:{self.server.server_port}"

    def reply(self, code, value):
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {"error": "host_denied"})
        if self.path != "/health":
            return self.reply(404, {"error": "not_found"})
        return self.reply(200, {"service": "fc-config-observer-v1", "bind": HOST,
                                "attached": time.monotonic() - self.server.last_attached < 90,
                                "observer_version": self.server.observer_version})

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        if not self.valid_host() or not re.fullmatch(r"chrome-extension://[a-p]{32}", origin):
            return self.reply(403, {"error": "origin_denied"})
        if self.path not in ("/attached", "/observation"):
            return self.reply(404, {"error": "not_found"})
        if self.headers.get("Content-Type") != "application/json" or self.headers.get("Transfer-Encoding"):
            return self.reply(415, {"error": "encoding_denied"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                return self.reply(413, {"error": "size_denied"})
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate_field")
                    result[key] = value
                return result
            value = json.loads(self.rfile.read(length), object_pairs_hook=unique_object)
            if self.path == "/attached":
                if value not in ({"observer_installed": True}, {"observer_installed": True, "observer_version": 2}):
                    raise ValueError("invalid_attach")
                self.server.last_attached = time.monotonic()
                self.server.observer_version = value.get("observer_version", 1)
            else:
                value = validate_observation(value, now=utc_now())
                with self.server.lock:
                    self.server.observations = (self.server.observations + [value])[-200:]
                    record = {"schema": 1, "source": "edge-main-world-observer",
                              "received_at": utc_now().isoformat(),
                              "observations": self.server.observations}
                    self.server.evidence_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.server.evidence_path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
                    temporary.replace(self.server.evidence_path)
        except (ValueError, TypeError, OSError, OverflowError):
            return self.reply(400, {"error": "invalid_payload"})
        return self.reply(200, {"accepted": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()  # No externally configurable bind address or evidence path.
    server = ObservationServer()
    print("FC observer ready on http://127.0.0.1:8766 (metadata only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
