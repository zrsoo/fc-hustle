"""All eight bounded-task acceptance checks; no live operations or retries.

PASS means the bounded experiment is truthfully complete. Explicit conditional
live gaps still prevent Objective 002 FULL GO and are emitted as UNVERIFIED.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.e2e_live_v2.audit import inspect,load,FINAL,ROOT,check

def validate():
    r=inspect();check(r==load(FINAL/'report.json'),'retained_summary_disagrees_with_independent_proof')
    check(r['command_timeline']==load(FINAL/'timeline.json'),'aggregate_timeline_changed')
    for name,h in load(FINAL/'manifest.json')['files'].items():check(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h,'sealed_content_changed:'+name)
    bids=[t for t in r['timeline'] if t['operation']=='bid'];hold=[e for e in r['journal_events'] if e['reason']=='HOLD']
    checks=[
      (r['original_limits_preserved'] and len(bids)==1 and all(w['closed'] for w in r['windows']),
       'Serialized, durable finite windows; expiry/ambiguity stopped further writes; closed checkpoints preserved.'),
      (bids[0]['network'][0]['bid_amount']==r['pricing']['opening_minimum']==800 and r['pricing']['estimate']['sample_count']>=5 and r['after_verified_opening_spendable']==r['initial_spendable']-800,
       'Real filtered exact-PC search, 12 comparables, native caps, minimum 800 ordinary entry, independent leading and 800 available-coin debit.'),
      (len(hold)==2 and all(e['data']['bid_writes']==1 and e['data']['additional_write'] is False for e in hold),
       'Two fresh authoritative leading HOLD events, one bid PUT total in that window; no added command or write.'),
      (r['resolution']['state']=='LOST' and r['resolution']['timeline'][0]['rows'][0]['current_bid']>800 and r['active_outbid_rebid'].startswith('LIVE_UNVERIFIED') and len(bids)==1,
       'Genuine competitive price movement and independently witnessed eventual loss; active-outbid/rebid was not witnessed before interruption and remains live-UNVERIFIED.'),
      (all(x>0 for x in r['timing']['bulk_refresh_native_ms']) and r['timing']['bid_native_ms']>0 and len(r['timing']['expiry'])==4 and r['timer_extension']=='LIVE_UNVERIFIED',
       'Actual bulk/dispatch/readback/pre-expiry timings plus terminal expiry retained. Interrupted 25-second sample and timer extension remain live-UNVERIFIED.'),
      (r['resolution']['state']=='LOST' and r['returned_available_coins']==800 and r['final_spendable']==r['initial_spendable']==16268 and r['actual_paid_acquisition_cost']==0 and not r['unresolved_active_bids'],
       'Fresh exact-trade and full-version watched CLOSED/OUTBID prove LOST; observed 800 available-coin recovery, zero acquisition cost. Missing coverage stays UNKNOWN.'),
      (not r['verified_wins'] and r['move_writes']==r['list_writes']==0 and r['won_resale_handoff']=='LIVE_UNVERIFIED_NO_WON_ITEM' and r['completed_sales'] is None and r['realized_profit'] is None,
       'No conclusive WON item: transfer/list correctly withheld; guarded WON/ownership/listing behavior is fixture-tested, live handoff remains UNVERIFIED.'),
      (r['native_requests_total']==len(r['command_timeline'])==44 and r['actual_bid_writes_total']==2 and r['gross_coin_reservations_total']==1500 and r['net_spendable_change']==0 and not r['new_owned_cards'] and bool(r['bounded_continuation']['needed_for_remaining_branches']),
       'All 44 native requests and both bid commands chronologically accounted; zero net spend/new unsold cards, retained historical ambiguity and exact bounded continuation disclosed.')]
    check(all(ok for ok,_ in checks),'acceptance_not_met')
    return r,checks

def main():
    p=argparse.ArgumentParser();p.add_argument('--criterion',type=int,choices=range(8));a=p.parse_args()
    r,checks=validate()
    print(json.dumps({'status':'PASS','scope':r['scope'],'release':r['objective_002_release'],
      'checks':[{'criterion':i,'status':'PASS','evidence':why} for i,(ok,why) in enumerate(checks) if a.criterion is None or a.criterion==i],
      'live_unverified':['active outbid/rebid','timer extension','25-second whole-queue cycle','WON physical-item transfer/list','sale/profit']},indent=2))
if __name__=='__main__':main()
