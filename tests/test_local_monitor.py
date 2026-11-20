"""Local fix-loop monitor; offline (fake health/stop, fixture files, trivial child)."""
from argparse import Namespace
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.locking import process_lock
from fc_access.controller_v1 import local_monitor as lm

GEN='e'*32


class Clock:
    def __init__(self):self.t=1000.
    def __call__(self):return self.t
    def sleep(self,s):self.t+=s


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.dir=Path(self.enterContext(tempfile.TemporaryDirectory()));self.p=lm.paths(self.dir)

    def run_watch(self,reports,*,stop=None,startup=90,gaps=None):
        clock=Clock();calls=[];reports=list(reports);gaps=list(gaps or [])
        def check():
            if gaps:clock.t+=gaps.pop(0)
            value=reports.pop(0);return value(GEN) if callable(value) else dict(value,generation=GEN)
        def stopper():
            calls.append(clock());return stop() if stop else dict(status='stopped',generation=GEN,diagnostic='OWNED_RUNTIME_EXITED')
        incident=lm.watch(GEN,interval=30,startup=startup,p=self.p,check=check,stop=stopper,clock=clock,sleep=clock.sleep,wall=lambda:'T')
        return incident,calls,lm.lines(self.p['monitor']/f'samples-{GEN}.jsonl')

    def test_consecutive_healthy_seconds_fault_stops_once_and_records_incident(self):
        h=dict(status='healthy',diagnostic='ACQUIRING',evidence=[])
        incident,calls,samples=self.run_watch([dict(status='starting',diagnostic='S'),h,h,h,dict(status='repair',diagnostic='PERSISTENT_WRITE_FAILURE')])
        self.assertEqual([s['healthy_seconds'] for s in samples],[0,0,30,60,0])
        self.assertEqual(len(calls),1)
        self.assertEqual((incident['kind'],incident['diagnostic'],incident['healthy_seconds']),('FAULT','PERSISTENT_WRITE_FAILURE',0))
        self.assertEqual(lm.lines(self.p['incidents']),[incident])
        self.assertEqual(json.loads(self.p['watcher'].read_text())['generation'],GEN)

    def test_monitoring_gap_resets_the_interval(self):
        h=dict(status='healthy',diagnostic='MANAGING',evidence=[])
        _,_,samples=self.run_watch([h,h,h,dict(status='repair',diagnostic='X')],gaps=[0,0,200,0])
        self.assertEqual([s['healthy_seconds'] for s in samples],[0,30,0,0])

    def test_starting_outside_grace_is_a_fault(self):
        st=dict(status='starting',diagnostic='STARTING_NATIVE_VALIDATION')
        incident,calls,_=self.run_watch([st,st,st,st,st],startup=60)
        self.assertEqual((incident['diagnostic'],len(calls)),('STARTING_OUTSIDE_GRACE',1))

    def test_operator_stop_is_labelled_and_stop_failures_are_retained(self):
        self.p['monitor'].mkdir(parents=True);(self.p['monitor']/f'operator-stop-{GEN}').write_text('T')
        incident,_,_=self.run_watch([dict(status='repair',diagnostic='OPERATIONAL_STOP')])
        self.assertEqual(incident['kind'],'OPERATOR_STOP')
        (self.p['monitor']/f'operator-stop-{GEN}').unlink()
        def failing():raise TimeoutError('SECRET_CANARY')
        incident,_,_=self.run_watch([dict(status='repair',diagnostic='X')],stop=failing)
        self.assertEqual(incident['stop'],dict(status='failed',exception='TimeoutError'))
        self.assertNotIn('CANARY',self.p['incidents'].read_text())

    def test_only_one_watcher_holds_the_lock(self):
        with process_lock(self.p['lock']):
            with self.assertRaises(ValueError):self.run_watch([dict(status='repair',diagnostic='X')])


class LaunchAndStatusTests(unittest.TestCase):
    def setUp(self):
        self.dir=Path(self.enterContext(tempfile.TemporaryDirectory()));self.p=lm.paths(self.dir)

    def test_launch_refuses_while_a_runtime_owns_the_lock(self):
        a=Namespace(base=str(self.dir),measure='noop',recovery_config=None,refresh_on_start=False,interval=30,epoch_floor=None,note='')
        with process_lock(self.p['runtime']/'owner.lock'):
            with self.assertRaises(SystemExit):lm.launch(a,self.p)
        self.assertEqual(lm.lines(self.p['launches']),[],'a refused launch records no intent')

    def test_status_summarizes_launch_health_runtime_bids_and_incident(self):
        self.assertEqual(lm.summarize(self.p),dict(launch=None))
        lm.append(self.p['launches'],dict(generation=GEN,at='T0',epoch_floor=37,measure='noop',state='spawned',breakaway=True,note=''))
        for i,(status,healthy) in enumerate((('starting',0),('healthy',0),('healthy',30))):
            lm.append(self.p['monitor']/f'samples-{GEN}.jsonl',dict(at=f'T{i}',status=status,diagnostic='D',healthy_seconds=healthy))
        log=self.dir/'events.jsonl'
        w=lambda **m:dict(kind='WORKER',at='T',message=m)
        rows=[dict(kind='STARTED',at='T',pid=1,limits={'x':1}),
              w(kind='native_result',operation='bid',success=True,wire_statuses=[200],local=False),
              w(kind='native_result',operation='bid',success=False,wire_statuses=[461],service_status=403,local=False),
              w(kind='native_result',operation='balance',success=True,wire_statuses=[200],local=False),
              w(kind='progress',stage='NATIVE',operation='bid'),
              w(kind='batch_result',state='SETTLED',confirmed=1,uncertain=1),
              dict(kind='STOP_REQUESTED',at='T',reason='PERSISTENT_WRITE_FAILURE')]
        log.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        run=self.p['runtime']/'runs'/GEN;run.mkdir(parents=True)
        (run/'state.json').write_text(json.dumps(dict(state='STOPPED',operational_state='STOPPED',reason='PERSISTENT_WRITE_FAILURE',
            at='T',log=str(log),recovery=None,semantic=dict(native_successes=5,write_failures=3,recoverable='STALE_DOCUMENT_WRITE_DENIAL'))))
        lm.append(self.p['incidents'],dict(generation=GEN,kind='FAULT',diagnostic='PERSISTENT_WRITE_FAILURE'))
        out=lm.summarize(self.p)
        self.assertEqual(out['launch']['generation'],GEN);self.assertFalse(out['watcher_alive'])
        self.assertEqual((out['samples'],out['max_healthy_seconds'],out['last_sample']['status']),(3,30,'healthy'))
        self.assertEqual(out['runtime']['reason'],'PERSISTENT_WRITE_FAILURE')
        self.assertEqual(out['runtime']['semantic']['recoverable'],'STALE_DOCUMENT_WRITE_DENIAL')
        self.assertEqual(out['bids'],dict(total=2,accepted=1,denied_461=1))
        self.assertEqual([e['kind'] for e in out['events']],['STARTED','native_result','batch_result','STOP_REQUESTED'])
        self.assertNotIn('limits',out['events'][0])
        self.assertEqual(out['incident']['kind'],'FAULT')

    def test_follow_prints_health_events_and_incident_once(self):
        lm.append(self.p['launches'],dict(generation=GEN,at='T0',epoch_floor=37,measure='noop',state='spawned'))
        lm.append(self.p['monitor']/f'samples-{GEN}.jsonl',dict(at='T1',status='healthy',diagnostic='ACQUIRING',healthy_seconds=30))
        log=self.dir/'events.jsonl'
        rows=[dict(kind='STARTED',at='2026-11-18T10:00:00',pid=4),
              dict(kind='WORKER',at='2026-11-18T10:00:05',message=dict(kind='native_result',operation='bid',success=False,
                   wire_statuses=[461],service_status=403,local=False)),
              dict(kind='WORKER',at='2026-11-18T10:00:06',message=dict(kind='progress',stage='LOCAL'))]
        log.write_text(''.join(json.dumps(r)+chr(10) for r in rows))
        run=self.p['runtime']/'runs'/GEN;run.mkdir(parents=True);(run/'state.json').write_text(json.dumps(dict(log=str(log))))
        lm.append(self.p['incidents'],dict(generation=GEN,kind='FAULT',diagnostic='PERSISTENT_WRITE_FAILURE',healthy_seconds=30))
        out=[];lm.follow(self.p,sleep=lambda s:None,rounds=2,out=out.append)
        self.assertEqual(out,['--- health healthy ACQUIRING healthy=30s gen=eeeeeeee watcher=stopped','10:00:00 STARTED pid=4',
                              '10:00:05 bid FAILED wire=461 service=403','*** INCIDENT FAULT PERSISTENT_WRITE_FAILURE healthy=30s'])

    def test_launch_builds_a_watcher_command_the_cli_accepts(self):
        argv=lm.watcher_argv(self.dir,GEN,30,90)
        a=lm.parser().parse_args(argv[3:])
        self.assertEqual((a.action,a.generation,a.interval,a.startup,a.base),('watch',GEN,30,90,str(self.dir)))

    def test_trading_counts_only_controller_items_with_tax_and_windows(self):
        import sqlite3
        db=sqlite3.connect(self.dir/'controller.sqlite')
        db.executescript("CREATE TABLE c4_work(id,action,body,before_read,state,at,dispatched_at,completed_at,proof);CREATE TABLE c4_members(trade_id,batch_id,state,body);")
        def work(op,at,params=None,before=None,state='CONFIRMED'):
            db.execute('INSERT INTO c4_work(body,before_read,state,at) VALUES (?,?,?,?)',(json.dumps(dict(operation=op,params=params or {})),json.dumps(before or {}),state,at))
        sold=lambda item,price:dict(item=dict(item_id=item),trade_state='closed',current_bid=price)
        work('list','2026-11-18T10:00',dict(item_id='item:a',paid=3000,buy_now_price=4500))
        work('list','2026-11-18T21:00',dict(item_id='item:b',paid=1000,buy_now_price=2000))
        work('list','2026-11-18T21:05',dict(item_id='item:c',paid=500,buy_now_price=900),state='UNKNOWN')
        work('relist_all','2026-11-18T22:00',dict(expected_item_ids=['item:b','item:manual']))
        work('clear_sold','2026-11-18T23:00',before=dict(result=dict(auctions=[sold('item:a',4300),sold('item:manual',6200)])))
        db.execute("INSERT INTO c4_members VALUES('t','b','PENDING_WIN','{}')");db.commit();db.close()
        all_time=lm.trading(self.dir,None)
        self.assertEqual((all_time['won_listed'],all_time['relisted'],all_time['sold']),(2,1,1))
        self.assertEqual(all_time['realized_profit'],int(4300*0.95)-3000,'manual 6200 sale excluded')
        self.assertEqual((all_time['unsold_listed_now'],all_time['unrealized_at_buy_now']),(1,int(2000*0.95)-1000))
        self.assertEqual(all_time['left_without_recorded_sale'],0,'no transfer-list read: nothing judged gone')
        self.assertEqual(all_time['pending_wins_now'],1)
        window=lm.trading(self.dir,'2026-11-18T20:00')
        self.assertEqual((window['won_listed'],window['relisted'],window['sold'],window['realized_profit']),(1,1,1,int(4300*0.95)-3000))
        self.assertEqual(lm.trading(self.dir,'2026-11-19T00:00')['realized_profit'],0)

    def test_unsold_means_still_on_the_latest_transfer_list(self):
        import sqlite3
        db=sqlite3.connect(self.dir/'controller.sqlite')
        db.executescript("CREATE TABLE c4_work(id,action,body,before_read,state,at,dispatched_at,completed_at,proof);"
                         "CREATE TABLE c4_members(trade_id,batch_id,state,body);CREATE TABLE c4_commands(id,body,state,result);")
        def work(op,at,params):
            db.execute('INSERT INTO c4_work(body,before_read,state,at) VALUES (?,?,?,?)',(json.dumps(dict(operation=op,params=params)),'{}','CONFIRMED',at))
        work('list','2026-11-18T10:00',dict(item_id='item:gone',paid=1000,buy_now_price=2000))
        work('list','2026-11-18T11:00',dict(item_id='item:listed',paid=1000,buy_now_price=3000))
        work('list','2026-11-18T13:00',dict(item_id='item:after_read',paid=1000,buy_now_price=4000))
        def pile(at,items,complete=True):
            v=dict(result=dict(success=True,auctions=[dict(item=dict(item_id=i)) for i in items]),
                   coverage=dict(complete=complete),freshness=dict(network_at=at))
            db.execute('INSERT INTO c4_commands VALUES (?,?,?,?)',('c',json.dumps(dict(operation='transfer_list')),'DONE',json.dumps(v)))
        pile('2026-11-18T12:00',['item:listed','item:manual'])
        pile('2026-11-18T12:30',[],complete=False)  # incomplete read never judges
        db.commit();db.close()
        out=lm.trading(self.dir,None)
        self.assertEqual((out['unsold_listed_now'],out['left_without_recorded_sale']),(2,1))
        self.assertEqual(out['unrealized_at_buy_now'],int(3000*0.95)-1000+int(4000*0.95)-1000)
        self.assertEqual(out['realized_profit'],0,'a card gone without a recorded sale is not profit')

    def test_launch_and_service_accept_the_maintenance_gap(self):
        a=lm.parser().parse_args(['launch','--maintenance-gap','180'])
        self.assertEqual(a.maintenance_gap,180.0)
        self.assertEqual(lm.parser().parse_args(['launch']).maintenance_gap,120.0)

    def test_detached_spawn_runs_a_child_and_logs_it(self):
        log=self.dir/'child.log'
        child,_=lm.spawn([sys.executable,'-c','print("child-ok")'],log)
        self.assertEqual(child.wait(20),0)
        self.assertIn('child-ok',log.read_text())


if __name__=='__main__':unittest.main(verbosity=2)
