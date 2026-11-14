"""Production protocol 2. Public labels are never EA authentication material.

Identity is comparable only within the same complete context (including the
identity namespace). A pseudonym cannot recover a native ID after key loss.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import math
import re

VERSION = 2
METADATA_PATH = '/ut/game/fc27/attributes/metadata'
ROUTES = {
    'search': ('GET', '/ut/game/fc27/transfermarket'),
    'watched': ('GET', '/ut/game/fc27/watchlist'),
    'balance': ('GET', '/ut/game/fc27/user/credits'),
    'unassigned': ('GET', '/ut/game/fc27/purchased/items'),
    'owned_item': ('GET', '/ut/game/fc27/item'),
    'transfer_list': ('GET', '/ut/game/fc27/tradepile'),
    'caps': ('GET', '/ut/game/fc27/marketdata/pricelimits'),
    'status': ('GET', '/ut/game/fc27/trade/status/lite'),
    'bid': ('PUT', '/ut/game/fc27/trade/:trade/bid'),
    'move': ('PUT', '/ut/game/fc27/item'),
    'list': ('POST', '/ut/game/fc27/auctionhouse'),
    'clear_sold': ('DELETE', '/ut/game/fc27/trade/sold'),
    'relist_all': ('PUT', '/ut/game/fc27/auctionhouse/relist'),
}
BULK = {'clear_sold', 'relist_all'}
MUTATIONS = {'bid', 'move', 'list'} | BULK
ERRORS = {'invalid_command', 'wrong_page', 'bridge_busy', 'persona_unverified',
          'service_unavailable', 'service_timeout', 'service_failed', 'schema_unrecognized',
          'unsafe_identity', 'stale_source', 'unauthenticated', 'ambiguous_network',
          'invalid_preconditions', 'internal_error', 'helpers_unavailable', 'helper_disagreement',
          'status_source_unsupported', 'known_identity_unavailable',
          'transfer_list_conflict', 'bulk_contract_changed'}  # old errors retained for sealed responses
LOCAL_OPERATIONS = {'price_helpers', 'status_support'}
CONTEXT = {'account', 'persona', 'game', 'platform', 'identity_namespace'}
FENCES = {'owner', 'epoch', 'host_epoch', 'worker_epoch', 'document'}
ITEM = {'item_id', 'definition_id', 'untradeable', 'last_sale_price'}
AUCTION = {'trade_id', 'item', 'starting_bid', 'current_bid', 'buy_now_price',
           'expires', 'trade_state', 'bid_state', 'native_is_won'}


def fields(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('invalid_fields')
    return value


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 2**53-1:
        raise ValueError('invalid_integer')
    return value


def token(value, prefix=None):
    if not isinstance(value, str) or not re.fullmatch(
            prefix + r':[a-f0-9]{24}' if prefix else r'[a-f0-9]{32}', value):
        raise ValueError('invalid_correlation')
    return value


def context(value):
    fields(value, CONTEXT)
    for k in ('account', 'persona', 'identity_namespace'):
        token(value[k])
    if value['game'] != 'fc27' or value['platform'] != 'pc':
        raise ValueError('unsupported_market')
    return value


def fences(value):
    fields(value, FENCES)
    for k in FENCES - {'epoch'}:
        token(value[k])
    integer(value['epoch'], 1)
    return value


def stamp(value):
    if not isinstance(value, str):
        raise ValueError('invalid_time')
    v = datetime.fromisoformat(value)
    if v.utcoffset() is None:
        raise ValueError('timezone_required')
    return v.astimezone(timezone.utc)


@dataclass(frozen=True)
class Search:
    purpose: str
    definition_id: int | None = None
    page: int = 1
    count: int = 21
    fresh: bool = True
    max_bid: int | None = None
    min_buy: int | None = None
    max_buy: int | None = None

    def __post_init__(self):
        if self.definition_id is not None or self.purpose != 'discovery':
            integer(self.definition_id, 1)
        if type(self.page) is not int or not 1 <= self.page <= (10 if self.purpose == 'discovery' else 1) or type(self.count) is not int or self.count != 21 or self.fresh is not True:
            raise ValueError('invalid_search_page')
        for v in (self.max_bid, self.min_buy, self.max_buy):
            if v is not None:
                integer(v)
        if self.max_buy is not None:
            integer(self.max_buy, 1)
        if self.purpose == 'discovery':
            if self.max_bid is None or self.min_buy is None or self.max_buy is not None:
                raise ValueError('invalid_discovery_filters')
        elif self.purpose == 'pricing':
            if self.max_bid is not None or self.min_buy is not None:
                raise ValueError('pricing_discovery_contamination')
        else:
            raise ValueError('invalid_search_purpose')

    @classmethod
    def discovery(cls, definition_id=None, *, page=1, max_bid=1000, min_buy=11000):
        return cls('discovery', definition_id, page=page, max_bid=max_bid, min_buy=min_buy)

    @classmethod
    def pricing(cls, definition_id, max_buy=None):
        return cls('pricing', definition_id, max_buy=max_buy)

    def params(self):
        return {k: v for k, v in asdict(self).items() if v is not None}


def command(c):
    fields(c, {'schema', 'id', 'operation', 'params', 'context', 'fences'})
    if type(c['schema']) is not int or c['schema'] != VERSION:
        raise ValueError('unsupported_schema')
    token(c['id']); context(c['context']); fences(c['fences'])
    p, op = c['params'], c['operation']
    if op not in ROUTES.keys() | LOCAL_OPERATIONS or type(p) is not dict:
        raise ValueError('unsupported_operation')
    if op == 'price_helpers':
        fields(p, {'version', 'probes'})
        if type(p['version']) is not int or p['version'] != 1 or type(p['probes']) is not list or len(p['probes']) > 32:
            raise ValueError('invalid_helper_request')
        for probe in p['probes']:
            fields(probe, {'direction', 'value'})
            if probe['direction'] not in {'above', 'below'}:
                raise ValueError('invalid_helper_direction')
            integer(probe['value'])
    elif op == 'search':
        try:
            q = Search(**p)
        except TypeError:
            raise ValueError('invalid_search') from None
        if q.params() != p:
            raise ValueError('noncanonical_search')
    elif op == 'caps':
        fields(p, {'definition_id'}); integer(p['definition_id'], 1)
    elif op in {'status','owned_item'}:
        fields(p, {'trade_id', 'item_id', 'definition_id'})
        token(p['trade_id'], 'trade'); token(p['item_id'], 'item'); integer(p['definition_id'], 1)
    elif op in BULK:
        fields(p, {'before_read_id', 'expected_item_ids', 'expected_inventory_ids',
                   'expected_sold_count', 'expected_expired_count'})
        token(p['before_read_id'])
        if c['id'] == p['before_read_id']:
            raise ValueError('independent_inventory_required')
        for k in ('expected_item_ids', 'expected_inventory_ids'):
            if type(p[k]) is not list or len(p[k]) > 100 or len(set(p[k])) != len(p[k]):
                raise ValueError('invalid_bulk_membership')
            for identity in p[k]: token(identity, 'item')
        for k in ('expected_sold_count', 'expected_expired_count'): integer(p[k])
        if not p['expected_item_ids'] or not set(p['expected_item_ids']) <= set(p['expected_inventory_ids']):
            raise ValueError('invalid_bulk_membership')
    elif op in {'move', 'list'}:
        fields(p, {'trade_id', 'item_id', 'definition_id', 'paid', 'owned_read_id',
                   'win_read_id', 'caps_read_id', 'starting_bid', 'buy_now_price', 'duration'})
        token(p['trade_id'], 'trade'); token(p['item_id'], 'item')
        for k in ('definition_id', 'paid', 'starting_bid', 'buy_now_price'):
            integer(p[k], 1)
        for k in ('owned_read_id', 'win_read_id', 'caps_read_id'):
            token(p[k])
        if type(p['duration']) is not int or p['duration'] != 3600 or p['starting_bid'] >= p['buy_now_price'] or c['id'] in {p['owned_read_id'], p['win_read_id'], p['caps_read_id']}:
            raise ValueError('invalid_listing_preconditions')
    elif op == 'bid':
        fields(p, {'trade_id', 'item_id', 'definition_id', 'amount', 'minimum', 'cap',
                   'deadline', 'status_read_id', 'balance_read_id'})
        token(p['trade_id'], 'trade'); token(p['item_id'], 'item')
        for k in ('definition_id', 'amount', 'minimum', 'cap'):
            integer(p[k], 1)
        for k in ('status_read_id', 'balance_read_id'):
            token(p[k])
        stamp(p['deadline'])
        if p['minimum'] != p['amount'] or p['amount'] > p['cap'] or len({c['id'], p['status_read_id'], p['balance_read_id']}) != 3:
            raise ValueError('invalid_bid_preconditions')
    else:
        fields(p, set())
    return c


def empty_result(error='invalid_command'):
    return dict(success=False, error=error, status=None, credits=None, items=None,
                auctions=None, caps=None, cache_invalidated=False, network=[])


def item(v, *, lite=False):
    fields(v, ITEM); token(v['item_id'], 'item')
    if not (lite and (v['definition_id'] is None or type(v['definition_id']) is int and v['definition_id'] == 0)):
        integer(v['definition_id'], 1)
    if v['untradeable'] is not None and type(v['untradeable']) is not bool:
        raise ValueError('invalid_item')
    if v['last_sale_price'] is not None:
        integer(v['last_sale_price'])


def auction(v):
    """Safe projection shape, independent of market/comparable validity."""
    fields(v, AUCTION); item(v['item']); token(v['trade_id'], 'trade')
    for k in ('starting_bid', 'current_bid', 'buy_now_price', 'expires'):
        integer(v[k], -1 if k == 'expires' else 0)
    if (v['trade_state'] not in {'active', 'closed', 'expired', 'inactive', None} or
            v['bid_state'] not in {'none', 'highest', 'outbid', 'buyNow', 'sold', None} or
            v['native_is_won'] is not None and type(v['native_is_won']) is not bool):
        raise ValueError('invalid_auction')


def timing(value):
    """Legacy captures may lack the split; missing timings mean unknown."""
    if type(value) is not dict or set(value) not in (
            {'native_service_ms'}, {'native_service_ms', 'ea_rtt_ms', 'native_helper_ms'}):
        raise ValueError('invalid_timing')
    for ms in value.values():
        if type(ms) not in (int, float) or not math.isfinite(ms) or ms < 0:
            raise ValueError('invalid_timing')
    if value.get('ea_rtt_ms', 0)+value.get('native_helper_ms', 0) > value['native_service_ms']:
        raise ValueError('invalid_timing')
    return value


def parse_response(v, c, *, now=None, source='native', max_age=30, pricing_rows=False):
    """Validate actual routes; no legacy route substitution or raw payload retention."""
    command(c)
    if pricing_rows and (c['operation'] != 'search' or c['params']['purpose'] != 'pricing'):
        raise ValueError('pricing_search_required')
    fields(v, {'schema', 'command_id', 'operation', 'context', 'fences', 'result', 'freshness', 'coverage', 'timing'})
    context(v['context']); fences(v['fences'])
    if type(v['schema']) is not int or v['schema'] != VERSION or v['command_id'] != c['id'] or v['operation'] != c['operation'] or v['context'] != c['context'] or v['fences'] != c['fences']:
        raise ValueError('response_correlation_mismatch')
    r, op = v['result'], c['operation']
    if op == 'price_helpers':
        return parse_helpers(v, c, now=now, source=source, max_age=max_age)
    if op == 'status_support':
        return parse_status_support(v, c, now=now, source=source, max_age=max_age)
    fields(r, empty_result())
    if type(r['success']) is not bool or r['error'] not in ERRORS | {None} or r['success'] != (r['error'] is None):
        raise ValueError('invalid_result')
    if r['status'] is not None and not (type(r['status']) is int and 100 <= r['status'] <= 599):
        raise ValueError('invalid_status')
    if type(r['cache_invalidated']) is not bool:
        raise ValueError('invalid_cache_evidence')
    if r['credits'] is not None:
        integer(r['credits'])
    for key in ('items', 'auctions'):
        rows = r[key]
        if rows is None:
            continue
        if type(rows) is not list or len(rows) > (21 if op == 'search' else 100):
            raise ValueError('invalid_rows')
        # Pricing excludes individual malformed/mismatched/duplicate offers and
        # records why. Envelope, wire, freshness and authentication stay strict.
        # Other reads (and the default parser) retain strict row validation.
        if pricing_rows and key == 'auctions':
            continue
        identities = set()
        for row in rows:
            i = row if key == 'items' else row.get('item') if type(row) is dict else None
            item(i, lite=op == 'status')
            identity = i['item_id']
            if key == 'auctions':
                fields(row, AUCTION); token(row['trade_id'], 'trade')
                identity = i['item_id'] if op == 'transfer_list' else row['trade_id']
                for k in ('starting_bid', 'current_bid', 'buy_now_price', 'expires'):
                    integer(row[k], -1 if k == 'expires' else 0)
                if row['trade_state'] not in {'active', 'closed', 'expired', 'inactive', None} or row['bid_state'] not in {'none', 'highest', 'outbid', 'buyNow', 'sold', None} or row['native_is_won'] is not None and type(row['native_is_won']) is not bool:
                    raise ValueError('invalid_auction')
                if op == 'status' and (row['trade_state'] is None or row['bid_state'] is None):
                    raise ValueError('invalid_status_state')
            if identity in identities:
                raise ValueError('duplicate_identity')
            identities.add(identity)
            if op == 'search' and 'definition_id' in c['params'] and i['definition_id'] != c['params']['definition_id']:
                raise ValueError('wrong_exact_definition')
            if op == 'status' and (row['trade_id'] != c['params']['trade_id'] or
                    i['item_id'] != c['params']['item_id'] or
                    i['definition_id'] not in (None, 0, c['params']['definition_id'])):
                raise ValueError('wrong_status_identity')
        if op == 'status' and len(rows) > 1:
            raise ValueError('ambiguous_status_identity')
    if r['caps'] is not None:
        fields(r['caps'], {'definition_id', 'minimum', 'maximum'})
        for k in r['caps']:
            integer(r['caps'][k], 1)
        if op != 'caps' or r['caps']['definition_id'] != c['params']['definition_id'] or r['caps']['minimum'] > r['caps']['maximum']:
            raise ValueError('wrong_caps')
    net = r['network']
    if type(net) is not list or len(net) > 30:
        raise ValueError('invalid_network')
    for n in net:
        fields(n, {'host', 'method', 'path', 'query', 'status', 'session_header_present'} |
               ({'body_empty'} if op in BULK else set()))
        if not isinstance(n['host'], str) or not re.fullmatch(r'utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com', n['host']) or \
                n['method'] not in {'GET', 'PUT', 'POST', 'DELETE', 'OTHER'} or n['path'] not in {p for _, p in ROUTES.values()} | {METADATA_PATH, '/unexpected'}:
            raise ValueError('wrong_native_route')
        if op in BULK and (n['body_empty'] is not True or n['query'] != {}):
            raise ValueError('bulk_wire_contract_changed')
        if (n['status'] is not None and (type(n['status']) is not int or not 100 <= n['status'] <= 599)) or type(n['session_header_present']) is not bool:
            raise ValueError('invalid_network_status')
        allowed = {'start', 'num', 'definitionId', 'defId', 'macr', 'minb', 'maxb', 'trade_id', 'item_id', 'defIds'}
        if type(n['query']) is not dict or set(n['query']) - allowed:
            raise ValueError('invalid_query')
        for k, x in n['query'].items():
            if k == 'trade_id':token(x, 'trade')
            elif k == 'item_id':token(x, 'item')
            elif k == 'defIds':
                if type(x) is not list or not 1 <= len(x) <= 21:raise ValueError('invalid_query')
                for definition in x:integer(definition, 1)
            else:integer(x)
    f = fields(v['freshness'], {'observed_at', 'network_at', 'request_count', 'read_id', 'source'})
    observed = stamp(f['observed_at'])
    network_at = stamp(f['network_at']) if f['network_at'] is not None else None
    integer(f['request_count'])
    if f['read_id'] != c['id'] or f['source'] != source or source not in {'native', 'fixture'} or f['request_count'] != len(net):
        raise ValueError('invalid_request_source')
    target = [n for n in net if (n['method'], n['path']) == ROUTES[op]]
    auxiliary = [n for n in net if op == 'search' and (n['method'], n['path']) == ('GET', METADATA_PATH)]
    if op == 'clear_sold':
        auxiliary = [n for n in net if (n['method'], n['path']) == ROUTES['transfer_list']]
    supported = len(target) == 1 and len(auxiliary) <= (2 if op == 'clear_sold' else 1) and len(target)+len(auxiliary) == len(net)
    authenticated = supported and all(n['session_header_present'] and type(n['status']) is int and
        200 <= n['status'] < 300 and n['host'] == target[0]['host'] for n in net)
    if op in BULK and r['success'] and any(n['status'] != 200 for n in net):
        raise ValueError('bulk_wire_contract_changed')
    if network_at is not None and (not authenticated or network_at > observed):
        raise ValueError('unsupported_freshness')
    coverage = v['coverage']
    extended = op == 'transfer_list' and type(coverage) is dict and 'transfer_list' in coverage
    fields(coverage, ({'complete', 'has_more', 'transfer_list'} if extended else {'complete', 'has_more'}) |
           ({'bulk'} if op == 'transfer_list' and 'bulk' in coverage else set()))
    if 'bulk' in coverage:
        proofs = coverage['bulk']
        if type(proofs) is not list or len(proofs) != len(r['auctions'] or []):
            raise ValueError('invalid_bulk_inventory')
        for proof, row in zip(proofs, r['auctions'] or []):
            fields(proof, {'item_id', 'trade_owner', 'sold', 'expired', 'active'})
            if proof['item_id'] != row['item']['item_id'] or any(type(proof[k]) is not bool for k in ('trade_owner', 'sold', 'expired', 'active')):
                raise ValueError('invalid_bulk_inventory')
    if type(coverage['complete']) is not bool or coverage['has_more'] is not None and type(coverage['has_more']) is not bool:
        raise ValueError('unsupported_coverage')
    if extended:
        proof = fields(coverage['transfer_list'], {'reason', 'wire_count', 'callback_count',
            'repository_count', 'repository_end_of_list'})
        if proof['reason'] not in {'TRANSFER_LIST_COMPLETE', 'TRANSFER_LIST_UNKNOWN',
                'TRANSFER_LIST_TRUNCATED', 'TRANSFER_LIST_CONFLICT'} or type(proof['repository_end_of_list']) is not bool:
            raise ValueError('invalid_inventory_coverage')
        for key in ('wire_count', 'callback_count', 'repository_count'):
            if proof[key] is not None: integer(proof[key])
        if proof['callback_count'] != len(r['auctions'] or []):
            raise ValueError('inventory_count_conflict')
        if coverage['complete'] != (proof['reason'] == 'TRANSFER_LIST_COMPLETE'):
            raise ValueError('inventory_count_conflict')
        if coverage['complete'] and (not r['success'] or coverage['has_more'] is not False or
                proof['repository_end_of_list'] is not True or
                not proof['wire_count'] == proof['callback_count'] == proof['repository_count']):
            raise ValueError('inventory_count_conflict')
    elif coverage['complete'] is not False:
        raise ValueError('unsupported_coverage')
    timing(v['timing'])
    if r['success']:
        if not supported:raise ValueError('wrong_native_route')
        current = now or datetime.now(timezone.utc)
        if not authenticated or network_at is None or not 0 <= (current-network_at).total_seconds() <= max_age or not 0 <= (observed-network_at).total_seconds() <= max_age:
            raise ValueError('stale_or_unauthenticated_source')
        if r['status'] != target[0]['status']:
            raise ValueError('native_status_mismatch')
        expected = {'search': 'auctions', 'watched': 'auctions', 'transfer_list': 'auctions',
                    'unassigned': 'items', 'owned_item': 'items', 'balance': 'credits', 'caps': 'caps', 'status': 'auctions'}.get(op)
        for key in ('auctions', 'items', 'credits', 'caps'):
            if (r[key] is not None) != (key == expected):
                raise ValueError('operation_payload_mismatch')
        if op in {'search', 'watched', 'unassigned', 'transfer_list'} and not r['cache_invalidated']:
            raise ValueError('cache_only_source')
        if op == 'search':
            q, p = target[0]['query'], c['params']
            # The native client advances 20 rows; the 21st is lookahead.
            expected_query = {'start': (p['page']-1)*20, 'num': 21}
            for k, wire in [('max_bid', 'macr'), ('min_buy', 'minb'), ('max_buy', 'maxb')]:
                if k in p:
                    expected_query[wire] = p[k]
            if 'definition_id' in p:
                if len(set(q) & {'definitionId', 'defId'}) != 1:
                    raise ValueError('missing_exact_wire_definition')
                expected_query['definitionId' if 'definitionId' in q else 'defId'] = p['definition_id']
            if q != expected_query:
                raise ValueError('wire_criteria_mismatch')
            definitions = {a['item']['definition_id'] for a in r['auctions'] if type(a) is dict and
                type(a.get('item')) is dict and type(a['item'].get('definition_id')) is int}
            if any(set(n['query']) != {'defIds'} or not set(n['query']['defIds']) <= definitions for n in auxiliary):
                raise ValueError('wire_metadata_identity_mismatch')
        if op == 'caps' and target[0]['query'] != {'defId': c['params']['definition_id']}:
            raise ValueError('wire_caps_identity_mismatch')
        if op in {'watched', 'unassigned', 'transfer_list', 'balance'} and target[0]['query'] != {}:
            raise ValueError('unexpected_read_query')
        if op == 'status' and target[0]['query'] != {'trade_id': c['params']['trade_id']}:
            raise ValueError('wire_status_identity_mismatch')
        if op == 'owned_item':
            if target[0]['query']!={'item_id':c['params']['item_id']} or len(r['items'])>1 or any(
                i['item_id']!=c['params']['item_id'] or i['definition_id']!=c['params']['definition_id'] for i in r['items']):
                raise ValueError('wire_owned_identity_mismatch')
    if pricing_rows and r['auctions'] is not None:
        # Preserve cardinality/exclusion evidence without retaining unknown keys,
        # arbitrary strings or other unsafe data from a malformed native row.
        from copy import deepcopy
        v = deepcopy(v)
        for index, row in enumerate(v['result']['auctions']):
            try:
                auction(row)
            except (ValueError, TypeError, KeyError):
                v['result']['auctions'][index] = None
    return v


def parse_status_support(v, c, *, now=None, source='native', max_age=30):
    """Local function availability only. Never a market/authentication claim."""
    r = fields(v['result'], {'success', 'error', 'function_available', 'retained_count', 'network'})
    if type(r['success']) is not bool or r['error'] not in ERRORS | {None} or r['success'] != (r['error'] is None):
        raise ValueError('invalid_result')
    if type(r['function_available']) is not bool:
        raise ValueError('invalid_function_availability')
    integer(r['retained_count'])
    f = fields(v['freshness'], {'observed_at', 'network_at', 'request_count', 'read_id', 'source'})
    if r['network'] != [] or f['network_at'] is not None or type(f['request_count']) is not int or f['request_count'] != 0 or f['read_id'] != c['id'] or f['source'] != source or source not in {'native', 'fixture'}:
        raise ValueError('invalid_local_provenance')
    age = ((now or datetime.now(timezone.utc)) - stamp(f['observed_at'])).total_seconds()
    if not 0 <= age <= max_age:
        raise ValueError('stale_local_source')
    if fields(v['coverage'], {'complete', 'has_more'}) != {'complete': False, 'has_more': None}:
        raise ValueError('unsupported_coverage')
    timing(v['timing'])
    return v


def parse_helpers(v, c, *, now, source, max_age):
    """Local loaded-client evidence has no network authentication claim."""
    r = fields(v['result'], {'success', 'error', 'version', 'above_available', 'below_available', 'probes', 'network'})
    if type(r['success']) is not bool or r['error'] not in ERRORS | {'helpers_unavailable', 'helper_disagreement', None} or r['success'] != (r['error'] is None):
        raise ValueError('invalid_helper_result')
    if type(r['version']) is not int or r['version'] != 1 or any(type(r[k]) is not bool for k in ('above_available', 'below_available')) or r['network'] != []:
        raise ValueError('invalid_helper_evidence')
    f = fields(v['freshness'], {'observed_at', 'network_at', 'request_count', 'read_id', 'source'})
    at = stamp(f['observed_at'])
    if f['network_at'] is not None or type(f['request_count']) is not int or f['request_count'] != 0 or f['source'] != source or source not in {'native', 'fixture'} or f['read_id'] != c['id']:
        raise ValueError('invalid_local_source')
    if not 0 <= ((now or datetime.now(timezone.utc))-at).total_seconds() <= max_age:
        raise ValueError('stale_local_source')
    fields(v['coverage'], {'complete', 'has_more'})
    if v['coverage']['complete'] is not False or v['coverage']['has_more'] is not None:
        raise ValueError('invalid_local_coverage')
    timing(v['timing'])
    if type(r['probes']) is not list or len(r['probes']) > 32:
        raise ValueError('invalid_helper_probes')
    if r['success']:
        if not r['above_available'] or not r['below_available'] or len(r['probes']) != len(c['params']['probes']):
            raise ValueError('missing_helpers')
        for row, p in zip(r['probes'], c['params']['probes']):
            fields(row, {'direction', 'value', 'price'})
            integer(row['value'])
            if {k: row[k] for k in p} != p:
                raise ValueError('helper_probe_mismatch')
            integer(row['price'])
            if p['direction'] == 'above' and row['price'] < p['value'] or p['direction'] == 'below' and row['price'] > p['value']:
                raise ValueError('helper_disagreement')
    elif r['probes']:
        raise ValueError('partial_helper_result')
    return v


def correlate_readbacks(write, status, balance, *, status_command, balance_command, after, now=None):
    """Independent reads can correlate an ACK; they never alone prove paid ownership."""
    if write['operation'] != 'bid':
        raise ValueError('bid_required')
    command(write)
    for value, read_command in ((status, status_command), (balance, balance_command)):
        parse_response(value, read_command, now=now)
        if stamp(value['freshness']['network_at']) < after:
            raise ValueError('readback_precedes_dispatch')
    for value, ops in ((status, {'watched', 'search'}), (balance, {'balance'})):
        if value['context'] != write['context'] or value['fences'] != write['fences'] or value['operation'] not in ops or not value['result']['success']:
            raise ValueError('readback_scope_mismatch')
        f = value['freshness']
        if f['source'] != 'native' or f['network_at'] is None or not 0 <= ((now or datetime.now(timezone.utc))-stamp(f['network_at'])).total_seconds() <= 30:
            raise ValueError('readback_stale')
    ids = {write['id'], write['params']['status_read_id'], write['params']['balance_read_id'],
           status['command_id'], balance['command_id']}
    if len(ids) != 5 or any(v['freshness']['read_id'] != v['command_id'] for v in (status, balance)):
        raise ValueError('independent_readbacks_required')
    p = write['params']
    rows = [a for a in status['result']['auctions'] if a['trade_id'] == p['trade_id'] and a['item']['item_id'] == p['item_id'] and a['item']['definition_id'] == p['definition_id']]
    if len(rows) != 1:
        raise ValueError('readback_identity_unknown')
    return {'state': 'PENDING' if rows[0]['trade_state'] == 'closed' and rows[0]['bid_state'] == 'highest' else 'OBSERVED',
            'status_read_id': status['command_id'], 'balance_read_id': balance['command_id']}
