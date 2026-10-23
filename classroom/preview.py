"""Run the real classroom application locally, with a persistent local DB."""
import argparse
from wsgiref.simple_server import make_server, WSGIRequestHandler
from .app import ClassroomApplication


class Quiet(WSGIRequestHandler):
    def log_message(self,*args):pass


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=4187);p.add_argument('--db',default='.private/classroom-preview.sqlite3');a=p.parse_args()
    app=ClassroomApplication(a.db,origin=f'http://127.0.0.1:{a.port}')
    print(f'课间班级版预览 http://127.0.0.1:{a.port}',flush=True)
    make_server('127.0.0.1',a.port,app,handler_class=Quiet).serve_forever()
