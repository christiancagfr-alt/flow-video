const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../downloads.js'),'utf8').replace('void dlRecover().catch(()=>{});','');
const ctx=vm.createContext({setTimeout,clearTimeout,URL,console,setInterval:()=>{},pushEvent:async()=>true,chrome:{storage:{local:{get:async()=>({}),set:async()=>{}}},downloads:{search:async()=>[],onChanged:{addListener(){}}},tabs:{query:async()=>[]},runtime:{onMessage:{addListener(){}}},alarms:{onAlarm:{addListener(){}},create(){}}}});
vm.runInContext(source,ctx);
(async()=>{
 ctx.sender={tab:{url:'https://flow.google.com/project/p'}};
 ctx.first={info:{document_number:1,task_id:'01-01',segment_id:101,host_id:1,command_id:'batch',round:1,download_name:'01-01-S000101'}};
 ctx.second={info:{document_number:1,task_id:'01-01',segment_id:202,host_id:2,command_id:'batch',round:1,download_name:'01-01-S000202'}};
 const a=await vm.runInContext('dlReserve(first,sender)',ctx),b=await vm.runInContext('dlReserve(second,sender)',ctx);
 assert.notEqual(a.key,b.key);assert.notEqual(a.filename,b.filename);
 const again=await vm.runInContext('dlReserve(first,sender)',ctx);assert.equal(a.key,again.key);
 assert.equal(vm.runInContext('dlState.entries.length',ctx),2);
 // Preserve a previously reserved old-key entry for the same unique segment.
 vm.runInContext("dlState.entries[0].key=JSON.stringify([dlState.entries[0].group,'batch','01-01',1])",ctx);
 const legacy=await vm.runInContext('dlReserve(first,sender)',ctx);assert.equal(legacy.key, a.key);assert.equal(legacy.filename,a.filename);assert.equal(legacy.existing,true);
 assert.equal(vm.runInContext('dlState.entries.length',ctx),2);
 console.log('PASS: duplicate display numbers across hosts stay distinct; same-segment/legacy reservations remain idempotent');
})().catch(e=>{console.error(e);process.exit(1)});
