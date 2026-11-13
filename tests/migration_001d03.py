"""Keep pre-change audits about their recorded revision after authorized D2 edits.

Current migrated bytes must match the new change manifest; the original Git blob
must match the immutable entry digest. All other evidence is read unchanged.
No runtime service imports this audit helper or uses hashes for authorization.
"""
import hashlib
import json
from pathlib import Path
import subprocess
from migration_001d06 import source_before_foundation

ROOT=Path(__file__).resolve().parents[1]
MIGRATED={'fc_access/bidding_v1/adapter.py','fc_access/bidding_v1/rules.py',
          'fc_access/durability_v1/harness.py','fc_access/pricing.py','tests/test_bidding_v1.py'}


def historical_reader(reader):
    manifest=json.loads((ROOT/'docs/research/001d/001d-03/migration.json').read_text())
    if set(manifest['paths'])!=MIGRATED:
        raise AssertionError('unexpected_migration_scope')
    entry=json.loads((ROOT/'docs/research/001d/entry.json').read_text())
    current=json.loads((ROOT/'docs/research/001d/001d-04/migration.json').read_text())
    if set(current['paths']) != MIGRATED | {'tests/test_durability_v1.py'}:
        raise AssertionError('unexpected_pricing_migration_scope')
    def read(path):
        raw=source_before_foundation(path, reader(path))
        if path not in current['paths']:return raw
        record=current['paths'][path]
        prior=manifest['paths'][path]['after_sha256'] if path in MIGRATED else entry['sha256'][path]
        if hashlib.sha256(raw).hexdigest()!=record['after_sha256'] or record['before_sha256']!=prior:
            raise AssertionError('migrated_source_changed:'+path)
        original=manifest['paths'][path]['before_sha256'] if path in MIGRATED else record['before_sha256']
        if original!=entry['sha256'][path]:
            raise AssertionError('original_migration_chain_changed:'+path)
        result=subprocess.run(['git','show',entry['head']+':'+path],cwd=ROOT,capture_output=True,timeout=10)
        if result.returncode or hashlib.sha256(result.stdout).hexdigest()!=original:
            raise AssertionError('original_source_missing:'+path)
        return result.stdout
    return read
