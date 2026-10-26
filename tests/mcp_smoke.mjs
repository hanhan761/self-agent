// Live protocol test against an isolated, synthetic preview account.
import {spawn} from 'node:child_process';
import {writeFile} from 'node:fs/promises';
const [python,root,clientConfig]=process.argv.slice(2);
const code="import os,sys;os.environ['SELF_AGENT_CLIENT_CONFIG']="+JSON.stringify(clientConfig)+";sys.path.insert(0,"+JSON.stringify(root)+");from self_agent.mcp_server import main;main()";
const child=spawn(python,['-X','utf8','-c',code],{windowsHide:true,stdio:['pipe','pipe','pipe']});
let buffer='',errors='',next=1;
const pending=new Map();
child.stderr.on('data',d=>errors+=d);
child.stdout.on('data',d=>{
 buffer+=d.toString('utf8');
 let at;
 while((at=buffer.indexOf('\n'))>=0){
  const line=buffer.slice(0,at);buffer=buffer.slice(at+1);
  let message;try{message=JSON.parse(line);}catch{continue;}
  if(message.id&&pending.has(message.id)){
   const {resolve,reject}=pending.get(message.id);pending.delete(message.id);
   if(message.error)reject(Error(JSON.stringify(message.error)));else resolve(message.result);
  }
 }
});
function call(method,params){return new Promise((resolve,reject)=>{
 const id=next++;pending.set(id,{resolve,reject});
 child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');
});}
const timeout=setTimeout(()=>{console.error('MCP test timed out',errors.slice(-1000));child.kill();process.exitCode=1;},18000);
try{
 const initialized=await call('initialize',{protocolVersion:'2025-11-25',capabilities:{},clientInfo:{name:'self-agent-acceptance',version:'1'}});
 child.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'})+'\n');
 const listed=await call('tools/list',{});
 if(listed.tools.length!==5)throw Error('Expected five tools');
 const remembered=await call('tools/call',{name:'memory_remember',arguments:{content:'协议验收样例：统一知识库支持跨客户端读取。',title:'MCP 协议验收',personal:true}});
 if(remembered.isError)throw Error('Remember failed: '+JSON.stringify(remembered.content));
 const found=await call('tools/call',{name:'memory_search',arguments:{query:'统一知识库 跨客户端'}});
 if(found.isError)throw Error('Search failed');
 const text=JSON.stringify(found);
 if(!text.includes('统一知识库支持跨客户端读取'))throw Error('Stored memory was not recalled');
 console.log(JSON.stringify({initialized:initialized.serverInfo.name,toolCount:listed.tools.length,rememberAndRecall:true,transport:'stdio'}));
}finally{clearTimeout(timeout);child.stdin.end();child.kill();}
