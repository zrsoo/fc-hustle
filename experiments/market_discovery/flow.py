"""Finite measured search -> evaluate -> fresh search -> DRY-RUN intent demo."""
import time

from fc_access.pricing import MarketKey, Rules
from .discovery import Budget, Runner, decision, observations
from .model import stamp
from .replay import FixtureClock, FixtureTransport


def simulated_flow():
    clock = FixtureClock()
    transport = FixtureTransport(clock, opportunity=True)
    runner = Runner(transport, mode='SIMULATED', clock=clock)
    params = {'definition_id':233731,'page':1,'count':21,'fresh':True,'max_buy':7000}
    budget = Budget(2)
    began = clock.perf_counter()
    first = runner.read(params,budget,'A',0,0)
    candidate = min(observations([first]), key=lambda o: (o.buy_now_price,o.trade_id))
    rules = {233731:Rules(MarketKey(233731,'pc'),150,15000000,stamp(clock.utc()))}
    # First evaluation can find a modeled candidate; intent is only retained after another read.
    initial = decision([first], candidate, now=stamp(clock.utc()), rules=rules, simulated=True)
    second = runner.read(params,budget,'A',0,1)
    final = decision([second], candidate, now=stamp(clock.utc()), rules=rules, simulated=True)
    complete = (clock.perf_counter()-began)*1000+initial['python_compute_ms']+final['python_compute_ms']
    final['search_to_intent_ms'] = complete if final['intent'] else None
    final['time_to_first_result_ms'] = first['elapsed_ms']
    final['python_total_ms'] = initial['python_compute_ms']+final['python_compute_ms']
    return {'schema':1,'mode':'SIMULATED','lineage':'DETERMINISTIC_SYNTHETIC_NOT_LIVE',
            'rules':'HYPOTHETICAL_NOT_VERIFIED', 'records':runner.records, 'flow':final,
            'EA_live_requests':0,'account_mutations':0,'budget':vars(budget)}
