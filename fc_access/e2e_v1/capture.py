"""One explicit command per invocation. Exclusive artifacts prevent replay."""
import argparse
import json
import time
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from .server import DIRECTORY

def request(path,value=None):
    req=Request('http://127.0.0.1:8780'+path,data=json.dumps(value).encode() if value is not None else None,headers={'Content-Type':'application/json'} if value is not None else {})
    try:
        with urlopen(req,timeout=28) as r:return r.status,json.load(r)
    except HTTPError as e:return e.code,json.load(e)

def main():
    p=argparse.ArgumentParser();p.add_argument('stage');p.add_argument('operation');p.add_argument('params',nargs='?',default='{}');a=p.parse_args()
    if not a.stage.replace('-','').isalnum():raise ValueError('invalid_stage')
    with (DIRECTORY/(a.stage+'.json')).open('x') as out:
        _,before=request('/health');t=time.time();payload={'stage':a.stage,'operation':a.operation,'params':json.loads(a.params)}
        status,r=request('/run',payload);elapsed=(time.time()-t)*1000;_,after=request('/health')
        json.dump({'argv':['{python}','-m','fc_access.e2e_v1.capture',a.stage,a.operation,a.params],'at':t,'http_status':status,'elapsed_ms':elapsed,'request':payload,'before':before,'after':after,'response':r},out,indent=2);out.write('\n')
    print(json.dumps({'stage':a.stage,'http_status':status,'success':r.get('success'),'error':r.get('error'),'rows':len(r.get('rows') or []),'credits':r.get('credits'),'network_count':len(r.get('network') or []),'elapsed_ms':elapsed}))
    if status!=200 or not r.get('success'):raise SystemExit(1)
if __name__=='__main__':main()
