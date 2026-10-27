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

    def call(self, task, timeout=15):
        future = asyncio.run_coroutine_threadsafe(task, self.loop)
        try:return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise

    def start(self):
        if not self.config.semantic:
            self.error='disabled'
            return
        try:
            import importlib.metadata
            if importlib.metadata.version('mcp-memory-service') != '12.4.0':
                raise RuntimeError('unexpected_memory_backend_version')
            if self.config.model_cache:
                os.environ['HF_HOME']=self.config.model_cache
            os.environ.update({'MCP_MEMORY_USE_ONNX':'true','MCP_MEMORY_ONNX_ALLOW_DOWNLOAD':'0',
                               'HF_HUB_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1',
                               'ANONYMIZED_TELEMETRY':'false','TOKENIZERS_PARALLELISM':'false'})
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
            memory=PinnedStorage(str(self.config.data_dir/'local-vectors.sqlite3'),embedding_model=self.config.embedding_model)
            memory.semantic_dedup_enabled=False  # Canonical, scoped reconciliation owns deduplication.
            self.call(memory.initialize(),timeout=90)
            self.memory=memory
            # A lost/recreated projection is fully rebuildable from canonical SQLite.
            with self.store.tx() as db:
                db.execute("UPDATE projections SET version=0 WHERE external_id NOT LIKE 'mms:%' OR external_id IS NULL")
                rows=list(db.execute('SELECT memory_id,external_id FROM projections WHERE external_id IS NOT NULL'))
            for row in rows:
                if row['external_id'].startswith('mms:') and not self.call(memory.get_by_hash(row['external_id'][4:])):
                    with self.store.tx() as db:db.execute('UPDATE projections SET version=0 WHERE memory_id=?',(row['memory_id'],))
            self.error=''
        except Exception as exc:
            self.error=type(exc).__name__
            self.memory=None
            import traceback
            (self.config.data_dir/'index-error.log').write_text(traceback.format_exc(),'utf-8')

    @staticmethod
    def scope(uid,project):
        return 'scope:'+hashlib.sha256((uid+'\0'+project).encode()).hexdigest()

    def sync(self):
        if self.memory is None:return
        from mcp_memory_service.models.memory import Memory
        with self.lock:
            with self.store.tx() as db:
                rows=[dict(x) for x in db.execute('SELECT m.*,p.external_id FROM memories m LEFT JOIN projections p ON p.memory_id=m.id WHERE p.version IS NULL OR p.version!=m.version LIMIT 20')]
            for row in rows:
                try:
                    old=row['external_id']
                    if old and old.startswith('mms:'):
                        self.call(self.memory.delete(old[4:]))
                    external=None
                    if row['status']=='active':
                        # Include scope and stable canonical identity: equal text across projects never coalesces.
                        key=hashlib.sha256((row['user_id']+'\0'+row['project']+'\0'+row['id']+'\0'+str(row['version'])).encode()).hexdigest()
                        item=Memory(content=row['content'],content_hash=key,
                                    tags=[self.scope(row['user_id'],row['project'])],
                                    metadata={'canonical_id':row['id'],'version':row['version']})
                        ok,_=self.call(self.memory.store(item,skip_semantic_dedup=True,recreate=True))
                        if not ok:raise RuntimeError('projection_store_failed')
                        external='mms:'+key
                    with self.store.tx() as db:
                        db.execute('INSERT OR REPLACE INTO projections VALUES(?,?,?,?)',(row['id'],row['version'],external,''))
                except Exception as exc:
                    self.error=type(exc).__name__
                    return
            self.error=''

    def search_ids(self,uid,query,project):
        if self.memory is None:return []
        results=self.call(self.memory.retrieve(query,n_results=20,
                      tags=list(dict.fromkeys([self.scope(uid,''),self.scope(uid,project)]))),timeout=1.5)
        return [item.memory.metadata.get('canonical_id') for item in results]

    def close(self):
        if self.thread and self.thread.is_alive():
            if self.memory:
                try:self.call(self.memory.close())
                except Exception:pass
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2)
