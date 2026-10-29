'use strict';
window.memoryGrowth=(()=>{
 const panel=document.querySelector('#growth-panel'),canvas=document.querySelector('#growth-chart');
 const period=document.querySelector('#growth-period'),imports=document.querySelector('#growth-imports');
 const fontFamily='Arial,"Microsoft YaHei",sans-serif';
 let chart=null,data=null,lastFetch=0,lastKey='',requestId=0,pendingKey='',shown=false,revisionKey='';
 function paint(){
  if(!data)return;
  const include=imports.checked,total=data.totals.regular+(include?data.totals.imported:0),today=data.today.regular+(include?data.today.imported:0);
  document.querySelector('#growth-summary').textContent='今天 '+today+' 条 · '+data.items.length+' 天 '+total+' 条';
  document.querySelector('#growth-import-count').textContent=data.totals.imported?'（'+data.totals.imported+' 条）':'';
  canvas.setAttribute('aria-label','最近'+data.items.length+'天每日新增记忆，'+(include?'包含历史导入':'仅日常新增')+'，共'+total+'条');
  const table=document.querySelector('#growth-daily-values');table.replaceChildren();
  for(const row of data.items){const tr=document.createElement('tr');for(const value of [row.date,row.regular,row.imported]){const td=document.createElement('td');td.textContent=value;tr.append(td);}table.append(tr);}
  if(panel.hidden||!panel.open)return;
  const datasets=[{label:'日常新增',data:data.items.map(row=>row.regular),backgroundColor:'#477451',borderRadius:3,maxBarThickness:24}];
  if(include)datasets.push({label:'历史导入',data:data.items.map(row=>row.imported),backgroundColor:'#b6c8a6',borderRadius:3,maxBarThickness:24});
  const chartData={labels:data.items.map(row=>row.date.slice(5).replace('-','/')),datasets};
  if(chart){chart.data=chartData;chart.update('none');return;}
  chart=new Chart(canvas,{
   type:'bar',data:chartData,
   options:{font:{family:fontFamily},responsive:true,maintainAspectRatio:false,animation:false,resizeDelay:80,
    interaction:{mode:'index',intersect:false},
    plugins:{legend:{display:false},tooltip:{titleFont:{family:fontFamily},bodyFont:{family:fontFamily},displayColors:true,callbacks:{title:points=>data.items[points[0].dataIndex].date}}},
    scales:{x:{stacked:true,grid:{display:false},border:{display:false},ticks:{autoSkip:false,maxRotation:0,color:'#718166',font:{family:'Arial',size:10},callback(value,index,ticks){const step=Math.ceil(ticks.length/7),last=ticks.length-1;return index===last||(index%step===0&&index<=last-step)?this.getLabelForValue(value):'';}}},
     y:{stacked:true,beginAtZero:true,suggestedMax:1,border:{display:false},ticks:{precision:0,maxTicksLimit:5,color:'#718166',font:{family:'Arial',size:10}},grid:{color:'#edf1e7'}}}}
  });
 }
 async function load(force,key=revisionKey){
  if(!shown)return;
  const query=period.value+'|'+key;
  if(!force&&((lastKey===query&&Date.now()-lastFetch<30000)||pendingKey===query))return;
  const request=++requestId;pendingKey=query;
  try{
   const response=await fetch('/v1/stats/daily?days='+period.value);
   if(!response.ok)throw Error('stats_unavailable');
   const result=await response.json();
   if(request!==requestId)return;
   data=result;lastKey=query;lastFetch=Date.now();paint();
  }catch(error){
   if(request===requestId){lastKey=query;lastFetch=Date.now();document.querySelector('#growth-summary').textContent='统计暂时不可用';}
  }finally{if(request===requestId)pendingKey='';}
 }
 period.onchange=()=>load(true);
 imports.onchange=paint;
 panel.addEventListener('toggle',()=>{if(panel.open){paint();if(chart)chart.resize();}});
 return {refresh(visible,key){
  const becomingVisible=visible&&!shown;shown=visible;revisionKey=key;panel.hidden=!visible;
  if(visible){if(becomingVisible&&data){paint();if(chart)chart.resize();}load(false,key);}
 }};
})();
