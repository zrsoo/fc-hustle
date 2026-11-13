import argparse
import json
import time
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from .server import DIRECTORY,OPERATIONS

def request(path,value=None):
    req=Request('http://127.0.0.1:8783'+path,data=json.dumps(value).encode() if value is not None else None,headers={'Content-Type':'application/json'} if value is not None else {})
    try:
        with urlopen(req,timeout=28) as r:return r.status,json.load(r)
    except HTTPError as e:return e.code,json.load(e)
def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=OPERATIONS);a=p.parse_args()
    with (DIRECTORY/(a.operation+'.json')).open('x') as f:
        _,before=request('/health');start=time.time();status,r=request('/run',{'operation':a.operation});elapsed=(time.time()-start)*1000;_,after=request('/health')
        json.dump({'argv':['{python}','-m','fc_access.e2e_resolution_v2.capture',a.operation],'at':start,'elapsed_ms':elapsed,'http_status':status,'before':before,'after':after,'response':r},f,indent=2)
    print(json.dumps({'operation':a.operation,'http_status':status,'success':r.get('success'),'error':r.get('error'),'rows':r.get('rows'),'credits':r.get('credits'),'network':r.get('network')}))
    if status!=200 or not r.get('success'):raise SystemExit(1)
if __name__=='__main__':main()
