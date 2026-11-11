"""Controlled localhost delivery benchmark. Simulated extension/native, zero EA reads.

Actual 30-second baseline polling; never scales its time and calls it measured.
MV3 wake/suspension, browser injection and EA service timing remain unvalidated.
"""
import argparse
import http.client
import json
from pathlib import Path
import threading
import time

from .bridge_server import SearchServer
from .model import summary, utc
from .replay import FixtureClock, FixtureTransport
from .transport import SearchTransport


def arm(mode, samples=3, interval=30):
    if mode not in ('alarm_30s','long_poll') or not 1 <= samples <= 20 or interval != 30:
        raise ValueError('controlled_contract')
    server = SearchServer('a'*32, port=0, poll_seconds=0 if mode=='alarm_30s' else 20)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    stop, attached = threading.Event(), threading.Event()
    errors = []
    def post(path, body):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=25)
        try:
            conn.request('POST',path,json.dumps(body),{'Content-Type':'application/json','Origin':'chrome-extension://'+'a'*32})
            response = conn.getresponse()
            value = json.loads(response.read())
            if response.status != 200:
                raise ValueError('local_rejected')
            return value
        finally:
            conn.close()
    def extension():
        due = time.perf_counter()
        try:
            while not stop.is_set():
                if mode=='alarm_30s' and stop.wait(max(0,due-time.perf_counter())):
                    break
                command = post('/next',{'protocol':1})
                received = time.perf_counter()
                attached.set()
                if command:
                    time.sleep(.002)  # explicitly simulated injection delay
                    native_start = time.perf_counter()
                    time.sleep(.01)  # explicitly simulated native observable
                    native_end = time.perf_counter()
                    value = FixtureTransport(FixtureClock()).search(command['params'],command['evidence_key'])
                    value['timing'] = {'worker_poll_to_native_ms':(native_start-received)*1000,
                                       'native_service_ms':(native_end-native_start)*1000,
                                       'page_total_ms':(time.perf_counter()-native_start)*1000}
                    post('/result',{'id':command['id']}|value)
                if mode=='alarm_30s': due += interval
        except Exception:
            errors.append('local_simulator_failed')
            attached.set()
    worker = threading.Thread(target=extension, daemon=True)
    worker.start()
    if mode=='alarm_30s':
        if not attached.wait(3): raise ValueError('local_attachment_failed')
    else:
        # Long poll is waiting on the condition before returning its first response.
        deadline=time.perf_counter()+3
        while not server.polling and time.perf_counter()<deadline: time.sleep(.001)
    transport = SearchTransport(server.server_port)
    records=[]
    try:
        for i in range(samples):
            # Controlled phase, no rate-limit or throughput testing.
            if mode=='alarm_30s': time.sleep(.05 if i==0 else (i % 3)*5+.05)
            start=time.perf_counter()
            value=transport.search({'definition_id':233731,'max_buy':7000,'page':1,'count':21,'fresh':True},'b'*32)
            elapsed=(time.perf_counter()-start)*1000
            if not value['result']['success']: raise ValueError('local_delivery_failed')
            records.append({'sample':i,'end_to_end_ms':elapsed,'timing':value['timing']|transport.last_timing,
                            'error':value['result']['error']})
    finally:
        stop.set()
        with server.condition:
            # Wake a waiting idle poll promptly during local test shutdown.
            server.pending={'command':None,'delivered':None,'deadline':time.monotonic()+1}
            server.condition.notify_all()
        worker.join(2)
        server.shutdown(); server.server_close(); serving.join(2)
    if errors: raise ValueError(errors[0])
    return {'transport':mode,'status':'LOCAL_SIMULATOR_ONLY','alarm_interval_seconds':30 if mode=='alarm_30s' else None,
            'records':records,'latency':{k:summary([r['timing'][k] for r in records]) for k in
              ('queue_delivery_ms','worker_poll_to_native_ms','native_service_ms','page_total_ms','result_return_ms')},
            'end_to_end':summary([r['end_to_end_ms'] for r in records])}


def benchmark(samples=3):
    start=utc()
    return {'schema':1,'status':'LOCAL_SIMULATOR_ONLY','started_utc':start,
            'arms':[arm('alarm_30s',samples),arm('long_poll',samples)],'completed_utc':utc(),
            'EA_live_requests':0,'account_mutations':0,'browser_alternative_status':'PREPARED_NOT_LIVE_VALIDATED',
            'limitations':['Python extension simulator, not Edge MV3','Native duration is controlled sleep, not EA latency',
                           'No live discovery throughput or profitable yield claim','p95 withheld below 20 samples']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--samples',type=int,default=3,choices=range(1,21))
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as out:
        json.dump(benchmark(args.samples),out,indent=2,allow_nan=False)
        out.write('\n')
    return 0


if __name__=='__main__': raise SystemExit(main())
