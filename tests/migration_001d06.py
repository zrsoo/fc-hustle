"""Read sealed pre-foundation snapshots for historical contract interpretation.

No assertion binds an evolving implementation to a source digest.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs/research/001d/001d-06'


def source_before_foundation(path, raw):
    record = json.loads((OUT/'migration.json').read_text())['paths'].get(path)
    return (OUT/record['snapshot']).read_bytes() if record else raw
