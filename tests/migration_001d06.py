"""Strictly bind historical source audits to their recorded pre-foundation bytes.

Current sources must independently match the new migration manifest. No sealed
evidence or historical manifest is edited, and runtime code never imports this.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs/research/001d/001d-06'


def source_before_foundation(path, raw):
    manifest = json.loads((OUT/'migration.json').read_text())
    record = manifest['paths'].get(path)
    if record is None:
        return raw
    if hashlib.sha256(raw).hexdigest() != record['after_sha256']:
        raise AssertionError('foundation_source_changed:'+path)
    before = (OUT/record['snapshot']).read_bytes()
    if hashlib.sha256(before).hexdigest() != record['before_sha256']:
        raise AssertionError('foundation_snapshot_changed:'+path)
    return before
