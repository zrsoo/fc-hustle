"""Controller reads and non-blocking outcome delivery; receipt is not confirmation."""
from copy import deepcopy
from datetime import datetime, timezone
from .protocol import command, parse_response


def denied(v):
    """EA permission denial of this exact bid: wire 461 -> service 403, matched
    identity/amount and an empty native receipt. Reads after such denials never
    showed our participation, so it is a no-effect outcome, not an unknown."""
    receipt = v.get('receipt') or {}
    network = v.get('network') or []
    return (v.get('success') is False and v.get('status') == 403 and len(network) == 1 and
            network[0].get('status') == 461 and receipt.get('verdict') == 'UNCONFIRMED' and
            receipt.get('native_error_code') == 461 and receipt.get('native_item_count') == 0 and
            receipt.get('wire_identity_matches') is True and receipt.get('wire_amount_matches') is True)


class ControllerAdapter:
    def __init__(self, executor, *, context, owner, epoch, now=None):
        self.executor, self.context = executor, deepcopy(context)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.fences = executor.attach(context,owner,epoch)
        self.commands, self.responses = {}, {}
        # This reader shares the exact same serialized executor and fence. It
        # cannot dispatch legacy mutations and does not perform a second attach.
        from fc_access.production_v1.adapter import NativeAdapter
        self.native = NativeAdapter.__new__(NativeAdapter)
        self.native.executor,self.native.context,self.native.fences=executor,self.context,self.fences
        self.native.now,self.native.source=self.now,'native'
        self.native.commands,self.native.responses,self.native.dispatched={},{},{}

    def envelope(self, cid, operation, params):
        return command(dict(schema=4,id=cid,operation=operation,params=params,context=self.context,fences=self.fences))

    def read(self, cid, operation, params=None):
        if operation not in {'watched','balance','status_batch'}: raise ValueError('read_only')
        c = self.envelope(cid,operation,{} if params is None else params)
        v = parse_response(self.executor.execute(c),c,now=self.now())
        self.commands[cid],self.responses[cid] = c,v
        return v

    def status_batch(self, cid, targets):
        return self.read(cid,'status_batch',{'targets':deepcopy(targets)})

    def deliver(self, cid, durable_params):
        """The server owns admission; caller parameters confer no permission."""
        c = self.envelope(cid,'bid',deepcopy(durable_params))
        try:
            v = parse_response(self.executor.execute(c),c,now=self.now())
        except Exception:
            return dict(command_id=cid,outcome='UNKNOWN',reason='DELIVERY_UNCONFIRMED',receipt=None,independently_confirmed=False)
        self.commands[cid],self.responses[cid] = c,v
        receipt = v['receipt']
        verdict = receipt.get('verdict') if receipt else None
        outcome = ('ACKNOWLEDGED' if v['success'] and verdict=='ACCEPTED' else
                   'REJECTED' if verdict=='REJECTED' and v['error']=='bid_rejected' else
                   'DENIED' if denied(v) else 'UNKNOWN')
        return dict(command_id=cid,outcome=outcome,reason=v['error'],receipt=deepcopy(receipt),independently_confirmed=False)

    def confirmation(self, cid, status_id):
        from fc_access.production_v1.contracts import stamp
        c,write = self.commands[cid],self.responses[cid]
        sc,status = self.commands[status_id],self.responses[status_id]
        parse_response(status,sc,now=self.now())
        if c['operation']!='bid' or not status['success'] or sc['operation']!='status_batch' or any(sc[k]!=c[k] for k in ('context','fences')) or stamp(status['network_at'])<=stamp(write['observed_at']):
            raise ValueError('independent_confirmation_required')
        t = c['params']['target']
        if t not in sc['params']['targets'] or not any(l['target']==t for l in status['links']):
            return False
        rows = [r for r in status['auctions'] if r['trade_id']==t['trade_id'] and r['item']['item_id']==t['item_id']]
        return len(rows)==1 and rows[0]['bid_state'] in {'highest','outbid'}
