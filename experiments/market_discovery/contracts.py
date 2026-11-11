"""Portable JSON Schema for sanitized observation records (runtime model is stricter)."""
from fc_access.harness import ERRORS, NUMERIC_ITEM_FIELDS


def obj(properties, required=None):
    return {'type':'object','properties':properties,'required':list(properties) if required is None else required,'additionalProperties':False}


def nullable(schema):
    return {'anyOf':[schema,{'type':'null'}]}


def schema():
    number={'type':'integer','minimum':0,'maximum':2**53-1}
    nonnegative={'type':'number','minimum':0}
    item={k:nullable(number) for k in sorted(NUMERIC_ITEM_FIELDS)}
    item.update(item_id={'type':'string','pattern':'^item:[a-f0-9]{24}$'},
                definition_id={'type':'integer','minimum':1,'maximum':2**53-1},
                position=nullable({'enum':['GK','CB','LB','RB','LWB','RWB','CDM','CM','CAM','LM','RM','LW','RW','CF','ST']}),
                untradeable=nullable({'type':'boolean'}))
    auction=obj({'trade_id':{'type':'string','pattern':'^trade:[a-f0-9]{24}$'},'item':obj(item),
                 **{k:nullable(number) for k in ('starting_bid','current_bid','buy_now_price')},
                 'expires':nullable({'type':'integer','minimum':-1,'maximum':2**53-1}),
                 'trade_state':{'enum':[None,'active','closed','expired','inactive']},
                 'bid_state':{'enum':[None,'none','highest','outbid','buyNow','sold']}})
    network=obj({'host':{'type':'string','pattern':r'^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$'},
                 'path':{'type':'string','pattern':r'^/ut/game/fc27/(?:user/credits|user/currencies|transfermarket|club|purchased/items|unassigned|tradepile|usermassinfo)$'},
                 'status':{'type':'integer','minimum':100,'maximum':599},'session_header_present':{'type':'boolean'}})
    result=obj({'status':nullable({'type':'integer','minimum':100,'maximum':599}), 'success':{'type':'boolean'},
                'error':{'enum':sorted(ERRORS)+[None]},'ea_error_code':nullable(number),
                'platform':{'enum':['pc',None]}, 'credits':{'type':'null'},'items':{'type':'null'},
                'auctions':nullable({'type':'array','items':auction,'maxItems':21}),
                'has_more':nullable({'type':'boolean'}),'cache_invalidated':nullable({'type':'boolean'}),
                'network':{'type':'array','items':network,'maxItems':30}})
    criteria=obj({'page':{'enum':[1,2]},'count':{'const':21},'fresh':{'type':'boolean'},
                  **{k:number for k in ('club','league','min_buy','max_buy')},
                  'definition_id':{'type':'integer','minimum':1,'maximum':2**53-1}},['page','count','fresh'])
    timing=obj({k:nullable(nonnegative) for k in ('queue_delivery_ms','worker_poll_to_native_ms','native_service_ms','page_total_ms',
               'result_return_ms','python_compute_ms','time_to_first_result_ms','search_to_intent_ms')},[])
    # Decision structures originate only in local pure Python; external messages cannot supply them.
    estimate=obj({'status':{'type':'string'},'target_sale_price':nullable(number),'acquisition_price':nullable(number),
                  'tax':nullable(number),'expected_profit':nullable({'type':'integer'}),'X':number,'meets_threshold':{'type':'boolean'},
                  'sample_count':number,'rejected':{'type':'array'},'assumptions':{'type':'array','items':{'type':'string'}}})
    decision=obj({'state':{'type':'string'},'intent':{'type':'null'},'estimate':estimate,'python_compute_ms':nonnegative},
                 ['state','intent','python_compute_ms'])
    record=obj({'schema':{'const':1},'mode':{'enum':['SIMULATED','LIVE_READ_ONLY','HISTORICAL_REPLAY']},
                'strategy':{'enum':['A','B','C','HISTORICAL_UNMATCHED']},'window':nullable(number),'slot':nullable(number),
                'game':{'const':'fc27'},'platform':{'const':'pc'},'criteria':criteria,
                'submitted_utc':{'type':'string','format':'date-time'},'completed_utc':{'type':'string','format':'date-time'},
                'elapsed_ms':nonnegative,'network_fresh':{'type':'boolean'},'response_bytes':number,
                'result':result,'timing':timing,'decision':decision})
    record['required'].remove('decision')
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:fc-hustle:market-discovery:observation:1',
            'title':'Sanitized exact-version FC27 PC search observation',**record}
