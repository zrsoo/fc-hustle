"""Interpret original contracts at the recorded revision, without source pins."""
import json
from pathlib import Path
import subprocess
from migration_001d06 import source_before_foundation

ROOT = Path(__file__).resolve().parents[1]


def historical_reader(reader):
    manifest = json.loads((ROOT/'docs/research/001d/001d-04/migration.json').read_text())
    entry = json.loads((ROOT/'docs/research/001d/entry.json').read_text())
    def read(path):
        if path in manifest['paths']:
            return subprocess.check_output(['git', 'show', entry['head']+':'+path], cwd=ROOT, timeout=10)
        return source_before_foundation(path, reader(path))
    return read
