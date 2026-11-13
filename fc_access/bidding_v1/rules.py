"""Compatibility entry points backed by the production native price service.

No artifact loading or full-market certification authorizes a price.
"""
from fc_access import pricing
from fc_access.production_v1.prices import PriceService, NativePrices
from .contracts import instant
from fc_access.production_v1.pricing import Quote, affordable_cap
from fc_access.production_v1.price_cache import TTL_SECONDS
from fc_access.production_v1.contracts import stamp

RulesProvider = PriceService
NativeRules = NativePrices


def minimum_bid(status, rules):
    if not isinstance(rules, NativePrices):
        raise ValueError('native_price_service_required')
    return rules.minimum_bid(definition_id=status.identity.definition_id,
                             platform=status.identity.platform,
                             starting_bid=status.starting_bid,
                             current_bid=status.current_bid)


def estimate_cap(status, quote, rules, provider, *, now, X=500):
    """Consume a completed production quote; never reprice caller observations."""
    key = pricing.MarketKey(status.identity.definition_id, status.identity.platform)
    prices = provider.validate(rules, key=key, now=now)
    if not isinstance(quote, Quote) or not quote.completed or quote.resale_price is None:
        raise ValueError('completed_quote_required_for_profitable_cap')
    e = quote.evidence
    if ((e['account'], e['game'], e['platform'], e['definition_id'], e['source']) !=
            (prices.context['account'], key.game, key.platform, key.definition_id, prices.source) or
            not 0 <= (instant(now)-stamp(e['observed_at'])).total_seconds() < TTL_SECONDS):
        raise ValueError('quote_context_or_age_mismatch')
    if any(c['row']['trade_id'] == status.identity.trade_id or
           c['row']['item']['item_id'] == status.identity.item_id for c in e['comparables']):
        raise ValueError('candidate_is_not_independent_comparable')
    return quote, affordable_cap(prices, quote.resale_price, X)
