"""One-shot exact-version estimate from independently checked native captures.

Client ticks and observed card caps never establish a realized sale or authorize
a write. A subsequent bidder must fetch fresh availability and native rules.
"""
from dataclasses import asdict
from datetime import timedelta
from fc_access import pricing
from .validation import assess,timestamp,availability,validate


def caps(capture,definition):
    validate(capture)
    read=capture.get('cap_read')
    net=[n for n in capture['network'] if n['route']=='/ut/game/fc27/marketdata/pricelimits']
    if not capture['persona'] or not capture['persona']['accepted'] or not read or read['success'] is not True or read['status']!=200 or read['rows'] is None or read['rows']!=read['wire'] or len(net)!=1:
        return None
    n=net[0]
    if n['status']!=200 or not n['session_header_present'] or n['query'].get('defId')!=definition or not n['ended_at'] or not n['started_at'] or not timestamp(n['started_at'])<=timestamp(n['ended_at'])<=timestamp(capture['observed_at']):
        return None
    matched=[r for r in read['rows'] if r['definition_id']==definition and 0<r['minimum']<=r['maximum']]
    return matched[0] if len(matched)==1 else None


def client_rules(capture,definition):
    cap=caps(capture,definition)
    native=capture.get('native_rules')
    if not cap or not native or not native['tiers']:return None
    tiers=sorted((t for t in native['tiers'] if t['minimum']>0),key=lambda t:t['minimum'])
    bands=tuple(pricing.Band(t['minimum'],tiers[i+1]['minimum'] if i+1<len(tiers) else max(cap['maximum']+1,t['minimum']+1),t['increment']) for i,t in enumerate(tiers))
    return pricing.Rules(pricing.MarketKey(definition,'pc'),cap['minimum'],cap['maximum'],timestamp(capture['observed_at']),bands)


def observations(capture):
    proof=assess(capture)
    fresh=all(proof[k] for k in ('fresh_authenticated_pc','independent_wire_entity_match','native_filters_match','observed_filter_semantics'))
    net=[n for n in capture['network'] if n['route']=='/ut/game/fc27/transfermarket']
    at=timestamp(net[0]['started_at']) if net else timestamp(capture['observed_at'])
    return [pricing.Observation(r['trade_id'],r['item_id'],pricing.MarketKey(r['definition_id'],'pc'),r['buy_now_price'],at,
                               r['expires'],r['trade_state']=='active',fresh) for r in capture['rows'] or []]


def evaluate(candidate_capture,comparable_capture,rules_capture,*,trade_id,now,X=500):
    """Return a conservative indicative cap plus explicit unsupported constraints."""
    validate(candidate_capture);validate(comparable_capture);validate(rules_capture)
    rows=[r for r in candidate_capture['rows'] or [] if r['trade_id']==trade_id]
    if len(rows)!=1:raise ValueError('candidate_missing_or_conflicting')
    row=rows[0];definition=row['definition_id'];key=pricing.MarketKey(definition,'pc')
    rules=client_rules(rules_capture,definition)
    candidate=next(r for r in observations(candidate_capture) if r.trade_id==trade_id)
    obs=observations(comparable_capture)
    result=pricing.evaluate(key,obs,candidate,rules,now=now,X=X)
    target=result.target_sale_price
    raw=target-target//20-X if target is not None else None
    rounded=pricing.floor_price(raw,rules) if raw is not None else None
    if rules and row['current_bid'] and pricing.floor_price(row['current_bid'],rules)==row['current_bid']:
        minimum=next((b.start+((max(row['current_bid']+1,b.start)-b.start+b.step-1)//b.step)*b.step for b in rules.bands if b.stop>row['current_bid']+1),None)
        if minimum is not None and minimum>rules.maximum:minimum=None
    elif rules and row['current_bid']==0 and pricing.floor_price(row['starting_bid'],rules)==row['starting_bid']:
        minimum=row['starting_bid']
    else:minimum=None
    available=availability(row,candidate_capture,now=now)
    eligible=result.status=='OK' and rounded is not None and minimum is not None and minimum<=rounded and minimum<row['buy_now_price'] and available=='AVAILABLE_READ_ONLY'
    return {'classification':'INDICATIVE_ASK_BASED_NOT_REALIZED','definition_id':definition,'platform':'pc','trade_id':trade_id,'item_id':row['item_id'],
            'evaluation_at':now.isoformat(),'estimate':asdict(result),'target':target,'X':X,'tax':target//20 if target is not None else None,
            'unrounded_profitable_cap':raw,'client_tick_rounded_cap':rounded,'minimum_client_bid':minimum,
            'projected_profit_at_minimum':target-target//20-minimum if target is not None and minimum is not None else None,
            'search_maxBid':1000,'availability_at_checkpoint':available,'pricing_qualified_at_checkpoint':eligible,
            'bid_authorized':False,'fresh_prebid_availability_required':True,
            'server_bid_tick_acceptance':'UNVERIFIED','server_listing_tick_acceptance':'UNVERIFIED',
            'realized_sale_price':None,'realized_profit':None}


def coverage(first,second,repeat):
    for c in (first,second,repeat):validate(c)
    a,b,c=first['rows'] or [],second['rows'] or [],repeat['rows'] or []
    ids=lambda rows:{r['trade_id'] for r in rows}
    shared=ids(a)&ids(b);old={r['trade_id']:r for r in a};new={r['trade_id']:r for r in c}
    changes=[{'trade_id':t,'fields':[k for k in ('current_bid','starting_bid','buy_now_price','item_id','definition_id') if old[t][k]!=new[t][k]]} for t in ids(a)&ids(c)]
    return {'page_rows':[len(a),len(b)],'requested_starts':[first['network'][0]['query'].get('start'),second['network'][0]['query'].get('start')],
            'page_overlap':sorted(shared),'unique_rows':len(ids(a)|ids(b)),
            'page1_lookahead':a[20]['trade_id'] if len(a)==21 else None,
            'lookahead_reappeared_on_page2':len(a)==21 and a[20]['trade_id'] in ids(b),
            'within_page_duplicates':[len(rows)-len(ids(rows)) for rows in (a,b,c)],
            'expiry_nondecreasing':[all(x['expires']<=y['expires'] for x,y in zip(rows,rows[1:])) for rows in (a,b,c)],
            'repeat_absent_from_first_page':sorted(ids(a)-ids(c)),
            'repeat_new_on_first_page':sorted(ids(c)-ids(a)),
            'repeat_changed':[r for r in changes if r['fields']],
            'complete_market_coverage':False,'server_order_guaranteed':False,
            'absence_interpretation':'ABSENT_IN_BOUNDED_SEARCH_NOT_PROOF_SOLD_LOST_OR_EXPIRED',
            'fresh_prebid_availability_required':True}
