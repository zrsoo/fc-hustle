"""Render the strategy report from analysis.json into an HTML page (no I/O to EA)."""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'private-captures/market-research'
OUT = ROOT/'experiments/market_research/report.html'

# Assumptions stated in the report.
A_BANDS = ('b1k_m11k', 'b3k_m20k', 'b5k_m30k')
A_MARGIN = 500
A_SEARCHES = 220          # discovery every ~2 min per band + card pricing (cached 45 min)
B_SEARCHES = 280
AVAIL_LO, AVAIL_HI = 0.22, 0.60   # share of underpriced listings we would actually get
GAP_REAL = 0.64           # share of price-check gaps confirmed real (9 of 14 traced)
HOURS_PER_DAY = 20


def fmt(v):
    return f'{int(round(v)):,}'


def k(v):
    return f'{v/1000:.1f}k' if v >= 1000 else fmt(v)


def main():
    d = json.loads((BASE/'analysis.json').read_text())
    db = sqlite3.connect((BASE/'research.sqlite').resolve().as_uri()+'?mode=ro', uri=True)
    searches_ok = db.execute("SELECT count(*) FROM reads WHERE op='search' AND ok=1").fetchone()[0]
    first_throttle = db.execute("SELECT min(at) FROM reads WHERE op='search' AND ok=0 AND error='service_failed'").fetchone()[0]
    span = db.execute("SELECT min(at), max(at) FROM reads WHERE ok=1").fetchone()
    cards = db.execute('SELECT count(DISTINCT definition_id) FROM rows').fetchone()[0]
    trades = db.execute('SELECT count(DISTINCT trade_id) FROM rows').fetchone()[0]
    outcomes = db.execute('SELECT count(*) FROM track WHERE done=2').fetchone()[0]
    cleared = db.execute("SELECT body FROM events WHERE kind='SEARCH_THROTTLE_CLEARED' ORDER BY rowid DESC LIMIT 1").fetchone()
    balance = db.execute("SELECT body FROM events WHERE kind='BALANCE' ORDER BY rowid DESC LIMIT 1").fetchone()
    balance = json.loads(balance[0])['credits'] if balance else None
    pr, au, h = d['projections'], d['auctions'], d['controller_history']
    calib = pr['calibration']['factor']

    # A: auction flipping in value bands
    bands = {b['band']: b for b in pr[f'auction_flip_margin_{A_MARGIN}']['bands']}
    a_likely = sum(bands[b]['coins_per_hour_likely'] for b in A_BANDS if b in bands)
    a_cal = a_likely*calib
    a_wins = sum(bands[b]['wins_per_hour'] for b in A_BANDS if b in bands)
    a_per_k = a_cal/A_SEARCHES*1000
    # B: underpriced BIN capture (high-value snipe + price-check gaps)
    v2 = d['snipe']['v2_high_value']
    b_hits_k = (v2['real_per_100_probes'] or 0)*10
    b_lo_k = b_hits_k*AVAIL_LO*(v2['median_profit_real'] or 0)
    b_hi_k = b_hits_k*AVAIL_HI*(v2['avg_profit_real'] or 0)
    sp = d['spreads']
    c_gaps_k = 1000/2.3*(sp['share'] or 0)*GAP_REAL
    c_lo_k = c_gaps_k*AVAIL_LO*(sp['median_profit'] or 0)
    c_hi_k = c_gaps_k*AVAIL_HI*(sp['median_profit'] or 0)
    b_lo, b_hi = min(b_lo_k, c_lo_k)*B_SEARCHES/1000, max(b_hi_k, c_hi_k)*B_SEARCHES/1000
    v1 = d['snipe']['v1_all_values']
    v1_k = (v1['real_per_100_probes'] or 0)*10*(v1['available_share'] or 0)*(v1['median_profit_real'] or 0)
    combo_lo, combo_hi = a_cal+b_lo, a_likely+b_hi

    rows = [
        ('Auction flipping, 6k–20k cards', 'Recommended', 'good', a_cal, a_likely, f'~{A_SEARCHES}/h', 'Search-light; bids and status reads are not searches.'),
        ('Underpriced Buy Now capture, 10k+ cards', 'Add-on', 'warn', b_lo, b_hi, f'~{B_SEARCHES}/h', 'Every hit costs searches; most fresh underpricings are bought within seconds.'),
        ('Buy Now sniping, all values', 'Skip', 'bad', v1_k*0.96*0.5, v1_k*0.96, '~960/h', 'Half the hits were the price moving, not a bargain.'),
        ('Per-card ending-soon auctions', 'Skip', 'bad', 0, 0, '—', f"{au['card']['strategy']['500:cap']['win_rate']*100:.1f}% of auctions closed below a profitable cap."),
        ('Cheap bands (bid ≤ 400, sub-1k cards)', 'Skip', 'bad', 0, 0, '—', 'No profitable close at any margin; 32% sell-through.'),
        ('Time-of-day buy low / sell high', 'Skip', 'bad', 0, 0, '—', 'Hourly price index moved ±1.3% (13–20 UTC); the 5% tax is larger.'),
    ]
    scale = max(r[4] for r in rows)*1.08 or 1

    def bar(lo, hi):
        if hi <= 0:
            return '<div class="bar none">no positive return measured</div>'
        lo_w, hi_w = lo/scale*100, hi/scale*100
        return (f'<div class="bar"><span class="rng" style="width:{hi_w:.1f}%"></span>'
                f'<span class="cal" style="width:{lo_w:.1f}%"></span>'
                f'<span class="lab">{k(lo)} – {k(hi)} / h</span></div>')

    table = '\n'.join(
        f'<tr><td><span class="pill {cls}">{tag}</span></td><td class="name">{name}<div class="note">{note}</div></td>'
        f'<td class="chart">{bar(lo, hi)}</td><td class="num">{srch}</td></tr>'
        for name, tag, cls, lo, hi, srch, note in rows)

    band_rows = '\n'.join(
        f"<tr><td>{b}</td><td class='num'>{fmt(bands[b]['market_median'])}</td><td class='num'>{bands[b]['flow_per_hour']}</td>"
        f"<td class='num'>{au[b]['contested_share']*100:.0f}%</td><td class='num'>{bands[b]['win_rate']*100:.1f}%</td>"
        f"<td class='num'>{fmt(bands[b]['coins_per_hour_likely']*calib)} – {fmt(bands[b]['coins_per_hour_likely'])}</td></tr>"
        for b in ('b1k_m11k', 'b3k_m20k', 'b5k_m30k', 'b8k_m40k', 'b15k_m60k', 'b20k_m100k') if b in bands and b in au)

    lv = d['listings']['by_value']
    sales = d['sales']['sale_over_lowest_bin']
    flow = d['flow']
    tod = d['time_of_day']['hourly_index']
    tod_lo = min(v['index'] for v in tod.values()); tod_hi = max(v['index'] for v in tod.values())
    throttle_note = (f"Searches came back after {json.loads(cleared[0])['minutes']} minutes." if cleared else
                     'Searches were still refused at the last probe; the sampler kept probing once every 15 minutes.')

    html = f'''<title>FC27 Strategy Study</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap">
<style>
/* Layout: one reading column; a verdict table with range bars up top, strategy sections below, method last. */
:root {{
  --bg: #f5f7f6; --surface: #ffffff; --fg: #15201c; --muted: #5b6a64; --line: #dbe2df;
  --accent: #1d6b52; --accent-soft: #cfe6dc; --warn: #a86a12; --warn-soft: #f4e3c4; --bad: #9a3b33; --bad-soft: #f3d9d5;
  --display: "Archivo", "Segoe UI", system-ui, sans-serif; --text: "Inter", "Segoe UI", system-ui, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #0f1513; --surface: #161e1b; --fg: #e3ebe7; --muted: #95a59e; --line: #2a3531;
  --accent: #5fc39c; --accent-soft: #1f3a30; --warn: #e0a54a; --warn-soft: #3a2d17; --bad: #e58a80; --bad-soft: #3b211e; color-scheme: dark }} }}
:root[data-theme="dark"] {{
  --bg: #0f1513; --surface: #161e1b; --fg: #e3ebe7; --muted: #95a59e; --line: #2a3531;
  --accent: #5fc39c; --accent-soft: #1f3a30; --warn: #e0a54a; --warn-soft: #3a2d17; --bad: #e58a80; --bad-soft: #3b211e; color-scheme: dark }}
body {{ background: var(--bg); color: var(--fg); font: 15px/1.6 var(--text); }}
main {{ max-width: 980px; margin: 0 auto; padding-block: 40px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 40px; }}
h1, h2, h3 {{ font-family: var(--display); text-wrap: balance; line-height: 1.2; margin: 0; }}
h1 {{ font-size: 2.1rem; font-weight: 700; letter-spacing: -0.01em; }}
h2 {{ font-size: 1.35rem; font-weight: 700; }}
h3 {{ font-size: 1.05rem; font-weight: 600; }}
p {{ margin: 0; max-width: 68ch; }}
section {{ display: grid; gap: 14px; min-width: 0; }}
.eyebrow {{ font: 600 0.72rem/1 var(--mono); letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }}
.lede {{ font-size: 1.05rem; color: var(--fg); }}
.muted {{ color: var(--muted); }}
.num, .mono {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}
.wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.92rem; }}
th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
tr:last-child td {{ border-bottom: 0; }}
th {{ font: 600 0.72rem/1.3 var(--mono); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }}
td.num {{ text-align: right; white-space: nowrap; }}
td.name {{ font-weight: 600; min-width: 200px; }}
.note {{ font-weight: 400; color: var(--muted); font-size: 0.85rem; margin-top: 2px; }}
td.chart {{ min-width: 260px; width: 42%; }}
.pill {{ display: inline-block; font: 600 0.7rem/1 var(--mono); letter-spacing: 0.05em; text-transform: uppercase; padding: 5px 8px; border-radius: 999px; white-space: nowrap; }}
.pill.good {{ background: var(--accent-soft); color: var(--accent); }}
.pill.warn {{ background: var(--warn-soft); color: var(--warn); }}
.pill.bad {{ background: var(--bad-soft); color: var(--bad); }}
.bar {{ position: relative; height: 26px; border-radius: 6px; background: color-mix(in srgb, var(--line) 45%, transparent); }}
.bar .rng {{ position: absolute; inset: 0 auto 0 0; background: var(--accent-soft); border-radius: 6px; }}
.bar .cal {{ position: absolute; inset: 0 auto 0 0; background: var(--accent); border-radius: 6px; }}
.bar .lab {{ position: absolute; left: 8px; top: 50%; transform: translateY(-50%); font: 600 0.78rem/1 var(--mono); color: var(--fg);
  background: color-mix(in srgb, var(--surface) 80%, transparent); padding: 3px 5px; border-radius: 4px; }}
.bar.none {{ display: flex; align-items: center; padding: 0 10px; font-size: 0.8rem; color: var(--muted); }}
.legend {{ display: flex; flex-wrap: wrap; gap: 16px; font-size: 0.82rem; color: var(--muted); }}
.legend i {{ display: inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -1px; margin-right: 6px; }}
.facts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
.fact {{ background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; display: grid; gap: 6px; min-width: 0; }}
.fact .big {{ font: 600 1.35rem/1.1 var(--mono); font-variant-numeric: tabular-nums; }}
.strategy {{ border-top: 1px solid var(--line); padding-top: 18px; display: grid; gap: 10px; }}
.strategy dl {{ display: grid; grid-template-columns: 170px 1fr; gap: 6px 16px; margin: 0; }}
.strategy dt {{ color: var(--muted); font-size: 0.85rem; }}
.strategy dd {{ margin: 0; min-width: 0; }}
ol, ul {{ margin: 0; padding-left: 1.2em; max-width: 72ch; display: grid; gap: 6px; }}
code {{ font-family: var(--mono); font-size: 0.86em; background: color-mix(in srgb, var(--line) 50%, transparent); padding: 1px 5px; border-radius: 4px; }}
@media (max-width: 640px) {{ .strategy dl {{ grid-template-columns: 1fr; }} h1 {{ font-size: 1.7rem; }} }}
</style>
<main>
<header style="display:grid;gap:10px">
  <div class="eyebrow">FC27 transfer market · read-only study · 19 Nov 2026</div>
  <h1>FC27 Strategy Study</h1>
  <p class="lede">Which trading strategies make coins on this account, measured from {fmt(searches_ok)} live market searches and {fmt(outcomes)} tracked auction and listing outcomes, with no bids, purchases or listings made.</p>
</header>

<section>
  <h2>Bottom line</h2>
  <p>Auction flipping stays the best strategy, but in a wider set of bands than the bot used: cards worth about 6k to 20k, bidding up to a cap of the lowest Buy Now price minus tax and a 500 margin. Calibrated to the bot's real win rate, that is about <b>{k(a_cal)} coins an hour</b>, up to about {k(a_likely)} if the bot won as often as the model says. Buying underpriced Buy Now listings of 10k+ cards adds roughly {k(b_lo)}–{k(b_hi)} an hour but spends the scarce resource, searches. Together that is about <b>{k(combo_lo*HOURS_PER_DAY)}–{k(combo_hi*HOURS_PER_DAY)} coins over a {HOURS_PER_DAY}-hour day</b>, against the {fmt(h['won'])} wins and about 1.2k realized profit the bot made so far.</p>
  <p>The hard limit is EA's search throttle: after {fmt(searches_ok)} searches in about 7 hours, every search returned HTTP 429. Any plan has to stay well under ~800 searches an hour.</p>
</section>

<section>
  <div class="eyebrow">Projected coins per hour, after 5% tax</div>
  <div class="legend"><span><i style="background:var(--accent)"></i>Calibrated to the live bot</span><span><i style="background:var(--accent-soft)"></i>Up to the model's likely case</span></div>
  <div class="wrap"><table>
    <thead><tr><th>Verdict</th><th>Strategy</th><th>Coins / hour</th><th style="text-align:right">Searches</th></tr></thead>
    <tbody>{table}</tbody>
  </table></div>
</section>

<section>
  <h2>What the market data says</h2>
  <div class="facts">
    <div class="fact"><span class="eyebrow">Lowest Buy Now clears</span><span class="big">{sales['0.5']:.2f}×</span><span class="muted">Median sale price over the lowest Buy Now at the time, across {fmt(d['sales']['n'])} observed sales. The lowest listing is a fair resale price.</span></div>
    <div class="fact"><span class="eyebrow">Sells within 10 min</span><span class="big">{lv['10-50k']['sold_share']*100:.0f}%</span><span class="muted">Share of the cheapest listings of 10k–50k cards bought within about 10 minutes. 2–10k: {lv['2-10k']['sold_share']*100:.0f}%; under 2k: {lv['<2k']['sold_share']*100:.0f}%.</span></div>
    <div class="fact"><span class="eyebrow">Auctions get extended</span><span class="big">{au['b1k_m11k']['contested_share']*100:.0f}–{au['b8k_m40k']['contested_share']*100:.0f}%</span><span class="muted">Value-band auctions still running after their deadline because a late bid added up to 30 seconds. It happened as often when no bid was in 2–5 minutes before the end (74%) as when one was (75%): when the first bid lands does not change the war.</span></div>
    <div class="fact"><span class="eyebrow">Search throttle</span><span class="big">~{fmt(searches_ok)}</span><span class="muted">Searches before EA answered every search with HTTP 429 (from {first_throttle[11:16] if first_throttle else '?'} UTC). Status reads still worked. {throttle_note}</span></div>
    <div class="fact"><span class="eyebrow">Auction supply</span><span class="big">{flow['b1000_m11000']['per_hour_median']}+{flow['b3000_m20000']['per_hour_median']}+{flow['b5000_m30000']['per_hour_median']}/h</span><span class="muted">Auctions ending per hour in the three recommended bands. Supply, not speed, caps auction flipping.</span></div>
    <div class="fact"><span class="eyebrow">No time-of-day edge</span><span class="big">{(tod_lo-1)*100:+.1f}% to {(tod_hi-1)*100:+.1f}%</span><span class="muted">Hourly price index of {d['time_of_day']['cards']} repeatedly priced cards, 13–20 UTC. Overnight was not covered.</span></div>
  </div>
</section>

<section>
  <h2>Strategies</h2>

  <article class="strategy">
    <h3>1 · Auction flipping in the 6k–20k bands <span class="pill good">Recommended</span></h3>
    <dl>
      <dt>How it works</dt><dd>Find auctions whose current bid is far below the card's lowest Buy Now, bid at most <code>lowest BIN × 0.95 − margin</code>, list wins one tick under the lowest Buy Now. This is the current bot widened from one band to three.</dd>
      <dt>Run it</dt><dd>Reuse the controller. Rotate discovery over the bands <code>(max_bid 1k, min_buy 11k)</code>, <code>(3k, 20k)</code>, <code>(5k, 30k)</code>; price each card once per 45 minutes; rebid up to the cap until the auction closes, since extensions run every war to the highest cap. When the first bid lands made no measurable difference, so bidding only in the last minutes just saves requests and keeps coins free. Skip auctions with more than 8 hours left; keep the existing maintenance phase for listing.</dd>
      <dt>Numbers</dt><dd>At margin {A_MARGIN}: ~{a_wins:.0f} modelled wins an hour, {k(a_cal)}–{k(a_likely)} coins an hour. The model predicted {pr['calibration']['model_win_rate']*100:.1f}% wins in the bot's old band, and the bot really won {pr['calibration']['real_win_rate']*100:.1f}% ({h['won']} of {h['won']+h['lost']}), so the low end is scaled by {calib:.2f}.</dd>
      <dt>Risks</dt><dd>The 461 bid denials the live bot hit are still unexplained and would cut this directly. The gap between the model and the bot's real win rate is not explained yet (denials, rebid latency across many auctions, or the model). Margin 300 gives a similar total with more, smaller wins.</dd>
    </dl>
    <div class="wrap"><table>
      <thead><tr><th>Band (max bid / min Buy Now)</th><th style="text-align:right">Typical card</th><th style="text-align:right">Auctions / h</th><th style="text-align:right">Extended</th><th style="text-align:right">Model win rate</th><th style="text-align:right">Coins / h</th></tr></thead>
      <tbody>{band_rows}</tbody>
    </table></div>
  </article>

  <article class="strategy">
    <h3>2 · Underpriced Buy Now capture, 10k+ cards <span class="pill warn">Add-on</span></h3>
    <dl>
      <dt>How it works</dt><dd>Someone lists a card well below its going price; buy it instantly and relist one tick under the second-cheapest listing. Nearly every real case was a listing under two minutes old.</dd>
      <dt>Run it</dt><dd>For ~40 liquid cards worth 10k–200k, search with <code>max_buy = second-lowest BIN × 0.95 − max(300, 3%)</code>; any result is a candidate. Needs a new Buy Now purchase operation in the extension and controller, which does not exist today.</dd>
      <dt>Numbers</dt><dd>{v2['real_per_100_probes']:.1f} real bargains per 100 searches, average profit {fmt(v2['avg_profit_real'] or 0)}, but only {v2['available_share']*100:.0f}% were still buyable 3–12 seconds later. Price checks found the same pattern in {sp['share']*100:.1f}% of reads (median gap {fmt(sp['median_profit'] or 0)}). At ~{B_SEARCHES} searches an hour: {k(b_lo)}–{k(b_hi)} coins an hour.</dd>
      <dt>Risks</dt><dd>Competing snipers react within seconds; our latency decides the real share. Every probe spends search budget.</dd>
    </dl>
  </article>

  <article class="strategy">
    <h3>3 · What did not pay <span class="pill bad">Skip</span></h3>
    <ul>
      <li><b>Buy Now sniping across all values:</b> {v1['real_per_100_probes']:.1f} real hits per 100 searches at a median {fmt(v1['median_profit_real'] or 0)} profit; most apparent bargains were the price moving.</li>
      <li><b>Per-card auctions ending soon:</b> {au['card']['sold_rate']*100:.0f}% of such listings sell at all, and almost none close below a profitable cap.</li>
      <li><b>Cheap bands and bronze/silver cards:</b> zero profitable closes at any margin; sub-2k cards sell {lv['<2k']['sold_share']*100:.0f}% of the time within 10 minutes. Apparent bargains there were cards with one or two listings and no real price.</li>
      <li><b>Time of day:</b> the hourly index stayed within ±1.3%; individual cards swing more (median {d['time_of_day']['max_swing_after_tax']['0.5']*100:.1f}% after tax), but not on a schedule you could trade.</li>
      <li><b>Consumables, packs and SBC fodder</b> were not measured: the extension can only search players and rows carry no rating.</li>
    </ul>
  </article>
</section>

<section>
  <h2>Proposed next step</h2>
  <ol>
    <li>Change the controller's acquisition to strategy 1: three bands, rebids up to the cap, an 8-hour auction-length limit, margin 500.</li>
    <li>Cap total searches at ~400 an hour and log every 429, so the throttle cannot stop trading.</li>
    <li>Run it for a day and compare real wins and profit against the {k(a_cal)}–{k(a_likely)} per hour projected here.</li>
    <li>Only then decide on strategy 2, which needs a new purchase operation.</li>
  </ol>
  <p class="muted">Nothing here is implemented. Each step waits for your go-ahead.</p>
</section>

<section>
  <h2>Method and caveats</h2>
  <ul class="muted">
    <li>Sampling ran {span[0][11:16]}–{span[1][11:16]} UTC on 19 Nov through the reviewed extension, using searches, status reads and one balance read only. {fmt(cards)} distinct cards, {fmt(trades)} distinct listings, {fmt(outcomes)} final outcomes.</li>
    <li>Value is the lowest Buy Now with at least 3 listings at or below it; sales confirmed it clears (median {sales['0.5']:.2f}×). Sale proceeds are one tick under it, minus 5% tax.</li>
    <li>The auction model counts a win when other bidders stopped below our cap and charges the full cap. Auctions extended by late bids before re-reads were added (20:00 UTC) count as losses. The model's win rate is about twice what the bot achieved, which is why the calibrated figure is shown.</li>
    <li>Auction supply per band is the 21 soonest auctions divided by the time until the last one ends; it is a lower bound for busy bands.</li>
    <li>Evening and early-night data only (13:13–20:24 UTC before the throttle). Weekend, promo and morning markets may differ.</li>
    <li>Before the next bot launch: the sampler raised the extension's owner epoch past 120, so start the controller with <code>--epoch-floor</code> above the latest epoch in <code>private-captures/market-research/bridge.sqlite</code>. Account balance at the last read: {fmt(balance or 0)} coins.</li>
  </ul>
</section>
</main>
'''
    OUT.write_text(html, encoding='utf-8')
    print('wrote', OUT, 'combo/day', round(combo_lo*HOURS_PER_DAY), round(combo_hi*HOURS_PER_DAY), 'A', round(a_cal), round(a_likely), 'B', round(b_lo), round(b_hi))


if __name__ == '__main__':
    main()
