"""Pinned MCP Memory Service SQLite-vec projection; canonical lifecycle stays in Store."""
import asyncio
import hashlib
import os
import threading
from concurrent.futures import TimeoutError


class LocalIndex:
    def __init__(self, config, store):
        self.config, self.store = config, store
        self.memory = None
        self.error = 'not_loaded'
        self.loop = asyncio.new_event_loop()
        self.thread = None
        self.lock = threading.Lock()
        self._projection_ready = False
        self.reranker=None
        self.rerank_error='not_loaded'

    def call(self, task, timeout=15):
        future = asyncio.run_coroutine_threadsafe(task, self.loop)
        try:return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise

    def start(self):
        if not self.config.semantic:
            self.error='disabled';self._projection_ready=True
            return
        try:
            import importlib.metadata
            if importlib.metadata.version('mcp-memory-service') != '12.4.0':
                raise RuntimeError('unexpected_memory_backend_version')
            if self.config.model_cache:
                os.environ['HF_HOME']=self.config.model_cache
            os.environ.update({'MCP_MEMORY_USE_ONNX':'true','MCP_MEMORY_ONNX_ALLOW_DOWNLOAD':'0',
                               'HF_HUB_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1',
                               'ANONYMIZED_TELEMETRY':'false','TOKENIZERS_PARALLELISM':'false',
                               'MCP_HYBRID_FUSION_METHOD':'weighted_average'})
            from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage
            self.thread=threading.Thread(target=self.loop.run_forever,daemon=True,name='memory-index')
            self.thread.start()
            from pathlib import Path
            from mcp_memory_service.embeddings.onnx_embeddings import ONNXEmbeddingModel
            cache=Path(self.config.model_cache)
            class BundledModel(ONNXEmbeddingModel):
                def _download_model_if_needed(self):
                    self._model_dir=cache
                    if not (cache/'model.onnx').is_file() or not (cache/'tokenizer.json').is_file():
                        raise RuntimeError('bundled_embedding_model_missing')
                def _init_model(self):
                    import onnxruntime as ort
                    from tokenizers import Tokenizer
                    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
                    self._model=ort.InferenceSession(str(cache/'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
                    self._tokenizer=Tokenizer.from_file(str(cache/'tokenizer.json'))
                    self._tokenizer.enable_truncation(max_length=128)
                    self.embedding_dimension=self._model.get_outputs()[0].shape[-1]
                    self._input_names={i.name for i in self._model.get_inputs()}
            class PinnedStorage(SqliteVecMemoryStorage):
                async def _initialize_embedding_model(self):
                    self.embedding_model=await asyncio.to_thread(BundledModel,self.embedding_model_name)
                    self.embedding_dimension=self.embedding_model.embedding_dimension
                    self._embedding_cache_namespace='self-agent:'+self.embedding_model_name
                    if self.embedding_dimension!=384:raise RuntimeError('embedding_dimension_mismatch')
            projection_existed=(self.config.data_dir/'local-vectors.sqlite3').exists()
            memory=PinnedStorage(str(self.config.data_dir/'local-vectors.sqlite3'),embedding_model=self.config.embedding_model)
            memory.semantic_dedup_enabled=False  # Canonical, scoped reconciliation owns deduplication.
            self.call(memory.initialize(),timeout=90)
            self.memory=memory
            # A schema marker invalidates the derived projection, not canonical knowledge.
            from .spool import atomic_json
            marker=self.config.data_dir/'index-layout.json'
            try:layout=__import__('json').loads(marker.read_text('utf-8')).get('layout')
            except (OSError,ValueError):layout=None
            if not projection_existed or layout!='scoped-live-archive-v2':
                with self.store.tx() as db:db.execute('UPDATE projections SET version=0')
                atomic_json(marker,{'layout':'scoped-live-archive-v2'})
            self.error=''
            try:
                from .rerank import OfflineReranker
                self.reranker=OfflineReranker(cache.parent/'rerank-bge');self.rerank_error=''
            except Exception as exc:self.rerank_error=type(exc).__name__
        except Exception as exc:
            self.error=type(exc).__name__
            self.memory=None
            import traceback
            (self.config.data_dir/'index-error.log').write_text(traceback.format_exc(),'utf-8')

    @staticmethod
    def scope(uid,project):
        return 'scope:'+hashlib.sha256((uid+'\0'+project).encode()).hexdigest()

    @property
    def ready_for_reconcile(self):
        return not self.config.semantic or self.memory is not None and self._projection_ready

    @classmethod
    def partition(cls,uid,project,active=True):
        return cls.scope(uid,project)+(':live' if active else ':archive')

    def sync(self):
        if self.memory is None:return
        from mcp_memory_service.models.memory import Memory
        from .capacity import Capacity,Backpressure
        with self.lock:
            with self.store.tx() as db:
                rows=[dict(x) for x in db.execute('SELECT m.*,p.external_id FROM memories m LEFT JOIN projections p ON p.memory_id=m.id WHERE p.version IS NULL OR p.version!=m.version ORDER BY m.created LIMIT ?',(self.config.projection_batch_size,))]
            if not rows:self._projection_ready=True;self.error='';return
            self._projection_ready=False
            try:Capacity(self.config).check(sum(len(r['content'].encode())*3+4096 for r in rows))
            except Backpressure as exc:self.error=exc.reason;return
            groups={}
            try:
                for row in rows:
                    old=row['external_id']
                    if old and old.startswith('mms:'):self.call(self.memory.delete(old[4:]))
                    partition=self.partition(row['user_id'],row['project'],row['status']=='active')
                    key=hashlib.sha256(('v2\0'+row['user_id']+'\0'+row['project']+'\0'+row['id']+'\0'+str(row['version'])).encode()).hexdigest()
                    item=Memory(content=row['content'],content_hash=key,tags=[self.scope(row['user_id'],row['project'])],
                                metadata={'canonical_id':row['id'],'version':row['version'],'kind':row['kind']},created_at=row['created'],updated_at=row['updated'])
                    groups.setdefault(partition,[]).append((row,item))
                for partition,pairs in groups.items():
                    # Upstream batches embeddings and SQLite commits; no custom vector loop.
                    results=self.call(self.memory.store_batch([item for _,item in pairs],store=partition,recreate=True),timeout=90)
                    if len(results)!=len(pairs):raise RuntimeError('projection_batch_incomplete')
                    for (row,item),(ok,_) in zip(pairs,results):
                        if not ok:
                            existing=self.call(self.memory.get_by_hash(item.content_hash,store=partition))
                            if not existing or existing.metadata.get('canonical_id')!=row['id'] or existing.metadata.get('version')!=row['version']:raise RuntimeError('projection_store_failed')
                        with self.store.tx() as db:db.execute('INSERT OR REPLACE INTO projections VALUES(?,?,?,?)',(row['id'],row['version'],'mms:'+item.content_hash,''))
                self.error=''
            except Exception as exc:self.error=type(exc).__name__

    def search_hits(self,uid,query,project):
        if self.memory is None:return []
        async def search():
            # Upstream owns BM25/vector score fusion and store filtering.
            groups=await asyncio.gather(*(self.memory.retrieve_hybrid(query,n_results=20,keyword_weight=.3,semantic_weight=.7,store=self.partition(uid,p)) for p in dict.fromkeys(['',project])))
            return [hit for group in groups for hit in group]
        hits=self.call(search(),timeout=2)
        result={}
        for hit in hits:
            mid=hit.memory.metadata.get('canonical_id')
            if not mid:continue
            item={'id':mid,'version':hit.memory.metadata.get('version'),'score':float(hit.relevance_score or 0),
                  'semantic_score':float(hit.debug_info.get('semantic_score',0)),'keyword_score':float(hit.debug_info.get('keyword_score',0))}
            if mid not in result or item['score']>result[mid]['score']:result[mid]=item
        return sorted(result.values(),key=lambda x:x['score'],reverse=True)

    def rerank(self,query,memories):
        if self.reranker is None:return None
        try:return self.reranker.score(query,memories)
        except Exception as exc:self.rerank_error=type(exc).__name__;return None

    def search_ids(self,uid,query,project):
        return [hit['id'] for hit in self.search_hits(uid,query,project)]

    def candidate_ids(self,uid,query,project):
        if self.memory is None:return []
        async def candidates():
            duplicates=[];ranked=[]
            for active in (True,False):
                partition=self.partition(uid,project,active)
                # Use the pinned upstream semantic duplicate detector as a nomination.
                duplicate,key=await self.memory._check_semantic_duplicate(query,time_window_hours=24*365*100,similarity_threshold=.85,store=partition)
                if duplicate:
                    memory=await self.memory.get_by_hash(key,store=partition)
                    if memory:duplicates.append(memory.metadata.get('canonical_id'))
                hits=await self.memory.retrieve_hybrid(query,n_results=12,keyword_weight=.3,semantic_weight=.7,store=partition)
                ranked.extend((hit.relevance_score,hit.memory.metadata.get('canonical_id')) for hit in hits)
            ids=duplicates+[mid for _,mid in sorted(ranked,key=lambda x:x[0],reverse=True)]
            return list(dict.fromkeys(mid for mid in ids if mid))[:24]
        return self.call(candidates(),timeout=3)

    def close(self):
        if self.thread and self.thread.is_alive():
            if self.memory:
                try:self.call(self.memory.close())
                except Exception:pass
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2)
        self.memory=None;self.reranker=None
        if not self.loop.is_running() and not self.loop.is_closed():self.loop.close()
