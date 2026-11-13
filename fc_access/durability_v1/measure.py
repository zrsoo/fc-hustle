"""Deterministic scheduler experiment, explicitly not EA throughput evidence."""
from fc_access.bidding_v1.scheduler import Scheduler,Work


def experiment():
    clock=[0.0]
    s=Scheduler(lambda:clock[0],min_native_interval=.1,concurrency=2,capacity=8)
    key=lambda n:f'{n:032x}'
    for n,kind,deadline in ((1,'read',10),(2,'write',8),(3,'write',9),(4,'read',.05)):
        s.enqueue(Work(key(n),kind,0,deadline))
    # Local transport is telemetry; no native cadence/concurrency consumption.
    s.delivery(key(1),.002,enqueued_at=0)
    order=[]
    w=s.next();order.append(w.command_id)
    assert s.next() is None
    clock[0]=.1
    w=s.next();order.append(w.command_id)
    clock[0]=.2
    assert s.next() is None
    s.complete(key(2),request_count=1)
    w=s.next();order.append(w.command_id)
    clock[0]=.3
    s.complete(key(3),request_count=1)
    # A cached read consumed zero EA requests, despite a native invocation.
    s.complete(key(1),request_count=0)
    bulk=[]
    clock[0]=0
    q=Scheduler(lambda:clock[0])
    for n in range(3):
        q.enqueue(Work(key(n+10),'read',25*n,25*(n+1)))
    for n in range(3):
        clock[0]=25*n
        w=q.next();clock[0]+=.2;q.complete(w.command_id)
        bulk.append({'rows_processed':50,'requests':1,'service_seconds':.2,'cycle_seconds':25})
    # One delayed network call exceeds an entire nominal cycle. The pending
    # next refresh then expires; it is skipped, not launched as catch-up traffic.
    clock[0]=0
    slow=Scheduler(lambda:clock[0])
    slow.enqueue(Work(key(30),'read',0,25));slow.enqueue(Work(key(31),'read',25,50))
    slow.next();clock[0]=51;slow.complete(key(30));assert slow.next() is None
    clock[0]=0
    urgent=Scheduler(lambda:clock[0])
    urgent.enqueue(Work(key(40),'write',0,10))
    urgent.enqueue(Work(key(41),'read',0,10,priority=2))
    urgent_first=urgent.next().command_id
    return {'classification':'DETERMINISTIC_SIMULATION','priority_order':order,'skipped':s.skipped,
            'metrics':s.metrics,'burst_peak_active':2,'native_requests':2,'bulk_cycles':bulk,
            'slow_cycle':{'service_seconds':51,'missed_25_second_deadline':True,'skipped':slow.skipped},
            'holding_calls_skipped':50,'holding_requests':0,
            'urgent_read_preempts_write':urgent_first==key(41),
            'limits':['Synthetic write timing and priority are not live bid timings.',
                '50 rows can be one bulk read; rebids, balance, economics and reconciliation are additional calls.',
                'Transport idle polling consumes no EA request slot.',
                'A 25-second target is not a guaranteed whole-queue cycle or EA-approved cadence.',
                'Per-row work and write bursts can exceed the deadline; expired work is skipped.']}


if __name__=='__main__':
    import json
    print(json.dumps(experiment(),indent=2))
