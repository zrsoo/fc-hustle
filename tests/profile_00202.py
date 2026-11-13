"""Offline comparison through the existing Foundation; never connects to Edge.

The baseline reproduces pre-optimization helper dispatch and row validation.
Controlled timings measure round-trip amplification, not future live latency.
"""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from foundation_fixture import Page, Clock, CONTEXT
from native_price_fixture import auction
from fc_access.production_v1.foundation import Foundation
from fc_access.production_v1.prices import PriceService, NativePrices

REPORT = ROOT/'docs/research/002/002-02/offline-profile.json'


class TimedPage(Page):
    def execute(self, c):
        value = super().execute(c)
        if c['operation'] == 'search' and c['params']['purpose'] == 'pricing':
            # 21 unsorted rows; repeated BINs across both samples.
            bins = [1700, 1500, 1600]*7 if 'max_buy' not in c['params'] else [1500]*21
            value['result']['auctions'] = [auction(123, price, 100+i) for i, price in enumerate(bins)]
            # Stable identity/BIN for all shared rows in the second sample.
            if 'max_buy' in c['params']:
                value['result']['auctions'] = [auction(123, 1500, 200+i) for i in range(21)]
        helpers = c['operation'] == 'price_helpers'
        helper_ms = len(c['params']['probes'])*.2 if helpers else 0
        ea_ms = 0 if helpers else 120
        value['timing'] = dict(native_service_ms=ea_ms+helper_ms+4,
                               ea_rtt_ms=ea_ms, native_helper_ms=helper_ms)
        # Bridge cost per command is the optimization's independently varied cost.
        self.clock.sleep((ea_ms+helper_ms+4+50)/1000-.005)
        self.last_sqlite_ms = 0  # no HTTP service in this offline page double
        return value


class SingleProbeService(PriceService):
    def helper(self, direction, value):
        r = self.adapter.price_helpers(self.command_ids(), [dict(direction=direction,value=value)])
        return r['result']['probes'][0]['price']


def scenario(optimized=True):
    with tempfile.TemporaryDirectory() as directory:
        clock = Clock(); page = TimedPage(directory, clock)
        f = Foundation(page, context=CONTEXT, journal_path=Path(directory)/'journal.sqlite3',
            fixture=True, now=clock.now, clock=clock.monotonic, sleep=clock.sleep)
        try:
            page.candidate['starting_bid'] = 150
            page.watched = [page.candidate]
            watched = f.read('watched'); balance = f.read('balance')
            if not optimized:
                f.prices = SingleProbeService(f.adapter, f.ids)
            start = clock.monotonic(); wall_start=time.perf_counter()
            # The baseline called legal() separately for every row in each pass.
            def old_legal_many(rules, values):
                return {v: rules.legal(v) for v in values}
            if optimized:
                decision = f.admit(watched, page.candidate['trade_id'], balance)
            else:
                with patch.object(NativePrices, 'legal_many', old_legal_many):
                    decision = f.admit(watched, page.candidate['trade_id'], balance)
            metrics = f.timing_summary()
            elapsed = (clock.monotonic()-start)*1000
            wall_elapsed = (time.perf_counter()-wall_start)*1000
            helpers = [c for c in page.calls if c['operation']=='price_helpers']
            pricing = [c['params'] for c in page.calls if c['operation']=='search']
            return dict(elapsed_ms=elapsed, offline_wall_elapsed_ms=wall_elapsed, helper_commands=len(helpers),
                helper_probes=sum(len(c['params']['probes']) for c in helpers),
                max_batch=max(len(c['params']['probes']) for c in helpers),
                pricing_queries=pricing, decision={k:decision[k] for k in ('action','reason','cap','amount')},
                resale_price=decision['quote']['resale_price'], metrics=metrics,
                persisted_executor_events=sum(e['kind']=='EXECUTOR_METRIC' for e in f.registry.events()),
                bid_calls=page.bid_calls)
        finally:
            f.close(); page.close()


def profile():
    # Descriptive analysis of sealed live evidence; never a source-code gate.
    retained = json.loads((ROOT/'docs/research/001d/final-remediation/valuation-followup.json').read_text())
    helpers = [o for o in retained['operations'] if o['command']['operation']=='price_helpers']
    metrics = retained['scheduler_metrics']
    historical = dict(path='docs/research/001d/final-remediation/valuation-followup.json',
        helper_commands=len(helpers), native_requests=sum(m['request_count'] for m in metrics),
        native_service_ms=sum(m['native_service_ms'] for m in metrics),
        helper_service_ms=sum(o['response']['timing']['native_service_ms'] for o in helpers),
        queue_ms=sum(m['queue_ms'] for m in metrics),
        delivery_ms=sum(m['delivery_ms'] for m in metrics),
        ea_rtt_ms=None, sqlite_ms=None, diagnostic_logging_ms=None,
        limitation='Historical native_service_ms includes service/projection; no isolated EA RTT or SQLite/log timing was captured.')
    return dict(schema=1, task='002-02', mode='OFFLINE_CONTROLLED_CLOCK',
        live_gate_executed=False, live_requests=0,
        historical_live=historical,
        inputs=dict(ea_rtt_ms=120, bridge_ms_per_command=50, browser_other_ms=4, helper_probe_ms=.2),
        baseline=scenario(False), optimized=scenario(True))


if __name__=='__main__':
    result = profile()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
