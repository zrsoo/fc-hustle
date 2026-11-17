"""Exact native lost-target cleanup. No prices, ownership inference or retries."""
from .watch_capacity import slots


def identity(row):
    return dict(trade_id=row['trade_id'],item_id=row['item']['item_id'],definition_id=row['item']['definition_id'])


def parameters(before):
    slots(before) # Requires matched native wire/callback/repository coverage.
    rows=before['result']['auctions']
    eligible=[identity(r) for r in rows if r['trade_state'] in {'closed','expired'} and
        r['expires']<=0 and r['bid_state'] in {'none','outbid'} and r['native_is_won'] is False]
    return dict(before_read_id=before['command_id'],targets=sorted(eligible,key=lambda t:t['trade_id']))


def effect(c,before,after):
    slots(before);slots(after)
    if c['context']!=before['context'] or c['context']!=after['context'] or parameters(before)!=c['params']:
        return False
    if before['coverage']['watch_list']['capacity']!=after['coverage']['watch_list']['capacity']:return False
    key=lambda t:(t['trade_id'],t['item_id'],t['definition_id'])
    prior={key(identity(r)) for r in before['result']['auctions']}
    current={key(identity(r)) for r in after['result']['auctions']}
    removed={key(t) for t in c['params']['targets']}
    return bool(removed) and current==prior-removed


def consumed(store, *, exclude=None):
    result=set()
    for cid,body in store.db.execute("SELECT id,body FROM c4_work WHERE json_extract(body,'$.operation')='clear_lost'"):
        if cid==exclude:continue
        import json
        result.update((t['trade_id'],t['item_id'],t['definition_id']) for t in json.loads(body)['params']['targets'])
    return result
