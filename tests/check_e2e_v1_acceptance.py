"""Strict live gates, independent from truthful-report/offline test success.

Exit 1 means remaining live evidence is required; never bids, logs in, restarts
or replays the consumed window. --criterion selects a zero-based requirement.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fc_access.e2e_v1.audit import inspect,load
from fc_access.e2e_v1.server import DIRECTORY

def gates(r):
    return [
      (r['mutations']==1 and r['bid_writes']==1 and load(DIRECTORY/'closed.json')['health']['stopped'],'Serialized finite run, immutable reservations and unresolved-write stop verified.'),
      (r['opening']=='LIVE_VERIFIED' and not r['unresolved_bid_commands'],'UNRESOLVED: actual 700 native PUT returned 200/outbid at 750; independent watched readback empty and balance unchanged. Successful opening/escrow not established.'),
      (r['leading_hold']=='LIVE_VERIFIED','UNRESOLVED: no live leading status; no HOLD can be claimed. Offline HOLD/no-extra-write guards pass separately.'),
      (r['competition'].startswith('LIVE_PRICE_ADVANCE') and r['rebid'].startswith('UNVERIFIED') and r['bid_writes']==1,'Observed 0-to-750 price advance; personal outbid/rebid UNVERIFIED. Pending reconciliation prevented a further write.'),
      (len(r['watchlist_refresh_ms'])>0 and r['bid_native_ms']>0 and len(r['expiry_observations'])>=3 and r['timer_extension'].startswith('UNVERIFIED'),'Actual native/dispatch/readback and expiry observations retained; timer extension/25-second queue guarantee unverified.'),
      (r['terminal_outcome']=='UNKNOWN_NOT_LOST' and not r['verified_losses'] and r['confirmed_paid_cost'] is None and r['observed_spendable_delta']==0,'No witnessed terminal state. UNKNOWN preserved; available balances reconciled, held/returned/paid amounts not invented.'),
      (not r['verified_wins'] and r['transfer_mutations']==0 and r['listing_mutations']==0 and r['realized_profit'] is None,'No conclusive won physical item; transfer/list correctly withheld, no sale/profit inferred. Live won-handoff remains unverified.'),
      (len(r['timeline'])==18 and len(r['unresolved_bid_commands'])==1 and r['continuation']['stage_1']['mutations_max']==0,'Every command and observed coin delta accounted; unresolved reservation, absent owned item and exact bounded continuation recorded.')]

def main():
    p=argparse.ArgumentParser();p.add_argument('--criterion',type=int,choices=range(8));a=p.parse_args()
    r=inspect();assert r==load(DIRECTORY/'report.json'),'retained report disagrees with independent derivation'
    result=[{'criterion':i,'status':'PASS' if ok else 'UNRESOLVED','diagnostic':why} for i,(ok,why) in enumerate(gates(r)) if a.criterion is None or i==a.criterion]
    ok=all(x['status']=='PASS' for x in result)
    print(json.dumps({'status':'PASS' if ok else 'UNRESOLVED','checks':result},indent=2));raise SystemExit(0 if ok else 1)
if __name__=='__main__':main()
