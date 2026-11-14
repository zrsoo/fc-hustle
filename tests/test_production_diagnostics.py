"""Offline boundary diagnostics and immutable historical compatibility replay."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import sys,tempfile,unittest
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.production_v1.store import Store
from fc_access.production_v1.contracts import Search,empty_result,auction
from fc_access.production_v1.diagnostics import result_summary
from native_price_fixture import auction as fixture_auction


class Diagnostics(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.store=Store(Path(self.temp.name)/'state.sqlite');self.addCleanup(self.store.db.close)
  self.now=datetime.now(timezone.utc).isoformat()
  context=dict(account='a'*32,persona='b'*32,identity_namespace='c'*32,platform='pc',game='fc27')
  self.store.activate(dict(context=context,owner='d'*32,epoch=1))
  self.peer=dict(context=context,fences=dict(owner='d'*32,epoch=1,host_epoch=self.store.host_epoch,worker_epoch='e'*32,document='f'*32))
  self.c=dict(schema=2,id='1'*32,operation='search',params=Search.discovery().params(),**deepcopy(self.peer))
  self.store.enqueue(self.c,self.peer);self.store.claim(self.peer)
  r=empty_result(None);r.update(success=True,status=200,auctions=[fixture_auction()],cache_invalidated=True,
   network=[dict(host='utas.test.ea.com',method='GET',path='/ut/game/fc27/transfermarket',query=dict(start=0,num=21,macr=1000,minb=11000),status=200,session_header_present=True)])
  self.value=dict(schema=2,command_id=self.c['id'],operation='search',**deepcopy(self.peer),result=r,
   freshness=dict(observed_at=self.now,network_at=self.now,read_id=self.c['id'],request_count=1,source='native'),
   coverage=dict(complete=False,has_more=False),timing=dict(native_service_ms=10,ea_rtt_ms=5,native_helper_ms=0))

 def test_rejection_reason_survives_validation_rollback_without_forged_ack(self):
  self.value['result']['auctions'][0]['expires']=None
  with self.assertRaisesRegex(ValueError,'invalid_integer'):self.store.finish(self.peer,self.c['id'],self.value)
  self.assertEqual(self.store.db.execute('SELECT state,result FROM commands').fetchone(),('DELIVERED',None))
  event=json.loads(self.store.db.execute('SELECT event FROM events ORDER BY seq DESC LIMIT 1').fetchone()[0])
  self.assertEqual(event['kind'],'RESULT_REJECTED');self.assertEqual(event['reason'],'invalid_integer')
  self.assertEqual(event['summary']['row_shapes'][0]['fields']['expires'],'null')
  self.store.uncertain(self.c['id'])
  self.assertEqual(self.store.db.execute('SELECT state,result FROM commands').fetchone(),('UNKNOWN',None))

 def test_rejected_private_fields_and_malformed_values_never_reach_diagnostic_log(self):
  self.value['result']['password']='SECRET_CANARY'
  with self.assertRaises(ValueError):self.store.finish(self.peer,self.c['id'],self.value)
  text=''.join(r[0] for r in self.store.db.execute('SELECT event FROM events'))
  self.assertNotIn('SECRET_CANARY',text);self.assertNotIn('password',text)
  bad=dict(result=dict(error=['SECRET_CANARY'],network=[dict(method=[],path=['SECRET_CANARY'])]))
  self.assertNotIn('SECRET_CANARY',json.dumps(result_summary(bad,self.c)))

 def test_accepted_result_unchanged_and_trace_is_scoped_strict_and_append_only(self):
  trace=[dict(stage='PAGE_ENTER',at=self.now,detail={})]
  self.store.diagnostic(self.peer,self.c['id'],trace)
  before=self.store.db.execute('SELECT state,result FROM commands').fetchone()
  for bad in ([dict(stage='PAGE_ENTER',at=self.now,detail=dict(token='SECRET'))],trace*65):
   with self.assertRaises(ValueError):self.store.diagnostic(self.peer,self.c['id'],bad)
  self.assertEqual(self.store.db.execute('SELECT state,result FROM commands').fetchone(),before)
  other=deepcopy(self.peer);other['fences']['document']='2'*32
  with self.assertRaises(ValueError):self.store.diagnostic(other,self.c['id'],trace)
  self.store.finish(self.peer,self.c['id'],self.value)
  self.assertEqual(self.store.result(self.c['id']),self.value)
  with self.assertRaisesRegex(Exception,'append_only'):self.store.db.execute('DELETE FROM events')

 def test_successful_historical_native_rows_remain_compatible_without_rewriting_filters(self):
  p=Path('docs/research/001c/001c-06-resume-02/search-2.json');raw=p.read_bytes();v=json.loads(raw)
  rows=v['response']['rows'];self.assertEqual(len(rows),21)
  self.assertEqual(v['response']['network'][0]['query']['minb'],10500)
  for r in rows:
   current={k:r[k] for k in ('trade_id','starting_bid','current_bid','buy_now_price','expires','trade_state','bid_state','native_is_won')}
   current['item']={k:r[k] for k in ('item_id','definition_id','untradeable','last_sale_price')}
   auction(current)
  self.assertEqual(p.read_bytes(),raw) # Captured EA evidence only.

 def test_probe_rejects_writes_wrong_order_extra_commands_and_stopped_window_before_delivery(self):
  from fc_access.production_v1 import diagnose_search as probe
  state=dict(status='RUNNING',deadline_ns=time.monotonic_ns()+10_000_000_000,operations=[])
  executor=probe.DiagnosticExecutor(state)
  with patch.object(probe.EdgeExecutor,'execute',side_effect=AssertionError('no browser call')):
   for op,p in [('bid',{}),('search',Search.discovery().params()),('caps',{'definition_id':123})]:
    with self.assertRaisesRegex(ValueError,'diagnostic_read_only_budget'):executor.execute(dict(operation=op,params=p))
   state['operations']=[{},{}]
   with self.assertRaisesRegex(ValueError,'diagnostic_read_only_budget'):executor.execute(dict(operation='balance',params={}))
   state['status']='DIAGNOSTIC_STOPPED_NO_RETRY'
   with self.assertRaisesRegex(ValueError,'diagnostic_window_stopped'):executor.execute(dict(operation='balance',params={}))

 def test_probe_existing_checkpoint_refuses_before_desktop_service_or_EA(self):
  from fc_access.production_v1 import diagnose_search as probe
  out=Path(self.temp.name)/'evidence';out.mkdir();checkpoint=out/'checkpoint.json';checkpoint.write_text('{"preserved":true}')
  with patch.object(probe,'OUT',out),patch.object(probe,'CHECKPOINT',checkpoint),\
       patch.object(probe.gate,'desktop_preflight',side_effect=AssertionError('no desktop')):
   with self.assertRaises(FileExistsError):probe.run()
  self.assertEqual(json.loads(checkpoint.read_text()),dict(preserved=True))


if __name__=='__main__':unittest.main(verbosity=2)
