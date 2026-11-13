"""002-01 acceptance: execute native behavior and preserve sealed evidence offline."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.evidence import evidence_hashes, is_evidence
from fc_access.production_v1.contracts import parse_response, stamp
from historical_contracts import parse_response as parse_historical_response
from fc_access import release_audit_v1

PRESERVATION = ROOT/'docs/research/002/002-01/preservation.json'


def preservation_defects(manifest, read):
    defects = []
    for path, digest in manifest['evidence_sha256'].items():
        if not is_evidence(path):
            defects.append('mutable_path:'+path)
            continue
        try:
            if hashlib.sha256(read(path)).hexdigest() != digest:
                defects.append('changed:'+path)
        except FileNotFoundError:
            defects.append('missing:'+path)
    return defects


class NativeStatusAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'samples.json'
            result = subprocess.run(['node', 'tests/native_status_checks.cjs', str(path)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=40)
            if result.returncode:
                raise AssertionError(result.stdout+result.stderr)
            cls.samples = json.loads(path.read_text(encoding='utf-8'))

    def test_c0_c1_actual_native_status_and_local_support_parse(self):
        operations = set()
        for sample in self.samples:
            c, v = sample['command'], sample['response']
            if not v['result']['success']:
                continue
            operations.add(c['operation'])
            self.assertEqual(parse_response(v, c, now=stamp(sample['now'])), v)
            if c['operation'] == 'status_support':
                self.assertEqual(v['freshness']['request_count'], 0)
                self.assertIsNone(v['freshness']['network_at'])
                self.assertNotIn('source_sha256', v['result'])
        self.assertEqual(operations, {'watched', 'status', 'status_support'})

    def test_c0_c1_parser_rejects_forged_auth_route_identity_schema_freshness_and_epochs(self):
        sample = next(s for s in self.samples if s['command']['operation'] == 'status' and s['response']['result']['success'])
        c, base, now = sample['command'], sample['response'], stamp(sample['now'])
        changes = [
            lambda v: v['result']['network'][0].update(method='PUT'),
            lambda v: v['result']['network'][0].update(path='/ut/game/fc27/watchlist'),
            lambda v: v['result']['network'][0].update(host='outside.example'),
            lambda v: v['result']['network'][0].update(session_header_present=False),
            lambda v: v['result']['network'][0].update(status=401),
            lambda v: v['result']['network'][0].update(query={'trade_id':'trade:'+'e'*24}),
            lambda v: v['result'].update(network=[]),
            lambda v: v['result'].update(status=201),
            lambda v: v['result'].update(auctions=[base['result']['auctions'][0]]*2),
            lambda v: v['result']['auctions'][0].update(trade_id='trade:'+'e'*24),
            lambda v: v['result']['auctions'][0]['item'].update(item_id='item:'+'e'*24),
            lambda v: v['result']['auctions'][0]['item'].update(definition_id=99),
            lambda v: v['result']['auctions'][0]['item'].update(definition_id=False),
            lambda v: v['result']['auctions'][0].update(trade_state=None),
            lambda v: v['result']['auctions'][0].update(bid_state='unknown'),
            lambda v: v['result']['auctions'][0].update(native_is_won='yes'),
            lambda v: v['result']['auctions'][0].update(current_bid=-1),
            lambda v: v['freshness'].update(network_at=(now-timedelta(seconds=31)).isoformat()),
            lambda v: v['freshness'].update(network_at=(now+timedelta(seconds=1)).isoformat()),
            lambda v: v['freshness'].update(source='fixture'),
            lambda v: v['freshness'].update(request_count=0),
            lambda v: v['context'].update(identity_namespace='e'*32),
        ]
        for field in c['fences']:
            changes.append(lambda v, field=field: v['fences'].update({field:99 if field=='epoch' else 'e'*32}))
        for index, change in enumerate(changes):
            value = deepcopy(base); change(value)
            with self.subTest(case=index), self.assertRaises(ValueError):
                parse_response(value, c, now=now)
        with self.assertRaisesRegex(ValueError, 'stale_or_unauthenticated_source'):
            parse_response(base, c, now=now+timedelta(seconds=31))

    def test_c0_local_availability_cannot_be_promoted_to_authenticated_status(self):
        sample = next(s for s in self.samples if s['command']['operation']=='status_support' and s['response']['result']['success'])
        c, base, now = sample['command'], sample['response'], stamp(sample['now'])
        for available in (True, False):
            value = deepcopy(base); value['result']['function_available'] = available
            self.assertEqual(parse_response(value, c, now=now), value)
        for change in (
            lambda v: v['result'].update(function_available=1),
            lambda v: v['result'].update(source_match=True),
            lambda v: v['freshness'].update(network_at=now.isoformat()),
            lambda v: v['freshness'].update(request_count=1),
            lambda v: v['freshness'].update(observed_at=(now-timedelta(seconds=31)).isoformat()),
        ):
            value=deepcopy(base);change(value)
            with self.assertRaises(ValueError):
                parse_response(value, c, now=now)

    def test_c2_historical_digest_is_provenance_and_current_protocol_rejects_old_shape(self):
        checkpoint=json.loads((ROOT/'docs/research/001d/001d-05/s1-checkpoint.json').read_text(encoding='utf-8'))
        sample=checkpoint['source_inspections'][0]
        c, base=sample['command'], sample['response']
        now=stamp(base['freshness']['observed_at'])
        with self.assertRaisesRegex(ValueError, 'invalid_fields'):
            parse_response(base, c, now=now)
        expected=parse_historical_response(base, c, now=now)
        # These are in-memory provenance edits, never changes to a sealed capture.
        evolved=deepcopy(base)
        evolved['result'].update(source_sha256='unrecognized historical provenance', source_match=False)
        self.assertEqual(parse_historical_response(evolved, c, now=now), expected)

    def test_c2_real_auditor_accepts_source_evolution_and_rejects_EA_evidence_changes(self):
        def evolved(path):
            raw=release_audit_v1.read(path)
            return raw if is_evidence(path) else raw+b'\nimplementation may evolve\n'
        self.assertEqual(release_audit_v1.preserve(evolved),release_audit_v1.preserve())
        target='docs/research/001c/001c-06-resume-02/comparables-2.json'
        def changed(path):
            raw=evolved(path)
            return raw+b' ' if path==target else raw
        with self.assertRaises(ValueError):
            release_audit_v1.preserve(changed)

    def test_c2_c3_historical_evidence_and_completed_windows_remain_unchanged(self):
        manifest=json.loads(PRESERVATION.read_text(encoding='utf-8'))
        paths=manifest['evidence_sha256']
        self.assertEqual(evidence_hashes(paths),paths)
        self.assertGreater(len(paths),100)
        for path in ('docs/research/001d/final-remediation/live-checkpoint.json',
                     'docs/research/001d/final-remediation/evidence-manifest.json',
                     'docs/research/001c/001c-06-resume-01/source-contract.json',
                     'docs/research/001d/001d-05/s1-checkpoint.json'):
            self.assertIn(path,paths)
        self.assertEqual(preservation_defects(manifest,lambda p:(ROOT/p).read_bytes()),[])
        target='docs/research/001d/final-remediation/live-checkpoint.json'
        single={'evidence_sha256':{target:paths[target]}}
        self.assertEqual(preservation_defects(single,lambda p:b'changed capture'),['changed:'+target])
        def absent(path): raise FileNotFoundError(path)
        self.assertEqual(preservation_defects(single,absent),['missing:'+target])
        for path in ('AGENTS.md','browser/production-v1/page.js','tests/test_00201_native_status.py',
                     'browser/production-v1/manifest.json'):
            self.assertEqual(preservation_defects({'evidence_sha256':{path:'provenance'}},absent),['mutable_path:'+path])


if __name__=='__main__':
    unittest.main(verbosity=2)
