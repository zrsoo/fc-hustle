"""Finite two-search observed-minimum API. No bidding, loops or undercutting.

The injected fetch(command_id, Search) returns the authoritative protocol-2
response; NativeAdapter.search is the production fetch. NativePrices supplies
current legality. Cached observations do not assert present market availability.
"""
from copy import deepcopy
from dataclasses import dataclass
from .contracts import Search, integer, token, stamp, parse_response, auction as validate_row
from .prices import CardKey, NativePrices


@dataclass(frozen=True)
class Quote:
    status: str
    completed: bool
    resale_price: int | None
    max_affordable_bid: int | None
    tax: int | None
    X: int
    evidence: dict


def affordable_cap(prices, resale_price, X=500):
    integer(resale_price, 1); integer(X)
    if not prices.minimum <= resale_price <= prices.maximum or not prices.legal(resale_price):
        raise ValueError('invalid_resale_price')
    raw = resale_price-resale_price//20-X
    return prices.floor(raw) if raw > 0 else None


def select_comparables(rows, candidate, prices, *, now):
    """Input rows carry network time separately; no statistical price trimming.

    Conflicting trade/item identities poison all their copies. Exact duplicates
    across samples count once; their freshest valid snapshot wins.
    """
    excluded, groups, items = {}, {}, {}

    def reject(reason):
        excluded[reason] = excluded.get(reason, 0)+1

    for wrapped in rows:
        row = wrapped['row']
        try:
            validate_row(row)
        except (ValueError, TypeError, KeyError):
            reject('invalid'); continue
        groups.setdefault(row['trade_id'], []).append(wrapped)
        items.setdefault(row['item']['item_id'], set()).add(row['trade_id'])
    accepted = []
    for trade, copies in sorted(groups.items()):
        if any(c['row']['trade_id'] == candidate['trade_id'] or
               c['row']['item']['item_id'] == candidate['item']['item_id'] for c in copies):
            reject('candidate_excluded'); continue
        identities = {(c['row']['item']['definition_id'], c['row']['item']['item_id'],
                       c['row']['buy_now_price']) for c in copies}
        if len(identities) != 1 or any(len(items[c['row']['item']['item_id']]) > 1 for c in copies):
            reject('conflicting_duplicate'); continue
        valid = []
        for wrapped in copies:
            r = wrapped['row']
            # Validity belongs to each successful sample's read time. The second
            # sample does not retroactively age out a previously valid first BIN.
            checked_at = stamp(wrapped['validated_at']) if 'validated_at' in wrapped else now
            age = (checked_at-stamp(wrapped['network_at'])).total_seconds()
            reason = None
            if r['item']['definition_id'] != prices.key.definition_id:
                reason = 'exact_version_mismatch'
            elif not 0 <= age <= 30:
                reason = 'stale_or_future'
            elif r['trade_state'] != 'active' or r['expires']-age <= 0 or r['bid_state'] not in {'none', 'outbid', 'highest'}:
                reason = 'inactive_or_expired'
            elif r['item']['untradeable'] is not False:
                reason = 'not_tradeable'
            elif (r['starting_bid'], r['buy_now_price']) == (600, 10000):
                reason = 'default_600_10000_template'
            elif not prices.minimum <= r['buy_now_price'] <= prices.maximum:
                reason = 'outside_card_limits'
            elif wrapped.get('max_buy') is not None and r['buy_now_price'] > wrapped['max_buy']:
                reason = 'outside_inclusive_max_buy'
            elif not prices.legal(r['buy_now_price']):
                reason = 'illegal_bin'
            if reason:
                reject(reason)
            else:
                valid.append(wrapped)
        if valid:
            accepted.append(deepcopy(max(valid, key=lambda c: stamp(c['network_at']))))
            if len(valid) > 1:
                excluded['duplicate'] = excluded.get('duplicate', 0)+len(valid)-1
    return accepted, dict(sorted(excluded.items()))


class PricingService:
    def __init__(self, adapter, command_ids, cache, *, fetch=None):
        self.adapter, self.command_ids, self.cache = adapter, command_ids, cache
        self.fetch = fetch or adapter.search

    def quote(self, candidate, prices, *, X=500):
        """Quote one exact candidate; at most two price searches, no retries.

        Candidate status freshness/availability and bid authorization remain the
        caller's separate responsibilities. last_sale_price is diagnostic only.
        """
        integer(X); validate_row(candidate)
        candidate = deepcopy(candidate)
        a = self.adapter
        key = CardKey(candidate['item']['definition_id'], a.context['platform'], a.context['game'])
        if not isinstance(prices, NativePrices) or prices.service.adapter is not a:
            raise ValueError('native_price_service_required')
        prices.check(key)
        minimum = prices.minimum_bid(definition_id=key.definition_id, platform=key.platform,
                                     starting_bid=candidate['starting_bid'], current_bid=candidate['current_bid'])
        base = dict(schema=1, completed=False, source=a.source,
                    identity_namespace=a.context['identity_namespace'], observed_at=None,
                    samples=[], comparables=[], exclusions={}, reasons=[],
                    account=a.context['account'], game=key.game, platform=key.platform,
                    definition_id=key.definition_id, coverage='TWO_FIRST_PAGE_SAMPLES_ONLY',
                    claim='OBSERVED_MINIMUM_ONLY', complete_market_coverage=False)
        used = set()

        def finish(payload, *, completed=False, reason=None, hit=False, resale=None, cap=None):
            e = deepcopy(payload)
            e.update(completed=completed, cache_hit=hit, price_searches=len(used), minimum_legal_bid=minimum,
                     candidate={'trade_id': candidate['trade_id'], 'item_id': candidate['item']['item_id'],
                                'last_sale_price': candidate['item']['last_sale_price']})
            e['age_seconds'] = (a.now()-stamp(e['observed_at'])).total_seconds() if e['observed_at'] else None
            for s in e['samples']:
                s['age_seconds'] = (a.now()-stamp(s['network_at'])).total_seconds() if s.get('network_at') else None
            e['sample_count'] = len(e['comparables'])
            if reason:
                e['reasons'].append(reason)
            status = 'INCOMPLETE'
            if completed or reason == 'minimum_exceeds_first_page_cap':
                status = 'REJECT' if cap is None or minimum is None or minimum > cap else 'COMPLETE'
                if completed and status == 'REJECT':
                    e['reasons'].append('minimum_exceeds_completed_cap')
            return Quote(status, completed, resale, cap, resale//20 if resale else None, X, e)

        cached = self.cache.get(a.context, key.definition_id, now=a.now(), source=a.source)
        if cached is not None:
            # Reuse observations for equivalent cards, never this candidate's ask.
            comps = [c for c in cached['comparables'] if c['row']['trade_id'] != candidate['trade_id'] and
                     c['row']['item']['item_id'] != candidate['item']['item_id']]
            removed = len(cached['comparables'])-len(comps)
            if removed:
                cached['exclusions']['cache_candidate_excluded'] = removed
            cached['comparables'] = comps
            if not comps:
                return finish(cached, hit=True, reason='cache_has_no_independent_comparables')
            resale = min(c['row']['buy_now_price'] for c in comps)
            try:
                cap = affordable_cap(prices, resale, X)
            except (ValueError, TimeoutError):
                return finish(cached, hit=True, reason='native_legality_unavailable')
            return finish(cached, completed=True, hit=True, resale=resale, cap=cap)

        all_rows = []
        for sample_number in (1, 2):
            query = Search.pricing(key.definition_id, first_min if sample_number == 2 else None)
            sample = dict(number=sample_number, success=False, params=query.params(), network_at=None)
            base['samples'].append(sample)
            try:
                cid = token(self.command_ids())
                if cid in used:
                    raise ValueError('duplicate_command_id')
                used.add(cid)
                # Revalidate even injected fetches against the requested contract.
                c = a.envelope(cid, 'search', query.params())
                v = parse_response(self.fetch(cid, query), c, now=a.now(), source=a.source, pricing_rows=True)
                if not v['result']['success']:
                    raise ValueError('search_failed')
                at = v['freshness']['network_at']
                sample.update(success=True, network_at=at, coverage=deepcopy(v['coverage']),
                              returned_count=len(v['result']['auctions']))
                if base['observed_at'] is None:
                    base['observed_at'] = at
                rows = [dict(row=deepcopy(r), network_at=at, validated_at=a.now().isoformat(), max_buy=query.max_buy)
                        for r in v['result']['auctions']]
                all_rows.extend(rows)
                own, own_excluded = select_comparables(rows, candidate, prices, now=a.now())
                sample.update(valid_unique_count=len(own), exclusions=own_excluded)
                accepted, excluded = select_comparables(all_rows, candidate, prices, now=a.now())
                base.update(comparables=accepted, exclusions=excluded)
                sample['combined_unique_count'] = len(accepted)
                if not accepted:
                    return finish(base, reason='no_valid_independent_comparables')
                resale = min(c['row']['buy_now_price'] for c in accepted)
                cap = affordable_cap(prices, resale, X)
            except Exception:
                # No exception text or arbitrary native payload enters evidence.
                sample['success'] = False
                return finish(base, reason='first_search_incomplete' if sample_number == 1 else 'second_search_incomplete')
            if sample_number == 1:
                first_min = resale
                base['first_min'] = first_min
                base['first_page_profit_cap'] = cap
                if minimum is None or cap is None or minimum > cap:
                    return finish(base, reason='minimum_exceeds_first_page_cap', resale=resale, cap=cap)
        base['completed'] = True
        base['reasons'].append('two_successful_samples')
        self.cache.put(a.context, key.definition_id, base)
        return finish(base, completed=True, resale=resale, cap=cap)
