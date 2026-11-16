"""004-02 behavior: shipped JS, strict Python adapter, durable authority and real loopback transport."""
from copy import deepcopy
from contextlib import ExitStack, closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.controller_v1.protocol import command, parse_response
from fc_access.controller_v1.store import ControllerStore
from fc_access.controller_v1.adapter import ControllerAdapter
from fc_access.controller_v1.executor import ControllerExecutor
from fc_access.controller_v1.server import Server
from fc_access.production_v1.contracts import stamp, parse_response as legacy_parse
from fc_access.production_v1.server import EXTENSION_ID


def hexid(n): return f'{n:032x}'


class ControllerContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'samples.json'
            p=subprocess.run(['node','tests/controller_native_checks.cjs',str(output)],cwd=ROOT,capture_output=True,text=True,timeout=45)
            if p.returncode:raise AssertionError(p.stdout+p.stderr)
            cls.samples=json.loads(output.read_text())

    def fixture(self,path,write=True):
        group=self.samples[:3]
        self.assertEqual([s['command']['operation'] for s in group],['watched','status_batch','balance'])
        store=ControllerStore(path,write_authority=write,now=lambda:stamp(group[-1]['now']))
        peer={k:deepcopy(group[0]['command'][k]) for k in ('context','fences')}
        store.host_epoch=peer['fences']['host_epoch']
        store.attach(peer)
        for s in group:
            store.enqueue(s['command'],peer);self.assertEqual(store.claim(peer),s['command']);store.finish(peer,s['command']['id'],s['response'])
        return store,peer,group

    def inventory(self,peer,now):
        c=dict(schema=2,id=hexid(901),operation='transfer_list',params={},**deepcopy(peer))
        v=dict(schema=2,command_id=c['id'],operation=c['operation'],**deepcopy(peer),
            result=dict(success=True,error=None,status=200,credits=None,items=None,auctions=[],caps=None,cache_invalidated=True,
                network=[dict(method='GET',path='/ut/game/fc27/tradepile',host='utas.test.ea.com',query={},status=200,session_header_present=True)]),
            freshness=dict(observed_at=now.isoformat(),network_at=now.isoformat(),request_count=1,read_id=c['id'],source='native'),
            coverage=dict(complete=True,has_more=False,transfer_list=dict(reason='TRANSFER_LIST_COMPLETE',wire_count=0,callback_count=0,repository_count=0,repository_end_of_list=True)),
            timing=dict(native_service_ms=0,ea_rtt_ms=0,native_helper_ms=0))
        legacy_parse(v,c,now=now)
        return c,v

    def decision(self,store,peer,group,*,index=0,batch=902,decision=903):
        ic,iv=self.inventory(peer,store.now())
        store.admit_batch(hexid(batch),balance_read_id=group[2]['command']['id'],inventory_command=ic,inventory_response=iv)
        t=group[1]['command']['params']['targets'][index]
        p=dict(batch_id=hexid(batch),status_read_id=group[1]['command']['id'],identity=t,amount=500,minimum=500,cap=1000,deadline=(store.now()+timedelta(seconds=100)).isoformat())
        store.decide(hexid(decision),**p)
        c=dict(schema=4,id=hexid(decision+100),operation='bid',params=dict(target=p['identity'],decision_id=hexid(decision),**{k:v for k,v in p.items() if k!='identity'}),**deepcopy(peer))
        return c

    def test_c0_c1_c3_c4_c5_shipped_page_samples_and_python_parser(self):
        successes=set()
        for sample in self.samples:
            c,v=sample['command'],sample['response']
            try:command(c)
            except ValueError:
                self.assertFalse(v['success']);continue
            parsed=parse_response(v,c,now=stamp(sample['now']))
            self.assertEqual(parsed,v)
            if v['success']:successes.add(c['operation'])
        self.assertEqual(successes,{'watched','status_batch','balance','bid'})

    def test_c1_parser_negative_identity_schema_versions_auth_and_scope(self):
        s=self.samples[1];c=s['command'];base=s['response']
        edits=[lambda v:v.update(schema=2),lambda v:v.update(success=1),lambda v:v['context'].update(persona=hexid(9)),
            lambda v:v['fences'].update(epoch=2),lambda v:v.update(network=[]),lambda v:v['network'][0].update(session_header_present=False),
            lambda v:v['network'][0].update(status=401),lambda v:v['network'][0].update(method='PUT'),lambda v:v['network'][0].update(path='/ut/game/fc27/transfermarket'),
            lambda v:v['network'][0].update(targets=[]),lambda v:v['network'][0].update(host='evil.example'),
            lambda v:v['auctions'].append(v['auctions'][0]),lambda v:v['auctions'][0]['item'].update(item_id='item:'+'e'*24),
            lambda v:v['auctions'][0]['item'].update(definition_id=99),lambda v:v['auctions'][0]['item'].update(definition_id=False),
            lambda v:v['auctions'][0].update(expires=-2),lambda v:v['auctions'][0].update(bid_state='unknown'),
            lambda v:v.update(missing=c['params']['targets']),lambda v:v['links'][0].update(current_dto_matches=False),
            lambda v:v['links'][0].update(version_observed=True),lambda v:v.update(background=[{'event':'SECRET'}])]
        for i,edit in enumerate(edits):
            with self.subTest(i=i):
                v=deepcopy(base);edit(v)
                with self.assertRaises((ValueError,TypeError)):parse_response(v,c,now=stamp(s['now']))
        with self.assertRaises(ValueError):parse_response(base,c,now=stamp(s['now'])+timedelta(seconds=31))
        for edit in [lambda c:c.update(new_mode=True),lambda c:c['params'].update(authorize=True),lambda c:c['params'].update(targets=[]),lambda c:c['params'].update(targets=c['params']['targets']*2)]:
            value=deepcopy(c);edit(value)
            with self.assertRaises(ValueError):command(value)

    def test_c1_c2_full_version_link_and_no_global_uncertainty_gate(self):
        with tempfile.TemporaryDirectory() as td, ExitStack() as resources:
            store,peer,group=self.fixture(Path(td)/'new.sqlite')
            resources.callback(store.close)
            c=self.decision(store,peer,group)
            row,_=store.linked_row(c['params']['status_read_id'],c['params']['target'])
            self.assertEqual(row['item']['definition_id'],c['params']['target']['definition_id'])
            self.assertEqual(store.result(group[1]['command']['id'])['auctions'][0]['item']['definition_id'],0)
            store.enqueue(c,peer);self.assertEqual(store.claim(peer),c);store.uncertain(c['id'])
            with self.assertRaisesRegex(ValueError,'possibly_sent'):store.enqueue(c,peer)
            duplicate=deepcopy(c);duplicate['id']=hexid(999)
            with self.assertRaisesRegex(ValueError,'possibly_sent'):store.enqueue(duplicate,peer)
            # A different eligible target still dispatches after uncertainty.
            other=self.decision(store,peer,group,index=1,batch=904,decision=905)
            store.enqueue(other,peer);self.assertEqual(store.claim(peer),other)
            # Independent writer obtains the SQLite write lock while native I/O is outside storage.
            with closing(sqlite3.connect(store.path,timeout=.1)) as writer, writer:writer.execute("INSERT INTO c4_events(kind,body) VALUES ('EXTERNAL_WRITER','{}')")
            store.uncertain(other['id'])
            full=store.result(group[0]['command']['id']);full['auctions'][0]['item']['definition_id']=99
            with store.db:store.db.execute('UPDATE c4_commands SET result=? WHERE id=?',(json.dumps(full),group[0]['command']['id']))
            with self.assertRaisesRegex(ValueError,'full_version_conflict'):store.linked_row(c['params']['status_read_id'],c['params']['target'])

    def test_c2_durable_authority_schema_exact_binding_scope_and_restart(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'new.sqlite';store,peer,group=self.fixture(path);c=self.decision(store,peer,group)
            for edit in [lambda c:c['params'].update(amount=600,minimum=600),lambda c:c['params']['target'].update(definition_id=99),
                         lambda c:c['params'].update(decision_id=hexid(999)),lambda c:c['fences'].update(epoch=2),
                         lambda c:c['context'].update(account=hexid(999)),lambda c:c.update(authority=True)]:
                value=deepcopy(c);edit(value)
                with self.assertRaises(ValueError):store.enqueue(value,peer)
            store.write_authority=False
            with self.assertRaisesRegex(ValueError,'durable_authority'):store.enqueue(c,peer)
            store.write_authority=True
            # Failed persistence permits zero claims, no mutation dispatch.
            store.db.execute("CREATE TRIGGER fail_intent BEFORE INSERT ON c4_commands WHEN NEW.state='WAITING' BEGIN SELECT RAISE(ABORT,'disk unavailable'); END")
            with self.assertRaises(sqlite3.IntegrityError):store.enqueue(c,peer)
            self.assertIsNone(store.claim(peer))
            store.db.execute('DROP TRIGGER fail_intent');store.enqueue(c,peer);self.assertEqual(store.claim(peer),c)
            store.close();reopened=ControllerStore(path,write_authority=True,now=lambda:stamp(group[-1]['now']))
            try:
                self.assertEqual(reopened.db.execute('SELECT state FROM c4_commands WHERE id=?',(c['id'],)).fetchone()[0],'UNKNOWN')
                newer=deepcopy(peer);newer['fences'].update(host_epoch=reopened.host_epoch,epoch=2);reopened.attach(newer)
                self.assertIsNone(reopened.claim(newer))
                with self.assertRaises(ValueError):reopened.enqueue(c,newer)
                self.assertEqual(reopened.db.execute('SELECT count(*) FROM c4_tombstones').fetchone()[0],1)
            finally:reopened.close()
            legacy=Path(td)/'legacy.sqlite'
            with closing(sqlite3.connect(legacy)) as db, db:db.execute('CREATE TABLE legacy(data TEXT)')
            with self.assertRaisesRegex(ValueError,'isolated'):ControllerStore(legacy)

    def test_c2_missing_batch_inventory_and_auth_do_not_admit(self):
        with tempfile.TemporaryDirectory() as td, ExitStack() as resources:
            store,peer,group=self.fixture(Path(td)/'new.sqlite');resources.callback(store.close)
            ic,iv=self.inventory(peer,store.now())
            for edit in [lambda v:v['coverage'].update(complete=False),lambda v:v['result']['network'][0].update(session_header_present=False),
                         lambda v:v['fences'].update(epoch=99),lambda v:v['coverage']['transfer_list'].update(wire_count=1)]:
                changed=deepcopy(iv);edit(changed)
                with self.assertRaises(ValueError):store.admit_batch(hexid(902),balance_read_id=group[2]['command']['id'],inventory_command=ic,inventory_response=changed)
            with self.assertRaises(ValueError):store.decide(hexid(999),batch_id=hexid(902),status_read_id=group[1]['command']['id'],identity=group[1]['command']['params']['targets'][0],amount=500,minimum=500,cap=1000,deadline=(store.now()+timedelta(seconds=100)).isoformat())

    def test_c2_c4_duplicate_waiting_and_expired_intents_do_not_block_other_work(self):
        with tempfile.TemporaryDirectory() as td, ExitStack() as resources:
            store,peer,group=self.fixture(Path(td)/'new.sqlite');resources.callback(store.close)
            c=self.decision(store,peer,group);duplicate=deepcopy(c);duplicate['id']=hexid(1999)
            store.enqueue(c,peer);store.enqueue(duplicate,peer)
            self.assertEqual(store.claim(peer),c);store.uncertain(c['id'])
            self.assertIsNone(store.claim(peer),'duplicate waiting intent must be retired without send')
            self.assertEqual(store.db.execute('SELECT state FROM c4_commands WHERE id=?',(duplicate['id'],)).fetchone()[0],'UNKNOWN')
            other=self.decision(store,peer,group,index=1,batch=904,decision=905);store.enqueue(other,peer)
            current=store.now();store.now=lambda:current+timedelta(seconds=101)
            self.assertIsNone(store.claim(peer),'expired intent must not dispatch')
            read=dict(schema=4,id=hexid(2000),operation='balance',params={},**deepcopy(peer));store.enqueue(read,peer)
            self.assertEqual(store.claim(peer),read)

    def test_c1_lite_omission_never_becomes_authority(self):
        with tempfile.TemporaryDirectory() as td, ExitStack() as resources:
            store,peer,group=self.fixture(Path(td)/'new.sqlite');resources.callback(store.close)
            c=deepcopy(group[1]['command']);c['id']=hexid(1900)
            value=deepcopy(group[1]['response']);value.update(command_id=c['id'],auctions=[],links=[],missing=c['params']['targets'])
            store.enqueue(c,peer);store.claim(peer);store.finish(peer,c['id'],value)
            with self.assertRaisesRegex(ValueError,'missing_target'):store.linked_row(c['id'],c['params']['targets'][0])

    def test_c4_late_mutation_receipt_preserved_without_replay(self):
        bid=next(s for s in self.samples if s['command']['operation']=='bid' and s['response']['success'])
        with tempfile.TemporaryDirectory() as td:
            store=ControllerStore(Path(td)/'new.sqlite',write_authority=True,now=lambda:stamp(bid['now']))
            try:
                c=deepcopy(bid['command']);peer={k:c[k] for k in ('context','fences')};store.host_epoch=peer['fences']['host_epoch'];store.attach(peer)
                # A captured claimed intent exercises the exact late-result storage
                # seam; admission behavior is tested above through its public API.
                with store.db:
                    store.db.execute('INSERT INTO c4_commands VALUES (?,?,?,NULL)',(c['id'],json.dumps(c),'CLAIMED'))
                    store.db.execute('INSERT INTO c4_tombstones VALUES (?,?)',('already_consumed_action',c['id']))
                store.uncertain(c['id']);store.finish(peer,c['id'],bid['response'])
                self.assertIsNone(store.result(c['id']));self.assertIsNone(store.claim(peer))
                stored=json.loads(store.db.execute("SELECT body FROM c4_events WHERE kind='LATE_RESULT'").fetchone()[0])
                self.assertEqual(stored['receipt'],bid['response']['receipt'])
                self.assertEqual(store.db.execute('SELECT count(*) FROM c4_tombstones').fetchone()[0],1)
            finally:store.close()

    def test_c3_c4_c5_actual_loopback_adapter_timeout_late_result_and_next_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            server=Server(Path(td)/'transport.sqlite',port=0,wait_seconds=.15,poll_seconds=0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            edge=ControllerExecutor(port=server.server_port,attach_timeout=1)
            sample=self.samples[1];peer={k:deepcopy(sample['command'][k]) for k in ('context','fences')}
            peer['fences']['host_epoch']=server.store.host_epoch
            server.store.now=lambda:stamp(sample['now'])
            def extension(path,value,origin=True):
                req=Request(edge.base+path,data=json.dumps(value).encode(),headers={'Content-Type':'application/json',**({'Origin':server.extension_origin} if origin else {})})
                with urlopen(req,timeout=3) as r:return json.load(r)
            try:
                edge.request('/activate',dict(context=peer['context'],owner=peer['fences']['owner'],epoch=1))
                self.assertEqual(extension('/hello',dict(schema=2,peer=peer)),dict(schema=2,service='fc-controller-v1',host_epoch=server.store.host_epoch,owner=dict(context=peer['context'],owner=peer['fences']['owner'],epoch=1)))
                adapter=ControllerAdapter(edge,context=peer['context'],owner=peer['fences']['owner'],epoch=1,now=lambda:stamp(sample['now']))
                targetset=sample['command']['params']['targets']
                c=adapter.envelope(hexid(991),'status_batch',{'targets':targetset})
                with self.assertRaises(TimeoutError):edge.execute(c)
                self.assertIsNone(extension('/next',peer),'timed out WAITING read must not dispatch later')
                def execute_native():
                    import time
                    for _ in range(50):
                        claimed=extension('/next',peer)
                        if claimed:
                            result=deepcopy(sample['response']);result.update(command_id=claimed['id'],fences=claimed['fences'])
                            for link in result['links']:link['status_read_id']=claimed['id']
                            extension('/result',dict(peer=peer,id=claimed['id'],result=result));return
                        time.sleep(.005)
                    raise AssertionError('no command')
                worker=threading.Thread(target=execute_native);worker.start()
                result=adapter.status_batch(hexid(992),targetset);worker.join()
                self.assertEqual(len(result['auctions']),10)
                self.assertIsNone(extension('/next',peer))
                # Claimed command times out; a late reply is retained as evidence only.
                latec=adapter.envelope(hexid(993),'status_batch',{'targets':targetset})
                server.store.enqueue(latec,peer);server.store.claim(peer);server.store.uncertain(latec['id'])
                late=deepcopy(result);late['command_id']=latec['id']
                for link in late['links']:link['status_read_id']=latec['id']
                extension('/result',dict(peer=peer,id=latec['id'],result=late))
                self.assertIsNone(server.store.result(latec['id']))
                self.assertEqual(server.store.db.execute("SELECT count(*) FROM c4_events WHERE kind='LATE_RESULT'").fetchone()[0],1)
                # Request-side flags cannot enable mutation authority on service.
                bid=next(s['command'] for s in self.samples if s['command']['operation']=='bid');bid=deepcopy(bid);bid['fences']=peer['fences']
                with self.assertRaises(ValueError):edge.execute(bid)
                with self.assertRaises(Exception):extension('/hello',{'schema':2,'peer':peer},origin=False)
            finally:server.shutdown();thread.join();server.server_close()

    def test_c4_adapter_receipts_remain_separate_from_confirmation(self):
        bid=next(s for s in self.samples if s['command']['operation']=='bid' and s['response']['success'])
        status=next(s for s in self.samples if s['command']['operation']=='status_batch' and s['response']['success'] and s['command']['fences']==bid['command']['fences'])
        class Executor:
            def attach(self,*a):return bid['command']['fences']
            def execute(self,c):return deepcopy((status if c['operation']=='status_batch' else bid)['response'])
        adapter=ControllerAdapter(Executor(),context=bid['command']['context'],owner=hexid(4),epoch=1,now=lambda:stamp(status['now']))
        outcome=adapter.deliver(bid['command']['id'],bid['command']['params'])
        self.assertEqual(outcome['outcome'],'ACKNOWLEDGED');self.assertFalse(outcome['independently_confirmed'])
        sc=status['command'];adapter.status_batch(sc['id'],sc['params']['targets'])
        self.assertTrue(adapter.confirmation(bid['command']['id'],sc['id']))
        original=deepcopy(adapter.responses[sc['id']]);adapter.responses[sc['id']].update(auctions=[],links=[],missing=sc['params']['targets'])
        self.assertFalse(adapter.confirmation(bid['command']['id'],sc['id']),'absence is not independent participation')
        adapter.responses[sc['id']]=original
        adapter.responses[sc['id']]['network_at']=bid['response']['observed_at']
        with self.assertRaisesRegex(ValueError,'independent_confirmation'):adapter.confirmation(bid['command']['id'],sc['id'])
        class Lost(Executor):
            def execute(self,c):raise TimeoutError('lost')
        adapter.executor=Lost()
        self.assertEqual(adapter.deliver(hexid(999),bid['command']['params'])['outcome'],'UNKNOWN')

    def test_c2_c4_at_most_once_mutation_through_actual_http_delivery(self):
        import time
        with tempfile.TemporaryDirectory() as td:
            server=Server(Path(td)/'mailbox.sqlite',port=0,write_authority=True,wait_seconds=.5,poll_seconds=0)
            server.store.close()
            server.store,peer,group=self.fixture(Path(td)/'authority.sqlite')
            server.owner=dict(context=peer['context'],owner=peer['fences']['owner'],epoch=1)
            server.attached_at=time.monotonic()
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            edge=ControllerExecutor(port=server.server_port,attach_timeout=1)
            adapter=ControllerAdapter(edge,context=peer['context'],owner=peer['fences']['owner'],epoch=1,now=server.store.now)
            native_sends=[]
            def extension(path,value):
                req=Request(edge.base+path,data=json.dumps(value).encode(),headers={'Content-Type':'application/json','Origin':server.extension_origin})
                with urlopen(req,timeout=3) as r:return json.load(r)
            receipt=next(s['response'] for s in self.samples if s['command']['operation']=='bid' and s['response']['success'])
            def worker():
                for _ in range(100):
                    c=extension('/next',peer)
                    if c:
                        native_sends.append(c)
                        value=deepcopy(receipt);value.update(command_id=c['id'],context=c['context'],fences=c['fences'])
                        value['network'][0]['targets']=[c['params']['target']]
                        extension('/result',dict(peer=peer,id=c['id'],result=value));return
                    time.sleep(.005)
                raise AssertionError('no mutation claimed')
            try:
                c=self.decision(server.store,peer,group)
                native=threading.Thread(target=worker);native.start()
                outcome=adapter.deliver(c['id'],c['params']);native.join()
                self.assertEqual(outcome['outcome'],'ACKNOWLEDGED')
                self.assertFalse(outcome['independently_confirmed'])
                self.assertEqual(len(native_sends),1)
                # Lost ACK / repeated caller and disguised new command IDs cannot resend.
                self.assertEqual(adapter.deliver(c['id'],c['params'])['outcome'],'UNKNOWN')
                self.assertEqual(adapter.deliver(hexid(1998),c['params'])['outcome'],'UNKNOWN')
                self.assertIsNone(extension('/next',peer));self.assertEqual(len(native_sends),1)
                self.assertEqual(server.store.db.execute('SELECT count(*) FROM c4_tombstones').fetchone()[0],1)
            finally:server.shutdown();thread.join();server.server_close()

    def test_c5_legacy_page_status_and_worker_compatibility(self):
        for suite in ['production_page_checks.cjs','native_status_checks.cjs','production_worker_checks.cjs','production_bid_receipt_checks.cjs']:
            with self.subTest(suite=suite):
                p=subprocess.run(['node','tests/'+suite],cwd=ROOT,capture_output=True,text=True,timeout=45)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)


if __name__=='__main__':unittest.main(verbosity=2)
