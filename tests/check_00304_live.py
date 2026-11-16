"""Strict read-only 003-04 acceptance. Missing live work exits nonzero.

Offline tests of this assessor are NOT operational acceptance. The evidence index
selects sealed SQLite captures; the collector's structural verdict cannot certify
business coverage or uptime. No EA calls, browser input, or source digests.
"""
from contextlib import closing
import argparse
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'tests'))
from baseline_00301 import assess_reads
from check_00303_preparation import REQUIRED
from fc_access.continuous_v1.evidence import assess, read_db, records
from fc_access.continuous_v1.runtime import production_config
from fc_access.continuous_v1.control import Control
from fc_access.production_v1.contracts import MUTATIONS, parse_response, stamp
from fc_access.continuous_v1.watchdog import alive
from fc_access.actors_v1.final_assessment import listing_proof, bulk_proof

OUT = ROOT/'docs/research/003/003-04'
CAPTURE_NAMES={'browser-recovery.jsonl','ghost-status-diagnostic.jsonl','launch.json','restored-health.json',
               'readonly-restoration.json','service-transition.json','processes-before.json','backup-receipt.json',
               'prelaunch-reconciliation.json','gate-regressions.json','gate-regressions-stdout.txt',
               'gate-regressions-stderr.txt','startup-structural-assessment.json'}


def need(ok, reason):
    if not ok: raise ValueError(reason)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines()]


def sealed_artifacts(directory):
    """Integrity applies solely to this attempt's captured evidence and logs."""
    import re
    out=Path(directory)
    manifest=load(out/'captured-evidence-manifest.json')
    need(manifest['scope']=='SEALED_CAPTURED_EVIDENCE_ONLY','wrong_integrity_scope')
    need(CAPTURE_NAMES<=set(manifest['captures']),'captured_evidence_missing')
    for name,expected in manifest['captures'].items():
        need(name in CAPTURE_NAMES or re.fullmatch(r'prelaunch-\d{8}T\d{6}Z\.jsonl',name),
             'mutable_implementation_digest_forbidden')
        with (out/name).open('rb') as stream:
            need(hashlib.file_digest(stream,'sha256').hexdigest()==expected,'sealed_capture_changed:'+name)
    transport=manifest['diagnostic_transport']
    path=(ROOT/transport['path']).resolve()
    need(path.is_relative_to((ROOT/'private-captures/003-04/sealed-diagnostic').resolve()) and
         path.name=='transport.sqlite3','wrong_sealed_transport_role')
    need(not any(Path(str(path)+s).exists() for s in ('-wal','-journal')),'unsealed_diagnostic_sidecar')
    with path.open('rb') as stream:
        need(hashlib.file_digest(stream,'sha256').hexdigest()==transport['sha256'],'sealed_diagnostic_changed')
    return path


def browser_contract(rows):
    reads = [i for i, r in enumerate(rows) if r['kind']=='AGENTS_READ' and r['path']=='AGENTS.md']
    actions = [(i, r) for i, r in enumerate(rows) if r['kind']=='VERIFIED_UI']
    need(reads and actions and reads[0] < actions[0][0], 'instructions_not_freshly_read')
    official = []
    for i, r in actions:
        v = r['result']
        need(any(n < i and 0 <= (stamp(r['at'])-stamp(rows[n]['at'])).total_seconds() <= 120
                 for n in reads), 'instructions_not_freshly_read')
        need(abs((stamp(r['at'])-stamp(v['observed_at'])).total_seconds()) < 5, 'stale_ui_observation')
        if 'official_tab' in v:
            need(v['official_tab'] and v['foreground_verified'] and v['edge_control_verified']
                 and not v['extensions_manager'], 'unverified_official_foreground')
            official.append(r)
        else:
            need(v['edge_foreground_verified'] and v['keyboard_or_mouse_input'] is False,
                 'unverified_foreground_recovery')
    need(official, 'official_tab_not_verified')
    scope = [r for r in rows if r['kind']=='RECOVERY_SCOPE']
    need(len(scope)==1 and scope[0]['designated_saved_account']=='zzorniss' and
         scope[0]['credentials_accessed'] is False and scope[0]['session_material_accessed'] is False,
         'recovery_scope_or_privacy_missing')
    if scope[0]['login_performed']:
        review=[r for r in rows if r['kind']=='LOGIN_REVIEW']
        need(len(review)==1 and review[0].get('designated_saved_account')=='zzorniss' and
             review[0].get('normal_ui_only') is True and review[0].get('challenge_bypassed') is False and
             review[0].get('credentials_or_session_extracted') is False and
             review[0].get('retained_ui_event_ids') and review[0].get('authenticated_read_ids'),
             'login_requires_separate_ui_challenge_review')


def login_evidence_contract(review, capture, native_reads):
    need(capture.get('scope')=='CAPTURED_UI_BOOLEAN_OUTPUTS_ONLY','wrong_login_capture_scope')
    events=capture['events']
    need({e['event_id'] for e in events}==set(review['retained_ui_event_ids']), 'login_ui_evidence_missing')
    values=[]
    for e in events:
        for line in e['captured_ui_output'].splitlines():
            try:values.append(json.loads(line))
            except json.JSONDecodeError:pass
    need(any(v.get('credential_values_read') is False and v.get('designated_saved_account_option_count')==1
             for v in values) and any(v.get('app_home') is True for v in values),
         'designated_saved_ui_login_not_witnessed')
    need(set(native_reads)==set(review['authenticated_read_ids']) and len(native_reads)>=3,
         'authenticated_login_readbacks_missing')
    for command,response in native_reads.values():
        parse_response(response,command,source='native',now=stamp(response['freshness']['observed_at']))
        need(command['operation'] in {'watched','balance','transfer_list'} and response['result']['success'] and
             response['freshness']['request_count']>0 and all(n['method']=='GET' and n['status']==200
             for n in response['result']['network']), 'login_native_authentication_unproven')


def segment_contract(rows, run, *, minimum=14400, resolved_intents=()):
    selected = [r for r in rows if r['run']==run]
    need(any(r['kind']=='READY' for r in selected), 'production_never_ready')
    need(not any(r['kind'] in {'INCIDENT','SUPERVISION_GAP','STOP_REQUESTED','RUN_STOPPED','EXCEPTION'}
                 for r in selected), 'healthy_segment_interrupted')
    ready = next(r for r in selected if r['kind']=='READY')
    samples = [r for r in selected if r['kind']=='SNAPSHOT' and r['seq']>ready['seq']]
    need(len(samples)>=2, 'healthy_samples_missing')
    seconds = 0
    previous = None
    counter_offset=0
    for row in samples:
        body = row['body']
        need(body['source']=='native' and all(i.get('command_id') in resolved_intents and
             0<=i.get('age_seconds',121)<=120 for i in body['intents']), 'unresolved_or_synthetic_health')
        if set(body['actors'])!={'bidder','acquirer','maintenance'}:
            # Do not count startup's process-creation grace as fully observed actor time.
            if previous is None and 0<=(stamp(row['at'])-stamp(ready['at'])).total_seconds()<=10:continue
            raise ValueError('actor_coverage_missing')
        need(body['maintenance'] and all(body['capacity'][k] is not None and 0<=body['capacity'][k]<=50
             for k in ('physical_occupied','unresolved','total')), 'account_invariant_unproven')
        need(body['credits'] and type(body['credits']['available_coins']) is int and
             body['credits']['available_coins']>=0, 'coin_invariant_unproven')
        if previous:
            delta = row['tick']-previous['tick']
            wall = (stamp(row['at'])-stamp(previous['at'])).total_seconds()
            need(0<delta<=10 and 0<wall<=10 and abs(delta-wall)<.5, 'monitor_gap_or_clock_disagreement')
            seconds += delta
        if previous is None:counter_offset=body['healthy_observed_seconds']
        need(abs(body['healthy_observed_seconds']-counter_offset-seconds)<.1, 'unreproducible_healthy_counter')
        previous = row
    need(seconds>=minimum, 'four_consecutive_healthy_hours_missing')
    return seconds


def stopped_contract(rows, run):
    selected = [r for r in rows if r['run']==run]
    stops = [r for r in selected if r['kind']=='RUN_STOPPED']
    need(len(stops)==1 and stops[0]['body']['verified_process_exit'] and
         stops[0]['body']['healthy_segment_closed'] and not stops[0]['body']['remaining_processes'],
         'unsealed_or_unawaited_stop')
    launched = {r['body']['pid'] for r in selected if r['kind']=='PROCESS_STARTED'}
    exits = {r['body']['pid'] for r in selected if r['kind']=='PROCESS_EXIT' and r['seq']<stops[0]['seq']}
    need(launched<=exits, 'owned_process_exit_missing')
    need(not any(r['kind'] in {'READY','RECOVERY_INTENT','NATIVE_RESULT','SNAPSHOT'}
                 and r['seq']>stops[0]['seq'] for r in selected), 'sealed_segment_reopened')


def repair_contract(fix, rows, *, commit_time, published, regression):
    """A repair is reviewable only across an awaited stop and a new owner."""
    stopped_contract(rows,fix['stopped_run'])
    old_end=next(r for r in rows if r['run']==fix['stopped_run'] and r['kind']=='RUN_STOPPED')
    new_open=next(r for r in rows if r['run']==fix['restart_run'] and r['kind']=='RUN_OPEN')
    need(fix['stopped_run']!=fix['restart_run'] and new_open['seq']>old_end['seq'], 'repair_reused_stopped_segment')
    need(stamp(old_end['at'])<=commit_time<=stamp(fix['published_at'])<=stamp(new_open['at']) and published,
         'repair_changed_before_exit_or_unpublished_restart')
    need(regression['exit_code']==0 and regression['tests_run']>0 and regression['failures']==0 and
         regression['errors']==0 and stamp(old_end['at'])<=stamp(regression['finished_at'])<=stamp(fix['published_at']),
         'repair_regressions_missing_or_failed')
    previous=next(r['body']['fences'] for r in rows if r['run']==fix['stopped_run'] and r['kind']=='ATTACHED')
    current=next(r['body']['fences'] for r in rows if r['run']==fix['restart_run'] and r['kind']=='ATTACHED')
    need(current['owner']!=previous['owner'] and current['epoch']>previous['epoch'], 'repair_owner_not_fresh')
    reconcile=next(r for r in rows if r['run']==fix['restart_run'] and r['kind']=='RECONCILED')
    ready=next(r for r in rows if r['run']==fix['restart_run'] and r['kind']=='READY')
    need(reconcile['seq']<ready['seq'] and len(set(reconcile['body']['read_ids']))>=3,
         'repair_restart_not_independently_reconciled')


def incident_contract(incident, rows, commands, *, operator_proof=None):
    need(incident['id'] and incident['root_cause'] and incident['known_account_effects'] and
         incident['unknown_account_effects'] and incident['fix'] and incident['regression_results'] and
         incident['restart_reconciliation'], 'incident_diagnosis_incomplete')
    run = incident['run']
    triggers = [r for r in rows if r['run']==run and r['seq'] in incident['trigger_control_seqs']]
    need(triggers and any(r['kind'] in {'EXCEPTION','INCIDENT','SUPERVISION_GAP'} for r in triggers),
         'incident_trigger_missing')
    for cid in incident['evidence_command_ids']:
        need(cid in commands, 'incident_native_evidence_missing')
    stopped_contract(rows, run)
    if incident['resolution'] in {'OPERATOR_RESOLVED','OPERATOR_NONREGISTRATION'}:
        p=operator_proof or {}
        expected='NOT_REGISTERED' if incident['resolution']=='OPERATOR_NONREGISTRATION' else 'LOST'
        need(p.get('source')=='operator' and p.get('outcome')==expected and
             p.get('native_outcome_verified') is False and p.get('refund_claimed') is False and
             p.get('attestation') and p.get('authorization') and
             p.get('command_id')==incident['triggering_command_id'] and
             p.get('amount')==incident['known_account_effects']['amount'],
             'explicit_operator_loss_proof_required')
        write=commands.get(p['command_id'],{})
        need(write.get('run')==run and write.get('command',{}).get('operation')=='bid' and
             all(write['command']['params'].get(k)==p['identity'][k]
                 for k in ('trade_id','item_id','definition_id')),
             'operator_resolution_native_identity_mismatch')
        need(incident['unknown_account_effects'].get('native_outcome_verified') is False and
             incident['restart_reconciliation']['status']=='INDEPENDENTLY_RECONCILED' and
             incident['fix'].get('pushed_revision') and incident['regression_results']['exit_code']==0,
             'operator_resolution_must_preserve_native_proof_gap')
        restart=incident['restart_reconciliation']
        reconciled=next((r for r in rows if r['run']==restart.get('run') and r['kind']=='RECONCILED'),None)
        need(reconciled and reconciled['seq']==restart.get('control_seq') and
             set(reconciled['body']['read_ids'])==set(restart.get('read_ids',[])) and
             all(cid in commands and commands[cid]['run']==restart['run'] and commands[cid]['response'] and
                 commands[cid]['response']['result']['success'] for cid in restart['read_ids']),
             'operator_resolution_restart_readbacks_missing')
    elif incident['resolution']=='UNRESOLVED_ACCOUNT_RELATION':
        need(incident['restart_reconciliation']['status']=='NOT_RESTARTED' and
             incident['known_account_effects']['bid_dispatched_once'] is True and
             incident['unknown_account_effects']['account_result']=='UNKNOWN' and
             incident['fix']['runtime_change'] is False,'unknown_account_relation_must_remain_gated')
        write=commands.get(incident['triggering_command_id'],{})
        need(write.get('command',{}).get('operation')=='bid' and write.get('response') and
             write['response']['result']['success'],'actual_bid_dispatch_evidence_missing')
        diagnostic=commands.get(incident['terminal_read_id'],{})
        need(diagnostic.get('command',{}).get('operation')=='status' and diagnostic.get('response') and
             diagnostic['response']['result']['success'],'exact_terminal_status_missing')
        params=diagnostic['command']['params'];bid=write['command']['params']
        need(all(params[k]==bid[k] for k in ('trade_id','item_id','definition_id')),'wrong_actual_bid_reconciliation_identity')
        rows=diagnostic['response']['result']['auctions']
        need(len(rows)==1 and rows[0]['trade_id']==params['trade_id'] and rows[0]['item']['item_id']==params['item_id'] and
             rows[0]['item']['definition_id'] in (None,0,params['definition_id']) and
             rows[0]['trade_state']=='closed' and rows[0]['expires']<=0 and rows[0]['bid_state']=='none',
             'account_relative_state_not_missing')
    elif incident['resolution']=='UNRESOLVED_ACTUAL_BID':
        need(incident['restart_reconciliation']['status']=='NOT_RESTARTED' and
             incident['known_account_effects']['bid_dispatched_once'] is True and
             incident['unknown_account_effects']['auction_state']=='UNKNOWN', 'actual_bid_unknown_must_remain_gated')
        need(any(c in commands and commands[c]['command']['operation']=='bid' and
                 commands[c]['response'] and commands[c]['response']['result']['success']
                 for c in incident['evidence_command_ids']), 'actual_bid_dispatch_evidence_missing')
        need(any(c in commands and commands[c]['response'] and
                 commands[c]['response']['result'].get('error')=='known_identity_unavailable'
                 for c in incident['evidence_command_ids']), 'identity_restriction_not_observed')
    elif incident['resolution']=='EXTERNAL_IDENTITY_PREREQUISITE':
        need(incident['fix']['runtime_change'] is False and incident['restart_reconciliation']['status']=='NOT_RESTARTED',
             'unresolved_incident_restarted')
        need(any(not commands[c]['response']['result']['success'] and
                 commands[c]['response']['result']['error']=='known_identity_unavailable'
                 for c in incident['evidence_command_ids']), 'identity_restriction_not_observed')
    else:
        need(incident['resolution']=='REPAIRED' and incident['restart_reconciliation']['status']=='INDEPENDENTLY_RECONCILED',
             'unresolved_incident')
        need(incident['regression_results']['exit_code']==0 and incident['fix']['pushed_revision'],
             'repair_unverified_or_unpublished')


def semantic_case(case, values, observations):
    """Require an observed branch, never a prose review or generic successful GET."""
    good=[v for v in values if v.get('response') and v['response']['result']['success']]
    byid={v['command']['id']:v for v in good}
    auctions=[a for v in good for a in (v['response']['result'].get('auctions') or [])]
    events=observations.get('registry',[])
    health=observations.get('health',[])
    controls=observations.get('controls',[])
    def operation(op): return [v for v in good if v['command']['operation']==op]
    def event(reason): return any(e.get('reason')==reason for e in events)
    def tick(direction,value):
        found={p['price'] for v in operation('price_helpers') for p in v['response']['result']['probes']
               if p['direction']==direction and p['value']==value}
        need(len(found)==1,'native_tick_unproven')
        return found.pop()
    if case=='discovery_pagination':
        searches=[v for v in operation('search') if v['command']['params']['purpose']=='discovery' and
                  v['command']['params'].get('max_bid')==1000 and v['command']['params'].get('min_buy')==11000]
        return {1,2}<={v['command']['params']['page'] for v in searches}
    if case=='fresh_pricing':
        searches=[v for v in operation('search') if v['command']['params']['purpose']=='pricing']
        for first in searches:
            p=first['command']['params']
            bins=[a['buy_now_price'] for a in first['response']['result']['auctions'] if a['buy_now_price']>0]
            if bins and 'max_buy' not in p and any(v['command']['params'].get('max_buy')==min(bins) and
                v['command']['params']['definition_id']==p['definition_id'] and
                stamp(v['response']['freshness']['network_at'])>stamp(first['response']['freshness']['network_at'])
                for v in searches): return True
        return False
    if case=='cached_pricing':
        return any(e.get('quote',{}).get('evidence',{}).get('cache_hit') is True and
                   e.get('identity',{}).get('trade_id') in {a['trade_id'] for a in auctions} for e in events)
    if case=='native_legality_admission':
        return bool(operation('caps') and operation('price_helpers') and operation('balance') and
                    any(e.get('reason')=='ELIGIBLE' and e.get('action')=='BID' and
                        0<e['amount']<=e['cap'] for e in events))
    if case in {'minimum_initial_bid','natural_outbid_rebid'}:
        for v in operation('bid'):
            p=v['command']['params'];pre=byid.get(p['status_read_id']);funds=byid.get(p['balance_read_id'])
            if not pre or not funds: continue
            matches=[a for a in pre['response']['result']['auctions'] if
                     (a['trade_id'],a['item']['item_id'],a['item']['definition_id'])==
                     (p['trade_id'],p['item_id'],p['definition_id'])]
            if len(matches)!=1: continue
            a=matches[0]
            if case=='natural_outbid_rebid' and not(a['bid_state']=='outbid' and a['current_bid']>0): continue
            if case=='minimum_initial_bid' and not(pre['command']['operation']=='search' and
                any(e.get('kind')=='ENROLLMENT' and e.get('trade_id')==p['trade_id'] for e in events)):continue
            minimum=tick('above',a['current_bid']) if a['current_bid'] else a['starting_bid']
            if not(p['amount']==p['minimum']==minimum<=p['cap'] and funds['response']['result']['credits']>=minimum): continue
            if any(a2['trade_id']==a['trade_id'] and
                   (a2['item']['item_id'],a2['item']['definition_id'])==
                   (a['item']['item_id'],a['item']['definition_id']) and
                   a2['current_bid']>=minimum and a2['bid_state'] in {'highest','outbid'} and
                   stamp(after['response']['freshness']['network_at'])>stamp(v['response']['freshness']['network_at'])
                   for after in operation('watched') for a2 in after['response']['result']['auctions']): return True
        return False
    if case=='leading_hold':
        return any(a['bid_state']=='highest' and a['trade_state']=='active' and
                   any(e.get('reason')=='LEADING' and e.get('action')=='HOLD' and
                       e.get('trade_id')==a['trade_id'] for e in events) for a in auctions)
    if case=='cap_stop': return event('OVER_CAP') and any(a['bid_state']=='outbid' for a in auctions)
    if case=='lost':
        return any(a['trade_state']=='closed' and a['bid_state']=='outbid' and a['expires']<=0 and
                   any(w['command']['params']['trade_id']==a['trade_id'] and
                       w['command']['params']['item_id']==a['item']['item_id'] and
                       w['command']['params']['definition_id']==a['item']['definition_id'] and
                       stamp(after['response']['freshness']['network_at'])>stamp(w['response']['freshness']['network_at'])
                       for w in operation('bid'))
                   for after in operation('watched') for a in after['response']['result']['auctions'])
    if case in {'won','physical_ownership'}:
        wins=[a for a in auctions if a['native_is_won'] is True and a['bid_state']=='highest' and
              a['trade_state']=='closed' and a['expires']<=0]
        return any(a['item']['item_id']==w['item']['item_id'] and a['item']['definition_id']==w['item']['definition_id'] and
                   a['item']['last_sale_price']==w['current_bid']>0 for w in wins
                   for v in operation('owned_item')+operation('unassigned')
                   for a in (v['response']['result'].get('auctions') or
                             [{'item':i} for i in (v['response']['result'].get('items') or [])]))
    if case=='stored_price_listing':
        for w in operation('list'):
            p=w['command']['params']
            policies=[e for e in events if e.get('kind')=='ENROLLMENT' and e.get('trade_id')==p['trade_id']]
            if not policies or not {p['owned_read_id'],p['caps_read_id']}<=set(byid): continue
            for after in operation('transfer_list'):
                try:
                    listing_proof(w,byid[p['owned_read_id']]['response'],byid[p['caps_read_id']]['response'],
                        after['response'],stored_price=policies[-1]['quote']['resale_price'],
                        previous_tick=tick('below',p['buy_now_price']),started_at=w['started'])
                    return True
                except (ValueError,KeyError): pass
        return False
    if case in {'sold_clear','expired_relist'}:
        for w in operation('clear_sold' if case=='sold_clear' else 'relist_all'):
            pre=byid.get(w['command']['params']['before_read_id'])
            if not pre: continue
            for after in operation('transfer_list'):
                try:
                    bulk_proof(w,pre['response'],after['response'],started_at=w['started'],finished_at=w['finished'])
                    return True
                except (ValueError,KeyError): pass
        return False
    if case=='occupancy_reservations':
        return bool(operation('transfer_list') and health and any(h['capacity']['unresolved']>0 and
            h['capacity']['total']==h['capacity']['occupied']+h['capacity']['pending_resale']+h['capacity']['unresolved']<=50
            for h in health))
    if case=='capacity_pause_resume':
        return event('CAPACITY_PAUSED') and event('CAPACITY_RESUMED') and any(h['capacity']['total']==50 for h in health)
    if case=='sticky_draining': return sum(h['draining'] is True for h in health)>=2 and event('DRAINING')
    if case=='priority_cadence':
        monitored=[h for h in health if {'bidder','acquirer','maintenance'}<=set(h['actors'])]
        return bool(monitored and
            all(any(e.get('actor')==r and e.get('reason')=='CYCLE_FINISHED' for e in events)
                for r in ('bidder','acquirer','maintenance')) and operation('bid'))
    if case=='reconnect_restart':
        return len({r['run'] for r in controls if r['kind']=='RUN_OPEN'})>=2 and sum(r['kind']=='RECONCILED' for r in controls)>=2
    if case=='uncertain_reconciliation':
        # The uncertain delivery belongs to the sealed earlier segment; the
        # referenced successful native read is the subsequent independent proof.
        # An operator attestation or an unsent cancelled read cannot satisfy it.
        uncertain={r['body']['command']['id']:(r['body']['command'],stamp(r['at'])) for r in controls
                   if r['kind']=='NATIVE_RESULT' and r['body'].get('state')=='UNKNOWN' and
                   r['body'].get('command',{}).get('operation')=='bid'}
        for e in observations.get('bid_events',[]):
            uncertain_row=uncertain.get(e.get('command_id'));read=byid.get(e.get('data',{}).get('read_id'))
            if not uncertain_row or not read or e.get('reason') not in {'BID_VERIFIED','WON_VERIFIED','LOST_VERIFIED'}:continue
            original,uncertain_at=uncertain_row
            if read['command']['operation'] not in {'watched','status'}:continue
            params=original['params']
            if any(a['trade_id']==params['trade_id'] and a['item']['item_id']==params['item_id'] and
                   a['item']['definition_id'] in (params['definition_id'],0,None) and
                   (a['item']['definition_id']==params['definition_id'] or read['command']['operation']=='status' and
                    read['command']['params']=={k:params[k] for k in ('trade_id','item_id','definition_id')}) and
                   ((e['reason']=='BID_VERIFIED' and a['bid_state'] in {'highest','outbid'} and a['current_bid']>=params['amount']) or
                    (e['reason']=='LOST_VERIFIED' and a['trade_state']=='closed' and a['bid_state']=='outbid' and a['expires']<=0) or
                    (e['reason']=='WON_VERIFIED' and a['trade_state']=='closed' and a['bid_state']=='highest' and a['expires']<=0 and
                     e['data'].get('paid',0)>0 and semantic_case('physical_ownership',values,observations))) and
                   stamp(read['response']['freshness']['network_at'])>uncertain_at
                   for a in read['response']['result']['auctions']):return True
        return False
    if case=='unrelated_browser_activity':
        return any(r['kind']=='BROWSER_ACTIVITY_REVIEW' and r['body'].get('independent_native_read_ids') and
                   r['body'].get('retained_diagnostic_references') for r in controls)
    if case=='lost_supervision':
        return any(r['kind']=='SUPERVISION_GAP' for r in controls) and any(r['kind']=='RECONCILED' for r in controls)
    if case=='normal_noop_rejection':
        return bool(good) and any(e.get('reason') in {'IDLE','QUOTE_REJECTED','NO_ELIGIBLE_ITEMS'} for e in events)
    if case=='identity_freshness':
        return bool(operation('watched') and operation('balance') and operation('transfer_list') and
                    any(r['kind']=='RECONCILED' for r in controls))
    if case=='post_bid_selector_reconciliation':
        for e in events:
            if e.get('kind')!='EXACT_STATUS' or e.get('reason')!='EXACT_STATUS_RECOVERED' or e.get('source')!='native':continue
            identity=e.get('identity',{});before=byid.get(e.get('watched_read_id'));after=byid.get(e.get('read_id'))
            if not before or not after or before['command']['operation']!='watched' or after['command']['operation']!='status':continue
            params=after['command']['params']
            if any(params.get(k)!=identity.get(k) for k in ('trade_id','item_id','definition_id')):continue
            if any(a['trade_id']==identity['trade_id'] for a in before['response']['result']['auctions']):continue
            matching=[a for a in after['response']['result']['auctions'] if a['trade_id']==identity['trade_id'] and
                      a['item']['item_id']==identity['item_id'] and
                      a['item']['definition_id'] in (None,0,identity['definition_id'])]
            if len(matching)!=1:continue
            a=matching[0]
            if not ((a['trade_state']=='active' and a['bid_state'] in {'highest','outbid'}) or
                    (a['trade_state']=='closed' and a['bid_state'] in {'highest','outbid'} and a['expires']<=0)):continue
            if any(all(w['command']['params'].get(k)==identity[k] for k in ('trade_id','item_id','definition_id')) and
                   stamp(w['response']['freshness']['network_at'])<stamp(after['response']['freshness']['network_at'])
                   for w in operation('bid')):return True
        return False
    raise ValueError('new_case_requires_semantic_assessor:'+case)


def coverage_contract(matrix, commands, run, revision, observations=None):
    ids = [r['id'] for r in matrix['cases']]
    need(len(ids)==len(set(ids)) and REQUIRED<=set(ids), 'missing_required_matrix_case')
    need(matrix['realized_profit']['status']=='DEFERRED' and
         matrix['realized_profit']['acceptance_required'] is False, 'profit_scope_changed')
    for row in matrix['cases']:
        live = row['current_run_live_proof']
        need(live['status']=='LIVE-VERIFIED', 'LIVE-UNVERIFIED:'+row['id'])
        need(live['run_id']==run and live['revision']==revision and live.get('reviewer') and
             live.get('semantic_assessment'), 'case_review_identity_missing:'+row['id'])
        refs = live['evidence']
        need(refs and all(r['command_id'] in commands for r in refs), 'case_native_evidence_missing:'+row['id'])
        for ref in refs:
            c = commands[ref['command_id']]
            need(c['run']==run and c['response'] and c['response']['freshness']['source']=='native' and
                 c['response']['result']['success'], 'failed_or_historical_callback_promoted:'+row['id'])
            need(ref['database'] in {'native','control'} and ref.get('table') and ref.get('key') is not None,
                 'case_database_join_missing:'+row['id'])
        need(semantic_case(row['id'],[commands[r['command_id']] for r in refs],observations or {}),
             'native_branch_unwitnessed:'+row['id'])
        if row['id'] in {'minimum_initial_bid','natural_outbid_rebid','stored_price_listing','sold_clear','expired_relist'}:
            operations = {'minimum_initial_bid':'bid','natural_outbid_rebid':'bid','stored_price_listing':'list',
                          'sold_clear':'clear_sold','expired_relist':'relist_all'}
            writes = [commands[r['command_id']] for r in refs if commands[r['command_id']]['command']['operation']==operations[row['id']]]
            need(writes, 'case_mutation_missing:'+row['id'])
            for w in writes:
                post = live.get('readback_command_ids', [])
                need(post and all(cid!=w['command']['id'] and cid in commands and
                     commands[cid]['response']['result']['success'] and
                     stamp(commands[cid]['response']['freshness']['network_at'])>
                     stamp(w['response']['freshness']['network_at']) for cid in post),
                     'case_independent_post_read_missing:'+row['id'])


def accepted_bid_readback_contract(write, readback):
    """Join actual participation to a distinct later native observation."""
    c,r=write['command'],write['response'];c2,r2=readback['command'],readback['response']
    parse_response(r,c,source='native',now=stamp(r['freshness']['observed_at']),require_bid_receipt=True)
    need(r['result']['bid_receipt']['verdict']=='ACCEPTED','accepted_native_receipt_required')
    need(r2 is not None,'independent_bid_readback_missing')
    parse_response(r2,c2,source='native',now=stamp(r2['freshness']['observed_at']))
    need(c2['operation'] in {'watched','status'} and r2['result']['success'] and
         c2['context']==c['context'] and c2['fences']==c['fences'] and
         c2['id'] not in {c['id'],c['params']['status_read_id']} and
         stamp(r2['freshness']['network_at'])>stamp(r['freshness']['network_at']),
         'independent_bid_readback_missing')
    p=c['params']
    matching=[a for a in r2['result']['auctions'] if a['trade_id']==p['trade_id'] and a['item']['item_id']==p['item_id'] and
              (a['item']['definition_id']==p['definition_id'] or c2['operation']=='status' and
               a['item']['definition_id'] in (None,0) and c2['params']=={k:p[k] for k in ('trade_id','item_id','definition_id')})]
    need(len(matching)==1 and matching[0]['bid_state'] in {'highest','outbid'} and
         (matching[0]['current_bid']>=p['amount'] or matching[0]['trade_state']=='closed' and
          matching[0]['expires']<=0 and matching[0]['bid_state']=='outbid'),'independent_personal_outcome_missing')


def capture_boundary_contract(index, bundle_dir, structural):
    """Only unexpired capture boundaries or certified unsent reads may be open."""
    if not structural['findings']:return
    need(index.get('phase')=='CONTINUOUS_PRODUCTION','unresolved_capture_findings')
    bundle=load(bundle_dir/'manifest.json')
    with closing(read_db(bundle_dir/'native.sqlite3')) as db:
        pending={cid:dict(state=s,deadline=stamp(d),started=a,reason=r,operation=json.loads(c)['operation'])
                 for cid,s,d,a,r,c in db.execute('SELECT id,state,deadline,started,reason,command FROM work')}
        claimed={cid for cid,b in db.execute('SELECT id,body FROM native_events') if json.loads(b)['kind']=='DISPATCH_CLAIM'}
    for finding in structural['findings']:
        cid=finding['reference'].get('command_id');row=pending.get(cid,{})
        cancelled=(cid in index.get('cancelled_before_dispatch',[]) and row.get('state')=='UNKNOWN' and
                   row.get('reason')=='CALLER_TIMEOUT' and row.get('started') is None and
                   row.get('operation') not in MUTATIONS and cid not in claimed)
        documented=False
        if (cid in index.get('documented_read_failures',[]) and row.get('state')=='UNKNOWN' and
                row.get('started') is not None and cid in claimed and row.get('operation') in
                {'watched','balance','transfer_list','status','owned_item','unassigned','caps'}):
            # A sealed failed GET is safe to diagnose, never successful native
            # evidence or work to replay. Mutations cannot enter this exception.
            with closing(read_db(bundle_dir/'transport.sqlite3')) as db:
                encoded=[e for (e,) in db.execute('SELECT event FROM events WHERE command_id=?',(cid,))]
                events=[json.loads(e) for e in encoded if e.startswith('{')]
                documented=('DELIVERED' in encoded and any(e.get('kind')=='RESULT_REJECTED' and
                    e.get('reason')=='invalid_network_status' and e.get('summary',{}).get('success') is False
                    for e in events) and any(r.get('stage')=='PAGE_FAILURE' and
                    r.get('detail',{}).get('error')=='service_failed' for e in events for r in e.get('records',[])))
        need(finding['reason'] in {'TRANSPORT_NOT_YET_CAPTURED','MISSING_RESPONSE_NO_RETRY','UNSETTLED_COMMAND'} and
             (cancelled or documented or row.get('state') in {'WAITING','CLAIMED'} and row['deadline']>=stamp(bundle['finished_at'])),
             'unresolved_capture_findings')


def assess_task(index, directory=OUT):
    """Evaluate each criterion independently; missing work cannot become PASS."""
    out = Path(directory)
    need(index['task']=='003-04' and index['schema']==1, 'wrong_task_index')
    diagnostic_transport=sealed_artifacts(out)
    ongoing=index.get('phase')=='CONTINUOUS_PRODUCTION'
    if ongoing:
        exports=[r for r in lines(ROOT/index['export_events']) if r['kind']=='CAPTURED' and r['run']==index['run']]
        need(exports,'periodic_export_missing')
        index=dict(index,snapshot=exports[-1]['path'])
    bundle_dir = ROOT/index['snapshot']
    structural = assess(bundle_dir)
    need(structural['evidence_class']=='NATIVE_CAPTURE_REQUIRES_CASE_REVIEW', 'fixture_is_not_live')
    bundle = load(bundle_dir/'manifest.json')
    capture_boundary_contract(index,bundle_dir,structural)
    with closing(read_db(bundle_dir/'control.sqlite3')) as db: rows = records(db)
    opened = [r for r in rows if r['kind']=='RUN_OPEN']
    final = opened[-1]; run = final['run']; revision = bundle['revision']
    if ongoing:need(run==index['run'] and revision==index['run_revisions'][run],'wrong_current_run')
    commands = {}
    for r in rows:
        if r['kind']=='RECOVERY_READ':
            v = r['body']; commands[v['command']['id']] = dict(run=r['run'], **v)
    fence_runs={json.dumps(r['body']['fences'],sort_keys=True):r['run'] for r in rows if r['kind']=='ATTACHED'}
    with closing(read_db(bundle_dir/'native.sqlite3')) as db:
        for c, v, started, finished in db.execute('SELECT command,response,started,finished FROM work'):
            c = json.loads(c)
            commands[c['id']] = dict(run=fence_runs.get(json.dumps(c['fences'],sort_keys=True)),command=c,
                                    response=json.loads(v) if v else None,started=started,finished=finished)
    for r in lines(out/'ghost-status-diagnostic.jsonl'):
        if r['kind']=='NATIVE_READ': commands[r['command']['id']] = dict(run=index['diagnostic_run'], command=r['command'], response=r['response'])
    for path in index.get('additional_diagnostics',[]):
        for r in lines(out/path):
            if r['kind']=='NATIVE_READ':
                parse_response(r['response'],r['command'],source='native',now=stamp(r['at']))
                commands[r['command']['id']]=dict(run=index.get('diagnostic_runs',{}).get(path,index['run']),
                                                 command=r['command'],response=r['response'])
    results = []
    def check(n, work):
        try:
            work(); results.append(dict(criterion=n,status='PASS'))
        except (ValueError, KeyError, TypeError, OSError, StopIteration) as e:
            results.append(dict(criterion=n,status='UNFULFILLED',reason=str(e) if isinstance(e,ValueError) else type(e).__name__))

    def prelaunch():
        p = load(out/'prelaunch-reconciliation.json')
        historical = [r['response'] for r in lines(ROOT/'docs/research/003/003-01/native-opening.jsonl') if r['kind']=='NATIVE_READ']
        if not ongoing:
            proof = assess_reads(lines(out/index['prelaunch_reads']), p['native']['context'], historical)
            need(proof==p['native'], 'prelaunch_summary_disagrees_with_native')
        else:
            reads=[v for v in commands.values() if v['run']==run and v['command']['id'] in
                   next(r['body']['read_ids'] for r in rows if r['run']==run and r['kind']=='RECONCILED')]
            operations={v['command']['operation'] for v in reads}
            need({'watched','balance','transfer_list'}<=operations and
                 operations<={'watched','balance','transfer_list','status','owned_item','unassigned','caps'},
                 'fresh_reconciliation_missing')
            for v in reads:
                parse_response(v['response'],v['command'],source='native',now=stamp(v['response']['freshness']['observed_at']))
                need(v['command']['context']==p['native']['context'] and v['response']['result']['success'],
                     'wrong_or_unauthenticated_prelaunch_context')
            pile=next(v['response'] for v in reads if v['command']['operation']=='transfer_list')
            need(pile['coverage']['complete'],'complete_prelaunch_inventory_required')
        need(p['config']==production_config().export()==final['body']['config'], 'strategy_configuration_changed')
        scan=load(out/index.get('processes_record','processes-before.json')); scan=scan if isinstance(scan,list) else [scan]
        if 'processes_record' in index:
            import re
            controllers=[r for r in scan if re.search(r'-m fc_access\.(continuous_v1|actors_v1)',r.get('CommandLine',''))]
            servers=[r for r in scan if 'fc_access.production_v1.server' in r.get('CommandLine','')]
            need(not controllers and len(servers)<=1,'competing_controller')
        else:
            need(len(scan)==1 and 'fc_access.production_v1.server' in scan[0]['command'], 'competing_controller')
        reconciled = [r for r in rows if r['run']==run and r['kind']=='RECONCILED']
        need(reconciled and any(r['kind']=='READY' and r['run']==run for r in rows), 'commitments_not_reconciled_startup_gated')
        need(len(reconciled[-1]['body']['read_ids'])>=3, 'fresh_reconciliation_missing')
    check(0, prelaunch)
    def browser():
        evidence=lines(out/index.get('browser_record','browser-recovery.jsonl'))
        browser_contract(evidence)
        review=next((r for r in evidence if r['kind']=='LOGIN_REVIEW'),None)
        if review:
            with closing(read_db(bundle_dir/'transport.sqlite3')) as db:
                native={cid:(json.loads(c),json.loads(v)) for cid in review['authenticated_read_ids']
                        for c,v in db.execute('SELECT body,result FROM commands WHERE id=?',(cid,)) if v}
            login_evidence_contract(review,load(out/review['evidence']),native)
    check(1,browser)

    with closing(read_db(bundle_dir/'journal.sqlite3')) as db:
        resolved_intents={r[0] for table in ('commands','bulk_writes_v1','resale_writes_v1')
                          for r in db.execute('SELECT id FROM '+table+" WHERE state='RECONCILED'")}

    def strategy():
        writes=[v for v in commands.values() if v['run']==run and v['command']['operation'] in MUTATIONS]
        need(any(v['command']['operation']=='bid' for v in writes), 'real_strategy_operations_absent')
        with closing(read_db(bundle_dir/'journal.sqlite3')) as db:
            for v in writes:
                c,r=v['command'],v['response']
                need(r is not None,'native_mutation_not_successful')
                parse_response(r,c,source='native',now=stamp(r['freshness']['observed_at']),
                               require_bid_receipt=index.get('require_bid_receipt',False))
                from fc_access.production_v1.bid_receipt import ordinary_rejection
                rejected=ordinary_rejection(c,r)
                need(r['result']['success'] or rejected,'native_mutation_not_successful')
                if c['operation']=='bid':
                    state=db.execute('SELECT state,amount FROM commands WHERE id=?',(c['id'],)).fetchone()
                    need(state and state==('RECONCILED',c['params']['amount']) and c['params']['amount']<=c['params']['cap'],
                         'bid_not_independently_reconciled')
                    if index.get('require_bid_receipt'):
                        stored=db.execute('SELECT receipt FROM bid_receipts_v1 WHERE command_id=?',(c['id'],)).fetchone()
                        need(stored and json.loads(stored[0])==r['result']['bid_receipt'],'durable_native_bid_receipt_missing')
                    reasons=('OPENING_REJECTED','BID_REJECTION_VERIFIED') if rejected else ('BID_VERIFIED','LOST_VERIFIED','WON_VERIFIED')
                    proof=db.execute('SELECT data FROM events WHERE command_id=? AND reason IN ('+
                                     ','.join('?' for _ in reasons)+')',(c['id'],*reasons)).fetchall()
                    need(proof and any(json.loads(p[0]).get('read_id')!=c['params']['status_read_id'] for p in proof),
                         'independent_bid_readback_missing')
                    if index.get('require_bid_receipt') and not rejected:
                        read_id=json.loads(proof[-1][0]).get('read_id')
                        need(read_id in commands,'independent_bid_readback_missing')
                        accepted_bid_readback_contract(v,commands[read_id])
                    if rejected:
                        data=json.loads(proof[-1][0])
                        need(data.get('balance_read_id') in commands and data.get('read_id') in commands,
                             'rejection_independent_reads_missing')
                        for key in ('balance_read_id','read_id'):
                            read=commands[data[key]]
                            need(read['command']['context']==c['context'] and read['command']['fences']==c['fences'] and
                                 read['response'] and read['response']['result']['success'] and
                                 stamp(read['response']['freshness']['network_at'])>stamp(v['started']),
                                 'rejection_independent_reads_missing')
    check(2, strategy)

    def monitoring():
        segment_contract(rows,run,minimum=1,resolved_intents=resolved_intents)
        path=Path(final['body']['state_dir'])/'control.sqlite3'
        with closing(read_db(path)) as db:
            c=object.__new__(Control);c.db=db
            import time
            c.clock=time.monotonic
            status=c.status()
        need(status['run']==run and status['supervised'] and status['status']=='RUNNING', 'persistent_supervision_not_active')
        need(all(alive(r['body']['pid']) for r in rows if r['run']==run and r['kind']=='PROCESS_STARTED'), 'runtime_process_not_alive')
        need((datetime.now(timezone.utc)-stamp(bundle['finished_at'])).total_seconds()<=300, 'periodic_evidence_export_overdue')
    check(3, monitoring)

    def incidents():
        docs = [load(out/p) for p in index['incidents']]
        need(len({r['id'] for r in docs})==len(docs), 'duplicate_incident_id')
        triggers=[r for r in rows if r['kind'] in {'INCIDENT','EXCEPTION','SUPERVISION_GAP'}]
        for r in triggers:
            need(any(d['run']==r['run'] and r['seq'] in d['trigger_control_seqs'] for d in docs), 'unrecorded_incident')
        for d in docs:
            operator_proof=None
            if d['resolution'] in {'OPERATOR_RESOLVED','OPERATOR_NONREGISTRATION'}:
                with closing(read_db(bundle_dir/'journal.sqlite3')) as db:
                    table='operator_nonregistrations_v1' if d['resolution']=='OPERATOR_NONREGISTRATION' else 'operator_losses_v1'
                    phase='OPERATOR_NOT_REGISTERED' if d['resolution']=='OPERATOR_NONREGISTRATION' else 'OPERATOR_LOST'
                    stored=db.execute('SELECT proof FROM '+table+' WHERE command_id=?',(d['triggering_command_id'],)).fetchone()
                    need(stored is not None,'operator_loss_audit_missing')
                    operator_proof=json.loads(stored[0]);identity=operator_proof['identity']
                    need(db.execute('SELECT state FROM commands WHERE id=?',(d['triggering_command_id'],)).fetchone()==('RECONCILED',),
                         'operator_loss_command_not_reconciled')
                    need(db.execute('SELECT phase FROM capacity_slots_v1 WHERE trade_id=? AND item_id=?',
                         (identity['trade_id'],identity['item_id'])).fetchone()==(phase,),'operator_loss_slot_not_retired')
                    need(not db.execute("SELECT 1 FROM events WHERE command_id=? AND reason IN ('LOST_VERIFIED','WON_VERIFIED')",
                         (d['triggering_command_id'],)).fetchone(),'operator_loss_falsely_promoted_to_native')
            incident_contract(d,rows,commands,operator_proof=operator_proof)
    check(4, incidents)

    def changes():
        need(not index.get('pending_runtime_fixes'), 'runtime_repair_waiting_for_independent_reconciliation')
        launch = load(out/index.get('launch_record','launch.json'))
        final_revision=index.get('run_revisions',{}).get(run,launch['revision'])
        need(final_revision==revision, 'launch_revision_mismatch')
        for ref in (revision,):
            r=subprocess.run(['git','merge-base','--is-ancestor',ref,'origin/main'],cwd=ROOT,capture_output=True,timeout=10)
            need(r.returncode==0,'runtime_revision_not_pushed')
        for fix in index['runtime_fixes']:
            need(index['run_revisions'][fix['restart_run']]==fix['revision'], 'repair_launch_revision_mismatch')
            info=subprocess.run(['git','show','-s','--format=%ct',fix['revision']],cwd=ROOT,capture_output=True,text=True,timeout=10)
            need(info.returncode==0,'repair_revision_missing')
            pushed=subprocess.run(['git','merge-base','--is-ancestor',fix['revision'],'origin/main'],cwd=ROOT,capture_output=True,timeout=10)
            regression=load(out/fix['regression_receipt'])
            import re
            log=(out/regression['stderr']).read_text(encoding='utf8')
            summary=re.search(r'Ran (\d+) tests? in [\d.]+s.*?\n\s*OK\s*$',log,re.S)
            need(summary and int(summary[1])==regression['tests_run'], 'repair_regression_output_missing')
            repair_contract(fix,rows,commit_time=datetime.fromtimestamp(int(info.stdout.strip()),timezone.utc),
                            published=pushed.returncode==0,regression=regression)
        with closing(read_db(bundle_dir/'native.sqlite3')) as db:
            claims=[i for i,b in db.execute('SELECT id,body FROM native_events') if json.loads(b)['kind']=='DISPATCH_CLAIM']
        recovery=[r['body']['command']['id'] for r in rows if r['kind']=='RECOVERY_INTENT']
        need(len(claims+recovery)==len(set(claims+recovery)), 'consumed_command_replayed')
        # Never claim repair/restart proof for a gated, unresolved first boot.
        need(any(r['kind']=='RECONCILED' and r['run']==run for r in rows), 'independent_restart_reconciliation_missing')
        need(len({r['body']['pid'] for r in opened})==len(opened), 'owner_reused')
        for previous in opened[:-1]: stopped_contract(rows,previous['run'])
    check(5, changes)

    def sealing():
        for r in opened:
            if any(x['kind']=='RUN_STOPPED' and x['run']==r['run'] for x in rows): stopped_contract(rows,r['run'])
        need(all(s['healthy_observed_seconds']>=0 for s in structural['healthy_segments']), 'earlier_counters_discarded')
        need(len(structural['healthy_segments'])==len(opened),'healthy_segment_missing')
    check(6,sealing)
    check(7,lambda: segment_contract(rows,run,resolved_intents=resolved_intents))
    with closing(read_db(bundle_dir/'journal.sqlite3')) as db:
        registry=[dict(at=a,trade_id=t,**json.loads(b)) for a,t,b in db.execute('SELECT at,trade_id,body FROM registry_events_v1')]
        bid_events=[dict(command_id=c,reason=r,data=json.loads(d)) for c,r,d in db.execute(
            "SELECT command_id,reason,data FROM events WHERE reason IN ('BID_VERIFIED','WON_VERIFIED','LOST_VERIFIED')")]
    epoch=next((r['body']['fences']['epoch'] for r in rows if r['run']==run and r['kind']=='ATTACHED'),None)
    observations=dict(registry=[e for e in registry if e.get('epoch')==epoch],
                      health=[r['body'] for r in rows if r['run']==run and r['kind']=='SNAPSHOT'],controls=rows,
                      bid_events=bid_events)
    check(8,lambda: coverage_contract(load(out/index.get('matrix','live-coverage-matrix.json')),commands,run,revision,observations))

    def restriction():
        incidents()
        docs=[load(out/p) for p in index['incidents']]
        if ongoing and all(d['resolution'] in {'REPAIRED','OPERATOR_RESOLVED','OPERATOR_NONREGISTRATION'} for d in docs):
            need(not any(r['run']==run and r['kind'] in {'INCIDENT','EXCEPTION','SUPERVISION_GAP','STOP_REQUESTED'}
                         for r in rows),'current_restriction_requires_diagnosis')
            return
        if ongoing and any(d['resolution']=='UNRESOLVED_ACCOUNT_RELATION' for d in docs):
            stopped_contract(rows,run)
            for d in docs:
                if d['resolution']!='UNRESOLVED_ACCOUNT_RELATION':continue
                h=load(out/d['safe_state']['readonly_health'])['health']
                need(h['attached'] and h['mutations_enabled'] is False and h['intent_journal'] is None,
                     'safe_readonly_state_missing')
                need(d['human_or_external_prerequisite']['minimal_action'] and
                     d['human_or_external_prerequisite']['prohibited_workarounds'],'exact_prerequisite_missing')
                with closing(read_db(bundle_dir/'journal.sqlite3')) as db:
                    bid=db.execute('SELECT state,amount,trade_id,item_id,definition_id FROM commands WHERE id=?',
                                   (d['triggering_command_id'],)).fetchone()
                    need(bid and bid[0]=='ACKNOWLEDGED' and bid[1]==d['known_account_effects']['amount'],
                         'actual_bid_was_released_or_replayed')
                    need(db.execute('SELECT phase FROM capacity_slots_v1 WHERE trade_id=? AND item_id=?',bid[2:4]).fetchone()==
                         ('UNRESOLVED',),'unresolved_slot_was_released')
                integrity=load(out/d['safe_state']['evidence_integrity'])
                need(integrity['scope']=='SEALED_CAPTURED_ACCOUNT_RELATION_EVIDENCE_ONLY','wrong_incident_integrity_scope')
                for ref in integrity['captures']:
                    path=(ROOT/ref['path']).resolve()
                    need(path.is_relative_to(out/'production-03/incident-outcome-01') and path.name in {
                        'native-diagnostic.jsonl','terminal-diagnostic.jsonl','followup-status.jsonl',
                        'process-stop.json','readonly-service.json','readonly-health.json'},'wrong_incident_capture_scope')
                    with path.open('rb') as stream:
                        need(hashlib.file_digest(stream,'sha256').hexdigest()==ref['sha256'],'incident_capture_changed')
                path=(ROOT/integrity['transport']['path']).resolve()
                need(path.is_relative_to(ROOT/'private-captures/003-04/production-03/incident-outcome-01') and
                     path.name=='transport.sqlite3','wrong_incident_transport')
                with path.open('rb') as stream:
                    need(hashlib.file_digest(stream,'sha256').hexdigest()==integrity['transport']['sha256'],
                         'incident_transport_changed')
                diagnostic=commands[d['terminal_read_id']]
                with closing(read_db(path)) as db:
                    stored=db.execute('SELECT body,result FROM commands WHERE id=?',(d['terminal_read_id'],)).fetchone()
                need(stored and json.loads(stored[0])==diagnostic['command'] and json.loads(stored[1])==diagnostic['response'],
                     'restriction_not_independently_retained')
            return
        if ongoing and any(d['resolution']=='UNRESOLVED_ACTUAL_BID' for d in docs):
            stopped_contract(rows,run)
            for d in docs:
                if d['resolution']!='UNRESOLVED_ACTUAL_BID':continue
                state=load(out/d['safe_state']['readonly_health'])['health']
                need(state['attached'] and state['mutations_enabled'] is False and state['intent_journal'] is None,
                     'safe_readonly_state_missing')
                with closing(read_db(bundle_dir/'journal.sqlite3')) as db:
                    p=db.execute('SELECT state,trade_id,item_id,definition_id FROM commands WHERE id=?',
                                 (d['triggering_command_id'],)).fetchone()
                need(p and p[0]=='ACKNOWLEDGED','actual_bid_was_released_or_replayed')
                diagnostic=commands[d['evidence_command_ids'][-1]]
                need(diagnostic['command']['params']==dict(zip(('trade_id','item_id','definition_id'),p[1:])),
                     'wrong_actual_bid_reconciliation_identity')
                integrity=load(out/index['incident_integrity'])
                need(integrity['scope']=='SEALED_CAPTURED_INCIDENT_EVIDENCE_ONLY','wrong_incident_integrity_scope')
                for ref in integrity['captures']:
                    path=(ROOT/ref['path']).resolve()
                    need(path.name in {'diagnostics.json','exact-status.jsonl','process-stop.json','readonly-service.json',
                         'readonly-health.json'} and
                         path.is_relative_to(ROOT/'docs/research/003/003-04/production-02/incident-identity-01'),
                         'wrong_incident_capture_scope')
                    with path.open('rb') as stream:
                        need(hashlib.file_digest(stream,'sha256').hexdigest()==ref['sha256'],'incident_capture_changed')
                path=ROOT/integrity['transport']['path']
                need(path.is_relative_to(ROOT/'private-captures/003-04/production-02/incident-identity-01') and
                     path.name=='transport.sqlite3','wrong_incident_transport')
                with path.open('rb') as stream:
                    need(hashlib.file_digest(stream,'sha256').hexdigest()==integrity['transport']['sha256'],
                         'incident_transport_changed')
                with closing(read_db(path)) as db:
                    stored=db.execute('SELECT body,result FROM commands WHERE id=?',(diagnostic['command']['id'],)).fetchone()
                need(stored and json.loads(stored[0])==diagnostic['command'] and
                     json.loads(stored[1])==diagnostic['response'],'restriction_not_independently_retained')
            return
        need(docs and all(d['human_or_external_prerequisite']['minimal_action'] and
             d['human_or_external_prerequisite']['prohibited_workarounds'] for d in docs), 'exact_prerequisite_missing')
        state=load(out/'restored-health.json')['health']
        need(state['attached'] and state['mutations_enabled'] is False, 'safe_readonly_state_missing')
        need(all(v['command']['operation'] not in MUTATIONS for v in commands.values()), 'unknown_account_effect_requires_review')
        diagnostic = next(r for r in lines(out/'ghost-status-diagnostic.jsonl') if r['kind']=='NATIVE_READ')
        with closing(read_db(diagnostic_transport)) as db:
            raw=db.execute('SELECT body,result FROM commands WHERE id=?',(diagnostic['command']['id'],)).fetchone()
        need(raw and json.loads(raw[0])==diagnostic['command'] and json.loads(raw[1])==diagnostic['response'],
             'external_restriction_not_independently_retained')
        parse_response(diagnostic['response'],diagnostic['command'],source='native',now=stamp(diagnostic['at']))
        need(diagnostic['response']['result']['error']=='known_identity_unavailable' and
             diagnostic['response']['freshness']['request_count']==0, 'external_restriction_not_observed')
    check(9,restriction)
    return dict(task='003-04',status='PASS' if all(r['status']=='PASS' for r in results) else 'INCOMPLETE',
                run=run,revision=revision,results=results,scope='LIVE_ACCEPTANCE_NOT_OFFLINE_TEST_SUCCESS')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index',type=Path,default=OUT/'evidence-index.json')
    args=parser.parse_args()
    try: result=assess_task(load(args.index),args.index.resolve().parent)
    except (OSError,ValueError,KeyError,TypeError) as e:
        result=dict(task='003-04',status='INVALID_EVIDENCE',error_type=type(e).__name__)
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__': raise SystemExit(main())
