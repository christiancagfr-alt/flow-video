const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.join(__dirname,'../downloads.js'),'utf8').replace('void dlRecover().catch(()=>{});','');
const ctx=vm.createContext({URL,Date,Promise,setTimeout,clearTimeout,setInterval(){},console,chrome:{storage:{local:{get:async()=>({}),set:async()=>{}}},downloads:{onChanged:{addListener(){}}},runtime:{onMessage:{addListener(){}}},alarms:{onAlarm:{addListener(){}},create(){}}}});
vm.runInContext(src,ctx);const run=x=>vm.runInContext(x,ctx);
(async()=>{await run(`dlReserve({info:{segment_id:9,document_number:9,command_id:'c',round:1}},{tab:{url:'https://flow.google.com/x'}}).then(e=>dlBind({key:e.key,ids:['actual-result']}))`);await assert.rejects(run(`dlReserve({info:{segment_id:10,document_number:10,command_id:'d',round:1}},{tab:{url:'https://flow.google.com/y'}}).then(e=>dlBind({key:e.key,ids:['actual-result']}))`),/RESULT_ID_CONFLICT/);
 const page=fs.readFileSync(path.join(__dirname,'../page-engine.js'),'utf8');const start=page.indexOf('  function attachmentIdentities'),end=page.indexOf('  function retainedReference',start);vm.runInContext(page.slice(start,end),ctx);
 ctx.item={id:'image-right',width:1080,height:1920,displayName:'right.png',created:'2026-09-12'};const ids=vm.runInContext('attachmentIdentities(item,[item])',ctx);assert.equal(ids.size,1);assert.equal(ids.has(1080),false);
 assert.ok(!page.includes('ticket.accepted=ticket.requestIds'));console.log('PASS: cross-channel duplicate result rejected; image dimensions/timestamps cannot identify first frame; request-ID guessing removed');
})().catch(e=>{console.error(e);process.exitCode=1});
