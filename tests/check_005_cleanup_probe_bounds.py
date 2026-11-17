"""Deterministic offline verification of finite cleanup dispatch limits."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from probe_005_clear_lost import Bounded
from fc_access.controller_v1.semantic import SemanticHealth
records=[]
class Edge:
    def execute(self,c):records.append(('sent',c));return {'offline':True}
def make():return Bounded(Edge(),lambda kind,**fields:records.append((kind,fields)),SemanticHealth(clock=lambda:0),clock=lambda:0)
def blocked(b,op):
    n=len(records)
    try:b.execute({'operation':op})
    except ValueError:assert len(records)==n
    else:raise AssertionError('scope_not_enforced')
b=make();b.execute({'operation':'clear_lost'});assert records[0][0]=='RESERVED_BEFORE_DELIVERY';blocked(b,'clear_lost')
for op in ('bid','move','list','clear_sold','relist_all'):blocked(make(),op)
b=make()
for _ in range(4):b.execute({'operation':'watched'})
blocked(b,'watched')
b=make();b.deadline=0;blocked(b,'watched')
b=make();b.semantic.reason='PERSISTENT_AUTH_FAILURE';blocked(b,'watched')
print('PASS OFFLINE cleanup limits: one mutation,four commands,deadline,semantic stop,pre-dispatch reservation,forbidden operations')
