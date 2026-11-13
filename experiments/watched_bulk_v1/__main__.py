"""One explicit bounded read, one immutable sanitized output; never retries."""
import argparse
import json
from pathlib import Path
import urllib.error
import urllib.request
from .validation import validate_projection

KEY = '001c0300000000000000000000000001'  # local pseudonym correlation, not authentication


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=['inspect','watched'])
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    target=args.output.resolve()
    allowed=Path('docs/research/001c/001c-03').resolve()
    if not target.is_relative_to(allowed) or target.exists():
        p.error('use a new output in docs/research/001c/001c-03')
    request=urllib.request.Request('http://127.0.0.1:8775/run',data=json.dumps({'operation':args.operation,'evidence_key':KEY}).encode(),headers={'Content-Type':'application/json'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),type('NoRedirect',(urllib.request.HTTPRedirectHandler,),{'redirect_request':lambda *args:None})())
    try:
        with opener.open(request,timeout=60) as r:
            v=json.loads(r.read(262145))
        validate_projection(v)
    except (OSError,ValueError):
        print(json.dumps({'status':'UNRESOLVED','reason':'local_read_failed_no_retry'}));return 1
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as f:
        f.write(json.dumps(v,indent=2)+'\n')
    print(json.dumps({'status':'CAPTURED','success':v['success'],'requests':v['request_count'],'output':str(args.output)}))
    return 0 if v['success'] else 1


if __name__=='__main__':
    raise SystemExit(main())
