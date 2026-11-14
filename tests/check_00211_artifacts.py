"""Check the bounded final-run contract and regression evidence, with negatives.

This validator neither starts actors nor contacts EA; implementation identity is
never enforced with source hashes. Regeneration is the regression runner's job.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.config import Config
from fc_access.production_v1.contracts import ROUTES,LOCAL_OPERATIONS
from regression_00211 import PYTHON,NODE

OUT=ROOT/'docs/research/002/002-11'


def need(value,reason):
    if not value:raise ValueError(reason)


def plan_check(p):
    need(p['schema']==1 and p['task']=='002-12' and p['state']=='PREPARED_NOT_LAUNCHED' and
        p['evidence_class']=='PROCEDURE_ONLY','unjustified_live_claim')
    b,q=p['bounds'],p['pacing'];cfg=Config()
    need(type(b['wall_seconds']) is int and 3660<b['wall_seconds']<=7200,'unbounded_window')
    need(type(b['native_request_budget']) is int and 0<b['native_request_budget']<=2000,'unbounded_requests')
    need(0<b['stop_request_threshold']<b['native_request_budget'] and
        b['native_request_budget']-b['stop_request_threshold']>=b['request_reserve']>=100,'no_reconciliation_reserve')
    for key in ('occupied_limit','unresolved_limit','combined_limit'):
        need(type(b[key]) is int and 0<b[key]<=50,'capacity_overflow')
    need(b['minimum_available_coins']>=cfg.min_available_coins,'coin_reserve_removed')
    need(q['single_broker'] is True and q['concurrency']==1 and q['native_interval_seconds']>=2,'unsafe_dispatch')
    need(q['priorities']==dict(reconciliation=100,bidder=90,acquirer=10,maintenance=0),'priority_drift')
    need(q['acquirer_interval_seconds']==cfg.search_interval_seconds and
        q['bidder_interval_seconds']==q['maintenance_interval_seconds']==cfg.target_check_interval_seconds and
        q['relist_interval_seconds']==cfg.bulk_relist_interval_seconds and
        q['listing_duration_seconds']==cfg.bulk_relist_duration_seconds,'cadence_drift')
    need(len(q['request_accounting'])>150 and len(q['on_overrun'])>100,'missing_fanout_or_overrun_policy')
    need(len(p['prerequisites'])>=6 and all(len(x)>50 for x in p['prerequisites']),'missing_prelaunch_checks')
    apis=p['native_apis']
    events=p['required_natural_events']
    ids={'rebid','leading_lost','win_list','status_gap','capacity','expiry','expired_relist','sold_clear','settlement'}
    need(len(events)==len(ids) and {e['id'] for e in events}==ids,'missing_natural_event')
    for e in events:
        need(len(e['event'])>40 and e['operations'] and set(e['operations'])<=set(apis) and
            len(e['evidence'])>=3 and all(isinstance(x,str) and x.strip() for x in e['evidence']),'unreviewable_event')
    for op,a in apis.items():
        need(len(a['call'])>15,'missing_native_api')
        if op in LOCAL_OPERATIONS:
            need(a['method']=='LOCAL' and a['path'] is None,'local_helper_as_request')
        else:
            need(op in ROUTES and (a['method'],a['path'])==ROUTES[op],'native_route_drift')
    for op in ('clear_sold','relist_all'):
        need(apis[op]['arguments']==[] and apis[op]['body'] is None,'changed_bulk_semantics')
    need(next(e for e in events if e['id']=='sold_clear')['operations']==
        ['transfer_list','clear_sold','transfer_list'],'missing_clear_independent_readback')
    need(next(e for e in events if e['id']=='expired_relist')['operations']==
        ['transfer_list','relist_all','transfer_list'],'missing_relist_independent_readback')
    required_stops={'WALL_DEADLINE','REQUEST_THRESHOLD','ACTOR_CYCLE_LIMIT','AUTH_OR_SECURITY_CHALLENGE',
        'RATE_LIMIT_OR_SERVICE_FAILURE','STALE_OR_INCOMPLETE_INVENTORY','ACCOUNT_PERSONA_EPOCH_CHANGE',
        'JOURNAL_FAILURE','UNKNOWN_WRITE','BULK_CONTRACT_CHANGE','CAPACITY_LIMIT_BREACH',
        'VALUATION_GATE_30_SECONDS','REQUIRED_EVENTS_COMPLETE'}
    need(required_stops<=set(p['stop_conditions']) and len(p['stop_procedure'])>500,'missing_stops')
    commands=p['launch_commands']
    need(len(commands)==4 and len([c for c in commands if 'executor' in c])==1,'multiple_brokers')
    for role in ('acquirer','bidder','maintenance'):
        matches=[c for c in commands if role in c]
        need(len(matches)==1,'missing_worker')
        c=matches[0]
        need(c[:3]==['{python}','-m','fc_access.actors_v1'] and '--state-dir' in c and
            c[c.index('--state-dir')+1]=='{existing_state}' and '--cycles' in c,'unbounded_or_wrong_state_worker')
        cycles=b['actor_cycles'][role]
        need(type(cycles) is int and 0<cycles<=280 and c[c.index('--cycles')+1]==str(cycles),'unbounded_cycles')
        need(cycles*q[role+'_interval_seconds']<=b['wall_seconds'],'cycles_exceed_window')
    need(b['actor_cycles']['acquirer']<=b['max_new_enrollments']<=12,'enrollment_budget')
    need(len(p['evidence_collection'])>=8 and all(len(x)>50 for x in p['evidence_collection']),'missing_evidence')
    need({'replay_consumed_windows','blind_write_retry','per_item_bulk_fallback','synthetic_competitor_or_sale',
        'credential_capture','infer_realized_profit_from_balance_delta'}<=set(p['prohibited']),'unsafe_fallback')


def regression_check(r):
    need(r['schema']==1 and r['status']=='PASS' and r['evidence_class']=='OFFLINE_IMPLEMENTATION_REGRESSION','regression_failed')
    need(r['live_requests']==r['live_actor_launches']==r['historical_windows_replayed']==0,'live_replay')
    expected={tuple(['{python}','tests/run_offline_suite.py','tests/'+n]) for n in PYTHON}
    expected|={('node','tests/'+n) for n in NODE}
    rows=r['checks']
    need(len(rows)==len(expected) and {tuple(x['command']) for x in rows}==expected,'incomplete_regression')
    for row in rows:
        need(row['exit_code']==0 and row['seconds']>=0 and 'failure' not in row,'regression_failure')
        if row['command'][0]=='{python}':need(row['python_tests']>0,'no_tests_executed')


class Artifacts(unittest.TestCase):
    def test_bounded_plan_matches_current_native_and_runtime_contracts(self):
        plan_check(json.loads((OUT/'final-run-plan.json').read_text()))

    def test_plan_rejects_bad_bounds_missing_events_routes_fallbacks_and_unbounded_launch(self):
        p=json.loads((OUT/'final-run-plan.json').read_text())
        changes=[lambda p:p['bounds'].update(wall_seconds=0),
            lambda p:p['bounds'].update(native_request_budget=100000),
            lambda p:p['bounds'].update(request_reserve=0),
            lambda p:p['bounds'].update(combined_limit=51),
            lambda p:p['pacing'].update(concurrency=2),
            lambda p:p['pacing']['priorities'].update(maintenance=100),
            lambda p:p['required_natural_events'].pop(),
            lambda p:p['required_natural_events'][7]['operations'].pop(),
            lambda p:p['native_apis']['clear_sold'].update(method='POST'),
            lambda p:p['native_apis']['relist_all'].update(arguments=[3600]),
            lambda p:p['launch_commands'][1].remove('--cycles'),
            lambda p:p['stop_conditions'].remove('UNKNOWN_WRITE'),
            lambda p:p['prohibited'].remove('replay_consumed_windows'),
            lambda p:p.update(state='LIVE_PASS')]
        for change in changes:
            v=deepcopy(p);change(v)
            with self.subTest(change=change),self.assertRaises(ValueError):plan_check(v)

    def test_complete_recorded_regression_commands_counts_and_status(self):
        regression_check(json.loads((OUT/'regressions.json').read_text()))

    def test_record_rejects_missing_checks_failures_zero_tests_and_live_replay(self):
        r=json.loads((OUT/'regressions.json').read_text())
        changes=[lambda r:r['checks'].pop(),lambda r:r['checks'][0].update(exit_code=1),
            lambda r:r['checks'][0].update(python_tests=0),lambda r:r.update(historical_windows_replayed=1),
            lambda r:r.update(status='FAIL')]
        for change in changes:
            v=deepcopy(r);change(v)
            with self.subTest(change=change),self.assertRaises(ValueError):regression_check(v)


if __name__=='__main__':unittest.main(verbosity=2)
