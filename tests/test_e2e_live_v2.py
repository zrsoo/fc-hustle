"""Deterministic adversarial checks; no live accounts or EA requests."""
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.e2e_live_v2 import policy
from fc_access.e2e_live_v2.server import Ledger,LIMITS

NOW=1794540000.
def iso(t=NOW):return datetime.fromtimestamp(t,timezone.utc).isoformat()
TRADE='trade:'+'a'*24;ITEM='item:'+'b'*24
def row(**kw):
    return dict(trade_id=TRADE,item_id=ITEM,definition_id=227323,starting_bid=700,current_bid=0,buy_now_price=11000,expires=120,trade_state='active',bid_state='none',untradeable=False,last_sale_price=None,**{})|kw
def response(op,cid='1'*32,rows=None):
    return dict(command_id=cid,operation=op,success=True,persona={'accepted':True},observed_at=iso(),network=[dict(route=policy.ROUTES[op],method='GET',session_header_present=True,status=200,started_at=iso(),ended_at=iso(),query={'macr':1000,'minb':10500})],rows=rows or [],wire_rows=copy.deepcopy(rows or []),credits=20000,caps=[dict(definition_id=227323,minimum=700,maximum=11000)],tiers=[dict(minimum=0,increment=150),dict(minimum=150,increment=50),dict(minimum=1000,increment=100),dict(minimum=10000,increment=250)])
def fixture():
    comps=[row(trade_id='trade:'+f'{i:024x}',item_id='item:'+f'{i:024x}',buy_now_price=6000+i*100) for i in range(1,8)]
    ev={'s':response('search',rows=[row()]),'b':response('balance','2'*32),'c':response('caps','3'*32),'p':response('search','4'*32,comps)}
    p=dict(trade_id=TRADE,item_id=ITEM,definition_id=227323,amount=700,status_id='s',balance_id='b',caps_id='c',comparables_id='p',status_operation='search')
    return ev,p

class PolicyTests(unittest.TestCase):
    def test_first_participation_above_existing_bid_is_minimum_ordinary_entry(self):
        ev,p=fixture();ev['s']['rows'][0].update(current_bid=750);ev['s']['wire_rows']=copy.deepcopy(ev['s']['rows']);p['amount']=800
        en=policy.bid_plan(p,ev,None,NOW)
        self.assertEqual(en['opening_minimum'],800)
        p['amount']=850
        with self.assertRaises(ValueError):policy.bid_plan(p,ev,None,NOW)
    def test_five_fresh_exact_economics_and_ordinary_minimum(self):
        ev,p=fixture();en=policy.bid_plan(p,ev,None,NOW)
        self.assertEqual(en['opening_minimum'],700);self.assertGreater(en['cap'],700);self.assertEqual(en['tax'],en['target']//20)
        self.assertEqual(en['cap'],policy.pricing.floor_price(en['target']-en['tax']-500,policy.rules(ev['c'],227323,NOW)))
    def test_reject_fewer_than_five_wrong_version_duplicate_and_stale(self):
        for mutation in ('few','version','duplicate','stale','no_wire','bad_filter'):
            ev,p=fixture()
            if mutation=='few':ev['p']['rows']=ev['p']['rows'][:4]
            if mutation=='version':
                for r in ev['p']['rows']:r['definition_id']=1
            if mutation=='duplicate':ev['p']['rows']=[ev['p']['rows'][0]]*7
            if mutation=='stale':ev['p']['network'][0]['started_at']=iso(NOW-121)
            if mutation=='bad_filter':ev['s']['network'][0]['query']['macr']=2000
            ev['p']['wire_rows']=copy.deepcopy(ev['p']['rows'])
            if mutation=='no_wire':ev['p']['wire_rows']=None
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):policy.bid_plan(p,ev,None,NOW)
    def test_leading_holds_and_rebid_requires_actual_outbid(self):
        ev,p=fixture();en=policy.bid_plan(p,ev,None,NOW)
        for state in ('highest','none'):
            r=row(current_bid=700,bid_state=state);ev['w']=response('watched','5'*32,[r]);p.update(status_id='w',status_operation='watched',candidate_id='s',amount=750)
            with self.subTest(state=state),self.assertRaises(ValueError):policy.bid_plan(p,ev,en,NOW)
        r=row(current_bid=700,bid_state='outbid');ev['w']=response('watched','5'*32,[r])
        result=policy.bid_plan(p,ev,en,NOW);self.assertLessEqual(result['cap'],en['cap'])
        p['amount']=800
        with self.assertRaises(ValueError):policy.bid_plan(p,ev,en,NOW)
    def test_cap_and_spendable_reserve(self):
        for cash,amount in ((5600,700),(20000,750)):
            ev,p=fixture();ev['b']['credits']=cash;p['amount']=amount
            with self.assertRaises(ValueError):policy.bid_plan(p,ev,None,NOW)
        ev,p=fixture();en=policy.bid_plan(p,ev,None,NOW);en['cap']=700
        ev['w']=response('watched','5'*32,[row(current_bid=700,bid_state='outbid')]);p.update(status_id='w',status_operation='watched',candidate_id='s',amount=750)
        with self.assertRaises(ValueError):policy.bid_plan(p,ev,en,NOW)
    def test_expiry_and_cached_reads_fail(self):
        ev,p=fixture();ev['s']['rows'][0]['expires']=1;ev['s']['wire_rows']=copy.deepcopy(ev['s']['rows'])
        with self.assertRaises(ValueError):policy.bid_plan(p,ev,None,NOW+2)
        ev,p=fixture();ev['s']['network']=[]
        with self.assertRaises(ValueError):policy.bid_plan(p,ev,None,NOW)
    def test_missing_never_loss_win_requires_paid_and_physical_owned(self):
        args=dict(trade=TRADE,item=ITEM,definition=227323)
        self.assertEqual(policy.classify({'rows':[]},{'rows':[]},**args),'UNKNOWN')
        s={'rows':[row(trade_state='closed',bid_state='highest',current_bid=700)]}
        self.assertEqual(policy.classify(s,{'rows':[]},paid=700,**args),'PENDING')
        self.assertEqual(policy.classify(s,{'rows':[row()]},paid=700,**args),'WON')
        self.assertEqual(policy.classify(s,{'rows':[row()]},paid=750,**args),'PENDING')
        s['rows'][0]['bid_state']='outbid';self.assertEqual(policy.classify(s,{'rows':[]},**args),'LOST')
    def test_tick_boundaries(self):
        ev,_=fixture();rr=policy.rules(ev['c'],227323,NOW)
        for current,expected in ((0,700),(700,750),(950,1000),(1000,1100),(9900,10000),(10000,10250)):
            self.assertEqual(policy.minimum(row(current_bid=current),rr),expected)

class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'run.sqlite';self.clock=[NOW];self.l=Ledger(self.path,now=lambda:self.clock[0])
    def tearDown(self):self.l.db.close();self.temp.cleanup()
    def command(self,i=1):return dict(id=f'{i:032x}',stage=f'read-{i}',operation='watched',params={})
    def test_serialized_duplicate_no_redelivery_and_restart_preserves_limits(self):
        c=self.command();self.l.reserve(c)
        with self.assertRaises(ValueError):self.l.reserve(self.command(2))
        self.assertEqual(self.l.claim(),c);self.assertIsNone(self.l.claim())
        deadline=self.l.health()['deadline'];self.l.db.close();self.l=Ledger(self.path,now=lambda:self.clock[0])
        self.assertEqual(self.l.health()['deadline'],deadline);self.assertTrue(self.l.health()['stopped']);self.assertIsNone(self.l.claim())
        self.assertEqual(self.l.health()['reads_reserved'],1)
    def test_exhaustion_and_deadline_persist(self):
        self.l.reserve(self.command());self.l.claim();self.l.db.execute("UPDATE commands SET state='ACKNOWLEDGED'")
        with self.assertRaises(Exception):self.l.reserve(self.command())
        self.clock[0]+=901
        with self.assertRaises(ValueError):self.l.reserve(self.command(2))
        self.assertEqual(self.l.health()['reads_reserved'],1)
    def test_read_limit(self):
        for i in range(40):self.l.reserve(self.command(i));self.l.claim();self.l.db.execute("UPDATE commands SET state='ACKNOWLEDGED'")
        with self.assertRaises(ValueError):self.l.reserve(self.command(41))
    def test_handoff_without_conclusive_ownership_rejected(self):
        c=self.command();c.update(operation='move',params={'item_id':ITEM,'definition_id':227323})
        with self.assertRaises(ValueError):self.l.reserve(c)
        self.assertEqual(self.l.health()['mutations_reserved'],0)
    def test_journal_append_only(self):
        with self.assertRaises(Exception):self.l.db.execute('DELETE FROM events')
        with self.assertRaises(Exception):self.l.db.execute("UPDATE events SET reason='FAKE'")
    def prepare_bid(self):
        ev,p=fixture()
        # Explicit simulated read results in a temporary ledger, never live evidence.
        for i,(key,r) in enumerate(ev.items(),100):
            r['command_id']=key
            self.l.db.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?,?)',(key,key,r['operation'],'{}','ACKNOWLEDGED',NOW,NOW,json.dumps(r)))
        c=dict(id='9'*32,stage='opening',operation='bid',params=p)
        return c
    def test_one_auction_and_pending_ack_block_all_further_writes(self):
        c=self.prepare_bid();self.l.reserve(c);self.l.claim()
        self.l.db.execute("UPDATE commands SET state='ACKNOWLEDGED' WHERE id=?",(c['id'],))
        other=copy.deepcopy(c);other.update(id='8'*32,stage='rebid')
        with self.assertRaisesRegex(ValueError,'reconciliation_required'):self.l.reserve(other)
        self.assertEqual(self.l.health()['mutations_reserved'],1);self.assertEqual(self.l.health()['gross_coins_reserved'],700)
        self.assertEqual(self.l.get('unreconciled'),c['id'])
    def test_ack_without_watched_state_cannot_reconcile(self):
        c=self.prepare_bid();self.l.reserve(c);self.l.claim()
        self.l.db.execute("UPDATE commands SET state='ACKNOWLEDGED',result=? WHERE id=?",(json.dumps({'success':True}),c['id']))
        self.clock[0]+=1
        for key,op in (('w','watched'),('balance','balance')):
            r=response(op,key);r['observed_at']=iso(NOW+1);r['network'][0].update(started_at=iso(NOW+1),ended_at=iso(NOW+1))
            self.l.db.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?,?)',(key,key,op,'{}','ACKNOWLEDGED',NOW+1,NOW+1,json.dumps(r)))
        with self.assertRaisesRegex(ValueError,'exact_physical_identity_required'):self.l.reconcile({'status_id':'w','balance_id':'balance'})
        self.assertEqual(self.l.get('unreconciled'),c['id'])
    def test_mutation_coin_and_per_bid_limits(self):
        c=self.prepare_bid()
        self.l.set('limits',{**LIMITS,'gross_coins':650})
        with self.assertRaisesRegex(ValueError,'bid_limit'):self.l.reserve(c)
        self.assertEqual(self.l.health()['mutations_reserved'],0)
        self.l.set('limits',{**LIMITS,'mutations':0})
        with self.assertRaisesRegex(ValueError,'mutation_limit'):self.l.reserve(c)
    def test_access_challenge_stops_without_replay(self):
        c=self.prepare_bid();self.l.reserve(c);self.l.claim()
        r=json.loads((Path(__file__).resolve().parents[1]/'docs/research/001c/001c-06-resume-02/opening-1.json').read_text())['response']
        r.update(command_id=c['id'],success=False,error='service_failed',status=403)
        r['network'][0].update(status=403,bid_amount=700)
        self.l.finish(c['id'],r)
        self.assertTrue(self.l.health()['stopped']);self.assertIsNone(self.l.claim())
        with self.assertRaises(ValueError):self.l.reserve(self.command(10))
        with self.assertRaises(ValueError):self.l.finish(c['id'],r)
        self.assertEqual(self.l.health()['bid_writes_reserved'],1)
    def test_success_without_actual_bid_amount_stops(self):
        c=self.prepare_bid();self.l.reserve(c);self.l.claim()
        r=json.loads((Path(__file__).resolve().parents[1]/'docs/research/001c/001c-06-resume-02/opening-1.json').read_text())['response']
        r['command_id']=c['id'];r['network'][0]['bid_amount']=None
        self.l.finish(c['id'],r)
        self.assertTrue(self.l.health()['stopped']);self.assertIsNone(self.l.claim())
    def ownership_fixture(self):
        ev,p=fixture();self.l.set('enrollment',{'trade_id':TRADE,'item_id':ITEM,'definition_id':227323});self.l.set('initial_balance',20000)
        for key in ('status','owned'):
            r=response('watched',key,[row(trade_state='closed',bid_state='highest',current_bid=700,native_is_won=True)])
            ev[key]=r
        ev['funds']=response('balance','funds');ev['funds']['credits']=19300
        for key,r in ev.items():
            self.l.db.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?,?)',(key,key,r['operation'],'{}','ACKNOWLEDGED',NOW,NOW,json.dumps(r)))
        return ev,dict(item_id=ITEM,definition_id=227323,paid=700,won_status_id='status',owned_id='owned',owned_operation='watched',balance_id='funds',caps_id='c')
    def test_conclusive_win_allows_one_transfer_but_blocks_duplicate_pending_write(self):
        ev,p=self.ownership_fixture();c=dict(id='7'*32,stage='move',operation='move',params=p)
        self.l.reserve(c);self.assertEqual(self.l.health()['mutations_reserved'],1)
        with self.assertRaises(ValueError):self.l.reserve(dict(id='8'*32,stage='move-again',operation='move',params=p))
    def test_valid_listing_requires_native_owned_win_and_legal_price(self):
        ev,p=self.ownership_fixture();p.update(starting_bid=5900,buy_now_price=6000)
        c=dict(id='7'*32,stage='list',operation='list',params=p)
        bad=copy.deepcopy(c);bad['params']['buy_now_price']=6001
        with self.assertRaisesRegex(ValueError,'illegal_listing_prices'):self.l.reserve(bad)
        bad=copy.deepcopy(ev['owned']);bad['rows'][0]['native_is_won']=False;bad['wire_rows']=copy.deepcopy(bad['rows'])
        self.l.db.execute('UPDATE commands SET result=? WHERE id=?',(json.dumps(bad),'owned'))
        with self.assertRaisesRegex(ValueError,'native_won_ownership_required'):self.l.reserve(c)
        self.l.db.execute('UPDATE commands SET result=? WHERE id=?',(json.dumps(ev['owned']),'owned'))
        self.l.reserve(c);self.assertEqual(self.l.health()['mutations_reserved'],1)
    def test_paid_cost_mismatch_blocks_handoff(self):
        ev,p=self.ownership_fixture();p['paid']=750
        with self.assertRaisesRegex(ValueError,'conclusive_win_required'):self.l.reserve(dict(id='7'*32,stage='move',operation='move',params=p))
        self.assertEqual(self.l.health()['mutations_reserved'],0)

class PageTests(unittest.TestCase):
    def test_actual_javascript_adapter(self):
        r=subprocess.run(['node','tests/e2e_live_v2_page_checks.cjs'],capture_output=True,text=True,timeout=20,cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__':unittest.main(verbosity=2)
