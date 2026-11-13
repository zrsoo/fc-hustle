"""Positive schema and conservative evidence assessment; never calls EA."""
import math
import re
from datetime import datetime
from experiments.market_discovery_followup_v1.server import persona_projection

FIELDS = {'schema','operation','observed_at','persona','method','status','success','error','network','auctions','has_more','sources','duration_ms','network_at','request_count'}
NET = {'method','route','session_header_present','status','duration_ms','payload_bytes','started_at','ended_at','pagination'}
AUCTION = {'trade_id','item_id','definition_id','current_bid','starting_bid','buy_now_price','expires','bid_state','trade_state'}


def stamp(v):
    if not isinstance(v, str) or len(v)>40 or datetime.fromisoformat(v).tzinfo is None:
        raise ValueError('timestamp')


def number(v, nullable=False):
    if nullable and v is None:
        return
    if type(v) not in (int,float) or not math.isfinite(v) or v<0:
        raise ValueError('number')


def validate_projection(v):
    if not isinstance(v,dict) or v.get('schema') not in (1,2) or set(v)!=(FIELDS if v['schema']==1 else FIELDS|{'account','cache_invalidated'}) or v['operation'] not in ('inspect','watched'):
        raise ValueError('schema')
    stamp(v['observed_at'])
    if v['schema']==2:
        if type(v['cache_invalidated']) is not bool:
            raise ValueError('cache_flag')
        a=v['account']
        if a is not None:
            if set(a)!={'platform_split','inbox_capacity','server_setting_capacity','cached_count_before','cached_count_after','inbox_dirty_before'} or a['platform_split'] is not None and type(a['platform_split']) is not bool or type(a['inbox_dirty_before']) is not bool:
                raise ValueError('account_schema')
            for k in ('inbox_capacity','server_setting_capacity','cached_count_before','cached_count_after'):
                number(a[k],True)
    if v['persona'] is not None:
        persona_projection(v['persona'])
    if type(v['success']) is not bool or v['error'] not in (None,'invalid_command','wrong_page','bridge_busy','unsafe_integer','schema_unrecognized','service_timeout','service_unavailable','persona_unverified','experiment_pacing','internal_error','service_failed'):
        raise ValueError('result')
    if v['method'] not in (None,'services.Item.requestWatchedItems()') or v['has_more'] not in (None,True,False):
        raise ValueError('method')
    number(v['status'],True);number(v['duration_ms']);number(v['request_count'])
    if v['network_at'] is not None:
        stamp(v['network_at'])
    if not isinstance(v['network'],list) or len(v['network'])>30 or v['request_count']!=len(v['network']):
        raise ValueError('network_count')
    for n in v['network']:
        if set(n)!=NET or n['method'] not in ('GET','POST','PUT','DELETE','OTHER') or not re.fullmatch(r'/ut/game/fc27/(watchlist|watchlist/items|pilesize|tradepile|purchased/items|user/currencies|trade/status|:unrecognized)',n['route']):
            raise ValueError('network_schema')
        if type(n['session_header_present']) is not bool or set(n['pagination'])!={'start','count'}:
            raise ValueError('network_fields')
        for k in ('status','duration_ms','payload_bytes'):
            number(n[k],True)
        for k in ('started_at','ended_at'):
            if n[k] is not None:
                stamp(n[k])
        for x in n['pagination'].values():
            number(x,True)
    if v['auctions'] is not None:
        if not isinstance(v['auctions'],list) or len(v['auctions'])>200:
            raise ValueError('rows')
        for a in v['auctions']:
            if set(a)!=AUCTION or not re.fullmatch('trade:[a-f0-9]{24}',a['trade_id']) or not re.fullmatch('item:[a-f0-9]{24}',a['item_id']):
                raise ValueError('identity')
            for k in ('definition_id','current_bid','starting_bid','buy_now_price'):
                number(a[k],True)
            if a['expires']!=-1:
                number(a['expires'],True)
            if a['bid_state'] not in (None,'none','highest','outbid','buyNow','sold') or a['trade_state'] not in (None,'active','closed','expired','inactive'):
                raise ValueError('state')
    if v['sources'] is not None:
        if not isinstance(v['sources'],list) or len(v['sources'])>100:
            raise ValueError('sources')
        for s in v['sources']:
            if set(s)!={'owner','name','length','sha256','source'} or s['owner'] not in ('services.Item','services.Item.itemDao','repositories.Item') or not re.fullmatch('[A-Za-z][A-Za-z0-9]{0,70}',s['name']) or not re.search('watch|pile|tradestatus|setDirty|isDirty',s['name'],re.I) or not re.fullmatch('[a-f0-9]{64}',s['sha256']):
                raise ValueError('source_schema')
            number(s['length'])
            if s['source'] is not None and (not isinstance(s['source'],str) or len(s['source'])>12000):
                raise ValueError('source_size')
    return v


def assess(v, visible_count=None):
    validate_projection(v)
    net=[n for n in v['network'] if n['method']=='GET' and n['route']=='/ut/game/fc27/watchlist' and n['session_header_present'] and n['status']==200 and n['ended_at']]
    fresh=bool(v['success'] and v['status']==200 and v['persona'] and v['persona']['accepted'] and v['method']=='services.Item.requestWatchedItems()' and net and v['network_at']==net[-1]['ended_at'] and v['auctions'] is not None)
    count=len(v['auctions']) if v['auctions'] is not None else None
    account=v.get('account') or {}
    cap=account.get('inbox_capacity')
    cap=cap if cap and cap==account.get('server_setting_capacity') else None
    empty=fresh and count==0 and visible_count==0
    if v['schema']==2:
        empty=empty and account.get('cached_count_after')==0 and account.get('platform_split') is False
    return {'fresh':fresh,'rows':count,'empty_verified':empty,
            'visible_count_matches':fresh and visible_count==count,
            'complete_nonempty_watchlist_proved':False,'account_capacity':cap,
            'missing_state':'UNKNOWN','queue_configuration':50}
