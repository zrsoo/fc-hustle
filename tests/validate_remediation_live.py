"""Independent checks of the NEW recorded live responses. Sends no requests."""
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fc_access.production_v1.contracts import stamp
from historical_contracts import parse_response

OUT = ROOT/'docs/research/001d/final-remediation'


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def validate():
    original = json.loads((OUT/'live-checkpoint.json').read_text(encoding='utf-8'))
    final = json.loads((OUT/'valuation-followup.json').read_text(encoding='utf-8'))
    fresh = json.loads((OUT/'fresh-admission.json').read_text(encoding='utf-8'))
    ids, network = set(), []
    for run in (original, final, fresh):
        need(run['phase'] == 'COMPLETED_BOUNDED_OPERATIONS', 'unfinished_live_stage')
        need(run['mode'] == 'LIVE_READ_ONLY' and run['account_mutations'] == 0, 'wrong_live_scope')
        need(run['health_before']['mutations_enabled'] is False, 'mutations_enabled')
        gets = local = 0
        for op in run['operations']:
            c, r = op['command'], op['response']
            need(op['state'] == 'RESPONSE_RECORDED' and c['id'] not in ids, 'ambiguous_or_duplicate_operation')
            ids.add(c['id'])
            parse_response(r, c, now=stamp(r['freshness']['observed_at']), source='native',
                           pricing_rows=c['operation'] == 'search' and c['params']['purpose'] == 'pricing')
            need(r['result']['success'] and c['operation'] != 'bid', 'failed_or_write_operation')
            for n in r['result']['network']:
                need(n['method'] == 'GET' and n['status'] == 200 and n['session_header_present'], 'EA_read_not_verified')
                network.append(n); gets += 1
            local += c['operation'] in {'price_helpers', 'status_support'}
        need(gets == run['reserved_GETs'] <= run['max_GETs'], 'GET_accounting')
        need(local == run['reserved_local'] <= run['max_local'], 'local_accounting')
        searches = [o for o in run['operations'] if o['command']['operation'] == 'search'
                    and o['command']['params']['purpose'] == 'pricing']
        need(len(searches) == (0 if run is fresh else 2), 'third_or_missing_pricing_search')
    need(original['reserved_GETs']+final['reserved_GETs'] == 14 <= final['aggregate_GET_limit'], 'quote_status_budget')
    need(fresh['reserved_GETs'] == fresh['max_GETs'] == 3 and len(network) == 17, 'fresh_admission_budget')
    quote = final['decision']['quote']; evidence = quote['evidence']
    need(quote['completed'] and quote['status'] == 'COMPLETE', 'incomplete_final_quote')
    searches = [o for o in final['operations'] if o['command']['operation'] == 'search'
                and o['command']['params']['purpose'] == 'pricing']
    caps = next(o['response']['result']['caps'] for o in final['operations'] if o['command']['operation'] == 'caps')
    helpers = {(p['direction'], p['value']): p['price'] for o in final['operations']
               if o['command']['operation'] == 'price_helpers' for p in o['response']['result']['probes']}
    seen, accepted, exclusions = {}, [], dict(default_templates=0, candidate=0, duplicate=0)
    for index, op in enumerate(searches):
        params, result = op['command']['params'], op['response']['result']
        need((params['definition_id'], params['page'], params['count']) == (233731, 1, 21), 'wrong_exact_page')
        need(not {'max_bid', 'min_buy'} & params.keys(), 'discovery_filters_in_pricing')
        if index == 0:
            need('max_buy' not in params, 'first_search_bounded')
        else:
            need(params['max_buy'] == evidence['first_min'] == result['network'][0]['query']['maxb'], 'maxb_not_first_min')
        local_prices = []
        for row in result['auctions']:
            if row['trade_id'] == final['decision']['identity']['trade_id'] or row['item']['item_id'] == final['decision']['identity']['item_id']:
                exclusions['candidate'] += 1; continue
            if (row['starting_bid'], row['buy_now_price']) == (600, 10000):
                exclusions['default_templates'] += 1; continue
            if row['trade_state'] != 'active' or row['expires'] <= 0 or row['item']['untradeable'] is not False:
                continue
            need(row['item']['definition_id'] == caps['definition_id'], 'wrong_card')
            price = row['buy_now_price']
            need(caps['minimum'] <= price <= caps['maximum'], 'price_outside_native_caps')
            lower = helpers[('below', price)]
            need(helpers[('above', lower)] == price, 'native_illegal_BIN')
            if index:
                need(price <= params['max_buy'], 'server_exceeded_maxb')
            local_prices.append(price)
            if row['trade_id'] in seen:
                need(seen[row['trade_id']] == (row['item']['item_id'], price), 'conflicting_comparable')
                exclusions['duplicate'] += 1
            else:
                seen[row['trade_id']] = (row['item']['item_id'], price); accepted.append(price)
        if index == 0:
            need(min(local_prices) == evidence['first_min'], 'wrong_first_minimum')
    need(quote['resale_price'] == min(accepted) == 6000 and len(accepted) == evidence['sample_count'] == 35, 'wrong_resale_minimum')
    need(quote['tax'] == 300 and quote['X'] == 500 and quote['max_affordable_bid'] == 5200, 'wrong_economics')
    need(quote['resale_price']-quote['tax']-quote['X'] == quote['max_affordable_bid'], 'profit_cap_not_rounded_down')
    need(helpers[('above', helpers[('below', 5200)])] == 5200, 'illegal_cap')
    hit = final['cache_hit']
    need(hit['completed'] and hit['resale_price'] == 6000 and hit['evidence']['cache_hit'] and
         hit['evidence']['price_searches'] == 0 and 0 <= hit['evidence']['age_seconds'] < 86400, 'cache_not_reused')
    need(final['cache_reopened']['completed'] and final['cache_reopened']['observed_at'] == evidence['observed_at'], 'cache_not_restart_readable')
    before, after = original['fences_before_reconnect'], original['fences_after_reconnect']
    need(before['document'] != after['document'] and after['epoch'] > before['epoch'], 'no_genuine_reconnect')
    need(original['mapping_after_reconnect_before_watched'] == 0, 'old_native_mapping_retained')
    known = original['known_identity']
    for key in ('status_before_reconnect', 'status_after_reconnect'):
        row = original[key]['row']
        need((row['trade_id'], row['item']['item_id']) == (known['trade_id'], known['item_id']), 'status_identity_mismatch')
    watched = [o for o in original['operations'] if o['command']['operation'] == 'watched']
    need(len(watched) == 2, 'missing_fresh_watched_reacquisition')
    for op in watched:
        need(any((r['trade_id'], r['item']['item_id'], r['item']['definition_id']) ==
                 (known['trade_id'], known['item_id'], known['definition_id']) for r in op['response']['result']['auctions']), 'not_same_exact_watched_identity')
    need(final['restart_readable'] == dict(integrity='ok', events=18, bid_commands=0), 'journal_not_durable_or_wrote_bid')
    need(any(e['kind'] == 'DECISION' and e.get('quote') == quote for e in final['registry_events']), 'decision_not_persisted')
    # Slow local helper/recording overhead must HOLD on stale reads, never bid.
    need((final['decision']['action'], final['decision']['reason']) == ('HOLD', 'STALE'), 'stale_safety_not_preserved')
    decision = fresh['decision']; cached = decision['quote']
    need((decision['action'], decision['reason'], decision['amount'], decision['cap']) ==
         ('BID', 'ELIGIBLE', 700, 5200), 'fresh_eligible_decision_missing')
    need(cached['completed'] and cached['resale_price'] == 6000 and cached['evidence']['cache_hit'] and
         cached['evidence']['price_searches'] == 0 and 0 <= cached['evidence']['age_seconds'] < 86400, 'fresh_admission_not_using_cache')
    need(fresh['registry_before_close']['context'] == final['registry_before_close']['context'] and
         fresh['registry_before_close']['scope'] == final['registry_before_close']['scope'], 'scope_changed_after_interruption')
    need(fresh['registry_before_close']['credits']['fresh'] and
         fresh['registry_before_close']['credits']['available_coins'] == 26026, 'fresh_funds_not_verified')
    need(fresh['restart_readable'] == dict(integrity='ok', events=23, bid_commands=0), 'fresh_registry_not_durable_or_sent_bid')
    need(any(e['kind'] == 'DECISION' and e.get('quote') == cached and e.get('reason') == 'ELIGIBLE'
             for e in fresh['registry_events']), 'fresh_decision_not_persisted')
    return dict(status='PASS', actual_GETs=len(network), pricing_searches_per_attempt=[2, 2],
        final_resale=6000, profitable_cap=5200, valid_unique=35, exclusions=exclusions,
        cache_hit_searches=0, known_status_reconnect='PASS', integration_decision='BID_ELIGIBLE_DECISION_ONLY',
        live_account_mutations=0, limits='Observed minimum; live default-template count is zero; no bid eligibility claim from stale reads.')


if __name__ == '__main__':
    print(json.dumps(validate(), indent=2))
