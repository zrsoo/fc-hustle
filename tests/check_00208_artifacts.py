"""Validate causal captured fixture evidence, never mutable source hashes."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.production_v1.contracts import command, parse_response


def require(condition, message):
    if not condition: raise AssertionError(message)


def validate(document):
    require(document['schema'] == 1 and document['source'] == 'synthetic','explicit synthetic provenance')
    require(set(document['scenarios']) == {'exact_listing','uncertain_listing'},'scenario coverage')
    for name, scenario in document['scenarios'].items():
        require(scenario['source']=='synthetic' and scenario['real_account_writes']==0,'no live claim')
        for count in scenario['capacity']:
            require(count['total']==count['occupied']+count['pending_resale']+count['unresolved']==1,'disjoint reservation conservation')
        require([c['operation'] for c in scenario['mutations']]==['move','list'],'one call per mutation; no blind retry')
        for c in scenario['mutations']: command(c)
    exact = document['scenarios']['exact_listing']
    require(exact['state']=='LISTED' and not exact['pending'],'independently completed lifecycle')
    events = exact['events']
    require([e['seq'] for e in events]==sorted({e['seq'] for e in events}),'ordered unique events')
    reads = {}
    helpers = {}
    for read in exact['reads']:
        c,v = read['command'],read['response']
        parse_response(v,c,now=datetime.fromisoformat(v['freshness']['observed_at']),source='fixture')
        reads[c['id']] = v
        if c['operation']=='price_helpers':
            for p in v['result']['probes']: helpers[p['direction'],p['value']] = p['price']
    policy = next(e for e in events if e['kind']=='ENROLLMENT')
    proof = next(e for e in events if e.get('reason')=='OWNED_WIN_VERIFIED')
    owned = reads[proof['owned_read_id']]['result']['items']
    watched = reads[proof['win_read_id']]['result']['auctions']
    item = next(i for i in owned if i['item_id']==policy['identity']['item_id'])
    won = next(r for r in watched if r['trade_id']==policy['identity']['trade_id'])
    require(item['definition_id']==policy['identity']['definition_id'] and item['untradeable'] is False,'exact owned version')
    require(item['last_sale_price']==proof['paid']==won['current_bid']>0,'independent actual paid-cost corroboration')
    require(won['trade_state']=='closed' and won['bid_state']=='highest' and won['expires']<=0,'terminal winning status')
    for c in exact['mutations']:
        p=c['params']
        require(p['trade_id']==policy['identity']['trade_id'] and p['item_id']==item['item_id'] and
            p['definition_id']==item['definition_id'] and p['paid']==proof['paid'],'physical acquisition identity and cost')
        require(p['duration']==3600 and p['buy_now_price']==policy['quote']['resale_price'],'stored BIN and hour')
        require(helpers['below',p['buy_now_price']]==p['starting_bid'] and
            helpers['above',p['starting_bid']]==p['buy_now_price'],'exact reciprocal native previous tick')
        caps=reads[p['caps_read_id']]['result']['caps']
        require(caps['definition_id']==p['definition_id'] and caps['minimum']<=p['starting_bid']<p['buy_now_price']<=caps['maximum'],'current card limits')
        trace=[e for e in events if e.get('command_id')==c['id']]
        reasons=[e['reason'] for e in trace]
        require(reasons==['INTENT_DURABLE','DISPATCH_CLAIM','ACKNOWLEDGED','VERIFIED'],'durable intent and claim before ACK and independent verification')
        require(trace[0]['params']==p,'sealed durable parameters')
        for rid in (p['owned_read_id'],p['caps_read_id']):
            v=reads[rid]
            require(v['context']==c['context'] and v['fences']==c['fences'],'full context and epoch fences')
            age=(datetime.fromisoformat(trace[0]['at'])-datetime.fromisoformat(v['freshness']['network_at'])).total_seconds()
            require(0<=age<=30,'fresh ownership/caps before intent')
        back=trace[-1]
        require(set(back['read_ids']).isdisjoint({c['id'],p['owned_read_id'],p['caps_read_id'],p['win_read_id']}),'independent item readbacks')
        for rid in back['read_ids']:
            v=reads[rid]
            require(v['context']==c['context'] and v['fences']==c['fences'],'readback scope and epoch')
            require(datetime.fromisoformat(v['freshness']['network_at'])>=datetime.fromisoformat(trace[1]['at']),'read after dispatch claim')
        pile=next(reads[rid] for rid in back['read_ids'] if reads[rid]['operation']=='transfer_list')
        require(pile['coverage']['complete'],'complete independent pile proof')
        rows=[r for r in pile['result']['auctions'] if r['item']['item_id']==p['item_id'] and r['item']['definition_id']==p['definition_id']]
        require(len(rows)==1,'readback exact physical card')
        if c['operation']=='move':
            unassigned=next(reads[rid] for rid in back['read_ids'] if reads[rid]['operation']=='unassigned')
            require(not any(i['item_id']==p['item_id'] for i in unassigned['result']['items']),'source absence after move')
        else:
            r=rows[0]
            require(r['trade_state']=='active' and r['starting_bid']==p['starting_bid'] and r['buy_now_price']==p['buy_now_price'] and
                3598<=r['expires']<=3600 and back['new_trade_id']==r['trade_id']!=p['trade_id'],'exact new one-hour auction')
    require(exact['capacity'][0]['unresolved']==1 and exact['capacity'][-1]['occupied']==1,'atomic unresolved to pending to occupied handoff')
    uncertain=document['scenarios']['uncertain_listing']
    require(uncertain['state']=='MOVED' and len(uncertain['pending'])==1 and uncertain['pending'][0]['operation']=='list','ambiguous listing unreconciled')
    require(uncertain['capacity'][-1]['pending_resale']==1 and uncertain['capacity'][-1]['physical_occupied']==0,'missing uncertain listing remains reserved')
    return True


if __name__=='__main__':
    document=json.loads((ROOT/'docs/research/002/002-08/scenarios.json').read_text(encoding='utf8'))
    validate(document)
    for corruption in ('paid','duration','physical','epoch','claim','capacity','tick'):
        changed=deepcopy(document)
        exact=changed['scenarios']['exact_listing']
        listing=exact['mutations'][-1]
        if corruption=='paid':
            proof=next(e for e in exact['events'] if e.get('reason')=='OWNED_WIN_VERIFIED')
            read=next(v for v in exact['reads'] if v['command']['id']==proof['owned_read_id'])
            read['response']['result']['items'][0]['last_sale_price']=750
        elif corruption=='duration':listing['params']['duration']=7200
        elif corruption=='physical':listing['params']['item_id']='item:'+'e'*24
        elif corruption=='epoch':listing['fences']['epoch']+=1
        elif corruption=='claim':exact['events']=[e for e in exact['events'] if e.get('reason')!='DISPATCH_CLAIM']
        elif corruption=='tick':listing['params']['starting_bid']=11500
        else:changed['scenarios']['uncertain_listing']['capacity'][0]['pending_resale']=0
        try:validate(changed)
        except (AssertionError,ValueError):pass
        else:raise AssertionError('accepted corrupt evidence: '+corruption)
    print(json.dumps(dict(status='PASS',scenarios=2,negative_checks=7)))
