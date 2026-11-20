"""Strict controller dialect. Legacy contracts remain schema 2."""
from copy import deepcopy
from datetime import datetime, timezone
from fc_access.production_v1.contracts import fields, context, fences, token, integer, stamp

VERSION = 4
READS = {'watched', 'balance', 'status_batch'}
SHARED_READS = {'search', 'transfer_list', 'watched', 'caps', 'price_helpers', 'owned_item', 'unassigned'}
MAINTENANCE = {'move', 'list', 'clear_sold', 'relist_all', 'clear_lost'}


def delivery_command(value):
    """Shared native mechanisms; maintenance additionally needs store work intent.

    Legacy schema 2 bidding never crosses this controller authority boundary.
    """
    if value.get('schema') == 2:
        from fc_access.production_v1.contracts import command as shared
        shared(value)
        if value['operation'] not in SHARED_READS | MAINTENANCE: raise ValueError('shared_read_only')
        return deepcopy(value)
    return command(value)


def delivery_response(value, c, *, now):
    if c['schema'] == 2:
        from fc_access.production_v1.contracts import parse_response as shared
        return shared(value,c,now=now,source=value['freshness']['source'],
                      pricing_rows=c['operation']=='search' and c['params']['purpose']=='pricing')
    return parse_response(value,c,now=now)


def target(value):
    fields(value, {'trade_id', 'item_id', 'definition_id'})
    token(value['trade_id'], 'trade'); token(value['item_id'], 'item')
    integer(value['definition_id'], 1)
    return value


def command(value):
    fields(value, {'schema', 'id', 'operation', 'params', 'context', 'fences'})
    if type(value['schema']) is not int or value['schema'] != VERSION:
        raise ValueError('wrong_schema')
    token(value['id']); context(value['context']); fences(value['fences'])
    p, op = value['params'], value['operation']
    if op in {'watched', 'balance'}:
        fields(p, set())
    elif op in {'status_batch','clear_lost'}:
        fields(p, {'targets','before_read_id'} if op=='clear_lost' else {'targets'})
        if op=='clear_lost':token(p['before_read_id'])
        rows = p['targets']
        if not isinstance(rows, list) or not 1 <= len(rows) <= (100 if op=='clear_lost' else 10):
            raise ValueError('invalid_target_count')
        for row in rows: target(row)
        if any(len({r[k] for r in rows}) != len(rows) for k in ('trade_id', 'item_id')):
            raise ValueError('duplicate_target')
    elif op == 'bid':
        fields(p, {'target', 'amount', 'minimum', 'cap', 'deadline', 'status_read_id', 'batch_id', 'decision_id'})
        target(p['target'])
        for k in ('amount', 'minimum', 'cap'): integer(p[k], 1)
        if p['amount'] < p['minimum'] or p['amount'] > p['cap']:
            raise ValueError('invalid_bid')
        for k in ('status_read_id', 'batch_id', 'decision_id'): token(p[k])
        stamp(p['deadline'])
    else:
        raise ValueError('invalid_operation')
    return deepcopy(value)


def parse_response(value, c, *, now=None):
    command(c)
    fields(value, {'schema','command_id','operation','context','fences','success','error','status','network',
                   'background','auctions','links','missing','credits','receipt','observed_at','network_at','designated_account_verified'})
    if value['schema'] != VERSION or type(value['schema']) is not int or value['command_id'] != c['id'] or value['operation'] != c['operation'] or any(value[k] != c[k] for k in ('context','fences')):
        raise ValueError('scope_mismatch')
    now = now or datetime.now(timezone.utc)
    age = (now-stamp(value['observed_at'])).total_seconds()
    from fc_access.production_v1.contracts import fresh
    if not fresh(age, 30) or type(value['success']) is not bool:
        raise ValueError('stale_response')
    if not isinstance(value['background'], list) or len(value['background']) > 32 or any(r != {'event':'UNOWNED_SEND'} for r in value['background']):
        raise ValueError('unsafe_diagnostics')
    op = c['operation']
    path = {'status_batch':'trade/status/lite','watched':'watchlist','balance':'user/credits','bid':'trade/:trade/bid','clear_lost':'watchlist'}[op]
    method='PUT' if op=='bid' else 'DELETE' if op=='clear_lost' else 'GET'
    expected = c['params']['targets'] if op in {'status_batch','clear_lost'} else [c['params']['target']] if op == 'bid' else []
    network = value['network']
    if not isinstance(network,list) or len(network)>1 or type(value['designated_account_verified']) is not bool:
        raise ValueError('invalid_network_schema')
    import re
    for n in network:
        fields(n, {'method','path','host','targets','status','session_header_present'})
        if n['method'] != method or n['path'] != '/ut/game/fc27/'+path or n['targets'] != expected or type(n['session_header_present']) is not bool or not isinstance(n['host'],str) or not re.fullmatch(r'utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com',n['host']):
            raise ValueError('invalid_owned_binding')
        if n['status'] is not None:integer(n['status'],1)
    if value['status'] is not None:integer(value['status'],1)
    for k in ('auctions','links','missing'):
        if not isinstance(value[k],list) or len(value[k])>100:raise ValueError('invalid_result_schema')
    if value['network_at'] is not None:stamp(value['network_at'])
    if value['credits'] is not None:integer(value['credits'])
    if op!='balance' and value['credits'] is not None or op!='bid' and value['receipt'] is not None:
        raise ValueError('invalid_operation_payload')
    if op=='clear_lost' and (value['auctions'] or value['links'] or value['missing']):raise ValueError('invalid_operation_payload')
    for row in value['auctions']:projection(row,lite=op=='status_batch')
    for t in value['missing']:target(t)
    for link in value['links']:
        fields(link, {'target','full_read_id','full_observed_at','status_read_id','version_observed','current_dto_matches'})
        target(link['target']);token(link['full_read_id']);token(link['status_read_id']);stamp(link['full_observed_at'])
        if any(type(link[k]) is not bool for k in ('version_observed','current_dto_matches')):
            raise ValueError('invalid_version_link_schema')
    errors = {'invalid_command','bridge_busy','known_identity_unavailable','invalid_preconditions','service_unavailable',
              'service_timeout','interrupted','ambiguous_network','unauthenticated','schema_unrecognized','service_failed',
              'persona_unverified','bid_unconfirmed','bid_rejected','internal_error'}
    if not value['success']:
        if value['error'] not in errors:
            raise ValueError('invalid_error')
        if c['operation']=='bid' and value['receipt'] is not None:
            validate_receipt(value,c)
        # A failed observation never supplies row/version authority.
        return deepcopy(value)
    if value['error'] is not None:
        raise ValueError('contradictory_result')
    if value['designated_account_verified'] is not True:
        raise ValueError('designated_account_required')
    at = stamp(value['network_at'])
    if not fresh((now-at).total_seconds(), 30) or at > stamp(value['observed_at']):
        raise ValueError('stale_network')
    if not isinstance(network, list) or len(network) != 1:
        raise ValueError('owned_request_required')
    n = network[0]
    fields(n, {'method','path','host','targets','status','session_header_present'})
    if n['method'] != method or n['path'] != '/ut/game/fc27/'+path or n['targets'] != expected or n['session_header_present'] is not True or type(n['status']) is not int or n['status'] != 200 or value['status'] != 200 or not re.fullmatch(r'utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com', n['host']):
        raise ValueError('unauthenticated_or_unbound')
    if op == 'balance': integer(value['credits'])
    rows = value['auctions']
    if not isinstance(rows, list) or len(rows) > (10 if op == 'status_batch' else 100):
        raise ValueError('invalid_rows')
    if any(len({r[k] if k == 'trade_id' else r['item']['item_id'] for r in rows}) != len(rows) for k in ('trade_id','item_id')):
        raise ValueError('duplicate_result')
    if op == 'status_batch':
        for row in rows:
            matches = [t for t in expected if t['trade_id'] == row['trade_id'] and t['item_id'] == row['item']['item_id']]
            if len(matches) != 1 or row['item']['definition_id'] not in (None, 0, matches[0]['definition_id']):
                raise ValueError('unexpected_identity')
        missing = [t for t in expected if not any(r['trade_id'] == t['trade_id'] for r in rows)]
        if value['missing'] != missing or len(value['links']) != len(rows):
            raise ValueError('invalid_coverage')
        for row, link in zip(rows, value['links']):
            fields(link, {'target','full_read_id','full_observed_at','status_read_id','version_observed','current_dto_matches'})
            target(link['target']); token(link['full_read_id']); stamp(link['full_observed_at'])
            if link['target'] not in expected or link['target']['trade_id'] != row['trade_id'] or link['target']['item_id'] != row['item']['item_id'] or link['status_read_id'] != c['id'] or link['current_dto_matches'] is not True or type(link['version_observed']) is not bool or link['version_observed'] != (row['item']['definition_id'] not in (None,0)):
                raise ValueError('invalid_version_link')
    elif value['links'] or value['missing']:
        raise ValueError('invalid_coverage')
    if op == 'bid':
        validate_receipt(value,c)
        if value['receipt']['verdict'] != 'ACCEPTED': raise ValueError('unconfirmed_receipt')
    return deepcopy(value)


def validate_receipt(value,c):
    from fc_access.production_v1.bid_receipt import validate
    result = dict(success=value['success'],error=value['error'],status=value['status'],
                  network=[{**n,'query':{}} for n in value['network']])
    return validate(value['receipt'],{'params':{**c['params'],**c['params']['target']}},result)


def projection(row, *, lite=False):
    """Sanitized shape applies to failed diagnostics as well as observations."""
    fields(row, {'trade_id','item','starting_bid','current_bid','buy_now_price','expires','trade_state','bid_state','native_is_won'})
    token(row['trade_id'],'trade')
    fields(row['item'], {'item_id','definition_id','untradeable','last_sale_price'})
    token(row['item']['item_id'],'item')
    d=row['item']['definition_id']
    if not (lite and (d is None or type(d) is int and d==0)):integer(d,1)
    if row['item']['last_sale_price'] is not None:integer(row['item']['last_sale_price'])
    if row['item']['untradeable'] is not None and type(row['item']['untradeable']) is not bool:raise ValueError('invalid_item')
    for k in ('starting_bid','current_bid','buy_now_price'):integer(row[k])
    integer(row['expires'],-1)
    if row['trade_state'] not in {'active','closed','expired','inactive'} or row['bid_state'] not in {'none','highest','outbid','buyNow','sold'} or row['native_is_won'] is not None and type(row['native_is_won']) is not bool:
        raise ValueError('invalid_state')
