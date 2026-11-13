"""Actual Edge PageExecutor for the zero-mutation lifecycle window.

The mutation harness accepts a separately reviewed mutation executor only after
live rules are conclusive. This executor cannot turn a lifecycle budget into
authorization to bid, transfer or list.
"""
import json
import time
from urllib.request import Request,urlopen


class EdgeReadExecutor:
    def __init__(self,port=8779,attach_timeout=45):
        if type(port) is not int or not 1<=port<=65535 or not 0<attach_timeout<=60:
            raise ValueError('invalid_transport')
        self.base=f'http://127.0.0.1:{port}';self.attach_timeout=attach_timeout

    def request(self,path,value=None):
        req=Request(self.base+path,data=json.dumps(value).encode() if value is not None else None,
            headers={'Content-Type':'application/json'} if value is not None else {})
        with urlopen(req,timeout=30) as response:return json.load(response)

    def attach(self,scope,owner,epoch):
        expected={'scope':scope,'owner':owner,'epoch':epoch}
        self.request('/activate',expected)
        end=time.monotonic()+self.attach_timeout
        while time.monotonic()<end:
            h=self.request('/health')
            if h['owner']==expected and h['attached'] and h['persona']['accepted']:
                return True
            time.sleep(.25)
        return False

    def execute(self,command):
        if command.get('operation') not in ('search','watched','balance'):
            raise ValueError('lifecycle_window_has_no_mutation_authority')
        return self.request('/run',command)

    def reconciled(self,*args):
        return False  # No mutation was authorized by this transport.
