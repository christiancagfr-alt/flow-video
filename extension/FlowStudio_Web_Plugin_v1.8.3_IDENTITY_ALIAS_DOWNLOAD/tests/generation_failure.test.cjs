const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../downloads.js'),'utf8').replace('void dlRecover().catch(()=>{});','');
const events=[];
const ctx=vm.createContext({setTimeout,clearTimeout,URL,console,setInterval:()=>{},pushEvent:async e=>{events.push(e)},chrome:{storage:{local:{get:async()=>({}),set:async()=>{}}},downloads:{search:async()=>[],onChanged:{addListener(){}}},tabs:{query:async()=>[]},runtime:{onMessage:{addListener(){}}},alarms:{onAlarm:{addListener(){}},create(){}}}});
vm.runInContext(source,ctx);
(async()=>{
 ctx.sender={tab:{url:'https://flow.google.com/project/a'}};ctx.msg={info:{document_number:1,segment_id:11,host_id:2,command_id:'cmd',round:1}};
 const entry=await vm.runInContext('dlReserve(msg,sender)',ctx);ctx.key=entry.key;await vm.runInContext('dlBind({key,ids:["media"]})',ctx);
 await vm.runInContext('dlObserve({rows:[{id:"media",status:"failed",error:"policy"}]},sender)',ctx);
 assert.equal(events.length,1);assert.equal(events[0].type,'generation_task_failed');assert.equal(events[0].segment_id,11);assert.equal(events[0].command_id,'cmd');
 await vm.runInContext('dlObserve({rows:[{id:"media",status:"failed"}]},sender)',ctx);assert.equal(events.length,1);
 const rc=vm.createContext({URL});vm.runInContext(fs.readFileSync(path.join(__dirname,'../result-core.js'),'utf8'),rc);
 const api=rc.FlowStudioResults;assert.ok(api);
 const failures=api.records({id:'media',status:'MEDIA_GENERATION_STATUS_FAILED'});assert.equal(failures[0].status,'failed');
 assert.equal(api.catalogLinks({type:'VIDEO',id:'media',status:'FAILED'}).rows[0].status,'failed');
 console.log('PASS: real generation failures report once with exact command and segment; catalog failure recognized');
})().catch(e=>{console.error(e);process.exit(1)});
