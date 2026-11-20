"""Strategy analysis over research.sqlite (+ the controller's own history).

Prints a summary and writes private-captures/market-research/analysis.json.
All projections are coins/hour BEFORE capacity limits unless stated; the 5% EA
sale tax is always applied. Selling price = lowest observed BIN minus one tick
(undercut), the usual way to sell inside an hour.
"""
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
import statistics as st

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'private-captures/market-research'
TAX = 0.05
MIN_DEPTH = 3


def tick(v):
    return 50 if v < 1000 else 100 if v < 10000 else 250 if v < 50000 else 500 if v < 100000 else 1000


def floor_tick(v):
    v = int(v)
    return 0 if v < 150 else v - v % tick(v)


def ts(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


def q(values, ps=(.1, .25, .5, .75, .9)):
    v = sorted(values)
    if not v: return None
    return {str(p): round(v[min(len(v)-1, int(p*(len(v)-1)+.5))], 3) for p in ps}


class Data:
    def __init__(self):
        self.db = sqlite3.connect((BASE/'research.sqlite').resolve().as_uri()+'?mode=ro', uri=True)
        self.market = defaultdict(list)
        self.depth = {}
        # Liquid valuations only: at least 3 listings at or below the first-page minimum.
        for d, at, price, count in self.db.execute('SELECT definition_id, at, price, count FROM market WHERE price IS NOT NULL ORDER BY at'):
            if (count or 0) >= MIN_DEPTH:
                self.market[d].append((ts(at), price))
        self.first_read, self.last_read = [ts(x) for x in self.db.execute('SELECT min(at), max(at) FROM reads').fetchone()]
        self.hours = max((self.last_read-self.first_read)/3600, 1e-6)

    def price_at(self, d, t, window=3600):
        s = self.market.get(d)
        if not s: return None
        times = [x[0] for x in s]
        i = bisect_left(times, t)
        best = None
        for j in (i-1, i):
            if 0 <= j < len(s) and abs(s[j][0]-t) <= window and (best is None or abs(s[j][0]-t) < abs(best[0]-t)):
                best = s[j]
        return best[1] if best else None


def sale_net(v):
    """Coins received listing at one tick under the lowest BIN, after tax."""
    sale = max(v-tick(v), 200) if v > 200 else v
    return sale*(1-TAX), sale


# ---------------------------------------------------------------- auctions (S1/S4)
def auctions(D):
    out = {}
    rows = D.db.execute('''SELECT t.trade_id, t.definition_id, t.band, t.deadline, t.outcome, r.starting_bid, r.current_bid, r.bin, r.expires
        FROM track t JOIN rows r ON r.read_id=t.source_read AND r.trade_id=t.trade_id
        WHERE t.kind='auction' AND t.done=2''').fetchall()
    by_band = defaultdict(list)
    for trade, d, band, deadline, outcome, sb, cb0, bin_, exp in rows:
        o = json.loads(outcome) if outcome else None
        if not isinstance(o, dict) or o.get('ts') not in ('closed', 'expired', 'active'): continue
        v = D.price_at(d, ts(deadline))
        if o['ts'] == 'active':
            # Extended by a late bid and never re-read (before 20:00 UTC): a contested
            # auction whose final is unknown. Counted as a loss for every strategy.
            by_band[band].append(dict(d=d, v=v, sold=True, final=None, contested=True, start=sb, bin=bin_)); continue
        sold = o['ts'] == 'closed' and (o.get('cb') or 0) > 0
        by_band[band].append(dict(d=d, v=v, sold=sold, final=o.get('cb') if sold else None, start=sb, bin=bin_))
    margins = [0, 100, 200, 300, 500]
    for band, xs in by_band.items():
        priced = [x for x in xs if x['v']]
        res = dict(n=len(xs), priced=len(priced), sold_rate=round(sum(x['sold'] for x in xs)/len(xs), 3) if xs else None,
                   contested_share=round(sum(1 for x in xs if x.get('contested'))/len(xs), 3) if xs else None,
                   final_over_market=q([x['final']/x['v'] for x in priced if x['sold'] and x['final']]),
                   unsold_start_over_market=q([x['start']/x['v'] for x in priced if not x['sold']]),
                   market_median=st.median([x['v'] for x in priced]) if priced else None)
        strat = {}
        for m in margins:
            for mode in ('optimistic', 'cap'):
                wins, profit = 0, 0.0
                for x in priced:
                    net, _ = sale_net(x['v'])
                    cap = floor_tick(net-m)
                    if cap <= 0: continue
                    if x.get('contested'):
                        continue
                    if not x['sold']:
                        pay = x['start']
                        ok = pay <= cap
                    elif mode == 'optimistic':
                        # last-second snipe one tick above the observed final bid
                        pay = x['final']+tick(x['final']); ok = pay <= cap
                    else:
                        # our max bid is what we pay whenever others stop below it
                        ok = x['final'] < cap; pay = cap
                    if ok:
                        wins += 1; profit += net-pay
                strat[f'{m}:{mode}'] = dict(win_rate=round(wins/len(priced), 4) if priced else None,
                                            avg_profit=round(profit/wins) if wins else None,
                                            profit_per_auction=round(profit/len(priced), 1) if priced else None)
        res['strategy'] = strat
        out[band] = res
    return out


def band_flow(D):
    """Auctions ending per hour in each band: page 1 is the 21 soonest; 21/T."""
    flows = defaultdict(list)
    for params, rid in D.db.execute("SELECT params, id FROM reads WHERE job='discovery' AND ok=1"):
        p = json.loads(params)
        exps = [e for (e,) in D.db.execute('SELECT expires FROM rows WHERE read_id=?', (rid,)) if e and e > 0]
        if len(exps) >= 21:
            flows[(p['max_bid'], p['min_buy'])].append(21/max(exps)*3600)
        elif exps:
            flows[(p['max_bid'], p['min_buy'])].append(len([e for e in exps if e <= 3600]))
    return {f'b{k[0]}_m{k[1]}': dict(per_hour_median=round(st.median(v)), reads=len(v)) for k, v in flows.items()}


# ---------------------------------------------------------------- BIN snipe (S2)
SNIPE_V2 = '2026-11-19T18:22'   # high-value set, second-lowest-BIN reference


def snipes(D):
    """Per era: v1 (all values, lowest-BIN reference) and v2 (10k-200k cards,
    second-lowest reference). A hit is validated by the next price read of the
    card (its lowest BIN, or second-lowest if the hit itself is still listed)."""
    out = {}
    for era, lo, hi in (('v1_all_values', '0', SNIPE_V2), ('v2_high_value', SNIPE_V2, '9')):
        probes = D.db.execute("SELECT count(*) FROM reads WHERE job='snipe' AND ok=1 AND at>=? AND at<?", (lo, hi)).fetchone()[0]
        hours = D.db.execute("SELECT (julianday(max(at))-julianday(min(at)))*24 FROM reads WHERE job='snipe' AND at>=? AND at<?", (lo, hi)).fetchone()[0] or 0
        seen, res = set(), []
        for at, d, trade, bin_, ref, follow in D.db.execute(
                'SELECT at, definition_id, trade_id, bin, market, followup FROM hits WHERE at>=? AND at<? ORDER BY at', (lo, hi)):
            if trade in seen: continue
            seen.add(trade)
            f = json.loads(follow) if follow else None
            nxt = D.db.execute('SELECT price, second FROM market WHERE definition_id=? AND at>? ORDER BY at LIMIT 1', (d, at)).fetchone()
            value = None
            if nxt and nxt[0]:
                value = nxt[1] if nxt[0] <= bin_ and nxt[1] else nxt[0]
            value = min(ref, value) if value else ref
            net, _ = sale_net(value)
            res.append(dict(d=d, bin=bin_, ref=ref, value=value, profit=round(net-bin_),
                            taken=isinstance(f, dict) and f.get('ts') == 'closed',
                            available=isinstance(f, dict) and f.get('ts') == 'active'))
        real = [r for r in res if r['profit'] > 0]
        avail = [r for r in real if r['available']]
        known = [r for r in real if r['available'] or r['taken']]
        out[era] = dict(probes=probes, hours=round(hours, 2), unique_hits=len(res), real=len(real),
                        available_after_followup=len(avail), taken_before_followup=sum(r['taken'] for r in real),
                        available_share=round(len(avail)/len(known), 3) if known else None,
                        real_per_100_probes=round(100*len(real)/probes, 2) if probes else None,
                        avg_profit_real=round(st.mean(r['profit'] for r in real)) if real else None,
                        median_profit_real=round(st.median(r['profit'] for r in real)) if real else None,
                        avg_buy_price=round(st.mean(r['bin'] for r in real)) if real else None,
                        examples=sorted(real, key=lambda r: -r['profit'])[:8])
    return out


# ---------------------------------------------------------------- sell-through (S5)
def listings(D):
    rows = D.db.execute('''SELECT t.definition_id, t.band, t.outcome, r.bin, t.deadline, t.source_read
        FROM track t JOIN rows r ON r.read_id=t.source_read AND r.trade_id=t.trade_id
        WHERE t.kind='listing' AND t.done=2''').fetchall()
    by_rank, res = defaultdict(list), []
    for d, wait, outcome, bin_, deadline, src in rows:
        o = json.loads(outcome) if outcome else None
        if not isinstance(o, dict): continue
        v = D.price_at(d, ts(deadline))
        if not v: continue
        sold = o.get('ts') == 'closed'
        rel = bin_/v
        bucket = 'at_min' if rel <= 1.0 else 'le_1tick' if bin_ <= v+tick(v) else 'above'
        by_rank[bucket].append(sold)
        res.append(dict(sold=sold, wait=float(wait), v=v))
    per_min = {}
    for k, v in by_rank.items():
        waits = [r['wait'] for r in res]
        per_min[k] = dict(n=len(v), sold_share=round(sum(v)/len(v), 3))
    price_bands = defaultdict(list)
    for r in res:
        b = '<2k' if r['v'] < 2000 else '2-10k' if r['v'] < 10000 else '10-50k' if r['v'] < 50000 else '50k+'
        price_bands[b].append(r['sold'])
    return dict(by_position=per_min, avg_wait_seconds=round(st.mean(r['wait'] for r in res)) if res else None,
                by_value={k: dict(n=len(v), sold_share=round(sum(v)/len(v), 3)) for k, v in price_bands.items()})


# ---------------------------------------------------------------- spreads (S2b / S6)
def spreads(D, margin=200):
    """Each pricing job (2-3 consecutive searches of one card): the cheapest live
    BINs. A gap L1 << L2 is an underpriced listing that was buyable at read time;
    buying L1 and listing one tick under L2 is the spread/relist trade."""
    jobs = defaultdict(list)
    reads = D.db.execute("SELECT id, at, params FROM reads WHERE job='pricing' AND ok=1 ORDER BY rowid").fetchall()
    cur = None
    for rid, at, params in reads:
        d = json.loads(params)['definition_id']
        if 'max_buy' not in json.loads(params) or cur is None or cur[0] != d:
            cur = (d, rid); jobs[cur] = []
        jobs[cur].append(rid)
    out, opps = [], []
    for (d, first), rids in jobs.items():
        seen = {}
        for rid in rids:
            for trade, bin_, sb, state, exp in D.db.execute('SELECT trade_id, bin, starting_bid, trade_state, expires FROM rows WHERE read_id=?', (rid,)):
                if state == 'active' and bin_ and (sb, bin_) != (600, 10000) and exp and exp > 30:
                    seen[trade] = bin_
        b = sorted(seen.values())
        if len(b) < 3 or b[0] < 1000 or b[2] > 1.1*b[1]: continue  # real price levels only (no bronze asks)
        l1, l2 = b[0], b[1]
        net, _ = sale_net(l2)
        profit = net-l1
        out.append(l1/l2)
        if profit >= margin:
            opps.append(dict(d=d, l1=l1, l2=l2, profit=round(profit)))
    jobs_h = len(out)
    return dict(pricing_jobs=jobs_h, l1_over_l2=q(out, (.02, .05, .1, .25, .5)),
                profitable_gaps=len(opps), share=round(len(opps)/jobs_h, 4) if jobs_h else None,
                avg_profit=round(st.mean(o['profit'] for o in opps)) if opps else None,
                median_profit=round(st.median(o['profit'] for o in opps)) if opps else None,
                examples=sorted(opps, key=lambda o: -o['profit'])[:10])


# ---------------------------------------------------------------- realized sales
def sales(D):
    """Observed sales: tracked listings that closed (bought at BIN) and auctions
    that closed with a bid. Ratio to the lowest BIN at the time = does the
    'market price' actually clear?"""
    ratios, by_kind = [], defaultdict(list)
    for kind, d, deadline, outcome, bin_ in D.db.execute('''SELECT t.kind, t.definition_id, t.deadline, t.outcome, r.bin
            FROM track t JOIN rows r ON r.read_id=t.source_read AND r.trade_id=t.trade_id WHERE t.done=2'''):
        o = json.loads(outcome) if outcome else None
        if not isinstance(o, dict) or o.get('ts') != 'closed' or not o.get('cb'): continue
        v = D.price_at(d, ts(deadline))
        if not v: continue
        price = o['cb'] if kind == 'auction' else bin_
        ratios.append(price/v); by_kind[kind].append(price/v)
    return dict(n=len(ratios), sale_over_lowest_bin=q(ratios),
                by_kind={k: dict(n=len(v), ratio=q(v)) for k, v in by_kind.items()})


# ---------------------------------------------------------------- time of day (S3)
def time_of_day(D):
    idx = defaultdict(list)
    for d, s in D.market.items():
        if len(s) < 6: continue
        med = st.median(p for _, p in s)
        for t, p in s:
            idx[datetime.fromtimestamp(t, timezone.utc).hour].append(p/med)
    hours = {h: dict(n=len(v), index=round(st.median(v), 4)) for h, v in sorted(idx.items()) if len(v) >= 5}
    swings = []
    for d, s in D.market.items():
        if len(s) < 8: continue
        ps = [p for _, p in s]
        lo, hi = min(ps), max(ps)
        swings.append(hi*(1-TAX)/lo-1)
    return dict(hourly_index=hours, cards=len(swings), max_swing_after_tax=q(swings))


# ---------------------------------------------------------------- controller history
def controller_history():
    db = sqlite3.connect((ROOT/'private-captures/controller-v1/controller.sqlite').resolve().as_uri()+'?mode=ro', uri=True)
    last = {}
    for body, res in db.execute("SELECT body,result FROM c4_commands WHERE result IS NOT NULL AND body LIKE '%status_batch%'"):
        c = json.loads(body)
        if c.get('operation') != 'status_batch': continue
        for a in (json.loads(res).get('auctions') or []):
            p = last.get(a['trade_id'])
            if p is None or a['current_bid'] > p['current_bid']: last[a['trade_id']] = a
    members = [(s, json.loads(b)) for s, b in db.execute('SELECT state, body FROM c4_members')]
    lost = [(m['resale_price'], m['cap'], last[m['target']['trade_id']]['current_bid']) for s, m in members
            if s == 'LOST' and m['target']['trade_id'] in last]
    return dict(members=len(members), won=sum(s == 'WON_ACCOUNTED' for s, _ in members), lost=len(lost),
                lost_final_over_resale=q([f/r for r, c, f in lost]),
                lost_final_minus_cap=q([f-c for r, c, f in lost]))


VALUE_BANDS = ('b1k_m11k', 'b3k_m20k', 'b5k_m30k', 'b8k_m40k', 'b15k_m60k', 'b20k_m100k', 'b40k_m150k')
REQUESTS_PER_HOUR = 1200   # 3 s pacing, the sampler's own sustained rate


def projections(out):
    """Coins/hour per strategy. 'likely' uses the pay-our-cap model; 'calibrated'
    scales it by the live bot's real win rate vs the model (b1k_m11k, margin 500);
    'optimistic' assumes a last-second snipe one tick over the final bid."""
    h = out['controller_history']
    a, flow = out['auctions'], out['flow']
    band_key = {f"b{mb}_m{mn}": None for mb, mn in []}
    model_500 = (a.get('b1k_m11k', {}).get('strategy', {}).get('500:cap') or {}).get('win_rate')
    real_500 = h['won']/max(1, h['won']+h['lost'])
    calib = min(1.0, real_500/model_500) if model_500 else 0.7
    res = {}
    for m in (200, 300, 500):
        rows, tot = [], dict(optimistic=0.0, likely=0.0)
        for band in VALUE_BANDS:
            v = a.get(band)
            if not v or v['priced'] < 15: continue
            name = band.replace('b', 'b', 1)
            # flow keys are b<max_bid>_m<min_buy>
            mb, mn = band[1:].split('_m')
            mb = int(mb.replace('k', '000')); mn = int(mn.replace('k', '000'))
            f = (flow.get(f'b{mb}_m{mn}') or {}).get('per_hour_median')
            if not f: continue
            o = v['strategy'][f'{m}:optimistic']['profit_per_auction'] or 0
            c = v['strategy'][f'{m}:cap']['profit_per_auction'] or 0
            wr = v['strategy'][f'{m}:cap']['win_rate'] or 0
            rows.append(dict(band=band, flow_per_hour=f, priced=v['priced'], win_rate=wr,
                             coins_per_hour_likely=round(f*c), coins_per_hour_optimistic=round(f*o),
                             wins_per_hour=round(f*wr, 2), market_median=v['market_median']))
            tot['optimistic'] += f*o; tot['likely'] += f*c
        res[f'auction_flip_margin_{m}'] = dict(bands=rows, optimistic=round(tot['optimistic']), likely=round(tot['likely']),
                                               calibrated=round(tot['likely']*calib))
    for era, sn in out['snipe'].items():
        probes_h = REQUESTS_PER_HOUR*0.8
        rate = (sn['real_per_100_probes'] or 0)/100
        res[f'bin_snipe_{era}'] = dict(probes_per_hour=probes_h, real_hits_per_hour=round(probes_h*rate, 1),
            optimistic=round(probes_h*rate*(sn['avg_profit_real'] or 0)),
            likely=round(probes_h*rate*(sn['available_share'] or 0)*(sn['median_profit_real'] or 0)))
    sn = out['snipe']['v1_all_values']
    sp = out['spreads']
    jobs_h = REQUESTS_PER_HOUR/2.3
    avail = out['snipe']['v2_high_value']['available_share'] or 0.3
    res['spread_capture'] = dict(pricing_jobs_per_hour=round(jobs_h), share=sp['share'],
        likely=round(jobs_h*(sp['share'] or 0)*(sp['median_profit'] or 0)*avail),
        optimistic=round(jobs_h*(sp['share'] or 0)*(sp['avg_profit'] or 0)), availability=round(avail, 2))
    res['calibration'] = dict(real_win_rate=round(real_500, 4), model_win_rate=model_500, factor=round(calib, 2))
    return res


def main():
    D = Data()
    out = dict(hours=round(D.hours, 2), reads=dict(D.db.execute('SELECT job, count(*) FROM reads GROUP BY job').fetchall()),
               priced_cards=len(D.market), flow=band_flow(D), auctions=auctions(D), snipe=snipes(D),
               listings=listings(D), spreads=spreads(D), sales=sales(D), time_of_day=time_of_day(D), controller_history=controller_history())
    out['projections'] = projections(out)
    (BASE/'analysis.json').write_text(json.dumps(out, indent=1, default=str))
    print('written', BASE/'analysis.json')


if __name__ == '__main__':
    main()
