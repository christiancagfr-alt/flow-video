const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../downloads.js'),'utf8').replace('void dlRecover().catch(()=>{});','');
async function run(fail){
 const entry={key:'k',group:'https://flow.google.com/test',status:'complete',download_id:1,completion_path_synced:true,info:{segment_id:1,host_id:2,command_id:'c'},media_id:'m'};
 const events=[];
 const ctx=vm.createContext({setTimeout,clearTimeout,URL,console,setInterval:()=>{},pushEvent:async e=>{if(fail)throw Error('storage failed');events.push(e)},chrome:{storage:{local:{get:async()=>({flowStudioDownloadsV0921:{entries:[entry],counters:{}}}),set:async()=>{}}},downloads:{search:async()=>[{filename:'/custom/downloads/video.mp4',state:'complete'}],onChanged:{addListener(){}}},tabs:{query:async()=>[]},runtime:{onMessage:{addListener(){}}},alarms:{onAlarm:{addListener(){}},create(){}}}});
 vm.runInContext(source,ctx);
 await vm.runInContext('dlTick()',ctx);
 if(fail){assert.equal(entry.qc_recovery_v27,undefined);assert.equal(events.length,0);}
 else {assert.equal(entry.qc_recovery_v27,true);assert.equal(events.length,1);assert.equal(events[0].output_path,'/custom/downloads/video.mp4');assert.equal(events[0].segment_id,1);await vm.runInContext('dlTick()',ctx);assert.equal(events.length,1);}
}
(async()=>{await run(false);await run(true);console.log('PASS: old completions requeued once; storage failure remains retryable');})().catch(e=>{console.error(e);process.exit(1)});
