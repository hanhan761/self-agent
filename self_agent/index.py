"""Mem0 is a rebuildable projection. SQLite owns content, lifecycle and access."""
import os
import threading

class Index:
    def __init__(self,config,store):
        self.config,self.store=config,store
        self.memory=None
        self.error='disabled' if not config.semantic else 'not_loaded'
        self.lock=threading.Lock()

    def start(self):
        if not self.config.semantic:return
        with self.lock:
            try:
                os.environ['MEM0_DIR']=str(self.config.data_dir/'mem0')
                os.environ['MEM0_TELEMETRY']='false'
                os.environ['ANONYMIZED_TELEMETRY']='false'
                os.environ['HF_HUB_OFFLINE']='1'
                os.environ['TOKENIZERS_PARALLELISM']='false'
                from .provider import register_mem0_provider
                native_llm=register_mem0_provider(self.config)
                from mem0 import Memory
                from mem0.configs.base import MemoryConfig
                self.memory=Memory(config=MemoryConfig(**{
                    'llm':native_llm,
                    'embedder':{'provider':'huggingface','config':{'model':self.config.embedding_model,
                        'model_kwargs':{'device':self.config.embedding_device,'local_files_only':True},'embedding_dims':self.config.embedding_dims}},
                    'vector_store':{'provider':'qdrant','config':{'collection_name':'self_agent','path':str(self.config.data_dir/'vectors'),'embedding_model_dims':self.config.embedding_dims}},
                    'history_db_path':str(self.config.data_dir/'mem0-history.db')}))
                self.error=''
            except Exception as exc:
                self.error=type(exc).__name__
                self.memory=None
                import traceback
                (self.config.data_dir/'index-error.log').write_text(traceback.format_exc(),'utf-8')

    def sync(self):
        if not self.memory:return
        with self.lock:
            with self.store.tx() as db:
                rows=[dict(x) for x in db.execute('SELECT m.*,p.external_id FROM memories m LEFT JOIN projections p ON p.memory_id=m.id WHERE p.version IS NULL OR p.version!=m.version LIMIT 20')]
            for row in rows:
                mid=row['id']
                try:
                    scope=row['user_id']+':'+row['project']
                    existing=self.memory.get_all(user_id=scope,limit=10000)
                    existing=existing.get('results',[]) if isinstance(existing,dict) else existing
                    for item in existing:
                        if item.get('metadata',{}).get('canonical_id')==mid:self.memory.delete(item['id'])
                    external=None
                    if row['status']=='active':
                        added=self.memory.add(row['content'],user_id=scope,infer=False,metadata={'canonical_id':mid,'version':row['version']})
                        results=added.get('results',added) if isinstance(added,dict) else added
                        external=results[0]['id'] if results else None
                        if not external:raise RuntimeError('empty_projection')
                    with self.store.tx() as db:db.execute('INSERT OR REPLACE INTO projections VALUES(?,?,?,?)',(mid,row['version'],external,''))
                except Exception as exc:
                    self.error=type(exc).__name__
                    return
            self.error=''

    def search_ids(self,uid,query,project):
        if not self.memory:return []
        result=[]
        with self.lock:
            for scope in dict.fromkeys([uid+':',uid+':'+project]):
                found=self.memory.search(query,user_id=scope,limit=20)
                items=found.get('results',[]) if isinstance(found,dict) else found
                result.extend(x.get('metadata',{}).get('canonical_id') for x in items)
        return result
