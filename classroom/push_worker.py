"""Optional isolated push sender; its dependencies are not needed by the web app."""
import json
import os
from pathlib import Path
import signal
import threading
import time
from .app import connect
from . import push
from .push_scheduler import Scheduler
from .push_dispatcher import ParallelSender


def validate_config(config):
    # Validate with the same library used by the sender, without contacting a device.
    from py_vapid import Vapid, VapidException
    try:
        vapid=Vapid.from_file(config['privateKeyPath'])
        vapid.sign({'sub':config['subject'],'aud':'https://web.push.apple.com',
                    'exp':int(time.time())+300})
    except (VapidException,ValueError,OSError,KeyError):
        raise push.ConfigurationError('Push sender configuration is invalid.') from None


def send(subscription, payload, config, ttl):
    from pywebpush import webpush
    from py_vapid import VapidException
    import requests
    class NoRedirects(requests.Session):
        def request(self, *args, **kwargs):
            kwargs['allow_redirects'] = False
            return super().request(*args, **kwargs)
    with NoRedirects() as session:
        try:
            response = webpush(subscription_info=subscription,data=json.dumps(payload,ensure_ascii=False),
                vapid_private_key=config['privateKeyPath'],vapid_claims={'sub':config['subject']},
                ttl=ttl,timeout=12,headers={'Urgency':'high','Topic':payload['id'].replace('-','')[:32]},
                requests_session=session)
        except VapidException:
            raise push.ConfigurationError('Push sender could not prepare credentials.') from None
        return response.status_code


def validate_database(config, database):
    if config['environment']=='production':
        if database!=Path('/var/lib/kejian/classroom.sqlite3'):
            raise ValueError('Production sender requires the production database')
    elif config['environment']=='testing':
        if database.parent!=Path('/var/lib/kejian-test'):
            raise ValueError('Test sender requires the isolated test database')
    else:raise ValueError('Unknown push environment')


def main():
    cfg = push.config(json.loads(Path(os.environ['KEJIAN_PUSH_CONFIG']).read_text()),os.environ['KEJIAN_BASE'])
    database = Path(os.environ['KEJIAN_DB']).resolve()
    validate_database(cfg,database)
    validate_config(cfg)
    stop=threading.Event()
    for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,lambda *_:stop.set())
    dispatcher=ParallelSender();scheduler=Scheduler(dispatcher=dispatcher);c=None
    try:
        while not stop.is_set():
            try:
                if c is None:c=connect(database)
                result=scheduler.step(c,cfg,send)
                delay=result['delay']
            except Exception:
                # Preserve in-flight results across DB errors. Never create a
                # replacement pool that might multiply concurrent requests.
                print('Push worker cycle failed; no sensitive details logged.',flush=True)
                if c is not None:c.close()
                c=None;scheduler=Scheduler(dispatcher=dispatcher)
                # Completed futures wake pause() immediately. A database error
                # must still respect backoff instead of creating a hot loop.
                stop.wait(5)
                continue
            dispatcher.pause(delay,stop)
    finally:
        dispatcher.close()
        try:
            if c is None:c=connect(database)
            dispatcher.reap(c)
        finally:
            if c is not None:c.close()


if __name__ == '__main__': main()
