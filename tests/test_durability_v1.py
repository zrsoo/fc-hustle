"""Offline durability acceptance: real subprocess crashes, HTTP and JS seams."""
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import socket
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_bidding_v1 import (Fixture,FakePage,NativeAdapter,State,Outcome,NOW,SCOPE,OWNER,KEY,
    cid,intent,status,balance,fresh,wire)
from fc_access.durability_v1.store import Store
from fc_access.durability_v1.server import Server,EXTENSION_ID
from fc_access.durability_v1.harness import BoundedHarness,OwnedProof


def command(n=1,operation='watched',epoch=1,owner=OWNER):
    return {'schema':1,'id':cid(n),'operation':operation,'params':{},'scope':SCOPE,'owner':owner,'epoch':epoch,'evidence_key':KEY}


def native_wire(n=1,operation='watched'):
    v=wire(cid(n),operation);v['freshness']['source']='native';return v


PERSONA={'schema':1,'persona_present':True,'platform_type':'string','platform_value':'PC','is_pc_type':'boolean',
         'is_pc':True,'native_pc_constant':'PC','accepted':True,'read_error':False}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'store.sqlite';self.clock=1000
    def store(self,**kw):
        s=Store(self.path,now=lambda:self.clock,**kw);self.addCleanup(s.db.close);return s
    def own(self,s,epoch=1,owner=OWNER):
        p={'scope':SCOPE,'owner':owner,'epoch':epoch};s.activate(p);return p
    def test_claim_result_loss_restart_never_redelivers_or_resets_budget(self):
        s=self.store(reads=2);p=self.own(s);s.enqueue(command());self.assertEqual(s.claim(p),command())
        self.assertIsNone(s.claim(p));deadline=s.health()['deadline']
        other=self.store(reads=100,seconds=1800)
        self.assertEqual(other.owner()['epoch'],2)
        self.assertEqual(other.health()['read_limit'],2)
        self.assertEqual(other.health()['deadline'],deadline)
        self.assertIsNone(other.claim(other.owner()))
        with self.assertRaises(ValueError):other.enqueue(command(epoch=2))
        with self.assertRaises(ValueError):other.finish(p,cid(1),native_wire())
        self.assertEqual(other.db.execute('SELECT state FROM commands').fetchone()[0],'UNKNOWN')
    def test_scope_owner_epoch_result_correlation_and_duplicate_rejection(self):
        s=self.store();p=self.own(s);s.enqueue(command());s.claim(p)
        for bad in (dict(p,scope=cid(9)),dict(p,owner=cid(8)),dict(p,epoch=2)):
            with self.assertRaises(ValueError):s.finish(bad,cid(1),native_wire())
        with self.assertRaises(ValueError):s.finish(p,cid(1),native_wire(2))
        s.finish(p,cid(1),native_wire())
        with self.assertRaises(ValueError):s.finish(p,cid(1),native_wire())
        self.own(s,2,cid(8))
        with self.assertRaises(ValueError):s.enqueue(command(2))
        with self.assertRaises(ValueError):self.own(s,1)
    def test_limits_expiry_and_malformed_commands_no_consumption(self):
        s=self.store(reads=1,seconds=10);p=self.own(s)
        for c in (dict(command(),cookie='PRIVATE'),dict(command(),operation='transfer'),dict(command(),params={'token':'PRIVATE'})):
            with self.assertRaises((ValueError,TypeError)):s.enqueue(c)
        self.assertEqual(s.health()['reads_reserved'],0)
        s.enqueue(command());s.uncertain(cid(1))
        with self.assertRaises(ValueError):s.enqueue(command(2))
        self.clock+=11
        self.assertTrue(s.health()['expired']);self.assertIsNone(s.claim(p))
    def test_real_process_crash_claim_and_lost_mutation_ack_stop_window(self):
        script='''
import os,sys
sys.path.insert(0,'tests')
from test_durability_v1 import *
s=Store(sys.argv[1],mutations=1,exposure=1000,now=lambda:1000)
p={'scope':SCOPE,'owner':OWNER,'epoch':1};s.activate(p)
c=command(operation='bid');c['params']={'trade_id':status().identity.trade_id,'item_id':status().identity.item_id,'definition_id':123,'amount':150,'minimum':150,'cap':1000,'deadline':NOW.isoformat()}
s.enqueue(c);s.claim(p)
with open(sys.argv[2],'a') as f:f.write('native-bid\\n');f.flush();os.fsync(f.fileno())
os._exit(31)
'''
        writes=self.path.with_suffix('.writes')
        r=subprocess.run([sys.executable,'-c',script,str(self.path),str(writes)],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,31,r.stderr)
        s=self.store(mutations=3,exposure=10000)
        self.assertTrue(s.health()['stopped']);self.assertEqual(s.health()['mutations_reserved'],1)
        self.assertEqual(s.health()['exposure_reserved'],150)
        self.assertIsNone(s.claim(s.owner()))
        with self.assertRaises(ValueError):s.enqueue(command(2,epoch=2))
        self.assertEqual(writes.read_text().splitlines(),['native-bid'])
    def test_scheduler_measurement_checks_priority_burst_staleness_cache_and_overrun(self):
        from fc_access.durability_v1.measure import experiment
        m=experiment()
        self.assertEqual(m['priority_order'],[cid(2),cid(3),cid(1)])
        self.assertEqual(m['skipped'],[(cid(4),'DEADLINE_SKIPPED')])
        self.assertEqual(m['burst_peak_active'],2)
        self.assertTrue(m['urgent_read_preempts_write'])
        self.assertEqual(sum(x.get('request_count',0) for x in m['metrics']),2)
        self.assertEqual(m['metrics'][0]['local_delivery_ms'],2)
        self.assertEqual([c['rows_processed'] for c in m['bulk_cycles']],[50,50,50])
        self.assertEqual(m['slow_cycle']['skipped'],[(cid(31),'DEADLINE_SKIPPED')])
    def test_balance_native_credits_route_is_preserved_and_other_routes_rejected(self):
        from fc_access.durability_v1.adapter import parse_durable_response
        v=native_wire(1,'balance');v['result']['network'][0]['path']='/ut/game/fc27/user/credits'
        r,f,_=parse_durable_response(v,command_id=cid(1),operation='balance')
        self.assertEqual(r['network'][0]['path'],'/ut/game/fc27/user/credits');self.assertEqual(r['credits'],50000)
        v['result']['network'][0]['path']='/ut/game/fc27/user/private'
        with self.assertRaises(ValueError):parse_durable_response(v,command_id=cid(1),operation='balance')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Server(Path(self.tmp.name)/'http.sqlite',port=0,wait_seconds=.2,poll_seconds=.05)
        self.thread=threading.Thread(target=self.s.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.cleanup)
        self.base='http://127.0.0.1:'+str(self.s.server_port)
        self.p={'scope':SCOPE,'owner':OWNER,'epoch':1}
        self.assertEqual(self.post('/activate',self.p)[0],200)
        self.peer={'boot':self.s.boot,**self.p,'document':cid(90),'worker':cid(91),'persona':PERSONA,
                   'fences':dict.fromkeys(('wrong_scope','wrong_owner','stale_epoch','bid_disabled'),True)}
    def cleanup(self):
        self.s.shutdown();self.thread.join(2);self.s.server_close();self.s.store.db.close()
    def post(self,path,value,origin=None):
        headers={'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        r=Request(self.base+path,data=json.dumps(value).encode(),headers=headers)
        try:
            with urlopen(r,timeout=3) as response:return response.status,json.load(response)
        except HTTPError as e:return e.code,json.load(e)
    def ext(self,path,value):return self.post(path,value,'chrome-extension://'+EXTENSION_ID)
    def attach(self):self.assertEqual(self.ext('/hello',{'protocol':1,'peer':self.peer})[0],200)
    def test_exact_origin_handshake_persona_and_stale_process_rejected(self):
        self.assertEqual(self.post('/hello',{'protocol':1},'chrome-extension://'+'a'*32)[0],403)
        self.assertEqual(self.post('/run',command())[0],409)
        self.attach()
        for p in (dict(self.peer,boot=cid(99)),dict(self.peer,owner=cid(99)),dict(self.peer,epoch=2)):
            self.assertEqual(self.ext('/next',p)[0],409)
        self.assertEqual(self.ext('/next',self.peer),(200,None))
        bad=PERSONA|{'platform_value':'PSN','is_pc':False,'accepted':False}
        self.peer['persona']=bad;self.attach()
        self.assertEqual(self.post('/run',command())[0],409)
        self.assertEqual(self.s.store.health()['reads_reserved'],0)
    def test_closed_live_window_and_executor_never_authorize_mutation(self):
        from fc_access.durability_v1.executor import EdgeReadExecutor
        self.attach()
        self.assertEqual(self.post('/close',{})[0],200)
        self.assertEqual(self.post('/run',command())[0],409)
        self.assertEqual(self.s.store.health()['reads_reserved'],0)
        executor=EdgeReadExecutor(self.s.server_port)
        for op in ('bid','transfer','list'):
            with self.assertRaises(ValueError):executor.execute({'operation':op})
    def test_split_header_body_client_receives_real_origin_rejection(self):
        # A real two-write request, without the legacy fixture coalescing shim.
        body=b'{"protocol":1}'
        sock=socket.create_connection(('127.0.0.1',self.s.server_port),timeout=2)
        self.addCleanup(sock.close)
        headers=(f'POST /hello HTTP/1.1\r\nHost: 127.0.0.1:{self.s.server_port}\r\n'
            f'Origin: https://attacker.invalid\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n').encode()
        sock.sendall(headers);sock.settimeout(.05)
        with self.assertRaises(socket.timeout):sock.recv(1)
        sock.sendall(body);sock.settimeout(2)
        response=b''
        while b'\r\n\r\n' not in response:response+=sock.recv(4096)
        self.assertIn(b' 403 ',response.split(b'\r\n',1)[0])
        self.assertEqual(self.s.store.health()['reads_reserved'],0)
    def test_long_poll_delivery_once_and_malformed_result_timeout_no_retry(self):
        self.attach();outputs=[]
        run=threading.Thread(target=lambda:outputs.append(self.post('/run',command())),daemon=True);run.start()
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            _,c=self.ext('/next',self.peer)
            if c:break
        self.assertEqual(c,command());self.assertEqual(self.ext('/next',self.peer),(200,None))
        value=native_wire();value['result']['cookie']='PRIVATE'
        self.assertEqual(self.ext('/result',{'peer':self.peer,'id':cid(1),'result':value})[0],409)
        run.join(2);self.assertEqual(outputs[0][0],504)
        self.assertEqual(self.ext('/result',{'peer':self.peer,'id':cid(1),'result':native_wire()})[0],409)
        self.assertEqual(self.post('/run',command())[0],409)
        self.assertNotIn('PRIVATE',str(self.s.store.db.execute('SELECT * FROM commands').fetchall()))
    def test_owner_change_between_claim_and_reply_rejects_old_page(self):
        self.attach();self.s.store.enqueue(command());self.s.store.claim(self.peer)
        self.assertEqual(self.post('/activate',dict(self.p,epoch=2,owner=cid(80)))[0],200)
        self.assertEqual(self.ext('/result',{'peer':self.peer,'id':cid(1),'result':native_wire()})[0],409)
    def test_extension_reload_fences_orphan_poll_before_any_delivery(self):
        self.s.poll_seconds=1
        self.attach();old=dict(self.peer);outputs=[]
        poll=threading.Thread(target=lambda:outputs.append(self.ext('/next',old)),daemon=True);poll.start()
        end=time.monotonic()+2
        while not self.s.polling and time.monotonic()<end:time.sleep(.001)
        self.assertEqual(self.s.polling,old)
        self.peer=dict(old,worker=cid(92));self.attach()
        with self.s.condition:
            self.s.store.enqueue(command())
            self.s.condition.notify_all()
        code,c=self.ext('/next',self.peer)
        self.assertEqual((code,c),(200,command()))
        poll.join(2);self.assertEqual(outputs[0][0],409)
        self.assertEqual(self.s.store.db.execute("SELECT COUNT(*) FROM audit WHERE event='DELIVERED'").fetchone()[0],1)
        self.assertEqual(self.ext('/result',{'peer':old,'id':cid(1),'result':native_wire()})[0],409)
        self.assertEqual(self.ext('/result',{'peer':self.peer,'id':cid(1),'result':native_wire()})[0],200)


class HarnessTests(Fixture,unittest.TestCase):
    def harness(self,*,mutations=1,exposure=1000,seconds=60,page=None):
        a=NativeAdapter(page or FakePage(),self.journal(),self.provider,scope=SCOPE,owner=OWNER,evidence_key=KEY,now=lambda:self.clock,fixture=True)
        h=BoundedHarness(self.path/'harness.sqlite',a,mutations=mutations,exposure=exposure,seconds=seconds)
        self.addCleanup(h.db.close);return h,a
    def readback(self,cid):
        return replace(status(state=State.LEADING,current=150),freshness=fresh(800)),balance(n=901)
    def bid(self,h,**kw):
        return h.bid_once(intent(epoch=h.adapter.epoch),status(),balance(),self.rules,quote=self.quote(),readback=kw.get('readback',self.readback))
    def test_default_denies_mutations_and_explicit_limits_survive_reopen(self):
        h,a=self.harness(mutations=0)
        with self.assertRaises(ValueError):self.bid(h)
        self.assertEqual(a.executor.commands,[])
        other=BoundedHarness(self.path/'harness.sqlite',a,mutations=3,exposure=10000,seconds=900)
        self.addCleanup(other.db.close)
        with self.assertRaises(ValueError):self.bid(other)
        self.assertEqual(other.db.execute('SELECT mutations,exposure FROM window').fetchone(),(0,1000))
    def test_independent_readbacks_and_durable_accounting_enforced(self):
        h,a=self.harness();after=self.bid(h)
        self.assertEqual(after.state,State.LEADING)
        self.assertEqual(h.db.execute('SELECT amount,state FROM actions').fetchall(),[(150,'VERIFIED')])
        with self.assertRaises(ValueError):self.bid(h)
        self.assertEqual(sum(c['operation']=='bid' for c in a.executor.commands),1)
    def test_unknown_ack_stops_even_if_another_command_and_owner_are_available(self):
        page=FakePage();page.fail=True;h,a=self.harness(mutations=3,page=page)
        with self.assertRaisesRegex(ValueError,'uncertain'):self.bid(h)
        self.assertEqual(h.db.execute('SELECT stopped FROM window').fetchone()[0],1)
        a.journal.session(SCOPE,cid(77))
        with self.assertRaises(ValueError):self.bid(h)
        self.assertEqual(sum(c['operation']=='bid' for c in page.commands),1)
    def test_bad_or_missing_readback_stops_and_never_unlocks(self):
        h,a=self.harness(mutations=3)
        with self.assertRaises(ValueError):self.bid(h,readback=lambda c:(status(state=State.UNKNOWN),balance(n=901)))
        self.assertEqual(h.db.execute('SELECT stopped FROM window').fetchone()[0],1)
        with self.assertRaises(ValueError):self.bid(h)
    def test_stale_cache_balance_deadline_amount_exposure_and_owner_preconditions(self):
        h,a=self.harness(exposure=149)
        with self.assertRaises(ValueError):self.bid(h)
        h.db.execute('UPDATE window SET exposure=1000')
        for s,b in ((replace(status(),freshness=fresh(at=NOW-timedelta(seconds=31))),balance()),
                     (status(),replace(balance(),freshness=replace(fresh(900),request_count=0))),
                     (status(),replace(balance(),freshness=fresh(1)))):
            with self.assertRaises(ValueError):h.bid_once(intent(s,b=b),s,b,self.rules,quote=self.quote(),readback=self.readback)
        self.clock+=timedelta(seconds=61)
        s,b=status(at=self.clock),balance(at=self.clock)
        with self.assertRaisesRegex(ValueError,'window_mutation'):
            h.bid_once(intent(s,b=b),s,b,self.rules,quote=self.quote(),readback=self.readback)
        self.assertEqual(a.executor.commands,[])
    def test_owner_takeover_after_ack_and_restart_reservation_stop(self):
        h,a=self.harness(mutations=3)
        def takeover(cid):
            a.journal.session(SCOPE,'d'*32);return self.readback(cid)
        with self.assertRaises(ValueError):self.bid(h,readback=takeover)
        other=BoundedHarness(self.path/'harness.sqlite',a,mutations=3,exposure=10000)
        self.addCleanup(other.db.close)
        self.assertEqual(other.db.execute('SELECT stopped FROM window').fetchone()[0],1)
        self.assertEqual(other.db.execute('SELECT COUNT(*),SUM(amount) FROM actions').fetchone(),(1,150))
    def test_transfer_and_listing_require_conclusive_owned_identity_and_readback(self):
        h,a=self.harness(mutations=3)
        won=replace(status(state=State.LEADING,current=150),state=State.WON,owned_item_id=status().identity.item_id,paid=150)
        proof=OwnedProof(won.identity,150,True,fresh(810))
        calls=[]
        for s,p in ((replace(won,state=State.PENDING),proof),(won,replace(proof,paid=200)),
                    (won,replace(proof,identity=status(2).identity)),(won,replace(proof,tradeable=False)),
                    (won,replace(proof,freshness=replace(fresh(810),network_at=None)))):
            with self.assertRaises(ValueError):h.won_action_once(cid(300),'transfer',s,p,send=lambda:calls.append(1),readback=lambda:(True,fresh(820)))
        self.assertEqual(calls,[])
        h.won_action_once(cid(301),'transfer',won,proof,send=lambda:True,readback=lambda:(True,fresh(820)))
        h.won_action_once(cid(302),'list',won,proof,send=lambda:True,readback=lambda:(True,fresh(821)),rules=self.rules,price=12000)
        self.assertEqual(h.db.execute('SELECT kind,state FROM actions ORDER BY id').fetchall(),[('transfer','VERIFIED'),('list','VERIFIED')])
    def test_javascript_lifecycle_worker_and_page_contracts(self):
        for f in ('durability_page_checks.cjs','durability_worker_checks.cjs'):
            r=subprocess.run(['node','tests/'+f],cwd=ROOT,capture_output=True,text=True,timeout=30)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
    def test_harness_process_dies_after_bid_and_restart_cannot_duplicate(self):
        script='''
import os,sys
sys.path.insert(0,'tests')
from test_durability_v1 import *
case=HarnessTests();case.setUp();case.path=Path(sys.argv[1])
class CrashPage(FakePage):
 def execute(self,c):
  with open(case.path/'writes.txt','a') as f:f.write('bid\\n');f.flush();os.fsync(f.fileno())
  os._exit(32)
h,a=case.harness(page=CrashPage(),mutations=3)
case.bid(h)
'''
        r=subprocess.run([sys.executable,'-c',script,str(self.path)],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,32,r.stderr)
        h,a=self.harness(mutations=3)
        self.assertEqual(a.epoch,2)
        with self.assertRaises(ValueError):self.bid(h)
        self.assertEqual(a.executor.commands,[])
        self.assertEqual((self.path/'writes.txt').read_text().splitlines(),['bid'])
        self.assertEqual(h.db.execute('SELECT amount,state FROM actions').fetchall(),[(150,'UNKNOWN')])


if __name__=='__main__':unittest.main(verbosity=2)
