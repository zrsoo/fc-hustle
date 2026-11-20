"""One-off: which whole-market discovery filters does the page accept? Read-only."""
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sampler import Bridge
from fc_access.production_v1.contracts import Search

b = Bridge(8784, 4.0, 1)
b.start()
try:
    print('epoch', b.attach(), flush=True)
    for max_bid, min_buy in [(10_000_000, 200), (1_000_000, 0), (15000, 0), (15000, 150), (200, 0)]:
        try:
            v = b.adapter.native.search(secrets.token_hex(16), Search.discovery(page=1, max_bid=max_bid, min_buy=min_buy))
            rows = v['result']['auctions']
            print(max_bid, min_buy, 'ok', len(rows), [(r['current_bid'] or r['starting_bid'], r['buy_now_price'], r['expires']) for r in rows[:5]], flush=True)
        except Exception as e:
            print(max_bid, min_buy, 'fail', e, flush=True)
finally:
    b.close()
