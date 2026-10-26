import threading
import time
from .index import Index
from .provider import XjtuProvider

class Engine:
    def __init__(self,config,store,provider=None):
        self.config,self.store=config,store
        self.provider=provider or XjtuProvider(config)
        self.index=Index(config,store)
        self.stop_event=threading.Event()
        self.thread=None

    def start(self):
        with self.store.tx() as db:db.execute("UPDATE jobs SET state='uncertain',error='interrupted_request' WHERE state='running'")
        self.thread=threading.Thread(target=self._loop,name='self-agent-worker',daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)

    def _loop(self):
        self.index.start()
        while not self.stop_event.is_set():
            self.process_one()
            self.index.sync()
            self.stop_event.wait(1)

    def process_one(self):
        if not self.provider.configured:return False
        with self.store.tx() as db:
            row=db.execute("SELECT j.*,s.content,s.project FROM jobs j JOIN sources s ON s.id=j.source_id WHERE j.state='pending' AND j.next_at<=? ORDER BY j.created LIMIT 1",(time.time(),)).fetchone()
            if not row:return False
            job=dict(row)
            db.execute("UPDATE jobs SET state='running',attempts=attempts+1 WHERE id=?",(job['id'],))
        try:
            extracted=self.provider.extract(job['content'])
            for item in extracted:
                self.store.add(job['user_id'],job['project'],item['content'],kind=item['kind'],source_id=job['source_id'],status='active' if item['explicit'] else 'candidate')
            with self.store.tx() as db:db.execute("UPDATE jobs SET state='done',error='' WHERE id=?",(job['id'],))
        except Exception as exc:
            state='failed' if isinstance(exc,ValueError) else 'uncertain'
            with self.store.tx() as db:db.execute('UPDATE jobs SET state=?,error=? WHERE id=?',(state,type(exc).__name__,job['id']))
        return True

    def search(self,uid,query,project='',limit=8):
        ranked=self.store.search(uid,query,project,limit=30)
        by_id={x['id']:x for x in ranked}
        scores={x['id']:1/(60+i) for i,x in enumerate(ranked)}
        try:ids=self.index.search_ids(uid,query,project)
        except Exception:ids=[]
        for i,mid in enumerate(ids):
            if not mid:continue
            try:item=self.store.get(uid,mid)
            except KeyError:continue
            if item['status']!='active' or item['project'] not in ('',project):continue
            by_id[mid]=item
            scores[mid]=scores.get(mid,0)+1/(60+i)
        result=[by_id[mid] for mid in sorted(scores,key=scores.get,reverse=True)[:limit]]
        for item in result:item['score']=scores[item['id']]
        return result
