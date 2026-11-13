"""Independent 001c-03 acceptance/artifact audit. No browser or EA requests."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.watched_bulk_v1.validation import validate_projection,assess
from experiments.watched_bulk_v1.contract import refresh_cost
from experiments.watched_bulk_v1.server import EXTENSION_ID
from experiments.watched_bulk_v1.source import decode_table,decoded_source

EVIDENCE=ROOT/'docs/research/001c/001c-03'


def read(name):
    return json.loads((EVIDENCE/name).read_text(encoding='utf-8-sig'))


def history_errors(mapping):
    return [p for p,digest in mapping.items() if not (ROOT/p).is_file() or hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=digest]


def ui_meta(text):
    return next(json.loads(line) for line in text.splitlines() if line.startswith('{'))


def load():
    return {'report':read('report.json'),'ready':read('readiness.json'),'entry':read('entry.json'),
            'captures':[read(f'watched-{n}.json') for n in range(1,5)],'inspect':read('inspect-3.json'),
            'ui':{n:(EVIDENCE/n).read_text(encoding='utf-8-sig') for n in ('edge-preflight.txt','edge-v2-attached.txt','transfers-summary.txt','targets-after-fresh.txt')},
            'native_source':read('native-source-decoded.json'),'repo_source':read('native-repository-source.json')}


def audit(b):
    errors=[]
    def need(c,yes,reason):
        if not yes:errors.append((c,reason))
    r,ready,entry,ins,vs=b['report'],b['ready'],b['entry'],b['inspect'],b['captures']
    need(0,entry['agents_sha256']==hashlib.sha256((ROOT/'AGENTS.md').read_bytes()).hexdigest(),'AGENTS hash changed')
    for name in ('edge-preflight.txt','edge-v2-attached.txt'):
        u=ui_meta(b['ui'][name]);need(0,all(u[k] is True for k in ('official_tab','foreground_verified','edge_control_verified')),'own foreground and official-tab proof missing')
    need(0,ready['health']['attached'] is True and ready['health']['service']=='fc-watched-bulk-v1' and ready['health']['bind']=='127.0.0.1' and ready['os_listener']=={'address':'127.0.0.1','port':8775},'local service/attachment proof missing')
    need(0,ready['health']['extension_id']==ready['installed_extension_id']==EXTENSION_ID,'installed and pinned extension mismatch')
    need(0,ins['success'] is True and ins['persona']['accepted'] is True and ins['request_count']==0,'persona inspection layer missing')
    need(0,assess(vs[-1])['fresh'],'authenticated market layer missing')
    need(0,ready['agents_reread_before_initial_recovery'] and ready['agents_reread_before_refresh'],'instruction reread record missing')
    review=read('review-v2.json')
    need(0,not history_errors(review['files']),'reviewed extension changed')
    for n,v in enumerate(vs,1):
        try:validate_projection(v)
        except (ValueError,KeyError,TypeError):
            need(1,False,'invalid sanitized capture');continue
        need(1,datetime.fromisoformat(v['observed_at'])>=datetime.fromisoformat(entry['at']),'historical capture promoted')
        need(1,v['success'] is True and v['method']=='services.Item.requestWatchedItems()','native watched invocation absent')
        if n==2:
            need(2,v['status']==304 and v['request_count']==0 and v['network_at'] is None and not assess(v)['fresh'],'cache mistaken for network')
            continue
        need(1,assess(v)['fresh'] and v['request_count']==1,'fresh authenticated single request missing')
        need(1,len(v['network'])==1,'native request count unsupported')
        for net in v['network']:
            need(1,net['route']=='/ut/game/fc27/watchlist' and net['method']=='GET' and net['status']==200 and net['session_header_present'] is True,'route/status/auth proof missing')
            need(1,net['payload_bytes']==44 and net['duration_ms']>0 and v['duration_ms']>=net['duration_ms'],'measured payload or timing missing')
            need(1,datetime.fromisoformat(net['started_at'])<=datetime.fromisoformat(net['ended_at'])<=datetime.fromisoformat(v['observed_at']),'network chronology invalid')
            need(3,net['pagination']=={'start':None,'count':None},'pagination observation changed')
        need(2,v['auctions']==[],'empty result claim mismatches rows')
        need(3,v['has_more'] is None,'absent has_more promoted to complete')
    need(2,assess(vs[-1],0)['empty_verified'],'fresh empty repository and UI conditions fail')
    summary=b['ui']['transfers-summary.txt']
    need(2,'TARGET_TEXT | Transfer Targets\nTARGET_TEXT | 0\nTARGET_TEXT | Items\nTARGET_TEXT | Winning\nTARGET_TEXT | 0\nTARGET_TEXT | Outbid\nTARGET_TEXT | 0' in summary,'independent zero-item summary missing')
    visible=b['ui']['targets-after-fresh.txt'];u=ui_meta(visible)
    need(2,all(u[k] is True for k in ('official_tab','foreground_verified','edge_control_verified')),'comparison tab/foreground missing')
    need(2,all(s in visible for s in ('Items you are currently bidding on will appear here','Items you are watching, but have not placed a bid on will appear here','Items you have won through bidding will appear here.','Expired Items')),'empty sections comparison missing')
    delta=(datetime.fromisoformat(u['observed_at'])-datetime.fromisoformat(vs[-1]['observed_at'])).total_seconds()
    need(2,0<=delta<=120,'UI comparison too far from fresh read')
    account=ins['account']
    need(3,account['inbox_capacity']==account['server_setting_capacity']==r['observed_reported_inbox_capacity']==r['observed_server_setting_capacity']==50,'observed account capacity unsupported')
    need(3,r['configured_queue_size']==50 and not r['coverage']['complete_nonempty_account'] and not r['coverage']['saturation_test'],'queue configuration promoted to observed coverage')
    need(3,all(v['cache_invalidated'] and v['account']==account for v in vs[2:]),'v2 fresh contract/account projections changed')
    sources={s['name']:s['source'] for s in b['native_source']['sources']}
    need(3,'["getWatchPile"]' in sources['requestWatchedItems'] and '["/watchlist"]' not in sources['requestWatchedItems'],'source delegation mismatch')
    need(3,'"/watchlist"' in sources['getWatchPile'] and 'NOT_MODIFIED' in sources['getWatchPile'] and 'isDirty' in sources['getWatchPile'],'source cache/route proof missing')
    repo={s['name']:s['source'] for s in b['repo_source']['repository_methods']}
    need(3,'this.inbox.endOfList=!0' in repo['setWatchedItems'],'repository coverage behavior absent')
    need(3,'TRANSFER_TARGET_SIZE' in b['repo_source']['server_settings_capacity_assignment'],'capacity setting provenance missing')
    need(4,account['platform_split'] is False and r['platform_split'] is False,'filter feature requires reevaluation')
    need(4,r['supplemental']['invoked'] is False and r['supplemental']['classification']=='SOURCE_CONFIRMED_ONLY' and r['supplemental']['missing_state']=='UNKNOWN','supplemental/terminal claim promoted')
    need(4,'["isWon"]' in sources['getWatchPile'] and 'PLATFORM_SPLIT_FOR_TRANSFER_MARKET' in sources['requestWatchedItems'],'native filtering caveat absent')
    need(5,r['timing']==refresh_cost(vs),'timing/request-cost report disagrees with captures')
    need(5,r['observed_EA_requests']==3 and r['native_watched_invocations']==4 and r['account_mutations']==0,'request or mutation accounting differs')
    need(5,r['constraints']=={'per_call_native_method_invocations':1,'experiment_gap_seconds':30,'gap_is_EA_requirement':False,'maximum_invocations':6,'consumed_invocations':4},'limits promoted or budget reset')
    need(5,read('budget.json')['consumed']==ready['health']['delivered_reads']==4,'consumed checkpoint mismatch')
    need(6,len(r['unproved'])>=8 and not r['timing']['live_50_verified'] and not r['timing']['sustained_25_second_cycle_verified'],'unobserved cases promoted')
    need(6,not history_errors(entry['history']),'historical bytes changed or deleted')
    return errors


class ArtifactTests(unittest.TestCase):
    def test_all_acceptance_criteria_have_independent_artifact_evidence(self):
        self.assertEqual(audit(load()),[])

    def test_reject_missing_native_auth_and_cached_empty_promotion(self):
        for change in ('auth','cached','payload'):
            b=load();v=b['captures'][-1]
            if change=='auth':v['network'][0]['session_header_present']=False
            if change=='cached':v.update(status=304,network=[],network_at=None,request_count=0)
            if change=='payload':v['network'][0]['payload_bytes']=None
            self.assertTrue(audit(b),change)

    def test_reject_missing_UI_and_capacity_coverage_promotions(self):
        for change in ('ui','capacity','complete','supplemental','timing','unproved'):
            b=load();r=b['report']
            if change=='ui':b['ui']['targets-after-fresh.txt']=b['ui']['targets-after-fresh.txt'].replace('Items you are watching','Missing')
            if change=='capacity':r['observed_reported_inbox_capacity']=30
            if change=='complete':r['coverage']['complete_nonempty_account']=True
            if change=='supplemental':r['supplemental']['invoked']=True
            if change=='timing':r['timing']['native_requests_per_sample']=[50]
            if change=='unproved':r['unproved']=[]
            self.assertTrue(audit(b),change)

    def test_public_source_matches_loaded_functions_and_static_decoding(self):
        b=load();pub=ROOT/'private-captures/001c-03-public-source'
        for name,digest in b['repo_source']['public_hashes'].items():
            self.assertEqual(hashlib.sha256((pub/name).read_bytes()).hexdigest(),digest)
        raw=(pub/'ocompiled.js').read_text(encoding='utf8');decode=decode_table(raw)
        loaded=read('inspect-2.json')
        for s in loaded['sources']:
            self.assertIn(s['source'],raw)
            self.assertEqual(hashlib.sha256(s['source'].encode()).hexdigest(),s['sha256'])
            match=next(x for x in b['native_source']['sources'] if x['name']==s['name'])
            self.assertEqual(match['source'],decoded_source(s['source'],decode))
        compiled=(pub/'compiled_2.js').read_text(encoding='utf8')
        for s in b['repo_source']['repository_methods']:
            self.assertIn(s['source'],compiled)
            self.assertEqual(hashlib.sha256(s['source'].encode()).hexdigest(),s['sha256'])

    def test_historical_changed_deleted_and_fixture_promotions_are_detected(self):
        h=deepcopy(read('entry.json')['history']);path=next(iter(h));h[path]='0'*64
        self.assertIn(path,history_errors(h))
        self.assertIn('missing-historical-file',history_errors({'missing-historical-file':'0'*64}))
        f=json.loads((ROOT/'experiments/watched_bulk_v1/fixtures/watched-50.json').read_text())
        self.assertEqual(f['classification'],'OFFLINE_VALIDATED');self.assertEqual(len(f['sample']['auctions']),50)
        self.assertEqual(f['source'],'fixture');self.assertEqual(f['sample']['request_count'],1)

    def test_manifest_positive_schema_and_all_artifact_hashes(self):
        m=read('manifest.json')
        self.assertEqual(set(m),{'task','files','criteria'})
        self.assertEqual(m['task'],'001c-03');self.assertEqual(m['criteria'],list(range(7)))
        self.assertFalse(history_errors(m['files']))
        for n in ('report.json','watched-1.json','watched-2.json','watched-3.json','watched-4.json','targets-after-fresh.txt','readiness.json','entry.json'):
            self.assertIn('docs/research/001c/001c-03/'+n,m['files'])
        self.assertIn('experiments/watched_bulk_v1/contract.py',m['files'])


if __name__=='__main__':
    unittest.main(verbosity=2)
