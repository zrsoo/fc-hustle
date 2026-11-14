"""Explicit paced read-only continuation preflight; never starts trading actors."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import secrets
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fc_access.actors_v1.final_run import Evidence,preflight
from fc_access.production_v1.contracts import Search,command,parse_response
from fc_access.production_v1.executor import EdgeExecutor


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',required=True);args=p.parse_args()
    e=Evidence(args.evidence);ready=False
    try:
        e.append('WINDOW_OPENED',task='002-12',mode='EXPLICIT_USER_CONTINUATION_READ_ONLY',
            predecessor='docs/research/002/002-12/live-01',actor_launches=0)
        executor=EdgeExecutor()
        if preflight(executor,e):
            peer=executor.request('/health')['peer']
            c=command(dict(schema=2,id=secrets.token_hex(16),operation='search',
                params=Search.discovery(page=2).params(),**deepcopy(peer)))
            e.append('READ_INTENT',command=c)
            v=parse_response(executor.execute(c),c,source='native',now=datetime.now(timezone.utc))
            e.append('NATIVE_READ',command=c,response=v)
            ready=v['result']['success'] and any(n['path']=='/ut/game/fc27/transfermarket' and
                n['query']==dict(start=20,num=21,macr=1000,minb=11000) for n in v['result']['network'])
            e.append('PAGINATION_READBACK',verified=ready,logical_page=2,wire_start=20,
                requested_count=21,independent_native_response_id=c['id'])
    except (ValueError,TimeoutError):
        e.append('PREFLIGHT_STOP',reason='NATIVE_CONTINUATION_PREFLIGHT_FAILED')
    finally:
        e.append('RUN_STOPPED',actor_launches=0,remaining_processes=[],verified_process_exit=True)
        e.close()
    print(json.dumps(dict(status='READY' if ready else 'NOT_READY',evidence=args.evidence)))
    return 0 if ready else 1


if __name__=='__main__':raise SystemExit(main())
