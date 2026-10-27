import {spawn} from 'node:child_process';
const [python,source,client]=process.argv.slice(2);
const code="import os,sys;os.environ['SELF_AGENT_CLIENT_CONFIG']="+JSON.stringify(client)+";sys.path.insert(0,"+JSON.stringify(source)+");from self_agent.mcp_server import main;main()";
const child=spawn(python,['-X','utf8','-c',code],{windowsHide:true,stdio:['pipe','pipe','pipe']});
let buffer='',errors='',next=1;const pending=new Map();
child.stderr.on('data',d=>errors+=d);
child.stdout.on('data',d=>{buffer+=d.toString('utf8');let at;while((at=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,at);buffer=buffer.slice(at+1);let msg;try{msg=JSON.parse(line)}catch{continue}if(msg.id&&pending.has(msg.id)){const {resolve,reject,start,method}=pending.get(msg.id);pending.delete(msg.id);console.log(JSON.stringify({method,seconds:(Date.now()-start)/1000}));if(msg.error)reject(Error('MCP protocol error'));else resolve(msg.result);}}});
function call(method,params){return new Promise((resolve,reject)=>{const id=next++;pending.set(id,{resolve,reject,start:Date.now(),method});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n')})}
const timer=setTimeout(()=>{console.error('MCP timeout; '+errors.slice(-1600));child.kill();process.exitCode=1},60000);
try{
 await call('initialize',{protocolVersion:'2025-11-25',capabilities:{},clientInfo:{name:'local-frozen-acceptance',version:'1'}});
 child.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'})+'\n');
 const list=await call('tools/list',{});if(list.tools.length!==5)throw Error('tool count');
 for(const args of [{query:'技术说明语言',project:'mcp-fixture'},{query:'技术说明语言'}]){
  const result=await call('tools/call',{name:'memory_search',arguments:args});if(result.isError)throw Error(JSON.stringify(result.content));
 }
 console.log(JSON.stringify({passed:true,toolCount:5,transport:'pythonw stdio',automaticProject:true}));
}finally{clearTimeout(timer);child.stdin.end();child.kill()}
