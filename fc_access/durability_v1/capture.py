"""Explicit, one-shot lifecycle read. Existing checkpoints cannot be replayed."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .adapter import parse_durable_response as parse_response

DIRECTORY=Path(__file__).resolve().parents[2]/'docs/research/001c/001c-05'


def request(path,value=None):
    r=Request('http://127.0.0.1:8779'+path,
        data=json.dumps(value).encode() if value is not None else None,
        headers={'Content-Type':'application/json'} if value is not None else {})
    try:
        with urlopen(r,timeout=30) as response:
            return response.status,json.load(response)
    except HTTPError as e:
        return e.code,json.load(e)


def main():
    p=argparse.ArgumentParser(); p.add_argument('stage',choices=['initial','idle','page-refresh','extension-reload','extension-reload-verified','server-restart','server-restart-verified','owner-change','owner-change-verified','balance-verified','final','final-verified'])
    p.add_argument('--operation',choices=['watched','balance'],default='watched'); a=p.parse_args()
    target=DIRECTORY/(a.stage+'.json')
    # Reserve artifact exclusively before dispatch; even a process crash never
    # authorizes replay of this stage or its deterministic command ID.
    with target.open('x') as out:
        _,before=request('/health')
        cid=hashlib.sha256(('001c-05:'+a.stage).encode()).hexdigest()[:32]
        c={'schema':1,'id':cid,'operation':a.operation,'params':{},'evidence_key':'25'*16,**before['owner']}
        started=time.time(); status,value=request('/run',c); elapsed=(time.time()-started)*1000
        _,after=request('/health')
        if status==200: parse_response(value,command_id=cid,operation=a.operation)
        json.dump({'stage':a.stage,'at':started,'elapsed_ms':elapsed,'http_status':status,
            'command':c,'before':before,'after':after,'response':value},out,indent=2); out.write('\n')
    print(json.dumps({'stage':a.stage,'status':status,'success':value.get('result',{}).get('success'),
        'request_count':value.get('freshness',{}).get('request_count'),'error':value.get('result',{}).get('error')}))
    if status!=200 or not value['result']['success']: raise SystemExit(1)


if __name__=='__main__': main()
