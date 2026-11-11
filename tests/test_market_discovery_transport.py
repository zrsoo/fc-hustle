"""T3 criteria 3..5: real loopback and JS-native fixture security/timing tests."""
from copy import deepcopy
import http.client
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.market_discovery.bridge_server import SearchServer
from experiments.market_discovery.replay import FixtureClock, FixtureTransport
from experiments.market_discovery.transport import SearchTransport


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.server = SearchServer('a'*32,port=0,wait_seconds=.18,poll_seconds=.03)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.body = {'operation':'search','params':{'page':1,'count':21,'fresh':True,'definition_id':233731},'id':'c'*32,'evidence_key':'d'*32}
        self.value = FixtureTransport(FixtureClock()).search(self.body['params'],self.body['evidence_key'])

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def request(self,path,body=None,extension=False,headers=None,method='POST',raw=None):
        conn = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        h = {'Content-Type':'application/json'}
        if extension: h['Origin']='chrome-extension://'+'a'*32
        h.update(headers or {})
        conn.request(method,path,raw if raw is not None else json.dumps(body) if body is not None else None,h)
        response = conn.getresponse()
        self.assertIsNone(response.getheader('Access-Control-Allow-Origin'))
        result = response.status,json.loads(response.read())
        conn.close()
        return result

    def attach(self):
        self.assertEqual(self.request('/next',{'protocol':1},True),(200,None))

    def start_command(self,body=None):
        results=[]
        thread=threading.Thread(target=lambda:results.append(self.request('/run',body or self.body)))
        thread.start()
        return thread,results

    def test_host_origin_pinning_routes_duplicate_json_and_mutation_rejection(self):
        self.assertEqual(self.server.server_address[0],'127.0.0.1')
        for h in ({'Origin':'https://evil.invalid'},{'Host':'evil.invalid'},{'Sec-Fetch-Site':'cross-site'},{'Origin':'null'}):
            self.assertEqual(self.request('/run',self.body,headers=h)[0],403)
        for h in ({},{'Origin':'chrome-extension://'+'b'*32},{'Origin':'https://www.ea.com'}):
            self.assertEqual(self.request('/next',{'protocol':1},headers=h)[0],403)
        self.assertEqual(self.request('/next',extension=True,method='GET')[0],403)
        self.assertEqual(self.request('/buy',self.body)[0],404)
        self.assertEqual(self.request('/next',{},True)[0],400)
        self.assertEqual(self.request('/run',raw='{"operation":"search","operation":"buy"}')[0],400)
        for op in ('buy','bid','move','list','relist','cancel','coins','unassigned','transfer_list','eval'):
            self.assertEqual(self.request('/run',self.body|{'operation':op})[0],400)
        for p in ({'count':22},{'nation':1},{'page':3},{'fresh':1},{'cookie':'secret'}):
            self.assertEqual(self.request('/run',self.body|{'params':self.body['params']|p})[0],400)
        self.assertEqual(self.request('/run',self.body)[1]['result']['error'],'bridge_not_attached')
        self.assertIsNone(self.server.pending)

    def test_single_delivery_result_matching_privacy_and_expiry(self):
        self.attach()
        caller,results=self.start_command()
        command=self.request('/next',{'protocol':1},True)[1]
        self.assertEqual(command,self.body)
        self.assertEqual(self.request('/next',{'protocol':1},True)[1],None)
        self.assertEqual(self.request('/run',self.body)[0],409)
        self.assertEqual(self.request('/result',{'id':'e'*32}|self.value,True)[0],409)
        unsafe=deepcopy(self.value); unsafe['result']['account']='private-canary'
        self.assertEqual(self.request('/result',{'id':command['id']}|unsafe,True)[0],400)
        self.assertEqual(self.request('/result',{'id':command['id']}|self.value,True)[0],200)
        caller.join(2)
        self.assertFalse(caller.is_alive())
        self.assertTrue(results[0][1]['result']['success'])
        self.assertGreaterEqual(results[0][1]['delivery']['queue_delivery_ms'],0)
        self.assertEqual(self.request('/result',{'id':command['id']}|self.value,True)[0],409)
        caller,results=self.start_command(self.body|{'id':'f'*32})
        command=self.request('/next',{'protocol':1},True)[1]
        caller.join(2)
        self.assertEqual(results[0][1]['result']['error'],'bridge_timeout')
        self.assertEqual(self.request('/result',{'id':command['id']}|self.value,True)[0],409)
        self.assertIsNone(self.server.pending)

    def test_long_poll_wakes_on_command_and_real_client_times_delivery(self):
        self.server.poll_seconds=.15
        polls=[]
        poll_thread=threading.Thread(target=lambda:polls.append(self.request('/next',{'protocol':1},True)))
        poll_thread.start()
        deadline=time.monotonic()+1
        while not self.server.polling and time.monotonic()<deadline: time.sleep(.001)
        self.assertTrue(self.server.polling)
        self.assertEqual(self.request('/next',{'protocol':1},True)[0],409)
        client=SearchTransport(self.server.server_port)
        replies=[]
        caller=threading.Thread(target=lambda:replies.append(client.search(self.body['params'],self.body['evidence_key'])))
        start=time.perf_counter(); caller.start(); poll_thread.join(1)
        self.assertFalse(poll_thread.is_alive())
        command=polls[0][1]
        self.assertEqual(command['operation'],'search')
        self.assertEqual(self.request('/result',{'id':command['id']}|self.value,True)[0],200)
        caller.join(1)
        self.assertFalse(caller.is_alive())
        self.assertLess(time.perf_counter()-start,1)
        self.assertTrue(replies[0]['result']['success'])
        self.assertGreaterEqual(client.last_timing['queue_delivery_ms'],0)
        self.assertGreaterEqual(client.last_timing['result_return_ms'],0)
        self.assertEqual(replies[0]['timing']['native_service_ms'],40)

    def test_javascript_search_only_and_both_worker_modes(self):
        result=subprocess.run(['node','tests/market_discovery_bridge_checks.cjs'],cwd=ROOT,capture_output=True,text=True,timeout=25)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('synthetic only',result.stdout)


if __name__=='__main__': unittest.main()
