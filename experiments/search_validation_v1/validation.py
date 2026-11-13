"""Independent strict search projection checks and conservative evidence analysis."""
from datetime import datetime
import math
import re

from fc_access.bidding_v1.contracts import Search

FIELDS = {'schema','command_id','params','observed_at','persona','method','criteria','success','error','status','network','rows','wire_rows','has_more','cache_invalidated','duration_ms'}
ROW = {'trade_id','item_id','definition_id','resource_id','asset_id','rating','rarity','untradeable','starting_bid','current_bid','buy_now_price','expires','trade_state','bid_state'}
NET = {'method','route','query','session_header_present','status','started_at','ended_at','duration_ms','payload_bytes'}
QUERY = {'start','num','count','maxb','minb','micr','macr','maskedDefId','definitionId','defId'}


def search_params(params):
    p=dict(params)
    if 'with_caps' in p and (type(p['with_caps']) is not bool or p['with_caps'] and not p.get('definition_id')):raise ValueError('invalid_caps_request')
    p.pop('with_caps',None)
    return Search(**p)


def number(v, null=True):
    return v is None and null or type(v) is int and 0 <= v <= 2**53-1


def timestamp(v):
    t = datetime.fromisoformat(v)
    if t.utcoffset() is None:
        raise ValueError('timezone_required')
    return t


def validate(v):
    if not isinstance(v,dict) or type(v.get('schema')) is not int or v['schema'] not in (1,2,3) or set(v)!=(FIELDS|({'native_rules'} if v['schema']>=2 else set())|({'cap_read'} if v['schema']==3 else set())):
        raise ValueError('invalid_search_projection')
    if not isinstance(v['command_id'],str) or not re.fullmatch('[a-f0-9]{32}',v['command_id']):
        raise ValueError('invalid_command')
    search_params(v['params'])
    timestamp(v['observed_at'])
    rules=v.get('native_rules')
    if rules is not None:
        if set(rules)!={'tiers','probes','card_caps_methods','classification'} or rules['classification']!='NATIVE_CLIENT_OBSERVED_SERVER_LEGALITY_UNVERIFIED':raise ValueError('invalid_native_rules')
        if rules['tiers'] is not None:
            if not isinstance(rules['tiers'],list) or len(rules['tiers'])>20:raise ValueError('invalid_tiers')
            for t in rules['tiers']:
                if set(t)!={'minimum','increment'} or not number(t['minimum'],False) or not number(t['increment'],False):raise ValueError('invalid_tiers')
        if not isinstance(rules['probes'],list) or len(rules['probes'])>20:raise ValueError('invalid_probes')
        for probe in rules['probes']:
            if set(probe)!={'value','above','below'} or any(not number(x,False) for x in probe.values()):raise ValueError('invalid_probes')
        if not isinstance(rules['card_caps_methods'],list) or len(rules['card_caps_methods'])>30 or any(not re.fullmatch('[A-Za-z][A-Za-z0-9]{0,70}',n) or not re.search('price|marketData',n,re.I) for n in rules['card_caps_methods']):raise ValueError('invalid_methods')
    if v['method']!='services.Item.searchTransferMarket(criteria,page)' or type(v['success']) is not bool or type(v['cache_invalidated']) is not bool:
        raise ValueError('invalid_method')
    if v['error'] not in (None,'invalid_command','wrong_page','bridge_busy','experiment_pacing','unsafe_identity','persona_unverified','service_timeout','service_failed','schema_unrecognized','internal_error'):
        raise ValueError('invalid_error')
    if v['criteria'] is not None and (set(v['criteria'])!={'type','count','maxBid','minBuy','maxBuy','defId'} or v['criteria']['type']!='player' or any(not number(x) for k,x in v['criteria'].items() if k!='type')):
        raise ValueError('invalid_criteria')
    # Shared reviewed persona helper returns an allowlisted projection only.
    if v['persona'] is not None:
        from experiments.market_discovery_followup_v1.server import persona_projection
        persona_projection(v['persona'])
    if not number(v['status']) or v['has_more'] is not None and type(v['has_more']) is not bool:
        raise ValueError('invalid_status')
    if type(v['duration_ms']) not in (int,float) or not math.isfinite(v['duration_ms']) or v['duration_ms']<0:
        raise ValueError('invalid_duration')
    if not isinstance(v['network'],list) or len(v['network'])>30:
        raise ValueError('invalid_network')
    for n in v['network']:
        if set(n)!=NET or n['method']!='GET' or n['route'] not in ('/ut/game/fc27/transfermarket','/ut/game/fc27/marketdata/pricelimits') or type(n['session_header_present']) is not bool or not number(n['status']) or not number(n['payload_bytes']):
            raise ValueError('invalid_network')
        if not isinstance(n['query'],dict) or not set(n['query'])<=QUERY or any(not number(x,False) for x in n['query'].values()):
            raise ValueError('invalid_query')
        for k in ('started_at','ended_at'):
            if n[k] is not None:timestamp(n[k])
        if n['duration_ms'] is not None and (type(n['duration_ms']) not in (int,float) or not math.isfinite(n['duration_ms']) or n['duration_ms']<0):
            raise ValueError('invalid_duration')
    for name in ('rows','wire_rows'):
        rows=v[name]
        if rows is None:continue
        if not isinstance(rows,list) or len(rows)>21:raise ValueError('invalid_rows')
        for r in rows:
            if set(r)!=(ROW|({'price_limits'} if name=='rows' else set())):
                raise ValueError('invalid_row_fields')
            for key,ns in [('trade_id','trade'),('item_id','item')]:
                if not isinstance(r[key],str) or not re.fullmatch(ns+':[a-f0-9]{24}',r[key]):raise ValueError('invalid_identity')
            for key in ('definition_id','resource_id','asset_id','rating','rarity','starting_bid','current_bid','buy_now_price'):
                if not number(r[key]):raise ValueError('invalid_row_number')
            if r['expires']!=-1 and not number(r['expires']):raise ValueError('invalid_expiry')
            if r['untradeable'] is not None and type(r['untradeable']) is not bool:raise ValueError('invalid_untradeable')
            if r['trade_state'] not in (None,'active','expired','closed','inactive') or r['bid_state'] not in (None,'none','highest','outbid','buyNow','sold'):raise ValueError('invalid_state')
            if name=='rows' and r['price_limits'] is not None and (set(r['price_limits'])!={'minimum','maximum'} or any(not number(x) for x in r['price_limits'].values())):raise ValueError('invalid_caps')
    cap=v.get('cap_read')
    if cap is not None:
        if set(cap)!={'method','status','success','rows','wire'} or cap['method']!='services.Item.transfersDao.getItemMarketDataByDefId' or not number(cap['status']) or type(cap['success']) is not bool:raise ValueError('invalid_caps_read')
        for key in ('rows','wire'):
            if cap[key] is not None:
                if not isinstance(cap[key],list) or len(cap[key])>10:raise ValueError('invalid_caps_rows')
                for row in cap[key]:
                    if set(row)!={'definition_id','minimum','maximum'} or any(not number(x,False) for x in row.values()):raise ValueError('invalid_caps_row')
    return v


def assess(v):
    validate(v)
    net=[n for n in v['network'] if n['route']=='/ut/game/fc27/transfermarket']
    fresh=(v['success'] and v['status']==200 and v['error'] is None and v['rows'] is not None and v['persona'] is not None and v['persona']['accepted'] and len(net)==1 and
           net[0]['session_header_present'] and net[0]['status']==200 and net[0]['ended_at'] is not None and
           timestamp(net[0]['started_at'])<=timestamp(net[0]['ended_at'])<=timestamp(v['observed_at']))
    rows=v['rows'] or []
    wire=v['wire_rows']
    keys=('trade_id','item_id','definition_id','starting_bid','current_bid','buy_now_price')
    # FC27 wire itemData.resourceId is the full version. The entity exposes it
    # as definitionId; wire assetId is the base card and cannot substitute.
    independent=(wire is not None and len(rows)==len(wire) and
                 [tuple(r[k] for k in keys) for r in rows]==
                 [tuple((r['definition_id'] or r['resource_id']) if k=='definition_id' else r[k] for k in keys) for r in wire])
    p=v['params']; q=net[0]['query'] if len(net)==1 else {}
    filters=all(v['criteria'] and v['criteria'][native]==p[param] and q.get(query)==p[param]
                for param,native,query in [('max_bid','maxBid','macr'),('min_buy','minBuy','minb'),('max_buy','maxBuy','maxb'),('definition_id','defId','definitionId')]
                if param in p)
    semantics=all((type(r['definition_id']) is int and r['definition_id']>0 and r['starting_bid'] is not None and r['current_bid'] is not None and r['buy_now_price'] is not None and
                   ('max_bid' not in p or max(r['starting_bid'],r['current_bid'])<=p['max_bid']) and
                   ('min_buy' not in p or r['buy_now_price']>=p['min_buy']) and
                   ('max_buy' not in p or 0<r['buy_now_price']<=p['max_buy']) and
                   ('definition_id' not in p or r['definition_id']==p['definition_id'])) for r in rows)
    return {'fresh_authenticated_pc':bool(fresh),'independent_wire_entity_match':independent,'native_filters_match':filters,
            'observed_filter_semantics':semantics,'zero_results':len(rows)==0,
            'row_count':len(rows),'semantics_nonempty_verified':bool(fresh and independent and filters and semantics and rows)}


def availability(candidate, capture, *, now, max_age=30):
    """A search absence has bounded coverage: never infer sold/lost."""
    a=assess(capture)
    if not all(a[k] for k in ('fresh_authenticated_pc','independent_wire_entity_match','native_filters_match','observed_filter_semantics')):
        return 'UNKNOWN'
    at=timestamp(capture['network'][0]['started_at']);age=(now-at).total_seconds()
    if not 0<=age<=max_age:return 'STALE'
    matches=[r for r in capture['rows'] if r['trade_id']==candidate['trade_id']]
    if not matches:return 'ABSENT_IN_BOUNDED_SEARCH'
    if len(matches)!=1:return 'CONFLICTING_DUPLICATE'
    r=matches[0]
    if any(r[k]!=candidate[k] for k in ('item_id','definition_id')):return 'IDENTITY_CHANGED'
    if any(r[k]!=candidate[k] for k in ('starting_bid','current_bid','buy_now_price')):return 'PRICE_CHANGED'
    if r['trade_state']!='active' or r['expires'] is None or r['expires']-age<=0:return 'UNAVAILABLE'
    return 'AVAILABLE_READ_ONLY'
