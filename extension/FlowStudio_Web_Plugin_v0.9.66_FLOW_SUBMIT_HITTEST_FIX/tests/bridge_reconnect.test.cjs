const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.join(__dirname,'../background.js'),'utf8');const start=src.indexOf("const OUTBOX_KEY="),end=src.indexOf('async function pollJobs()',start);
let offline=true,sent=[];
const ctx=vm.createContext({browserInstanceReady:Promise.resolve("browser-test"),Set,Date,Promise,AbortSignal,crypto:require('node:crypto').webcrypto,token:'t',heartbeat:async()=>true,pluginLog:async()=>{},chrome:{storage:{local:{get:async()=>({}),set:async()=>{}}}},fsFetch:async(u,opt)=>{if(offline)return {ok:false,status:503};sent.push(JSON.parse(opt.body));return {ok:true}}});
vm.runInContext(src.slice(start,end),ctx);const run=x=>vm.runInContext(x,ctx);const settle=async()=>{for(let i=0;i<10;i++)await new Promise(r=>setImmediate(r));};
(async()=>{
 await run("pushEvent({type:'web_plugin_progress_snapshot',host_id:0,channel_key:'CH1',command_id:'c',pending:5})");await settle();
 await run("pushEvent({type:'web_plugin_progress_snapshot',host_id:0,channel_key:'CH1',command_id:'c',pending:4})");await settle();
 await run("pushEvent({type:'generation_task_failed',segment_id:17,command_id:'c',event_id:'failure-17'})");await settle();
 assert.equal(run('outbox.length'),2);offline=false;
 await run('flushEvents()');assert.equal(run('outbox.length'),0);assert.equal(sent[0].event_id,'failure-17');assert.equal(sent[1].pending,4);
 console.log('PASS: failed HTTP retains receipts; reconnect prioritizes exact failure; redundant snapshots coalesced');
})().catch(e=>{console.error(e);process.exitCode=1});
