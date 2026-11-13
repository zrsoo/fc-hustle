"""Independent read requirements and finite one-shot auction decisions."""
from dataclasses import asdict
from datetime import datetime, timezone
from fc_access import pricing

ROUTES={'search':'/ut/game/fc27/transfermarket','caps':'/ut/game/fc27/marketdata/pricelimits',
 'watched':'/ut/game/fc27/watchlist','balance':'/ut/game/fc27/user/credits',
 'unassigned':'/ut/game/fc27/purchased/items','transfer_list':'/ut/game/fc27/tradepile',
 'bid':'/ut/game/fc27/trade/:trade/bid','move':'/ut/game/fc27/item','list':'/ut/game/fc27/auctionhouse'}
WRITES={'bid','move','list'}

def at(v): return datetime.fromisoformat(v.replace('Z','+00:00'))

def fresh(r,op,now,max_age=30):
    if not isinstance(r,dict) or r.get('operation')!=op or r.get('success') is not True or r.get('persona',{}).get('accepted') is not True:
        raise ValueError('native_success_required')
    net=r['network']
    verb='PUT' if op in ('bid','move') else 'POST' if op=='list' else 'GET'
    if len(net)!=1 or net[0]['route']!=ROUTES[op] or net[0]['method']!=verb or not net[0]['session_header_present'] or not 200<=net[0]['status']<300:
        raise ValueError('one_authenticated_native_request_required')
    if not 0<=now-at(net[0]['started_at']).timestamp()<=max_age:
        raise ValueError('stale_read')
    if not at(net[0]['started_at'])<=at(net[0]['ended_at'])<=at(r['observed_at']):
        raise ValueError('invalid_read_times')
    if op in ('search','watched','transfer_list'):
        # Native entity normalization may add tradeability/lastSalePrice. The
        # auction identity, amounts and state must match the independent wire.
        keys=('trade_id','item_id','definition_id','starting_bid','current_bid','buy_now_price','expires','trade_state','bid_state')
        proj=lambda rows:[{k:x[k] for k in keys} for x in rows]
        if r['wire_rows'] is None or proj(r['rows'])!=proj(r['wire_rows']):raise ValueError('wire_entity_mismatch')
    return r

def exact(r,trade,item,definition):
    rows=[x for x in r['rows'] or [] if x['trade_id']==trade]
    if len(rows)!=1 or rows[0]['item_id']!=item or rows[0]['definition_id']!=definition:
        raise ValueError('exact_physical_identity_required')
    return rows[0]

def rules(capture,definition,now):
    fresh(capture,'caps',now,120)
    caps=[c for c in capture['caps'] or [] if c['definition_id']==definition]
    if len(caps)!=1:raise ValueError('native_caps_required')
    c=caps[0];tiers=sorted((t for t in capture['tiers'] if t['minimum']>0),key=lambda t:t['minimum'])
    bands=tuple(pricing.Band(t['minimum'],tiers[i+1]['minimum'] if i+1<len(tiers) else max(c['maximum']+1,t['minimum']+1),t['increment']) for i,t in enumerate(tiers))
    result=pricing.Rules(pricing.MarketKey(definition,'pc'),c['minimum'],c['maximum'],at(capture['observed_at']),bands)
    pricing.validate_rules(result);return result

def minimum(row,rules):
    if row['current_bid']==0:value=row['starting_bid']
    else:
        values=[b.start+max(0,(max(row['current_bid']+1,rules.minimum)-b.start+b.step-1)//b.step)*b.step for b in rules.bands]
        values=[v for v,b in zip(values,rules.bands) if b.start<=v<b.stop and v<=rules.maximum]
        value=min(values) if values else None
    if value is None or pricing.floor_price(value,rules)!=value:raise ValueError('unsupported_minimum')
    return value

def economics(candidate,comps,caps,*,trade,item,definition,now):
    fresh(candidate,'search',now);fresh(comps,'search',now,120)
    row=exact(candidate,trade,item,definition);rr=rules(caps,definition,now)
    def observations(r):
        when=at(r['network'][0]['started_at'])
        return [pricing.Observation(x['trade_id'],x['item_id'],pricing.MarketKey(x['definition_id'],'pc'),x['buy_now_price'],when,x['expires'],x['trade_state']=='active',True) for x in r['rows']]
    obs=observations(comps);cand=next(x for x in observations(candidate) if x.trade_id==trade)
    est=pricing.evaluate(rr.key,obs,cand,rr,now=datetime.fromtimestamp(now,timezone.utc),X=500)
    if est.status!='OK':raise ValueError('five_fresh_comparables_required:'+est.status)
    cap=pricing.floor_price(est.target_sale_price-est.target_sale_price//20-500,rr)
    return {'trade_id':trade,'item_id':item,'definition_id':definition,'target':est.target_sale_price,'tax':est.target_sale_price//20,'X':500,'cap':cap,'opening_minimum':minimum(row,rr),'estimate':asdict(est),'rules_basis':'FRESH_NATIVE_CARD_CAPS_AND_OBSERVED_CLIENT_TICKS;SERVER_ACCEPTANCE_PENDING_REAL_BID'}

def bid_plan(p,evidence,enrollment,now):
    s=fresh(evidence[p['status_id']],p['status_operation'],now)
    b=fresh(evidence[p['balance_id']],'balance',now)
    if s['command_id']==b['command_id']:raise ValueError('separate_balance_required')
    row=exact(s,p['trade_id'],p['item_id'],p['definition_id'])
    if row['trade_state']!='active' or row['expires']<=now-at(s['network'][0]['started_at']).timestamp() or row['bid_state']=='highest':raise ValueError('not_active_or_already_leading')
    rr=rules(evidence[p['caps_id']],p['definition_id'],now)
    if enrollment is None:
        # First participation may enter an auction that already has other bids.
        # It still uses the smallest legal price; subsequent writes require a
        # genuine authoritative personal outbid below, never another search.
        if p['status_operation']!='search' or row['bid_state']!='none':raise ValueError('opening_requires_not_already_participating')
        query=s['network'][0]['query']
        if query.get('macr')!=1000 or query.get('minb')!=10500:raise ValueError('real_filtered_search_required')
        enrollment=economics(s,evidence[p['comparables_id']],evidence[p['caps_id']],trade=p['trade_id'],item=p['item_id'],definition=p['definition_id'],now=now)
    else:
        if p['status_operation']!='watched' or row['bid_state']!='outbid':raise ValueError('genuine_outbid_required')
        # Reprice independently; never raise the stored cap.
        repriced=economics(evidence[p['candidate_id']],evidence[p['comparables_id']],evidence[p['caps_id']],trade=p['trade_id'],item=p['item_id'],definition=p['definition_id'],now=now)
        enrollment={**enrollment,'cap':min(enrollment['cap'],repriced['cap'])}
    amount=minimum(row,rr)
    if p['amount']!=amount or amount>enrollment['cap'] or amount>=row['buy_now_price'] or amount>1000 or b['credits']-amount<5000:
        raise ValueError('minimum_cap_balance_or_reserve')
    return enrollment

def classify(status,owned,*,trade,item,definition,paid=None):
    """Callers validate freshness. Missing coverage always remains UNKNOWN."""
    rows=[r for r in status.get('rows') or [] if r['trade_id']==trade]
    if len(rows)!=1:return 'UNKNOWN'
    r=exact(status,trade,item,definition)
    if r['trade_state'] in ('closed','expired') and r['bid_state']=='outbid':return 'LOST'
    if r['trade_state'] in ('closed','expired') and r['bid_state']=='highest':
        match=[x for x in owned.get('rows') or [] if x['item_id']==item and x['definition_id']==definition]
        if len(match)==1 and paid==r['current_bid'] and paid and match[0]['untradeable'] is False:return 'WON'
        return 'PENDING'
    return 'LEADING' if r['bid_state']=='highest' else 'OUTBID' if r['bid_state']=='outbid' else 'UNKNOWN'
