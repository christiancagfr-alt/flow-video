const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../downloads.js'),'utf8').replace('void dlRecover().catch(()=>{});','');
let scans=0,queries=0,notifications=[],started=[];
const tabs=Array.from({length:10},(_,id)=>({id,url:'https://flow.google.com/project/'+id}));
const context=vm.createContext({URL,Date,Promise,setTimeout,clearTimeout,setInterval:()=>{},console:{info(){},error(){}},pushEvent:async e=>notifications.push(e),chrome:{storage:{local:{get:async()=>({}),set:async()=>{}}},tabs:{query:async()=>{queries++;return tabs},sendMessage:async(id,msg)=>{if(msg.type==='FS_DOWNLOAD_SCAN')scans++}},downloads:{download:async info=>{started.push(info);return started.length;},search:async({id})=>[{id,state:'complete',filename:'/tmp/result-'+id+'.mp4'}],onChanged:{addListener(){}}},runtime:{onMessage:{addListener(){}}},alarms:{onAlarm:{addListener(){}},create(){}}}});
vm.runInContext(source,context);
const run=s=>vm.runInContext(s,context);
(async()=>{
 for(let i=0;i<10;i++){
  context.i=i;
  await run(`dlReserve({info:{document_number:1,segment_id:i+1,command_id:'cmd',round:1}},{tab:{url:'https://flow.google.com/project/'+i}}).then(e=>dlBind({key:e.key,ids:['media'+i]}))`);
 }
 await Promise.all(Array.from({length:100},()=>run('dlTick()')));
 assert.equal(queries,1);assert.equal(scans,10);
 // Cloud failure arrives before the ID binding callback.
 await run(`dlObserve({rows:[{id:'early',status:'failed',error:'generation rejected'}]},{tab:{url:'https://flow.google.com/project/0'}})`);
 await run(`dlReserve({info:{document_number:2,segment_id:99,command_id:'cmd',round:1}},{tab:{url:'https://flow.google.com/project/0'}}).then(e=>dlBind({key:e.key,ids:['early']}))`);
 assert.equal(notifications.filter(e=>e.type==='generation_task_failed').length,1);
 // Each group starts independently, all successful assets drain and are reported once.
 for(let i=0;i<10;i++){context.i=i;await run(`dlObserve({rows:[{id:'media'+i,status:'ready',url:'https://flow-content.google/video/file'+i}]},{tab:{url:'https://flow.google.com/project/'+i}})`);}
 for(let i=0;i<20;i++){await new Promise(r=>setTimeout(r,1));await run('dlPump()');}
 assert.equal(started.length,10);assert.equal(notifications.filter(e=>e.type==='video_download_completed').length,10);
 await run('dlLastTick=0;dlTick()');
 assert.equal(notifications.filter(e=>e.type==='video_download_completed').length,10);
 const results=require('../result-core.js');
 assert.equal(results.catalogLinks({type:'VIDEO',id:'x',mediaGenerationStatus:'SUCCESSFUL'}).rows[0].status,'ready');
 assert.equal(results.catalogLinks({type:'VIDEO',id:'x',history:[{id:'x',status:'SUCCESSFUL'}]}).rows.length,0);
 console.log('PASS: 100 polls -> one 10-channel scan; early failure rebound; 10 channels downloaded; completion exactly once; explicit success without CDN URL recognized');
})().catch(e=>{console.error(e);process.exitCode=1});
