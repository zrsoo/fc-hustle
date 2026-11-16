"""Safe bid evidence, independent of the service's input-derived itemIds.

Archive envelopes may lack this extension. Every live bid delivery requires it.
An accepted receipt still requires independent fresh account readbacks.
"""
from .contracts import AUCTION, auction, fields, integer, token

REJECTIONS = {'STATE_INVALID', 'NO_TRADE_EXISTS', 'NOT_ENOUGH_CREDIT', 'INVALID_OWNER', 'CARD_IN_TRADE'}
REASONS = {'MISSING_NATIVE_RECEIPT', 'MATCHING_NATIVE_PARTICIPATION',
           'EXPLICIT_NATIVE_REJECTION', 'STALE_NATIVE_ITEM', 'EMPTY_NATIVE_ITEMS', 'NO_ACCOUNT_PARTICIPATION', 'ENVELOPE_VALIDATION_FAILED'}
KEYS = {'schema', 'verdict', 'reason', 'wire_trade_id', 'wire_amount', 'wire_identity_matches',
        'wire_amount_matches', 'wire_item_count', 'wire_error_code', 'native_success',
        'native_error_code', 'native_error_name', 'native_item_count', 'matching_item_count', 'input_stale', 'before_bid_state', 'auction'}


def shape(receipt, p):
    r = fields(receipt, KEYS)
    if type(r['schema']) is not int or r['schema'] != 1 or r['verdict'] not in {'ACCEPTED','REJECTED','UNCONFIRMED'} or r['reason'] not in REASONS:
        raise ValueError('invalid_bid_receipt')
    for key in ('wire_identity_matches', 'wire_amount_matches'):
        if type(r[key]) is not bool: raise ValueError('invalid_bid_receipt')
    for key in ('native_success', 'input_stale'):
        if r[key] is not None and type(r[key]) is not bool: raise ValueError('invalid_bid_receipt')
    for key in ('wire_amount', 'wire_item_count', 'wire_error_code', 'native_error_code', 'native_item_count', 'matching_item_count'):
        if r[key] is not None: integer(r[key])
    integer(r['matching_item_count'])
    if r['wire_trade_id'] is not None: token(r['wire_trade_id'], 'trade')
    if r['native_error_name'] not in REJECTIONS | {None}: raise ValueError('invalid_bid_receipt')
    if r['before_bid_state'] not in {'none','outbid',None}: raise ValueError('invalid_bid_receipt')
    if r['wire_identity_matches'] != (r['wire_trade_id'] == p['trade_id']) or r['wire_amount_matches'] != (r['wire_amount'] == p['amount']):
        raise ValueError('bid_wire_binding_mismatch')
    a = r['auction']
    if a is not None:
        fields(a, AUCTION); auction(a, lite=True)
        if (a['trade_id'], a['item']['item_id']) != (p['trade_id'], p['item_id']) or a['item']['definition_id'] not in (None, 0, p['definition_id']):
            raise ValueError('bid_receipt_identity_mismatch')
    if r['matching_item_count'] != (1 if a else 0): raise ValueError('invalid_bid_receipt')
    return r


def validate(receipt, command, result):
    p = command['params']
    r = shape(receipt, p)
    a = r['auction']
    if r['verdict'] != 'UNCONFIRMED':
        target = result['network']
        if not (r['wire_identity_matches'] and r['wire_amount_matches']) or len(target) != 1 or not target[0]['session_header_present'] or target[0]['query'] != {} or (
                target[0]['method'], target[0]['path']) != ('PUT', '/ut/game/fc27/trade/:trade/bid') or target[0]['status'] != result['status']:
            raise ValueError('bid_wire_binding_mismatch')
    if r['verdict'] == 'ACCEPTED':
        # Outbid is permitted only for an initial participation receipt; the page
        # compares its retained prior state. Rebid acceptance requires highest.
        if not (result['success'] and r['reason']=='MATCHING_NATIVE_PARTICIPATION' and
                r['native_success'] is True and r['native_error_code'] is None and r['wire_error_code'] is None and
                r['native_error_name'] is None and r['input_stale'] is not True and
                r['wire_item_count']==r['native_item_count']==r['matching_item_count']==1 and a and
                (a['bid_state']=='highest' and a['current_bid']==p['amount'] or
                 a['bid_state']=='outbid' and r['before_bid_state']=='none' and a['current_bid']>=p['amount'])):
            raise ValueError('unproven_bid_acceptance')
    elif r['verdict'] == 'REJECTED':
        if not (not result['success'] and result['error']=='bid_rejected' and r['reason']=='EXPLICIT_NATIVE_REJECTION' and
                r['native_success'] is False and r['native_error_name'] in REJECTIONS and
                r['native_error_code'] is not None and r['wire_error_code']==r['native_error_code'] and
                r['native_item_count']==0 and a is None and type(result['status']) is int and 400<=result['status']<500):
            raise ValueError('unproven_bid_rejection')
    elif result['success'] or result['error']=='bid_rejected':
        raise ValueError('unconfirmed_bid_marked_successful')
    return r


def ordinary_rejection(command, response):
    """Called only after the enclosing response contract has been validated."""
    return command['operation']=='bid' and response['result'].get('bid_receipt',{}).get('verdict')=='REJECTED'
