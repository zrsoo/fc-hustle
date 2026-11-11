"""Explicit, one-shot public GET research. Never called by offline validators.

No authentication, browser impersonation, cookie jar, retries or challenge solving.
Raw public responses stay in ignored private-captures; evidence retains only
allowlisted metadata. Run in a NEW directory; existing captures are never replaced.
"""
import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def utc():
    return datetime.now(timezone.utc).isoformat()


def capture(urls, output, private):
    output.mkdir(parents=True, exist_ok=False)
    private.mkdir(parents=True, exist_ok=False)
    rows = []
    # A plain identified client; no credentials or browser headers.
    opener = urllib.request.build_opener()
    for index, url in enumerate(urls):
        started = utc()
        tick = time.monotonic()
        row = {"id": f"http-{index:02}", "url": url, "method": "GET",
               "started_at_utc": started, "access": "anonymous_public_get",
               "authentication_sent": False, "retry_count": 0}
        request = urllib.request.Request(url, headers={
            "User-Agent": "fc-hustle-readonly-research/1.0",
            "Accept": "application/json, text/html;q=0.9, */*;q=0.5"})
        try:
            try:
                response = opener.open(request, timeout=25)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                body = response.read(2 * 1024 * 1024 + 1)
                row.update(status=response.code, final_url=response.geturl(),
                           headers={key.lower(): response.headers[key] for key in (
                               "Content-Type", "Date", "ETag", "Last-Modified",
                               "Retry-After", "Cache-Control") if key in response.headers},
                           bytes_read=len(body), truncated=len(body) > 2 * 1024 * 1024,
                           response_sha256=hashlib.sha256(body).hexdigest())
                (private / (row["id"] + ".body")).write_bytes(body)
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            row.update(status=None, error_type=type(error).__name__)
        row.update(ended_at_utc=utc(), elapsed_ms=round((time.monotonic()-tick)*1000, 3))
        rows.append(row)
        # Incremental evidence survives interruption; never retry a refusal.
        (output / "http.json").write_text(json.dumps({"schema": 1,
            "collector": "experiments/price_provider_research/collect_http.py",
            "user_agent": "fc-hustle-readonly-research/1.0", "attempts": rows},
            indent=2) + "\n", encoding="utf-8")
        print(row["id"], row["status"], url, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--private", required=True, type=Path)
    parser.add_argument("urls", nargs="+")
    args = parser.parse_args()
    capture(args.urls, args.output, args.private)
