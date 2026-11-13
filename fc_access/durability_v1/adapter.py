"""Current native balance route adaptation; prior versioned sources stay sealed."""
from fc_access.bidding_v1.adapter import NativeAdapter,parse_response


def parse_durable_response(value,*,command_id,operation):
    # Both observed /user/credits and the older currencies projection describe
    # the native currency service. Preserve the actual path in retained results.
    if operation=='balance' and isinstance(value,dict) and isinstance(value.get('result'),dict):
        rows=value['result'].get('network')
        if isinstance(rows,list):
            safe=[r|{'path':'/ut/game/fc27/user/currencies'} if isinstance(r,dict) and r.get('path')=='/ut/game/fc27/user/credits' else r for r in rows]
            normalized=value|{'result':value['result']|{'network':safe}}
            _,f,c=parse_response(normalized,command_id=command_id,operation=operation)
            return value['result'],f,c
    return parse_response(value,command_id=command_id,operation=operation)


class DurableNativeAdapter(NativeAdapter):
    def _read(self,command_id,operation,params):
        try:
            response=self.executor.execute(self.envelope(command_id,operation,params))
            value=parse_durable_response(response,command_id=command_id,operation=operation)
            if value[1].source!=('fixture' if self.fixture else 'native'):
                raise ValueError('wrong_evidence_source')
            self.journal.record(self.scope,'READ_OBSERVED',{'read_id':command_id,'source':value[1].source,
                'request_count':value[1].request_count,'native_service_ms':response['timing']['native_service_ms']},command_id=command_id)
            return value
        except Exception:
            self.journal.record(self.scope,'LIFECYCLE_ERROR',{'epoch':self.epoch},command_id=command_id)
            raise
