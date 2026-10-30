import threading
import time
from .index import Index
from .provider import XjtuProvider,ReconciliationError,ExtractionError,ProviderUnavailable
from .capacity import Capacity,Backpressure
from .xjtu_top import TopError

class ReconciliationUnavailable(RuntimeError):pass

class Engine:
    def __init__(self,config,store,provider=None):
        self.config,self.store=config,store
        self.provider=provider or XjtuProvider(config)
        if config.index_backend=='mcp-memory-service':
            from .local_index import LocalIndex
            self.index=LocalIndex(config,store)
        else:self.index=Index(config,store)
        self.stop_event=threading.Event()
        self.thread=None
        self.scheduler=None
        self.worker_error=''

    def start(self):
        from datetime import datetime,timezone
        import logging
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.executors.pool import ThreadPoolExecutor
        from apscheduler.events import EVENT_JOB_ERROR
        with self.store.tx() as db:
            db.execute("UPDATE jobs SET state='uncertain',error='interrupted_request' WHERE state='running'")
            db.execute("UPDATE cleanup_jobs SET state='uncertain',error='interrupted_request' WHERE state='running'")
        logging.getLogger('apscheduler.scheduler').setLevel(logging.ERROR)
        self.scheduler=BackgroundScheduler(executors={name:ThreadPoolExecutor(1) for name in ('capture','generation','index')},
                    job_defaults={'coalesce':True,'max_instances':1,'misfire_grace_time':5},timezone=timezone.utc)
        self.scheduler.add_listener(lambda event:setattr(self,'worker_error',type(event.exception).__name__),EVENT_JOB_ERROR)
        for name,fn,seconds in [('capture',self._capture_tick,.5),('generation',self._generation_tick,.5),('index',self._index_tick,1)]:
            self.scheduler.add_job(fn,'interval',seconds=seconds,id=name,executor=name,next_run_time=datetime.now(timezone.utc))
        self.scheduler.start()

    def close(self):
        self.stop_event.set()
        if self.scheduler:self.scheduler.shutdown(wait=True)
        if hasattr(self.index,'close'):self.index.close()

    def _capture_tick(self):
        if self.stop_event.is_set():return
        if self.config.local:
            from .spool import drain
            drain(self.config,self.store)
        self.store.lifecycle.expire()

    def _generation_tick(self):
        if self.stop_event.is_set():return
        if hasattr(self.provider,'check_health'):self.provider.check_health()
        if getattr(self.provider,'health',{}).get('state')=='blocked':return
        if not self.process_one():self.process_cleanup_one()

    def _index_tick(self):
        if self.stop_event.is_set():return
        if self.index.error=='not_loaded':self.index.start()
        self.index.sync()

    def process_one(self,job_id=None):
        # Explicit import jobs use separate states so live capture cannot claim them.
        history=job_id is not None
        if history and (not self.config.local or not self.config.local_user_id):raise ValueError('local_import_only')
        pending,running=('history_pending','history_running') if history else ('pending','running')
        if not self.provider.configured or not getattr(self.index,'ready_for_reconcile',True):return False
        with self.store.tx() as db:
            row=db.execute("SELECT j.*,s.content,s.project FROM jobs j JOIN sources s ON s.id=j.source_id WHERE j.state=? AND j.next_at<=? AND (? IS NULL OR j.id=? AND j.user_id=?) ORDER BY j.created LIMIT 1",(pending,time.time(),job_id,job_id,self.config.local_user_id)).fetchone()
            if not row:return False
            job=dict(row)
        try:Capacity(self.config).check(1024**2)
        except Backpressure:return False
        if hasattr(self.provider,'preflight'):
            try:self.provider.preflight()
            except Exception as exc:
                with self.store.tx() as db:db.execute('UPDATE jobs SET next_at=?,error=? WHERE id=?',(time.time()+30,getattr(exc,'reason',type(exc).__name__),job['id']))
                return False
        with self.store.tx() as db:
            if not db.execute("UPDATE jobs SET state=?,attempts=attempts+1 WHERE id=? AND state=?",(running,job['id'],pending)).rowcount:return False
        try:
            import json
            with self.store.tx() as db:cached=db.execute('SELECT items,next_item FROM job_extractions WHERE job_id=?',(job['id'],)).fetchone()
            if cached:extracted=json.loads(cached['items']);offset=cached['next_item']
            else:
                if history:raise ValueError('history_extraction_checkpoint_required')
                extracted=self.provider.extract(job['content']);offset=0
                with self.store.tx() as db:db.execute('INSERT INTO job_extractions VALUES(?,?,0)',(job['id'],json.dumps(extracted,ensure_ascii=False)))
            with self.store.tx() as db:source=dict(db.execute('SELECT * FROM sources WHERE id=? AND user_id=?',(job['source_id'],job['user_id'])).fetchone())
            # Complete validated extraction is checkpointed before infrastructure deferrals.
            for position,item in enumerate(extracted[offset:],offset):
                quarantined=False
                try:candidates,decision=self.prepare(job['user_id'],source,item)
                except ReconciliationError:
                    if not history:raise
                    # Invalid confirmed relationships cannot overwrite knowledge or stall later items.
                    candidates,decision,quarantined=[],{'relation':'ambiguous'},True
                Capacity(self.config).check(len(item['content'].encode())*4+32768)
                with self.store.tx() as db:
                    learned=self.store.lifecycle.apply(job['user_id'],source,item,decision,candidates)
                    if quarantined and learned and learned['status']=='candidate':
                        self.store.lifecycle.metadata(learned['id'],observed_at=learned['observed_at'],valid_until=learned['valid_until'],topic=learned['topic'],reason='unvalidated_reconciliation')
                    db.execute('UPDATE job_extractions SET next_item=? WHERE job_id=?',(position+1,job['id']))
            with self.store.tx() as db:db.execute("UPDATE jobs SET state='done',error='' WHERE id=?",(job['id'],))
        except (Backpressure,ReconciliationUnavailable) as exc:
            with self.store.tx() as db:db.execute("UPDATE jobs SET state=?,next_at=?,error=? WHERE id=?",(pending,time.time()+5,getattr(exc,'reason','index_unavailable'),job['id']))
        except ProviderUnavailable as exc:
            with self.store.tx() as db:db.execute('UPDATE jobs SET state=?,next_at=?,error=? WHERE id=?',(pending,time.time()+30,exc.reason,job['id']))
        except (ExtractionError,ReconciliationError) as exc:
            retry=not history and job['attempts']<1 and getattr(self.provider,'retry_after_quality_failure',lambda:False)()
            with self.store.tx() as db:db.execute('UPDATE jobs SET state=?,next_at=?,error=? WHERE id=?',('pending' if retry else 'failed',time.time()+1,'model_quality_retry' if retry else type(exc).__name__,job['id']))
        except TopError as exc:
            receipt=exc.rate_receipt or {}
            if self.config.xjtu_auto_switch and exc.action in ('CreateConversation','BatchCreateMessages') and exc.http_status in (401,403):
                with self.store.tx() as db:db.execute('UPDATE jobs SET state=?,next_at=?,error=? WHERE id=?',(pending,time.time()+60,'account_unavailable',job['id']))
            elif history and receipt.get('limited'):
                with self.store.tx() as db:db.execute('UPDATE jobs SET state=?,next_at=?,error=? WHERE id=?',(pending,time.time()+max(65,receipt.get('retry_after_seconds',0)),'native_rate_limited',job['id']))
            else:
                with self.store.tx() as db:db.execute("UPDATE jobs SET state='uncertain',error=? WHERE id=?",(type(exc).__name__,job['id']))
        except Exception as exc:
            state='failed' if isinstance(exc,ValueError) else 'uncertain'
            with self.store.tx() as db:db.execute('UPDATE jobs SET state=?,error=? WHERE id=?',(state,type(exc).__name__,job['id']))
        return True

    def prepare(self,uid,source,item,exclude=None):
        scope='' if item.get('scope')=='personal' else source['project']
        try:
            nominate=getattr(self.index,'candidate_ids',self.index.search_ids)
            semantic=nominate(uid,item['content'],scope)
        except Exception as exc:
            if self.config.index_backend=='mcp-memory-service' and self.config.semantic:raise ReconciliationUnavailable() from exc
            semantic=[]
        candidates=[m for m in self.store.lifecycle.candidates(uid,scope,item,semantic) if m['id']!=exclude]
        if scope:
            personal=[m for m in self.store.lifecycle.candidates(uid,'',item,semantic) if m['status']=='active'][:4]
            candidates+=personal
        item['_project']=scope
        if not candidates:return candidates,{'relation':'independent'}
        from .store import fingerprint
        exact=next((m for m in candidates if m['project']==scope and fingerprint(m['content'])==fingerprint(item['content']) and m['valid_until']==item.get('valid_until')),None)
        if exact:return candidates,{'relation':'equivalent','target_id':exact['id'],'target_version':exact['version']}
        if not hasattr(self.provider,'reconcile'):return candidates,{'relation':'ambiguous'}
        return candidates,self.provider.reconcile(item,candidates)

    def start_cleanup(self,uid):
        import secrets
        with self.store.tx() as db:
            old=db.execute("SELECT id FROM cleanup_jobs WHERE user_id=? AND state IN ('pending','running')",(uid,)).fetchone()
            if old:return {'id':old[0],'queued':True}
            jid=secrets.token_hex(16)
            db.execute("INSERT INTO cleanup_jobs(id,user_id,state,created) VALUES(?,?,'pending',?)",(jid,uid,time.time()))
            db.execute("INSERT INTO cleanup_items(job_id,memory_id) SELECT ?,id FROM memories WHERE user_id=? AND status IN ('active','candidate') ORDER BY created",(jid,uid))
            return {'id':jid,'queued':True}

    def process_cleanup_one(self):
        if not self.provider.configured or not getattr(self.index,'ready_for_reconcile',True):return False
        with self.store.tx() as db:
            job=db.execute("SELECT * FROM cleanup_jobs WHERE state IN ('pending','running') ORDER BY created LIMIT 1").fetchone()
            if not job:return False
            job=dict(job)
            row=db.execute("SELECT memory_id FROM cleanup_items WHERE job_id=? AND state='pending' ORDER BY rowid LIMIT 1",(job['id'],)).fetchone()
            if not row:
                db.execute("UPDATE cleanup_jobs SET state='done' WHERE id=?",(job['id'],));return True
            mid=row[0]
            db.execute("UPDATE cleanup_jobs SET state='running' WHERE id=?",(job['id'],))
            db.execute("UPDATE cleanup_items SET state='running' WHERE job_id=? AND memory_id=?",(job['id'],mid))
        try:Capacity(self.config).check(1024**2)
        except Backpressure:
            with self.store.tx() as db:
                db.execute("UPDATE cleanup_jobs SET state='pending' WHERE id=?",(job['id'],))
                db.execute("UPDATE cleanup_items SET state='pending' WHERE job_id=? AND memory_id=?",(job['id'],mid))
            return False
        try:
            memory=self.store.get(job['user_id'],mid)
            if memory['status'] in ('active','candidate') and memory['source_id']:
                with self.store.tx() as db:source=dict(db.execute('SELECT * FROM sources WHERE id=? AND user_id=?',(memory['source_id'],job['user_id'])).fetchone())
                source['created']=min(source['created'],memory['observed_at'])
                # Re-extract the original evidence, never treat a previous model summary as a user statement.
                extracted=self.provider.extract(source['content'])
                related=[x for x in extracted if x['kind']==memory['kind'] and x.get('scope')!='session']
                matched=[]
                for proposed in related:
                    if proposed['content']==memory['content']:
                        matched.append(proposed)
                    elif hasattr(self.provider,'reconcile'):
                        check=self.provider.reconcile(proposed,[memory])
                        if check['relation']=='equivalent' and check['target_id']==mid:matched.append(proposed)
                if len(matched)==1:
                    item=matched[0]
                    if memory['source_kind']=='manual':
                        item['explicit']=True;item['evidence']=source['content']
                    candidates,decision=self.prepare(job['user_id'],source,item,exclude=mid)
                    if not item.get('explicit') or decision['relation']=='ambiguous':
                        # A cleanup suggestion must not demote or move a confirmed memory.
                        item={**item,'explicit':False,'scope':'project'}
                        suggestion=[memory]
                        self.store.lifecycle.apply(job['user_id'],source,item,{'relation':'ambiguous','target_id':mid,'target_version':memory['version']},suggestion)
                    else:
                        self.store.lifecycle.apply(job['user_id'],source,item,decision,candidates,legacy=mid,legacy_version=memory['version'])
            with self.store.tx() as db:
                db.execute("UPDATE cleanup_items SET state='done' WHERE job_id=? AND memory_id=?",(job['id'],mid))
                db.execute('UPDATE cleanup_jobs SET processed=processed+1 WHERE id=?',(job['id'],))
        except Exception as exc:
            with self.store.tx() as db:
                db.execute("UPDATE cleanup_items SET state='uncertain' WHERE job_id=? AND memory_id=?",(job['id'],mid))
                db.execute("UPDATE cleanup_jobs SET state='uncertain',error=? WHERE id=?",(type(exc).__name__,job['id']))
        return True

    def context(self,uid,project='',limit=8):
        """No-query startup context: bounded confirmed defaults, not semantic neighbors."""
        from itertools import zip_longest
        self.store.lifecycle.expire(uid)
        groups=[]
        with self.store.tx() as db:
            for scope in dict.fromkeys(['',project]):
                ids=[r[0] for r in db.execute("SELECT m.id FROM memories m LEFT JOIN memory_metadata x ON x.memory_id=m.id WHERE m.user_id=? AND m.project=? AND m.status='active' AND m.kind IN ('preference','decision','procedure') ORDER BY COALESCE(x.observed_at,m.created) DESC,m.updated DESC LIMIT ?",(uid,scope,limit))]
                groups.append([self.store.brief(uid,mid) for mid in ids])
        pool=[m for batch in zip_longest(*groups) for m in batch if m and m['effective_state']!='expired']
        topics={m['topic'] for m in pool if m['project']==project and project and m['topic']}
        overridden={r['target_id'] for m in pool if m['project']==project and project for r in m['relations'] if r['relation']=='overrides'}
        return [m for m in pool if m['id'] not in overridden and not (not m['project'] and m['topic'] in topics)][:limit]

    def search(self,uid,query,project='',limit=8):
        from .store import search_terms
        self.store.lifecycle.expire(uid)
        query_terms=set(search_terms(query))
        if not query_terms:return []
        def lexical(item):
            terms=set(search_terms(item['content']+' '+item['title']+' '+item.get('topic','')))
            return sum(len(t) for t in query_terms&terms)/max(1,sum(len(t) for t in query_terms))
        found={};scores={}
        try:
            if hasattr(self.index,'search_hits'):hits=self.index.search_hits(uid,query,project)
            else:hits=[{'id':mid,'score':0,'semantic_score':0} for mid in self.index.search_ids(uid,query,project)]
        except Exception:hits=[]
        for hit in hits:
            try:item=self.store.brief(uid,hit['id'])
            except KeyError:continue
            if item['status']!='active' or item['effective_state']=='expired' or item['project'] not in ('',project):continue
            if hit.get('version') is not None and hit['version']!=item['version']:continue
            coverage=lexical(item)
            if hit.get('semantic_score',0)<self.config.min_recall_similarity and coverage<self.config.min_lexical_coverage:continue
            found[item['id']]=item;scores[item['id']]=max(float(hit.get('score',0)),coverage*.7)
        for raw in self.store.search(uid,query,project,limit=30):
            item=self.store.brief(uid,raw['id']);coverage=lexical(item)
            if coverage<self.config.min_lexical_coverage or item['effective_state']=='expired':continue
            if item['id'] not in found:found[item['id']]=item;scores[item['id']]=coverage*.7
        if self.config.semantic and hasattr(self.index,'rerank'):
            pool=sorted(found.values(),key=lambda m:scores[m['id']],reverse=True)[:24]
            ranked=self.index.rerank(query,pool)
            if ranked is None:
                # Model unavailable: retain only meaningful literal matches, never a forced vector hit.
                found={m['id']:m for m in pool if lexical(m)>=.6}
            else:
                scores={m['id']:m['score'] for m in ranked if m['id'] in found and m['score']>=self.config.min_rerank_score}
                found={mid:m for mid,m in found.items() if mid in scores}
        for mid,item in list(found.items()):
            # A concurrent edit/remove during reranking must take effect before returning context.
            current=self.store.brief(uid,mid)
            if current['version']!=item['version'] or current['status']!='active' or current['effective_state']=='expired':
                del found[mid];continue
            if item['kind']=='fact':scores[mid]*=.8+.2*2**(-max(0,time.time()-item['observed_at'])/(180*86400))
        topics={m['topic'] for m in found.values() if m['project']==project and project and m['topic']}
        overridden={r['target_id'] for m in found.values() if m['project']==project and project for r in m['relations'] if r['relation']=='overrides' and r['source_id']==m['id']}
        result=[]
        for mid in sorted(found,key=lambda key:scores[key],reverse=True):
            item=found[mid]
            if mid in overridden or not item['project'] and item['topic'] in topics:continue
            item['score']=scores[mid];result.append(item)
            if len(result)>=limit:break
        return result
