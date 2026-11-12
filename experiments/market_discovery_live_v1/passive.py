"""Reuse the existing metadata observer, writing only into this new live run.

No EA requests, page commands, credentials or historical evidence writes.
The append-only ledger supplements the old sink's bounded rolling snapshot.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time

from fc_access.server import ObservationServer
from experiments.market_discovery.model import stamp


def unseen(observations, seen):
    for value in observations:
        key = json.dumps(value, sort_keys=True, separators=(',', ':'))
        if key not in seen:
            seen.add(key)
            yield value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--end-utc', required=True)
    args = parser.parse_args()
    end = stamp(args.end_utc)
    if not args.output_dir.is_dir():
        parser.error('existing_live_run_required')
    ledger = args.output_dir/'passive-observations.jsonl'
    heartbeats = args.output_dir/'passive-heartbeats.jsonl'
    if ledger.exists() or heartbeats.exists():
        parser.error('new_passive_ledger_required')
    server = ObservationServer(port=8766, evidence_path=args.output_dir/'passive-rolling.json')
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    seen = set()
    try:
        with ledger.open('x', encoding='utf-8') as observations, heartbeats.open('x', encoding='utf-8') as status:
            while True:
                now = datetime.now(timezone.utc)
                with server.lock:
                    values = list(server.observations)
                    attached = time.monotonic()-server.last_attached < 90
                    version = server.observer_version
                for value in unseen(values, seen):
                    observations.write(json.dumps({'received_utc': now.isoformat(), 'observation': value})+'\n')
                observations.flush()
                status.write(json.dumps({'at': now.isoformat(), 'attached': attached,
                    'observer_version': version, 'unique_observations_received': len(seen)})+'\n')
                status.flush()
                if now >= end:
                    break
                time.sleep(min(5, (end-now).total_seconds()))
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)


if __name__ == '__main__':
    main()
