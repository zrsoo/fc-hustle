"""Fenced loopback transport; no replay on any delivery failure."""
import time
from fc_access.production_v1.executor import EdgeExecutor
from .protocol import delivery_command


class ControllerExecutor(EdgeExecutor):
    def attach(self, context, owner, epoch):
        expected = dict(context=context,owner=owner,epoch=epoch)
        self.request('/activate',expected)
        end = time.monotonic()+self.attach_timeout
        while time.monotonic() < end:
            h = self.request('/health')
            if h.get('service') != 'fc-controller-v1' or h.get('schema') != 4:
                raise ValueError('wrong_service')
            if h['owner'] == expected and h['attached']:
                return h['peer']['fences']
            time.sleep(.25)
        raise ValueError('attachment_required_click_production_extension')

    def execute(self, value):
        delivery_command(value)
        return self.request('/run',value)


class SerializedExecutor:
    """Shared native mechanisms and schema 4 requests, one paced native boundary.

    Local helpers consume no EA slot. Failed requests consume their slot too.
    There is no queue, retry, background worker, or catch-up delivery.
    """
    def __init__(self, executor, *, spacing=2, clock=time.monotonic, sleep=time.sleep, progress=None):
        import threading
        if spacing < 0:raise ValueError('invalid_spacing')
        self.executor,self.spacing,self.clock,self.sleep=executor,spacing,clock,sleep
        self.lock=threading.RLock()
        self.guard=None
        self.last_start=None
        self.metrics=[]
        self.progress=progress

    def attach(self, *args):
        with self.lock:
            if self.progress:self.progress('ATTACHING')
            try:return self.executor.attach(*args)
            finally:
                if self.progress:self.progress('LOCAL')

    def execute(self, value):
        from fc_access.production_v1.contracts import LOCAL_OPERATIONS, stamp
        delivery_command(value)
        local=value['schema']==2 and value['operation'] in LOCAL_OPERATIONS
        with self.lock:
            if self.guard:self.guard(value)
            if not local and self.last_start is not None:
                delay=self.last_start+self.spacing-self.clock()
                if delay>0:self.sleep(delay)
            if self.guard:self.guard(value)
            # Recheck absolute deadline after pacing; expired writes never enter I/O.
            if value['operation']=='bid':
                from datetime import datetime, timezone
                now=getattr(self,'now',lambda:datetime.now(timezone.utc))()
                if stamp(value['params']['deadline'])<=now:raise TimeoutError('deadline_skipped')
            start=self.clock()
            if not local:self.last_start=start
            if self.progress:self.progress('NATIVE' if not local else 'LOCAL',value['operation'])
            try:return self.executor.execute(value)
            finally:
                self.metrics.append(dict(command_id=value['id'],operation=value['operation'],
                                         local=local,started=start,elapsed=self.clock()-start))
                if self.progress:self.progress('LOCAL')
