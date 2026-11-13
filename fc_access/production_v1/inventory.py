"""One-shot state interpretation; absence and native victory are not ownership.

These functions dispatch no account operations. Paid cost and independent owned
physical-item proof remain Objective 002 inputs before any move or listing.
"""
from copy import deepcopy
from dataclasses import dataclass
from .contracts import context, integer, parse_response, token


@dataclass(frozen=True)
class KnownTrade:
    trade_id: str
    item_id: str
    definition_id: int

    def __post_init__(self):
        token(self.trade_id, 'trade'); token(self.item_id, 'item'); integer(self.definition_id, 1)

    def params(self):
        return dict(trade_id=self.trade_id, item_id=self.item_id, definition_id=self.definition_id)


def compare_lite_identity(known, row):
    """Native lite version omission means unobserved, never a different card.

    Caller supplies the retained same-context full identity separately; this
    comparison cannot recover a native ID or bridge unrelated namespace keys.
    """
    if not isinstance(known, KnownTrade) or type(row) is not dict or set(row) - {'trade_id', 'item_id', 'definition_id'}:
        raise ValueError('invalid_identity')
    token(row.get('trade_id'), 'trade'); token(row.get('item_id'), 'item')
    if (row['trade_id'], row['item_id']) != (known.trade_id, known.item_id):
        return 'IDENTITY_MISMATCH'
    definition = row.get('definition_id')
    if definition is None or type(definition) is int and definition == 0:
        return 'MATCH_RETAINED_VERSION_UNOBSERVED'
    integer(definition, 1)
    return 'MATCH' if definition == known.definition_id else 'DIFFERENT_CARD'


def watched_status(response, command, known, *, expected_context, now=None, source='native'):
    """Revalidate the fresh bulk read before selecting a single exact row."""
    if command['operation'] != 'watched' or not isinstance(known, KnownTrade):
        raise ValueError('watched_read_and_identity_required')
    context(expected_context)
    if command['context'] != expected_context:
        raise ValueError('identity_context_mismatch')
    v = parse_response(response, command, now=now, source=source)
    r = v['result']
    if not r['success']:
        raise ValueError(r['error'])
    rows = [a for a in r['auctions'] if a['trade_id'] == known.trade_id]
    result = dict(outcome='UNKNOWN', reason='MISSING_WATCHED_ROW', row=None,
                  read_id=command['id'], ownership_proven=False)
    if not rows:
        return result
    a = rows[0]
    result['row'] = deepcopy(a)
    if (a['item']['item_id'], a['item']['definition_id']) != (known.item_id, known.definition_id):
        result['reason'] = 'EXACT_IDENTITY_MISMATCH'
        return result
    terminal = a['trade_state'] in {'closed', 'expired'} and a['expires'] <= 0
    if a['trade_state'] == 'closed' and a['bid_state'] == 'highest' or a['native_is_won'] is True:
        result.update(outcome='PENDING', reason='INDEPENDENT_OWNED_ITEM_PROOF_REQUIRED')
    elif terminal and a['bid_state'] == 'outbid':
        result.update(outcome='LOST', reason='EXACT_TERMINAL_OUTBID')
    elif a['trade_state'] == 'active' and a['expires'] > 0 and a['bid_state'] in {'highest', 'outbid', 'none'}:
        result.update(outcome={'highest': 'LEADING', 'outbid': 'OUTBID', 'none': 'WATCHING'}[a['bid_state']], reason='EXACT_ACTIVE_ROW')
    else:
        result['reason'] = 'INCONCLUSIVE_NATIVE_STATE'
    return result
