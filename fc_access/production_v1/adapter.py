"""One adapter for all production operations; no legacy response normalization."""
from datetime import datetime, timezone
from .contracts import VERSION, Search, command, parse_response, correlate_readbacks


class NativeAdapter:
    def __init__(self, executor, *, context, owner, epoch, now=None, fixture=False):
        self.executor = executor
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.source = 'fixture' if fixture else 'native'
        self.context = dict(context)
        self.commands, self.dispatched, self.responses = {}, {}, {}
        self.fences = executor.attach(self.context, owner, epoch)
        # Validate the returned full fence before accepting an attachment.
        self.envelope('0'*32, 'balance', {})

    def envelope(self, command_id, operation, params):
        return command(dict(schema=VERSION, id=command_id, operation=operation, params=params,
                            context=dict(self.context), fences=dict(self.fences)))

    def read(self, command_id, operation, params=None):
        if operation == 'bid':
            raise ValueError('read_cannot_write')
        c = self.envelope(command_id, operation, {} if params is None else params)
        v = parse_response(self.executor.execute(c), c, now=self.now(), source=self.source,
                           pricing_rows=operation == 'search' and c['params']['purpose'] == 'pricing')
        if not v['result']['success']:
            # Only an enumerated code escapes, never arbitrary native exception text.
            raise ValueError(v['result']['error'])
        self.commands[command_id] = c
        from copy import deepcopy
        self.responses[command_id] = deepcopy(v)
        return v

    def search(self, command_id, query):
        if not isinstance(query, Search):
            raise ValueError('invalid_search')
        return self.read(command_id, 'search', query.params())

    def balance(self, command_id):
        return self.read(command_id, 'balance')

    def watched(self, command_id):
        return self.read(command_id, 'watched')

    def unassigned(self, command_id):
        return self.read(command_id, 'unassigned')

    def transfer_list(self, command_id):
        return self.read(command_id, 'transfer_list')

    def status_support(self, command_id):
        """Local source/mapping inspection, with zero EA requests."""
        return self.read(command_id, 'status_support')

    def known_status(self, command_id, *, trade_id, item_id, definition_id):
        """Read only a previously observed exact native trade in this page epoch.

        No reverse mapping from a pseudonym, historical artifact, or lost namespace.
        After reconnect a fresh full-identity read must establish the mapping again.
        Native lite omission remains null/0; it never overwrites retained identity.
        """
        return self.read(command_id, 'status', dict(trade_id=trade_id, item_id=item_id, definition_id=definition_id))

    def caps(self, command_id, definition_id):
        return self.read(command_id, 'caps', {'definition_id': definition_id})

    def price_helpers(self, command_id, probes=()):
        return self.read(command_id, 'price_helpers', {'version': 1, 'probes': list(probes)})

    def dispatch_intent(self, command_id, params, *, journal, prices=None, resale_price=None, profit_threshold=500):
        """Injected durable journal must consume an intent before invoking send once.

        The installed localhost service rejects writes. D5 owns production journal
        integration/authorization; fixtures can exercise this protocol without EA.
        """
        c = self.envelope(command_id, 'bid', params)
        from .prices import NativePrices, CardKey
        from .contracts import integer
        if not isinstance(prices, NativePrices) or prices.service.adapter is not self:
            raise ValueError('native_price_service_required')
        prices.check(CardKey(params['definition_id']))
        if prices.source != self.source:
            raise ValueError('wrong_evidence_source')
        integer(resale_price, 1); integer(profit_threshold)
        cap = prices.profitable_cap(resale_price, profit_threshold)
        if cap is None or params['cap'] > cap:
            raise ValueError('unsupported_profitable_cap')
        status = self.responses.get(params['status_read_id'])
        funds = self.responses.get(params['balance_read_id'])
        if status is None or funds is None or status['operation'] not in {'watched', 'search'} or funds['operation'] != 'balance':
            raise ValueError('independent_native_reads_required')
        for value in (status, funds):
            parse_response(value, self.commands[value['command_id']], now=self.now(), source=self.source)
            if value['context'] != self.context or value['fences'] != self.fences:
                raise ValueError('intent_snapshot_mismatch')
        rows = [a for a in status['result']['auctions'] if a['trade_id'] == params['trade_id'] and a['item']['item_id'] == params['item_id'] and a['item']['definition_id'] == params['definition_id']]
        if len(rows) != 1:
            raise ValueError('intent_snapshot_mismatch')
        a = rows[0]
        from .contracts import stamp
        from datetime import timedelta
        end = stamp(status['freshness']['network_at']) + timedelta(seconds=a['expires'])
        if a['item']['untradeable'] is not False or a['trade_state'] != 'active' or a['bid_state'] not in {'none', 'outbid'} or self.now() >= end or stamp(params['deadline']) > end or (a['buy_now_price'] and params['amount'] >= a['buy_now_price']):
            raise ValueError('bid_not_eligible')
        minimum = prices.minimum_bid(definition_id=params['definition_id'], platform=self.context['platform'],
                                     starting_bid=a['starting_bid'], current_bid=a['current_bid'])
        if minimum != params['amount'] or funds['result']['credits'] < params['amount']:
            raise ValueError('bid_not_eligible')
        def send():
            self.dispatched[command_id] = self.now()
            try:
                v = parse_response(self.executor.execute(c), c, now=self.now(), source=self.source)
            except TimeoutError:
                return {'command_id': command_id, 'outcome': 'UNKNOWN', 'reason': 'TIMEOUT'}
            except Exception:
                return {'command_id': command_id, 'outcome': 'UNKNOWN', 'reason': 'INVALID_RESULT'}
            r = v['result']
            return {'command_id': command_id, 'outcome': 'ACKNOWLEDGED' if r['success'] else 'UNKNOWN',
                    'reason': 'NATIVE_ACK' if r['success'] else 'TIMEOUT' if r['error'] == 'service_timeout' else 'SERVICE_ERROR'}
        return journal.dispatch_once(c, send)

    def correlate(self, write, status, balance):
        if write['id'] not in self.dispatched:
            raise ValueError('unknown_dispatch')
        return correlate_readbacks(write, status, balance,
                                  status_command=self.commands[status['command_id']],
                                  balance_command=self.commands[balance['command_id']],
                                  after=self.dispatched[write['id']], now=self.now())
