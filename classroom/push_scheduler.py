"""Bounded, change-driven planning and due-time delivery with no history cache."""
import time
from . import push,reminders,reminder_changes

DIRTY_POLL_SECONDS=10
FALLBACK_SECONDS=15*60
HEARTBEAT_SECONDS=30
CLEANUP_SECONDS=60
PLAN_MEMBERS=5
SEND_BATCH=10
SEND_BUDGET_SECONDS=1


class Scheduler:
    def __init__(self, clock=time.time, monotonic=time.monotonic, dispatcher=None):
        self.clock=clock;self.monotonic=monotonic;self.dispatcher=dispatcher
        self.poll_at=self.fallback_at=self.heartbeat_at=self.cleanup_at=monotonic()

    def step(self,c,cfg,send):
        mono=self.monotonic();now=int(self.clock())
        if mono>=self.heartbeat_at:
            cleanup=mono>=self.cleanup_at
            push.maintain(c,now,cleanup=cleanup)
            self.heartbeat_at=mono+HEARTBEAT_SECONDS
            if cleanup:self.cleanup_at=mono+CLEANUP_SECONDS
        if mono>=self.fallback_at:
            reminder_changes.enqueue_active(c,now)
            self.fallback_at=mono+FALLBACK_SECONDS;self.poll_at=mono
        processed=0
        if mono>=self.poll_at:
            result=reminders.plan_dirty(c,now,limit=PLAN_MEMBERS)
            processed=result['processed']
            self.poll_at=self.monotonic()+(.25 if result['remaining'] else DIRTY_POLL_SECONDS)
        sent=0;started=self.monotonic()
        if self.dispatcher is not None:
            sent=self.dispatcher.pump(c,cfg,send)['admitted']
        else:
            # Synchronous adapter used by deterministic scheduling tests.
            while sent<SEND_BATCH:
                if sent and self.monotonic()-started>=SEND_BUDGET_SECONDS:break
                if not push.tick(c,cfg,send,int(self.clock()),maintenance=False):break
                sent+=1
        now=self.clock();mono=self.monotonic()
        delay=min(self.poll_at,self.fallback_at,self.heartbeat_at)-mono
        due=push.next_due(c)
        if due is not None and (self.dispatcher is None or self.dispatcher.capacity):delay=min(delay,due-now)
        return {'delay':max(.05,min(DIRTY_POLL_SECONDS,delay)),'plannedMembers':processed,'deliveryAttempts':sent}
