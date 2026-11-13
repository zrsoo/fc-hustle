"""Independent retained-evidence checks. Never drives Edge or invokes EA."""
import ast
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fc_access.durability_v1.adapter import parse_durable_response as parse_response
from fc_access.durability_v1.server import EXTENSION_ID
from fc_access.durability_v1.measure import experiment
D=ROOT/'docs/research/001c/001c-05'
STAGES=('initial','idle','page-refresh','server-restart-verified','extension-reload-verified','owner-change-verified','balance-verified','final-verified')
def load(name):return json.loads((D/name).read_text(encoding='utf-8-sig'))


class Artifacts(unittest.TestCase):
    def test_0_genuine_idle_read_is_after_historical_failure_boundary_and_costs_one_call(self):
        initial,idle=load('initial.json'),load('idle.json')
        self.assertGreater(idle['at']-initial['at'],300)
        self.assertEqual(initial['after']['window']['reads_reserved'],1)
        self.assertEqual(idle['before']['window']['reads_reserved'],1,'idle generated native calls')
        self.assertEqual(idle['after']['window']['reads_reserved'],2)
        self.assertEqual(initial['before']['boot'],idle['before']['boot'])
        self.assertTrue(idle['before']['attached']);self.assertTrue(idle['before']['polling'])
        old=ROOT/'experiments/market_discovery_live_v1/runs/20261112T064306Z/records.jsonl'
        records=[json.loads(s) for s in old.read_text().splitlines()]
        self.assertEqual(records[-1]['result']['error'],'bridge_not_attached')
        self.assertEqual(records[-1]['result']['network'],[])

    def test_0_actual_server_restart_page_refresh_extension_reload_and_budget_preservation(self):
        before,after=load('restart2-before.json'),load('restart2-recovered.json')
        self.assertNotEqual(before['health']['boot'],after['health']['boot'])
        self.assertEqual(after['health']['owner']['epoch'],before['health']['owner']['epoch']+1)
        self.assertFalse(after['manual_action_during_restart'])
        self.assertGreater(after['recovery_seconds'],0);self.assertLessEqual(after['recovery_seconds'],75)
        self.assertEqual(before['health']['window'],after['health']['window'])
        self.assertEqual(before['health']['document'],after['health']['document'])
        refresh_old,refresh_new=load('refresh-before.json'),load('refresh-recovered.json')
        self.assertNotEqual(refresh_old['health']['document'],refresh_new['health']['document'])
        self.assertTrue(refresh_new['health']['attached'])
        ext_old,ext_new=load('extension-fixed-before.json'),load('extension-fixed-recovered.json')
        self.assertEqual(ext_old['health']['owner'],ext_new['health']['owner'])
        self.assertEqual(ext_old['health']['window'],ext_new['health']['window'])
        self.assertNotEqual(ext_old['health']['worker'],ext_new['health']['worker'])
        self.assertTrue(ext_new['normal_action_reattach'])
        for filename in ('edge-before-refresh-verified.txt','edge-refreshed-verified.txt','edge-reattached.txt'):
            observation=json.loads((D/filename).read_text(encoding='utf-8-sig').splitlines()[0])
            self.assertTrue(observation['edge_control_verified']);self.assertTrue(observation['official_tab'])
        self.assertTrue(load('server-down.json')['connection_refused'])

    def test_1_actual_edge_persona_fences_host_owner_rejections_and_safe_correlations(self):
        for stage in STAGES:
            v=load(stage+'.json');c=v['command']
            self.assertEqual(c['id'],hashlib.sha256(('001c-05:'+stage).encode()).hexdigest()[:32])
            self.assertEqual(v['http_status'],200)
            r,f,_=parse_response(v['response'],command_id=c['id'],operation=c['operation'])
            self.assertTrue(r['success']);self.assertEqual(r['platform'],'pc')
            self.assertEqual(f.source,'native');self.assertEqual(f.request_count,1)
            self.assertTrue(r['network'][0]['session_header_present']);self.assertEqual(r['network'][0]['status'],200)
            self.assertTrue(v['before']['persona']['accepted']);self.assertEqual(v['before']['extension_id'],EXTENSION_ID)
            self.assertLessEqual(abs(f.network_at.timestamp()-v['at']),5)
            self.assertGreater(v['elapsed_ms'],0)
            self.assertEqual(v['before']['window']['mutation_limit'],0)
        for stage in ('server-restart-verified','extension-reload-verified','owner-change-verified','balance-verified','final-verified'):
            self.assertTrue(all(load(stage+'.json')['before']['page_checks'].values()))
        probes=load('ownership-probes.json')
        self.assertEqual({r['fault'] for r in probes['requests']},{'scope','owner','epoch','old_owner_after_takeover','origin'})
        self.assertTrue(all(r['status'] in (403,409) for r in probes['requests']))
        self.assertEqual(probes['before']['window']['reads_reserved'],probes['after']['window']['reads_reserved'])
        self.assertNotEqual(probes['before']['owner']['owner'],probes['after']['owner']['owner'])
        self.assertGreater(probes['after']['owner']['epoch'],probes['before']['owner']['epoch'])

    def test_2_delivery_accounting_is_durable_no_duplicate_and_early_probe_never_delivered(self):
        db=sqlite3.connect((D/'live-final.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
        self.addCleanup(db.close)
        rows=db.execute('SELECT id,operation,body,state,amount,created,delivered,result FROM commands').fetchall()
        self.assertEqual(len(rows),len(STAGES)+2);self.assertEqual(len({r[0] for r in rows}),len(rows))
        self.assertTrue(all(r[1] in ('watched','balance') and r[4]==0 for r in rows))
        unknown={r[0] for r in rows if r[3]=='UNKNOWN'}
        self.assertEqual(unknown,{load(s+'.json')['command']['id'] for s in ('extension-reload','owner-change')})
        for r in rows:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit WHERE command_id=? AND event='DELIVERED'",(r[0],)).fetchone()[0],1)
            self.assertIsNotNone(r[6])
            if r[0] not in unknown:self.assertIsNotNone(r[7]);self.assertEqual(r[3],'ACKNOWLEDGED')
        early=load('server-restart.json')
        self.assertEqual(early['http_status'],409)
        self.assertNotIn(early['command']['id'],{r[0] for r in rows})
        self.assertEqual(load('final.json')['http_status'],409)
        self.assertNotIn(load('final.json')['command']['id'],{r[0] for r in rows})
        self.assertEqual(db.execute('SELECT mutations,exposure,stopped FROM window').fetchone(),(0,0,1))
        self.assertEqual(load('final-verified.json')['after']['window']['reads_reserved'],len(rows))

    def test_3_scheduler_metrics_and_live_latency_are_separately_classified(self):
        self.assertEqual(load('scheduler.json'),json.loads(json.dumps(experiment())))
        report=load('measurements.json')
        observed=[load(s+'.json')['response']['timing']['native_service_ms'] for s in STAGES]
        self.assertEqual(report['native_read_ms'],observed)
        self.assertEqual(report['native_read_min_ms'],min(observed));self.assertEqual(report['native_read_max_ms'],max(observed))
        self.assertEqual(report['live_write_timing'],'UNVERIFIED')
        self.assertEqual(report['idle_native_calls'],0)
        self.assertEqual(report['whole_queue_25_second_guarantee'],False)

    def test_4_6_harness_has_no_actor_loop_and_live_campaign_cannot_write(self):
        tree=ast.parse((ROOT/'fc_access/durability_v1/harness.py').read_text())
        self.assertFalse(any(isinstance(n,(ast.While,ast.AsyncFor)) for n in ast.walk(tree)))
        self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('serve_forever','create_task','start') for n in ast.walk(tree)))
        h=(ROOT/'fc_access/durability_v1/harness.py').read_text()
        for phrase in ('conclusive_owned_physical_item_required','independent_action_readback_required','live_listing_rules_required'):
            self.assertIn(phrase,h)
        manifest=json.loads((ROOT/'browser/durability-v1/manifest.json').read_text())
        self.assertEqual(set(manifest['permissions']),{'activeTab','scripting','storage','alarms'})
        self.assertEqual(manifest['host_permissions'],['http://127.0.0.1:8779/*'])
        review=load('review-v4.json')
        for path,digest in review['files'].items():self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)

    def test_5_existing_artifacts_preserved_and_exact_relevant_check_commands_recorded(self):
        for path,digest in load('entry.json')['preserve'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)
        checks=load('checks.json')
        commands={tuple(r['command']):r for r in checks['commands']}
        for c in (('{python}','tests/test_durability_v1.py'),('{python}','tests/test_readiness_regressions.py')):
            self.assertIn(c,commands);self.assertEqual(commands[c]['returncode'],0)
            log=(D/commands[c]['output']).read_text()
            self.assertIn('OK',log);self.assertNotIn('FAILED',log)
        self.assertTrue(checks['earlier_observations'])
    def test_source_and_checkpoint_manifest_detects_changes(self):
        from fc_access.durability_v1.seal import sources
        manifest=load('manifest.json')
        self.assertEqual(manifest['task'],'001c-05')
        required={p.relative_to(ROOT).as_posix() for p in sources()}
        self.assertTrue(required<=set(manifest['files']))
        self.assertIn('docs/research/001c/001c-05/live-final.sqlite',manifest['files'])
        for path,digest in manifest['files'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)


if __name__=='__main__':unittest.main(verbosity=2)
