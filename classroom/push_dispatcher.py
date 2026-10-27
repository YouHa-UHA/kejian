"""Five bounded network requests; SQLite stays on the owning worker thread."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import time
from . import push

CONCURRENCY=5
ADMISSION_BATCH=10
ADMISSION_BUDGET_SECONDS=1


class ParallelSender:
    def __init__(self, concurrency=CONCURRENCY, clock=time.time, monotonic=time.monotonic):
        if not 1<=concurrency<=CONCURRENCY:raise ValueError('Unsupported sender concurrency')
        self.limit=concurrency;self.clock=clock;self.monotonic=monotonic
        self.pool=ThreadPoolExecutor(max_workers=concurrency,thread_name_prefix='kejian-push')
        self.pending={}

    @property
    def capacity(self):return self.limit-len(self.pending)

    def reap(self,c):
        finished=0
        for future,delivery in list(self.pending.items()):
            if not future.done():continue
            try:outcome=future.result()
            except Exception:
                # A failed task may already have submitted a request. Do not
                # leak its exception text or blindly retry that delivery.
                outcome=('unknown',None,'NETWORK_OR_TIMEOUT')
            push.complete(c,delivery,outcome,int(self.clock()))
            # Keep a completed future until the database write succeeds. A
            # transient DB error retries only this write, never network I/O.
            del self.pending[future];finished+=1
        return finished

    def pump(self,c,cfg,send):
        completed=self.reap(c);admitted=0;started=self.monotonic()
        while self.capacity and admitted<ADMISSION_BATCH:
            if admitted and self.monotonic()-started>=ADMISSION_BUDGET_SECONDS:break
            delivery=push.claim(c,int(self.clock()))
            if delivery is None:break
            admitted+=1
            if delivery is False:continue
            try:future=self.pool.submit(push.deliver,delivery,cfg,send,self.clock)
            except Exception:
                # A thread-start failure can occur after the executor enqueues
                # work. Treat submission errors conservatively as uncertain.
                push.complete(c,delivery,('unknown',None,'DISPATCH_UNCERTAIN'),int(self.clock()))
                raise
            self.pending[future]=delivery
        return {'admitted':admitted,'completed':completed,'inflight':len(self.pending)}

    def pause(self,seconds,stop=None):
        if self.pending:
            wait(tuple(self.pending),timeout=seconds,return_when=FIRST_COMPLETED)
        elif stop is not None:stop.wait(seconds)
        else:time.sleep(seconds)

    def close(self):
        # No unbounded executor queue: at most five claimed requests exist.
        self.pool.shutdown(wait=True)
