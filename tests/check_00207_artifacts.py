"""Validate the captured synthetic policy timelines by their causal contracts.

No mutable implementation hashes or byte-identity assertions are used.
"""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ARTIFACT=ROOT/'docs/research/002/002-07/timelines.json'


def require(condition, message):
    if not condition:raise AssertionError(message)


def at(event):
    value=datetime.fromisoformat(event['at'])
    require(value.utcoffset() is not None,'timestamp must include UTC offset')
    return value


def validate(document):
    require(document['schema']==1 and document['source']=='synthetic','fixture evidence must be labeled')
    scenarios=document['scenarios']
    require(set(scenarios)=={'lost_release','sold_clear_verified','independent_work','selling_maintenance',
        'simultaneous_limits','restart','projected_reserve'},'required scenario coverage')
    for name,scenario in scenarios.items():
        require(scenario['source']=='synthetic',name+': source')
        registry,journal=scenario['registry'],scenario['journal']
        for timeline in (registry,journal):
            require(bool(timeline),name+': empty timeline')
            seq=[e['seq'] for e in timeline]
            require(seq==sorted(set(seq)),name+': ordered unique event IDs')
            times=[at(e) for e in timeline]
            require(times==sorted(times),name+': chronological events')
        paused=False
        for event in registry:
            reason=event.get('reason')
            if reason not in {'CAPACITY_CHECKED','CAPACITY_PAUSED','CAPACITY_RESUMED'}:continue
            counts,limits,occupancy=event['capacity'],event['limits'],event['occupancy']
            require(1<=limits['unresolved']<=50 and 1<=limits['total']<=50 and 1<=limits['occupied']<=50,
                name+': policy limits')
            require(counts['unresolved']>=0 and counts['pending_resale']>=0,name+': negative count')
            if counts['total'] is not None:
                require(counts['total']==counts['occupied']+counts['pending_resale']+counts['unresolved'],name+': disjoint counts')
            gate=event['capacity_reason']
            expected='DRAINING' if event['draining'] else gate
            require(event['effective_reason']==expected,name+': coin precedence')
            require(event['action']==('HOLD' if expected else 'CONTINUE'),name+': gate action')
            if gate=='QUEUE_FULL':require(counts['unresolved']>=limits['unresolved'],name+': unresolved limit')
            if gate=='PIPELINE_FULL':require(counts['total']>=limits['total'],name+': combined limit')
            if gate is None:
                require(counts['fresh'] and counts['total']<limits['total'] and
                    counts['unresolved']<limits['unresolved'] and occupancy['enrollment_allowed'] and
                    occupancy['occupied']<limits['occupied'],name+': release must be verified and below every limit')
                require(counts['read_id']==occupancy['read_id'],name+': resume uses the validated inventory')
            if reason=='CAPACITY_PAUSED':
                require(gate is not None,name+': pause reason');paused=True
            if reason=='CAPACITY_RESUMED':
                require(paused and gate is None,name+': resume requires an earlier pause');paused=False
        unresolved=set();draining=False
        for event in journal:
            reason=event['reason']
            if reason=='ENROLLED':
                require(not draining,name+': no enrollment during coin drain')
                unresolved.add(event['trade_id'])
            elif reason in {'LOST_VERIFIED','WON_VERIFIED'}:unresolved.discard(event['trade_id'])
            elif reason=='DRAINING':
                draining=True
                require(event['data']['spendable']-event['data']['amount']<=event['data']['target'],name+': reserve trigger')
                require(bool(event['data']['balance_read_id']),name+': coin read provenance')
            elif reason=='DRAINED':
                require(draining and not unresolved,name+': all enrolled auctions must end before coin reset')
                require(event['data']['spendable']>event['data']['target'],name+': future passing reserve check')
                draining=False
    def events(name,reason,kind='registry'):
        return [e for e in scenarios[name][kind] if e.get('reason')==reason]
    for name in ('lost_release','sold_clear_verified','selling_maintenance','restart'):
        resumes=events(name,'CAPACITY_RESUMED')
        require(bool(resumes),name+': missing resume')
        bids=[e for e in scenarios[name]['registry'] if e.get('action')=='BID']
        require(any(e['seq']>resumes[-1]['seq'] for e in bids),name+': actual enrollment decision after resume')
    lost=events('lost_release','LOST_VERIFIED','journal')
    require(bool(lost) and at(lost[0])<=at(events('lost_release','CAPACITY_RESUMED')[0]),'LOST precedes release')
    sold_pauses=events('sold_clear_verified','CAPACITY_PAUSED')
    require(any(e['occupancy']['occupied']==1 for e in sold_pauses),'sold remains physically occupied')
    require(any(e['capacity_reason']=='TRANSFER_LIST_UNKNOWN' for e in sold_pauses),'incomplete clear readback holds')
    sold_resume=events('sold_clear_verified','CAPACITY_RESUMED')[0]
    require(sold_resume['capacity']['total']==0 and sold_resume['occupancy']['coverage']['complete'],
        'sold release requires complete absence')
    simultaneous=events('simultaneous_limits','CAPACITY_CHECKED')
    require(any(e['capacity_reason']=='PIPELINE_FULL' and e['draining'] for e in simultaneous),'simultaneous limits')
    resume=events('simultaneous_limits','CAPACITY_RESUMED')[0]
    require(resume['draining'] and resume['action']=='HOLD','capacity release leaves sticky drain')
    drained=events('simultaneous_limits','DRAINED','journal')
    require(len(drained)==1 and at(drained[0])>at(resume),'later cycle passing reserve resets drain')
    require(events('projected_reserve','DRAINING','journal'),'projected reserve drain')
    require(any(e.get('reason')=='DRAINING' and e.get('action')=='HOLD'
        for e in scenarios['projected_reserve']['registry']),'projected drain explains hold')
    restart_pause=events('restart','CAPACITY_PAUSED')[0]
    restart_resume=events('restart','CAPACITY_RESUMED')[-1]
    require(restart_resume['epoch']>restart_pause['epoch'],'restart history spans epochs')
    require(len(scenarios['independent_work']['bid_amounts'])==3,'opening and two rebids continue across capacity holds')
    require(events('independent_work','CAPACITY_PAUSED'),'independent-work pause evidence')
    return True


if __name__=='__main__':
    document=json.loads(ARTIFACT.read_text(encoding='utf8'))
    validate(document)
    # The validator itself must reject broken causal evidence, rather than merely
    # accepting the fixture label or a claimed success field.
    for corruption in ('remove_resume','clear_coin_precedence','invent_release'):
        changed=deepcopy(document)
        if corruption=='remove_resume':
            s=changed['scenarios']['lost_release']
            s['registry']=[e for e in s['registry'] if e.get('reason')!='CAPACITY_RESUMED']
        elif corruption=='clear_coin_precedence':
            e=next(e for e in changed['scenarios']['simultaneous_limits']['registry']
                if e.get('reason')=='CAPACITY_RESUMED')
            e['effective_reason']=None
        else:
            e=next(e for e in changed['scenarios']['sold_clear_verified']['registry']
                if e.get('reason')=='CAPACITY_RESUMED')
            e['capacity']['total']=1
        try:validate(changed)
        except AssertionError:pass
        else:raise AssertionError('validator accepted '+corruption)
    print(json.dumps(dict(status='PASS',scenarios=len(document['scenarios']),negative_checks=3)))
