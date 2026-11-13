"""Explicit third read-only attempt. Bounded discovery, one timed valuation only."""
from copy import deepcopy
import json
from . import gate_00203 as gate
from .contracts import Search, stamp
from .executor import EdgeExecutor
from .foundation import Foundation


def discovery_candidates(response, *, now):
    age=(now-stamp(response['freshness']['network_at'])).total_seconds()
    gate.need(0<=age<=30,'stale_discovery')
    return sorted((r for r in response['result']['auctions'] if
        r['trade_state']=='active' and r['bid_state'] in {'none','outbid'} and
        r['native_is_won'] is not True and r['expires']-age>120 and
        r['item']['untradeable'] is False and r['item']['definition_id']>0 and
        0<(r['current_bid'] or r['starting_bid'])<=1000 and r['buy_now_price']>=11000),
        key=lambda r:(r['current_bid'] or r['starting_bid'],r['trade_id']))


def discover(f,w):
    """No quote, cap, helper, credits read or cache modification before timing."""
    s=w.state
    s.update(stage='BOUNDED_DISCOVERY',discovery_deadline_ns=w.clock()+180_000_000_000,
             discovery_cache_checks=[],discovery_reads=[])
    w.save()
    for _ in range(3):
        w.check()
        response=f.read('search',Search.discovery().params())
        s['discovery_reads'].append(response['command_id'])
        checked={}
        for row in discovery_candidates(response,now=f.now()):
            w.check()
            definition=row['item']['definition_id']
            if definition not in checked:
                inventory=gate.cache_snapshot(gate.ROOT/'private-captures',s['context'],definition)
                gate.need(inventory,'real_cache_inventory_required')
                checked[definition]=inventory
                s['discovery_cache_checks'].append(dict(definition_id=definition,
                    read_id=response['command_id'],inventory=inventory))
            inventory=checked[definition]
            if any(c['exact_key_rows'] for c in inventory):continue
            s.update(cache_inventory=inventory,selection=dict(read_id=response['command_id'],
                definition_id=definition,trade_id=row['trade_id'],item_id=row['item']['item_id'],selected_ns=w.clock()))
            w.save();w.check()
            return response,row
        w.save()
    raise ValueError('bounded_discovery_exhausted_no_uncached_eligible_auction')


def run():
    (gate.ROOT/'AGENTS.md').read_text(encoding='utf8')
    w=gate.Window(gate.THIRD_CHECKPOINT,authorization=gate.third_authorization(),attempt_id=gate.THIRD_ATTEMPT)
    f=None;s=w.state
    try:
        s.update(stage='DESKTOP_PREFLIGHT',live_command_attempted=True);w.save()
        s['desktop']=gate.desktop_preflight()
        h=EdgeExecutor().request('/health')
        gate.need(h['service']=='fc-production-v1' and h['attached'] and h['mutations_enabled'] is False,
                  'read_only_attachment_required')
        s.update(health_before=h,context=h['owner']['context'])
        f=Foundation(gate.ReadOnlyGateExecutor(w),context=s['context'],owner=h['owner']['owner'],
                     journal_path=gate.JOURNAL,cache_path=gate.CACHE,interval=2)
        s['fences']=deepcopy(f.adapter.fences)
        discovery,candidate=discover(f,w)
        # No further candidate or another valuation is permitted beyond this call.
        gate.evaluate_window(f,w,discovery,candidate)
        gate.admission_proof(s)
        s.update(status='PASS',hard_stop=False,dependent_tasks_allowed=True,finished_at=gate.utc())
        s['evidence_sha256']=gate.digest(s);w.save()
    except Exception as error:
        reason=str(error) if type(error) in {ValueError,TimeoutError} and str(error).replace('_','').isalnum() else type(error).__name__
        w.stop(reason)
    finally:
        if f is not None:f.close()
    return {k:s.get(k) for k in ('status','reason','elapsed_ns','hard_stop','dependent_tasks_allowed')}


if __name__=='__main__':print(json.dumps(run()))
