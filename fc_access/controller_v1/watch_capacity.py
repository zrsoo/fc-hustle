"""Native transfer-target slots, including closed entries that still occupy INBOX."""
def slots(observation):
    proof=observation.get('coverage',{}).get('watch_list')
    rows=observation.get('result',{}).get('auctions')
    if observation.get('operation')!='watched' or observation.get('result',{}).get('success') is not True or type(proof) is not dict or type(rows) is not list:
        raise ValueError('native_watch_capacity_required')
    capacity=proof.get('capacity');count=proof.get('repository_count')
    if type(capacity) is not int or not 1<=capacity<=1000 or type(count) is not int or not 0<=count<=100 or proof.get('wire_count')!=count or proof.get('callback_count')!=count or count!=len(rows) or type(proof.get('repository_full')) is not bool or proof['repository_full']!=(count>=capacity):
        raise ValueError('invalid_watch_capacity')
    return max(0,capacity-count)
