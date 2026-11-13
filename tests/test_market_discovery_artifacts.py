"""T3 portable schema, provenance, measurements, and read-only preservation checks."""
import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.market_discovery.contracts import schema
from experiments.market_discovery.discovery import metrics, pagination
from experiments.market_discovery.model import PROTOCOL, reply, stamp, summary

BASE=ROOT/'experiments/market_discovery'
RUN=BASE/'runs/t3-harness'


from fc_access.evidence import evidence_hashes

def check_schema(value, spec):
    """Small independent evaluator for the keywords used by the retained schema.

    No third-party installation; the runtime's positive projection is checked
    independently below. Invalid fixture cases ensure this checker can fail.
    """
    if 'anyOf' in spec:
        for branch in spec['anyOf']:
            try:
                check_schema(value,branch)
                return
            except (AssertionError,ValueError,TypeError):
                pass
        raise AssertionError('anyOf')
    if 'const' in spec:
        assert type(value) is type(spec['const']) and value==spec['const'],'const'
    if 'enum' in spec:
        assert any(type(value) is type(v) and value==v for v in spec['enum']),'enum'
    types={'object':lambda v:type(v) is dict,'array':lambda v:type(v) is list,'string':lambda v:type(v) is str,
           'integer':lambda v:type(v) is int,'number':lambda v:type(v) in (int,float) and math.isfinite(v),
           'boolean':lambda v:type(v) is bool,'null':lambda v:v is None}
    if 'type' in spec:
        assert types[spec['type']](value),'type'
    if type(value) is dict:
        assert set(spec.get('required',[])) <= set(value),'required'
        if spec.get('additionalProperties') is False:
            assert set(value) <= set(spec['properties']),'additionalProperties'
        for k,v in value.items():
            if k in spec.get('properties',{}): check_schema(v,spec['properties'][k])
    if type(value) is list:
        assert len(value)<=spec.get('maxItems',len(value)),'maxItems'
        if 'items' in spec:
            for item in value: check_schema(item,spec['items'])
    if type(value) in (int,float):
        assert value>=spec.get('minimum',value),'minimum'
        assert value<=spec.get('maximum',value),'maximum'
    if type(value) is str:
        if 'pattern' in spec: assert re.search(spec['pattern'],value),'pattern'
        if spec.get('format')=='date-time': stamp(value)


class ArtifactTests(unittest.TestCase):
    def test_schema_validates_all_retained_observations_and_rejects_canaries(self):
        contract=json.loads((BASE/'observation.schema.json').read_text())
        self.assertEqual(contract,schema())
        count=0
        for name in ('demo','historical','flow','attachment-attempt'):
            artifact=json.loads((RUN/(name+'.json')).read_text())
            self.assertEqual(artifact['account_mutations'],0)
            for record in artifact['records']:
                check_schema(record,contract)
                native_timing={k:record['timing'].get(k) for k in ('worker_poll_to_native_ms','native_service_ms','page_total_ms')}
                reply({'result':record['result'],'timing':native_timing})
                self.assertLessEqual(stamp(record['submitted_utc']),stamp(record['completed_utc']))
                count+=1
        self.assertEqual(count,78)
        source=json.loads((RUN/'demo.json').read_text())['records'][0]
        for change in ('extra','raw_trade','raw_item','platform','game','definition','bool_integer','bad_timestamp'):
            bad=deepcopy(source)
            if change=='extra':bad['token']='private-canary'
            if change=='raw_trade':bad['result']['auctions'][0]['trade_id']='22222222222222222222'
            if change=='raw_item':bad['result']['auctions'][0]['item']['item_id']='11111111111111111111'
            if change=='platform':bad['platform']='ps5'
            if change=='game':bad['game']='fc26'
            if change=='definition':bad['result']['auctions'][0]['item']['definition_id']=None
            if change=='bool_integer':bad['criteria']['definition_id']=True
            if change=='bad_timestamp':bad['submitted_utc']='2026-11-11T22:00:00'
            with self.subTest(change=change), self.assertRaises((AssertionError,ValueError,TypeError)): check_schema(bad,contract)

    def test_recompute_strategy_budget_metrics_and_no_synthetic_live_claims(self):
        artifact=json.loads((RUN/'demo.json').read_text())
        self.assertEqual(artifact['mode'],'SIMULATED')
        self.assertEqual(artifact['protocol_sha256'],hashlib.sha256(PROTOCOL.read_bytes()).hexdigest())
        self.assertEqual(artifact['overall'],metrics(artifact['records']))
        self.assertEqual(artifact['source_availability']['EA']['live_samples'],0)
        self.assertEqual(artifact['source_availability']['external']['status'],'UNAVAILABLE')
        for strategy in 'ABC':
            subset=[r for r in artifact['records'] if r['strategy']==strategy]
            self.assertEqual(artifact['by_strategy'][strategy],metrics(subset))
            self.assertEqual(len(subset),24)
        for w in artifact['windows']:
            records=[r for r in artifact['records'] if r['window']==w['window']]
            self.assertEqual(w['metrics'],metrics(records))
            self.assertEqual(w['pagination'],pagination(records))
            self.assertEqual(w['budget']['requests'],8)
        live=json.loads((RUN/'attachment-attempt.json').read_text())
        self.assertEqual(live['mode'],'LIVE_READ_ONLY')
        self.assertEqual(live['status'],'PARTIAL')
        self.assertEqual(live['stop_reason'],'bridge_unavailable')
        self.assertEqual(live['overall']['EA_requests'],0)
        self.assertIsNone(live['live_opportunity_yield'])
        self.assertEqual(live['source_availability']['EA']['status'],'UNAVAILABLE')
        flow=json.loads((RUN/'flow.json').read_text())
        self.assertEqual(flow['mode'],'SIMULATED')
        self.assertEqual(flow['flow']['intent']['mode'],'DRY_RUN_ONLY')
        self.assertGreaterEqual(flow['flow']['search_to_intent_ms'],100)

    def test_local_baseline_actually_waited_30_seconds_and_aggregates_recompute(self):
        artifact=json.loads((RUN/'local-latency.json').read_text())
        self.assertEqual(artifact['status'],'LOCAL_SIMULATOR_ONLY')
        self.assertEqual(artifact['EA_live_requests'],0)
        self.assertEqual(artifact['account_mutations'],0)
        self.assertEqual(artifact['browser_alternative_status'],'PREPARED_NOT_LIVE_VALIDATED')
        baseline,alternative=artifact['arms']
        self.assertEqual(baseline['transport'],'alarm_30s')
        self.assertEqual(baseline['alarm_interval_seconds'],30)
        self.assertEqual(alternative['transport'],'long_poll')
        for arm in artifact['arms']:
            self.assertEqual(len(arm['records']),3)
            self.assertEqual(arm['end_to_end'],summary([r['end_to_end_ms'] for r in arm['records']]))
            for key,value in arm['latency'].items():
                self.assertEqual(value,summary([r['timing'][key] for r in arm['records']]))
                self.assertEqual(value['n'],3)
                self.assertIsNone(value['p95_ms'])
            self.assertTrue(all(r['error'] is None for r in arm['records']))
            self.assertGreater(arm['latency']['native_service_ms']['median_ms'],0)
        self.assertGreater(baseline['records'][0]['timing']['queue_delivery_ms'],29000)
        self.assertGreater(baseline['latency']['queue_delivery_ms']['median_ms'],15000)
        self.assertLess(alternative['latency']['queue_delivery_ms']['median_ms'],1000)
        elapsed=(stamp(artifact['completed_utc'])-stamp(artifact['started_utc'])).total_seconds()
        self.assertGreaterEqual(elapsed,89)
        self.assertGreater(elapsed,sum(r['timing']['queue_delivery_ms'] for r in baseline['records'])/1000)

    def test_review_pins_preserved_sources_baseline_and_license_boundary(self):
        from js_contract import check_js
        check_js(self, 'market_discovery_bridge_checks.cjs')
        review=json.loads((BASE/'source-review.json').read_text())
        self.assertEqual(review['competitor_reuse'],[])
        self.assertEqual(review['transport']['commands'],['search'])
        self.assertEqual(review['transport']['mutation_paths'],[])
        self.assertFalse(review['transport']['credential_reads_or_exports'])
        self.assertEqual(review['transport']['baseline_alarm_seconds'],30)
        self.assertTrue(review['transport']['baseline_next_is_nonblocking'])
        self.assertTrue(review['upstream_context']['no_license_grant'])
        ledger=json.loads((ROOT/'docs/research/evidence/repositories.json').read_text(encoding='utf-8'))
        for name,repo in (('copilot','liusihang/fc27-copilot'),('sniffer','puredan824-hub/fc27-sniffer')):
            row=next(r for r in ledger['repositories'] if r['repository']==repo)
            self.assertEqual(row['revision'],review['upstream_context'][name]['revision'])
            self.assertEqual(row['declared_license'],review['upstream_context'][name]['reviewed_license'])
        for name,digest in evidence_hashes(review['checksums']).items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)
        preservation=json.loads((ROOT/'docs/research/001b/preservation.json').read_text())['static_sha256']
        baseline='browser/transaction-bridge/worker.js'
        self.assertEqual(review['checksums'][baseline],preservation[baseline])
        for name,digest in evidence_hashes(preservation).items():
            if name.startswith(('browser/','fc_access/','objectives/')):
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest,name)
        self.assertIn('periodInMinutes: 0.5',(ROOT/baseline).read_text())
        manifest=json.loads((BASE/'browser/manifest.json').read_text())
        self.assertEqual(manifest['host_permissions'],['http://127.0.0.1:8770/*'])
        self.assertEqual(set(manifest['permissions']),{'activeTab','scripting','alarms','storage'})
        self.assertNotIn('externally_connectable',manifest)
        self.assertNotIn('web_accessible_resources',manifest)
        # No path to the repository's mutation-capable transport in this package.
        for path in BASE.glob('*.py'):
            tree=ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    self.assertFalse(any(term in (node.module or '') for term in ('transaction','fc_execution','read_server')),str(path))
                if isinstance(node,ast.Import):
                    self.assertFalse(any('transaction' in a.name or 'fc_execution' in a.name for a in node.names))
        page=(BASE/'browser/page.js').read_text()
        self.assertEqual(set(re.findall(r'services\.Item(?:\?\.)?\.?(\w+)\(',page)),{'searchTransferMarket','clearTransferMarketCache'})
        for text in ('buyNow(', 'placeBid(', 'sendToTradepile(', 'listOnMarket(', 'fetch(', 'document.cookie', 'localStorage'):
            self.assertNotIn(text,page)


if __name__=='__main__':unittest.main()
