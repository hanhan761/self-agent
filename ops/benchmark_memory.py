"""Isolated reproducible scale/relevance checks. Never opens the user's knowledge DB."""
import argparse,gc,hashlib,json,math,os,platform,sqlite3,time
from dataclasses import replace
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from self_agent.auth import Auth
from self_agent.config import Config
from self_agent.store import Store,fingerprint
from self_agent.engine import Engine

p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--canonical-sizes',type=int,nargs='+',default=[10000,100000]);p.add_argument('--vectors',type=int,default=10000);p.add_argument('--model-cache');a=p.parse_args()
out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
if (out/'canonical').exists():raise ValueError('benchmark_output_must_be_new')
report={'environment':{'platform':platform.system(),'machine':platform.machine(),'logical_cpus':os.cpu_count(),'python':platform.python_version()},'generative_requests':0,'components':{'mcp-memory-service':'12.4.0','APScheduler':'3.11.3','FlashRank':'0.2.10','reranker':'BGE base int8 CPU'},'canonical':[]}

def measure(fn,n=20):
    fn();times=[]
    for _ in range(n):start=time.perf_counter();fn();times.append(time.perf_counter()-start)
    values=sorted(times);return {'samples':n,'median_ms':round(values[n//2]*1000,3),'p95_ms':round(values[math.ceil(n*.95)-1]*1000,3),'max_ms':round(max(values)*1000,3)}

def seed(store,uid,start,end,noise=False):
    now=time.time()
    for begin in range(start,end,2000):
        rows=[];fts=[];versions=[]
        for i in range(begin,min(end,begin+2000)):
            mid='fixture-'+str(i);text=('压测构建批次 sample'+str(i)+'，完成固定编号的运行记录。') if noise else ('canonical benchmark memory sample'+str(i)+' uses sqlite storage')
            rows.append((mid,uid,'p','fact',text[:60],text,None,'active',1,now,now+i/10000,fingerprint(text)));fts.append((mid,text));versions.append((mid,1,text,'active',now))
        with store.tx() as db:db.executemany('INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',rows);db.executemany('INSERT INTO memory_fts VALUES(?,?)',fts);db.executemany('INSERT INTO versions VALUES(?,?,?,?,?)',versions)

def init(name):
    root=out/name;root.mkdir();store=Store(root/'memory.sqlite3');auth=Auth(store)
    return root,store,auth.create_user('owner','long-isolated-fixture-password')

root,store,uid=init('canonical');engine=Engine(Config(root),store);previous=0
for size in sorted(a.canonical_sizes):
    seed(store,uid,previous,size);previous=size
    target='canonical benchmark memory sample0 uses sqlite storage';item={'content':target,'kind':'fact'}
    result={'records':size,'keyword_unique':measure(lambda:engine.search(uid,'sample42','p')),'keyword_broad':measure(lambda:engine.search(uid,'sqlite memory','p')),
            'candidate_lookup':measure(lambda:store.lifecycle.candidates(uid,'p',item)), 'listing_100':measure(lambda:store.listing(uid,details=False))}
    rows_read=[0]
    def counted(cursor,row):rows_read[0]+=1;return sqlite3.Row(cursor,row)
    store.db.row_factory=counted;candidates=store.lifecycle.candidates(uid,'p',item);store.db.row_factory=sqlite3.Row
    result['candidate_python_rows']=rows_read[0];assert rows_read[0]<80 and len(candidates)<=8
    assert candidates[0]['id']=='fixture-0'
    report['canonical'].append(result);print(json.dumps({'canonical':result}),flush=True)
store.close();engine.close()

if a.vectors:
    if not a.model_cache:raise ValueError('explicit_offline_model_cache_required')
    from self_agent.local_index import LocalIndex
    root,store,uid=init('vectors');seed(store,uid,0,a.vectors,noise=True)
    other=Auth(store).create_user('other','another-long-fixture-password')
    fixtures=[('storage','知识库文件应存放在 D 盘，系统盘不要放资料。','p'),('language','技术说明默认使用中文。',''),('ui','管理页面保持简单，只显示记忆列表和搜索。','p'),('manual','我可以自己修改或移出长期记忆。','p')]
    ids={}
    for key,text,project in fixtures:ids[key]=store.add(uid,project,text,kind='preference')['id']
    foreign=store.add(other,'p',fixtures[0][1]);cross=store.add(uid,'secret-project',fixtures[0][1])
    removed=store.add(uid,'p','工程缓存应放在独立的本地目录。',kind='preference');store.update(uid,removed['id'],status='forgotten')
    cfg=Config(root,local=True,local_user_id=uid,semantic=True,index_backend='mcp-memory-service',model_cache=a.model_cache,embedding_model='paraphrase-multilingual-MiniLM-L12-v2')
    engine=Engine(cfg,store);index=engine.index;start=time.perf_counter();index.start()
    assert index.memory is not None,index.error
    assert index.reranker is not None,index.rerank_error
    loops=0
    while not index.ready_for_reconcile:
        index.sync();loops+=1
        if index.error:raise RuntimeError('projection_error:'+index.error)
        if loops>math.ceil((a.vectors+20)/cfg.projection_batch_size)+3:raise AssertionError('projection_not_progressing')
    build_seconds=time.perf_counter()-start;print(json.dumps({'vectors_indexed':a.vectors,'build_seconds':build_seconds}),flush=True)
    positive=[('storage','知识库文件应该存在哪个磁盘？'),('storage','Where should I keep the knowledge database files?'),('language','解释技术问题用什么语言？'),('language','Please explain technical details in Chinese'),('ui','管理页面应该是什么风格？'),('ui','How simple should the memory dashboard be?'),('manual','我可以删除不想要的记忆吗？'),('manual','Can I edit stored knowledge manually?'),('storage','文件默认保存在 D 盘吗？'),('ui','管理界面需要哪些内容？'),('manual','能由我手工移走某条长期知识吗？'),('language','Which language should your technical explanations use?')]
    negative=['北京明天天气怎样','晚饭红烧肉怎么做','跑鞋应该选哪个品牌','今天欧冠比分如何','纽约机票价格','怎样给盆栽浇水','推荐周末徒步路线','How do I bake bread?','What is the capital of Peru?','怎么给小猫喂食','量子纠缠是什么','如何练习游泳换气']
    cases=[]
    for key,query in positive:
        hits=engine.search(uid,query,'p');found={m['id'] for m in hits};cases.append({'kind':'positive','query':query,'passed':ids[key] in found and not any(mid.startswith('fixture-') for mid in found),'returned':len(hits),'noise_excluded':not any(mid.startswith('fixture-') for mid in found)})
        assert foreign['id'] not in found and cross['id'] not in found and removed['id'] not in found
    for query in negative:
        hits=engine.search(uid,query,'p');cases.append({'kind':'negative','query':query,'passed':not hits,'returned':len(hits)})
    candidates=store.lifecycle.candidates(uid,'p',{'content':'工程缓存放在本地单独的文件夹','kind':'preference'},index.candidate_ids(uid,'工程缓存放在本地单独的文件夹','p'))
    assert removed['id'] in {m['id'] for m in candidates},'forgotten semantic nomination missing'
    hybrid=measure(lambda:engine.search(uid,'知识库文件存放磁盘','p'))
    report['vectors']={'records':a.vectors+len(fixtures)+3,'build_seconds':round(build_seconds,3),'hybrid_recall':hybrid,'relevance_cases':cases,
                       'positive_passed':sum(c['passed'] for c in cases if c['kind']=='positive'),'positive_total':len(positive),
                       'negative_passed':sum(c['passed'] for c in cases if c['kind']=='negative'),'negative_total':len(negative),
                       'owner_project_isolation':True,'removed_excluded_from_recall':True,'removed_available_for_dedup':True}
    print(json.dumps({'vector_acceptance':report['vectors']}),flush=True)
    index.close();store.close();del engine,index;gc.collect()
    # Test loss/rebuild with a small separate fixture, not by deleting the large benchmark.
    root,store,uid=init('rebuild');mem=store.add(uid,'p','重建后仍需保留的明确记忆',kind='preference')
    cfg=replace(cfg,data_dir=root,local_user_id=uid);index=LocalIndex(cfg,store);index.start()
    while not index.ready_for_reconcile:index.sync()
    index.close();del index;gc.collect()
    for name in ['local-vectors.sqlite3','local-vectors.sqlite3-wal','local-vectors.sqlite3-shm']:
        file=root/name
        if file.exists():
            assert file.resolve().parent==root.resolve();file.unlink()
    index=LocalIndex(cfg,store);index.start()
    while not index.ready_for_reconcile:index.sync()
    assert mem['id'] in index.search_ids(uid,'重建保留的记忆','p');report['projection_loss_rebuilt']=True
    index.close();store.close()
report['passed']=all(c['passed'] for c in report.get('vectors',{}).get('relevance_cases',[]))
(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'completed':True,'passed':report['passed']}),flush=True)
if not report['passed']:raise SystemExit(2)
