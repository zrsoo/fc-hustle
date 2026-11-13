"""Capture exactly one requested read. Never overwrites an existing artifact."""
import argparse
import json
import urllib.request
from .server import DIRECTORY
from .validation import validate,assess


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    p.add_argument('--page',type=int,default=1)
    p.add_argument('--with-caps',action='store_true',default=None)
    for k in ('max-bid','min-buy','max-buy','definition-id'):p.add_argument('--'+k,type=int)
    a=p.parse_args();target=DIRECTORY/a.output
    if target.exists() or target.parent.resolve()!=DIRECTORY.resolve():p.error('new basename required')
    params={k:v for k,v in vars(a).items() if k!='output' and v is not None}|{'count':21}
    req=urllib.request.Request('http://127.0.0.1:8778/run',data=json.dumps({'params':params}).encode(),headers={'Content-Type':'application/json'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req,timeout=60) as r:v=json.loads(r.read(262145))
    validate(v)
    with target.open('x',encoding='utf-8') as f:f.write(json.dumps(v,indent=2)+'\n')
    print(json.dumps({'output':a.output,'assessment':assess(v),'error':v['error']}))
    return 0 if v['success'] else 1


if __name__=='__main__':raise SystemExit(main())
