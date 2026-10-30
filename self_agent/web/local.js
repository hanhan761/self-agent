'use strict';
const $=s=>document.querySelector(s);
const labels={fact:'事实',preference:'偏好',decision:'约定',procedure:'做法'};
const states={active:'已保存',candidate:'待确认',superseded:'历史记录',forgotten:'已移出'};
let info={},editing=null,currentMemory=null,items=[],selected=new Map(),status='active',limit=50,revision=0,searchTimer;
const time=t=>t?new Date(t*1000).toLocaleString('zh-CN',{year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}):'—';
function element(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function toast(text){$('#toast').textContent=text;$('#toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').hidden=true,4500);}
function closeAll(){document.querySelectorAll('dialog[open]').forEach(d=>d.close());}
function lock(){closeAll();$('#app').hidden=true;$('#locked').hidden=false;closeReview();}
async function api(path,options={}){const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});const data=await response.json();if(!response.ok){if(response.status===401)lock();throw Error(typeof data.detail==='string'?data.detail:response.status===409?'有等义记忆已在目标范围，请分开整理。':'操作未完成，请刷新后重试');}return data;}
const action=fn=>Promise.resolve().then(fn).catch(error=>toast(error.message));
function button(text,handler,cls=''){const b=element('button',text,'button '+cls);b.type='button';b.onclick=()=>action(handler);return b;}
function projectName(project){return project?(info.project_names?.[project]||project.split('/').filter(Boolean).pop()):'全局记忆';}
function updateProjects(){
 for(const id of ['scope','memory-project','source-project','detail-project','bulk-project']){
  const select=$('#'+id),old=select.value;select.replaceChildren();
  if(id==='scope')select.append(new Option('全部范围','*'));
  if(id==='bulk-project')select.append(new Option('选择项目…','*'));else select.append(new Option('全局记忆',''));
  for(const p of info.projects||[])select.append(new Option(projectName(p),p));
  if([...select.options].some(o=>o.value===old))select.value=old;
 }
 renderNavigation();
}
function renderNavigation(){
 const global=info.scope_counts?.global?.active||0;
 const numbers={all:info.counts?.active||0,global,candidate:info.counts?.candidate||0,history:info.counts?.superseded||0,forgotten:info.counts?.forgotten||0};
 const scope=$('#scope').value,view=status==='active'?(scope===''?'global':scope==='*'?'all':'project'):({candidate:'candidate',superseded:'history',forgotten:'forgotten'}[status]);
 for(const [name,n] of Object.entries(numbers)){const b=$('#nav-'+name);b.querySelector('b').textContent=n;b.classList.toggle('selected',view===name);b.setAttribute('aria-current',view===name?'page':'false');}
 const list=$('#project-list');list.replaceChildren();const query=$('#project-query').value.toLocaleLowerCase();
 for(const p of info.projects||[]){
  if(!projectName(p).toLocaleLowerCase().includes(query))continue;
  const n=info.project_counts?.[p]?.active||0;
  const b=button('',()=>switchView('project',p),'nav-item');b.append(element('span',projectName(p)),element('b',String(n)));b.title=projectName(p);b.classList.toggle('selected',scope===p&&status==='active');list.append(b);
 }
 const title=status==='active'?(scope==='*'?'全部记忆':projectName(scope)):states[status];
 $('#view-title').textContent=title;
 const descriptions={candidate:'依据不足或存在冲突的内容，只在你确认后使用。',superseded:'被更新或替代的旧记忆，不参与自动召回。',forgotten:'你移出的内容，不会被自动重新加入。'};
 $('#view-description').textContent=descriptions[status]||(scope===''?'跨项目复用的习惯、偏好与通用方法。':scope==='*'?'从全局习惯到项目约定，都有来源可查。':'这里仅显示该项目的内容；智能体使用时会同时参考全局记忆。');
 $('#rename-project').hidden=scope==='*'||scope==='';
}
function switchView(view,project){
 status=({candidate:'candidate',history:'superseded',forgotten:'forgotten'}[view]||'active');
 $('#scope').value=view==='global'?'':view==='project'?project:'*';resetFilters();
}
function resetFilters(){limit=50;selected.clear();closeReview();action(()=>refresh());}
function renderMemories(){
 const list=$('#memory-list');list.replaceChildren();const grouping=$('#group').value,groups=new Map();
 for(const m of items){const key=grouping==='kind'?labels[m.kind]:grouping==='project'?projectName(m.project):'';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(m);}
 const orderedGroups=[...groups];if(grouping==='kind')orderedGroups.sort(([a],[b])=>['偏好','做法','约定','事实'].indexOf(a)-['偏好','做法','约定','事实'].indexOf(b));
 for(const [name,rows] of orderedGroups){
  if(name)list.append(element('h2',name,'group-heading'));
  for(const m of rows){
   const row=element('article',undefined,'memory-row');row.dataset.id=m.id;row.classList.toggle('is-current',currentMemory?.id===m.id);
   const check=element('input');check.type='checkbox';check.checked=selected.has(m.id);check.setAttribute('aria-label','选择记忆：'+m.content.slice(0,40));check.onchange=()=>{if(check.checked){if(selected.size>=100){check.checked=false;toast('每次最多整理100条');return;}selected.set(m.id,m.version);}else selected.delete(m.id);renderSelection();};
   const copy=element('button',undefined,'memory-copy');copy.type='button';copy.setAttribute('aria-label','查看记忆：'+m.title);
   const content=element('p',m.content);copy.append(content);const meta=element('div',undefined,'memory-meta');
   meta.append(element('span',labels[m.kind]||'记忆','kind-label'),element('span',projectName(m.project)),element('time',time(m.observed_at||m.created)));
   copy.append(meta);copy.onclick=()=>{if(currentMemory?.id===m.id)closeReview();else action(()=>openDetail(m.id));};row.append(check,copy,element('span','›','row-chevron'));list.append(row);
  }
 }
 if(!items.length){const empty=element('div',undefined,'empty');empty.append(element('h2',$('#query').value?'没有找到相关记忆':'这里暂时没有内容'),element('p','可以调整范围或筛选，也可以手动添加。'));list.append(empty);}
 renderSelection();
}
function renderSelection(){
 $('#bulk-bar').hidden=!selected.size;$('#selection-count').textContent='已选 '+selected.size+' 条';$('#bulk-activate').hidden=status!=='candidate';
 const writable=['active','candidate'].includes(status);for(const id of ['bulk-global','bulk-project','bulk-move'])$('#'+id).hidden=!writable;
 $('#bulk-forget').hidden=status==='forgotten';
 $('#select-all').checked=items.length>0&&items.every(m=>selected.has(m.id));$('#select-all').indeterminate=selected.size>0&&!$('#select-all').checked;
}
async function refresh(){
 const generation=++revision,scope=$('#scope').value,params=new URLSearchParams({status,q:$('#query').value.trim(),kind:$('#kind').value,sort:$('#sort').value,exact_project:'true',limit:'50'});
 if(scope!=='*')params.set('project',scope);
 const [overview,first]=await Promise.all([api('/api/overview'),api('/v1/memories?'+params)]);
 let loaded=first.items;
 while(loaded.length<limit&&loaded.length<first.total){params.set('offset',loaded.length);const next=await api('/v1/memories?'+params);if(!next.items.length)break;loaded=loaded.concat(next.items);}
 if(generation!==revision)return;info=overview;items=loaded;updateProjects();renderMemories();
 $('#memory-count').textContent='共 '+first.total+' 条 · 已载入 '+items.length+' 条';$('#load-more').hidden=items.length>=first.total;
 $('#capture-status').textContent=info.last_captured_at?'最近采集 '+time(info.last_captured_at):'等待下一次对话采集';
 const pressure=info.capacity?.blocked_reason,preparing=info.processing?.waiting_for_index,health=info.provider.health||{},blocked=health.state==='blocked';
 const problems=(info.job_counts?.failed||0)+(info.job_counts?.uncertain||0);
 $('#service-state').textContent=pressure?'资源保护中':blocked?'自动整理暂停':preparing?'正在准备索引':health.state==='fallback'?'备用模型工作中':problems?'部分资料待处理':info.provider.configured?'自动记忆已开启':'等待后台整理';
 renderModelStatus(problems);
 const gb=n=>(n/1024**3).toFixed(2);
 $('#service-info').textContent='共 '+info.sources+' 条原始资料 · '+(info.search.semantic?'本机语义检索已开启':'关键词检索可用')+(info.capacity?' · 已用 '+gb(info.capacity.bytes_used)+' GB，磁盘剩余 '+gb(info.capacity.disk_free_bytes)+' GB':'');
 renderJobs();
 window.memoryGrowth.refresh(status==='active'&&scope==='*',JSON.stringify(info.counts));
}
function renderModelStatus(problems){
 const h=info.provider.health||{},blocked=h.state==='blocked',fallback=h.state==='fallback',active=h.active_model||info.provider.model;
 const reasons={model_not_granted:'候选模型均未获使用权限',models_cooling_down:'候选模型都在故障冷却中',account_unavailable:'当前交晓智账号暂时无法调用',catalog_unavailable:'暂时无法核验模型权限',provider_request_failed:'模型请求失败，正在重新选择',rate_limited:'当前模型限流，正在重新选择',model_quality_rejected:'模型回复未通过校验，正在重新选择',native_account_not_allowed:'登录账号已变化，需要重新确认授权',xjcode_login_required:'需要重新登录交晓智',xjcode_login_unavailable:'本机校园登录暂不可用'};
 const last=(h.switches||[]).at(-1),retryingPreferred=!blocked&&!fallback&&last?.reason==='preferred_recovered'&&Date.now()/1000-last.at<3600;
 const confirmed=(h.models||[]).some(m=>m.name===active&&m.last_validated>=last?.at);
 const notice=$('#processing-notice');notice.hidden=!blocked&&!fallback&&!problems&&!retryingPreferred;notice.dataset.tone=retryingPreferred&&confirmed&&!problems?'success':'warning';
 notice.textContent=(blocked?(reasons[h.reason]||'自动整理暂时不可用')+'。新对话继续保存在本机，待可用模型恢复后整理。':fallback?'优先模型 '+h.preferred_model+' 暂不可用，已自动切换到备用模型 '+active+'。':retryingPreferred?(confirmed?'已恢复使用优先模型 ':'正在重新验证优先模型 ')+active+'。':'')+(problems?'有 '+problems+' 份资料未完成整理，可在下方“后台动态”查看。':'');
 $('#model-status-summary').textContent=(blocked?'整理暂停 · '+(h.active_model?'上次模型 ':'优先模型 '):'当前模型 ')+active+' · '+(h.auto_switch?'自动切换已开启':'固定模型')+(h.checked_at?' · 最近检查 '+time(h.checked_at):'');
 const body=$('#model-status-body');body.replaceChildren();
 for(const m of h.models||[]){
  const row=element('div',undefined,'model-status-row'),cooling=m.cooldown_until>Date.now()/1000;
  row.append(element('strong',m.name),element('span',m.name===active?(blocked?'上次选择':'当前使用'):m.name===h.preferred_model?'优先':'备用','muted'));
  row.append(element('span',cooling?'冷却至 '+time(m.cooldown_until):!m.granted?'暂无权限':m.last_validated&&m.last_validated>=(m.last_failure||0)?'最近校验 '+time(m.last_validated):'已授权，等待实际回复验证','muted'));
  body.append(row);
 }
 const labels={model_not_granted:'权限不可用',provider_request_failed:'请求失败',rate_limited:'限流',model_quality_rejected:'回复未通过校验',preferred_recovered:'重新尝试优先模型'};
 for(const e of (h.switches||[]).slice(-5).reverse())body.append(element('p',time(e.at)+' · '+e.from+' → '+e.to+' · '+(labels[e.reason]||'模型切换'),'model-switch-event'));
}
function renderJobs(){
 const pending=(info.capacity?.pending_jobs||0)+(info.capacity?.capture_batches||0);const problems=(info.job_counts?.failed||0)+(info.job_counts?.uncertain||0);$('#activity-label').textContent=problems?problems+' 项未完成'+(pending?' · '+pending+' 项'+(info.provider.health?.state==='blocked'?'等待模型恢复':'等待整理'):''):pending?pending+' 项'+(info.provider.health?.state==='blocked'?'等待模型恢复':'正在整理'):info.provider.health?.state==='blocked'?'整理暂停':info.provider.health?.state==='fallback'?'备用模型工作中':'已同步';const list=$('#job-list');list.replaceChildren();
 const names={done:'整理完成',pending:'等待整理',running:'正在整理',history_pending:'历史资料等待整理',history_running:'历史资料正在整理',failed:'未能完成整理',uncertain:'处理结果待核实'};
 for(const job of (info.jobs||[]).slice(0,12)){const row=element('div',undefined,'job-row');row.append(element('span',names[job.state]||job.state),element('span',time(job.created),'muted'));if(['failed','uncertain'].includes(job.state))row.append(button('重试',async()=>{if(job.state==='uncertain'&&!confirm('上次结果不明，重试可能再次消耗模型额度。继续？'))return;await api('/v1/jobs/'+job.id+'/retry',{method:'POST',body:'{}'});await refresh();}));list.append(row);}
}
function closeReview(){resizingReview=false;document.body.classList.remove('resizing-review');detailRevision++;currentMemory=null;$('#review-detail').hidden=true;$('#review-panel').hidden=true;$('#review-panel').classList.remove('is-open');$('#app').classList.remove('review-open','review-expanded');$('#expand-review').textContent='展开阅读';$('#expand-review').setAttribute('aria-expanded','false');document.querySelectorAll('.is-current').forEach(n=>n.classList.remove('is-current'));}
async function openDetail(id){
 const request=++detailRevision,m=await api('/v1/memories/'+id);if(request!==detailRevision)return;currentMemory=m;$('#review-detail').hidden=false;$('#review-panel').hidden=false;$('#review-panel').classList.add('is-open');$('#app').classList.add('review-open');
 $('#detail-title').textContent=m.topic||labels[m.kind]+'记忆';$('#detail-content').textContent=m.content;
 const properties=$('#detail-properties');properties.replaceChildren();for(const [k,v] of [['类型',labels[m.kind]],['范围',projectName(m.project)],['状态',states[m.status]],['陈述时间',time(m.observed_at)]])properties.append(element('dt',k),element('dd',v));
 const reasons={unvalidated_reconciliation:'原话已保留，但与旧记忆的关系尚未确认。',historical_one_off:'历史中的一次性操作，不作为未来的通用授权。',historical_scope_uncertain:'适用范围尚不明确，暂不自动使用。',conflict:'与已有记忆存在冲突，暂不自动使用。'};
 $('#detail-explanation').textContent=reasons[m.reason]||(m.project?'用于这个项目；全局记忆会另外参与相关问题的召回。':'可跨项目复用，只在与当前问题相关时提供给智能体。');
 const readonly=['forgotten','superseded'].includes(m.status);$('#edit-memory').hidden=readonly;$('#detail-forget').hidden=m.status!=='active'&&m.status!=='candidate';$('#detail-restore').hidden=m.status!=='forgotten';$('#detail-organization').hidden=readonly;
 $('#detail-project').value=m.project;const evidence=$('#detail-evidence');evidence.replaceChildren();for(const e of m.evidence||[]){const section=element('section');section.append(element('blockquote',e.quote),element('small',time(e.observed_at),'muted'));evidence.append(section);}if(!evidence.childElementCount)evidence.append(element('p','这条记忆没有附加引文，可查看原始资料。','muted'));
 $('#detail-source').hidden=!m.source_id;
 const history=$('#detail-history');history.replaceChildren();for(const v of (m.history||[]).slice(0,8)){const row=element('div',undefined,'history-item');row.append(element('small',time(v.changed)+' · '+(states[v.status]||v.status)),element('p',v.content));history.append(row);}
 const latest=(m.changes||[])[0];$('#undo-last').hidden=!latest||!!latest.undone;
 document.querySelectorAll('.memory-row').forEach(n=>n.classList.toggle('is-current',n.dataset.id===id));
}
async function organize(actionName,project,selection=selected){
 const result=await api('/v1/memories/bulk',{method:'POST',body:JSON.stringify({items:[...selection].map(([id,version])=>({id,version})),action:actionName,...(project!==undefined?{project}:{})})});
 selected.clear();toast('已整理 '+result.updated+' 条记忆');await refresh();if(currentMemory)await openDetail(currentMemory.id);
}
async function remove(memory){await api('/v1/memories/'+memory.id,{method:'DELETE'});closeAll();selected.delete(memory.id);toast('已移出，不再调用这条记忆');await refresh();await openDetail(memory.id);}
async function restore(memory){await api('/v1/memories/'+memory.id+'/restore',{method:'POST',body:JSON.stringify({version:memory.version})});closeAll();toast('已重新加入记忆');await refresh();await openDetail(memory.id);}
function newMemory(){editing=null;$('#memory-form').reset();updateProjects();$('#memory-project').value=$('#scope').value==='*'?'':$('#scope').value;$('#memory-content').disabled=false;$('#memory-project').disabled=false;$('#editor-title').textContent='添加记忆';$('#evidence').hidden=true;$('#evidence').open=false;$('#editor-remove').hidden=true;$('#editor-error').textContent='';$('#save-memory').hidden=false;$('#save-memory').textContent='保存';closeAll();$('#editor').showModal();$('#memory-content').focus();}
async function openEditor(id){const m=await api('/v1/memories/'+id);editing=m;closeAll();updateProjects();$('#memory-content').value=m.content;$('#memory-project').value=m.project;$('#memory-content').disabled=false;$('#memory-project').disabled=false;$('#editor-title').textContent='编辑记忆';$('#editor-remove').hidden=m.status!=='active';$('#save-memory').hidden=false;$('#save-memory').textContent=m.status==='candidate'?'确认并保存':'保存修改';$('#editor-error').textContent='';$('#evidence').hidden=true;$('#editor').showModal();}
$('#memory-form').onsubmit=async e=>{e.preventDefault();const save=$('#save-memory');save.disabled=true;$('#editor-error').textContent='';try{const values={content:$('#memory-content').value.trim(),project:$('#memory-project').value};const m=editing?await api('/v1/memories/'+editing.id,{method:'PATCH',body:JSON.stringify({...values,version:editing.version,...(editing.status==='candidate'?{status:'active'}:{})})}):await api('/v1/memories',{method:'POST',body:JSON.stringify(values)});if(m.status==='forgotten')throw Error('已移出的记忆请先明确重新加入。');$('#editor').close();toast('记忆已保存');await refresh();await openDetail(m.id);}catch(error){$('#editor-error').textContent=error.message;}finally{save.disabled=false;}};
$('#editor-remove').onclick=()=>action(()=>remove(editing));$('#add-memory').onclick=newMemory;
$('#edit-memory').onclick=()=>action(()=>openEditor(currentMemory.id));$('#detail-forget').onclick=()=>action(()=>remove(currentMemory));$('#detail-restore').onclick=()=>action(()=>restore(currentMemory));$('#close-review').onclick=closeReview;
$('#detail-move').onclick=()=>action(()=>organize('move',$('#detail-project').value,new Map([[currentMemory.id,currentMemory.version]])));
$('#detail-source').onclick=()=>action(()=>sourceDetail(currentMemory.source_id));
$('#undo-last').onclick=()=>action(async()=>{await api('/v1/changes/'+currentMemory.changes[0].id+'/undo',{method:'POST',body:'{}'});toast('已撤销最近整理');await refresh();await openDetail(currentMemory.id);});
$('#more').onclick=()=>$('#more-dialog').showModal();document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$('#'+b.dataset.close).close());
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>switchView(b.dataset.view));
$('#query').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(resetFilters,220);};
for(const id of ['scope','kind','sort'])$('#'+id).onchange=resetFilters;
$('#group').onchange=renderMemories;$('#project-query').oninput=renderNavigation;
$('#load-more').onclick=()=>{limit+=50;action(()=>refresh());};
$('#select-all').onchange=e=>{selected.clear();if(e.target.checked)for(const m of items.slice(0,100))selected.set(m.id,m.version);renderMemories();};
$('#clear-selection').onclick=()=>{selected.clear();renderMemories();};
$('#bulk-global').onclick=()=>action(()=>organize('move',''));$('#bulk-move').onclick=()=>action(async()=>{if($('#bulk-project').value==='*')throw Error('请先选择目标项目');await organize('move',$('#bulk-project').value);});
$('#bulk-activate').onclick=()=>action(()=>organize('activate'));$('#bulk-forget').onclick=()=>action(async()=>{if(confirm('移出选中的 '+selected.size+' 条记忆？以后不再调用，可在已移出中重新加入。'))await organize('forget');});
$('#rename-project').onclick=()=>action(async()=>{const project=$('#scope').value,label=prompt('项目名称',projectName(project));if(label===null||!label.trim())return;await api('/v1/projects/name',{method:'PATCH',body:JSON.stringify({project,label:label.trim()})});await refresh();});

async function sourceDetail(id){const source=await api('/v1/sources/'+id);closeAll();$('#source-view-title').textContent=source.title;const body=$('#source-view-body');body.replaceChildren();let messages;try{messages=JSON.parse(source.content);}catch{}if(Array.isArray(messages)&&messages.every(x=>x&&typeof x.content==='string')){for(const m of messages){const row=element('section',undefined,'source-message');row.append(element('strong',m.role==='user'?'你':'智能体'),element('p',m.content));body.append(row);}}else body.append(element('pre',source.content));$('#source-view').showModal();}
$('#view-sources').onclick=()=>action(async()=>{const data=await api('/v1/sources');closeAll();$('#source-view-title').textContent='原始资料';const body=$('#source-view-body');body.replaceChildren();for(const source of data.items)body.append(button(source.title+' · '+time(source.created),()=>sourceDetail(source.id),'source-row'));if(!data.items.length)body.append(element('p','尚无原始资料。','muted'));$('#source-view').showModal();});
$('#import-source').onclick=()=>{closeAll();$('#source-form').reset();updateProjects();$('#source-error').textContent='';$('#source-dialog').showModal();};
$('#text-file').onchange=()=>action(async()=>{const file=$('#text-file').files[0];if(!file)return;if(file.size>400000)throw Error('文件较大，请拆成较短的文字资料');const text=await file.text();if(text.length>120000)throw Error('内容超过 120000 字符');$('#source-content').value=text;if(!$('#source-title').value)$('#source-title').value=file.name;});
$('#source-form').onsubmit=async e=>{e.preventDefault();const b=e.currentTarget.querySelector('.primary');b.disabled=true;try{await api('/v1/sources',{method:'POST',body:JSON.stringify({title:$('#source-title').value,content:$('#source-content').value,project:$('#source-project').value,kind:'document'})});$('#source-dialog').close();toast('资料已保存，将在后台整理');await refresh();}catch(error){$('#source-error').textContent=error.message;}finally{b.disabled=false;}};
$('#export').onclick=()=>action(async()=>{const data=await api('/v1/export'),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),link=element('a');link.href=url;link.download='self-agent-'+new Date().toISOString().slice(0,10)+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('#restore').onclick=()=>action(async()=>{const file=$('#restore-file').files[0];if(!file)throw Error('请先选择备份文件');if(file.size>8*1024*1024)throw Error('备份超过 8 MiB');const data=JSON.parse(await file.text());if(!confirm('将备份合并到当前知识库，已有内容会保留。继续？'))return;const result=await api('/v1/restore',{method:'POST',body:JSON.stringify(data)});toast('已合并 '+result.restored+' 条记忆');await refresh(true);});


let detailRevision=0,preferredReviewWidth=380;
try{const saved=Number(localStorage.getItem('self-agent.review-width'));if(saved>=300&&saved<=720)preferredReviewWidth=saved;}catch{}
function setReviewWidth(width,persist=false){
 const maximum=Math.max(300,Math.min(720,innerWidth-618));
 const value=Math.round(Math.max(300,Math.min(maximum,width)));
 $('#app').style.setProperty('--review-width',value+'px');
 $('#review-resizer').setAttribute('aria-valuenow',String(value));
 $('#review-resizer').setAttribute('aria-valuemax',String(maximum));
 if(persist){preferredReviewWidth=value;try{localStorage.setItem('self-agent.review-width',String(value));}catch{}}
 return value;
}
function expandReview(){
 const expanded=$('#app').classList.toggle('review-expanded');
 $('#expand-review').textContent=expanded?'恢复侧栏':'展开阅读';
 $('#expand-review').setAttribute('aria-expanded',String(expanded));
}
const reviewResizer=$('#review-resizer');
let resizingReview=false;
reviewResizer.onpointerdown=e=>{
 if(e.button!==0)return;e.preventDefault();resizingReview=true;
 reviewResizer.setPointerCapture(e.pointerId);document.body.classList.add('resizing-review');
};
reviewResizer.onpointermove=e=>{if(resizingReview)setReviewWidth(innerWidth-e.clientX);};
function finishReviewResize(e){
 if(!resizingReview)return;resizingReview=false;document.body.classList.remove('resizing-review');
 setReviewWidth(parseFloat($('#app').style.getPropertyValue('--review-width')),true);
 if(reviewResizer.hasPointerCapture(e.pointerId))reviewResizer.releasePointerCapture(e.pointerId);
}
reviewResizer.onlostpointercapture=finishReviewResize;reviewResizer.onpointerup=finishReviewResize;reviewResizer.onpointercancel=finishReviewResize;
reviewResizer.onkeydown=e=>{
 const current=Number(reviewResizer.getAttribute('aria-valuenow'));
 const values={ArrowLeft:current+24,ArrowRight:current-24,Home:300,End:720};
 if(!(e.key in values))return;e.preventDefault();setReviewWidth(values[e.key],true);
};
$('#expand-review').onclick=expandReview;
addEventListener('resize',()=>setReviewWidth(preferredReviewWidth));
setReviewWidth(preferredReviewWidth);

reviewResizer.ondblclick=()=>setReviewWidth(380,true);
async function init(){try{await api('/api/me');$('#app').hidden=false;$('#locked').hidden=true;await refresh();}catch(error){if(!$('#app').hidden)toast(error.message);else lock();}}
setInterval(()=>{if(!$('#app').hidden&&document.visibilityState==='visible'&&!document.querySelector('dialog[open]'))action(()=>refresh());},5000);document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.querySelector('dialog[open]'))closeReview();});init();

document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&!$('#app').hidden)action(()=>refresh());});
