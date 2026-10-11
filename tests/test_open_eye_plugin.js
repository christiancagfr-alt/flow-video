const fs=require('fs'), vm=require('vm'), assert=require('assert/strict');
const path=require('path');
const root=path.join(__dirname,'../extension/FlowStudio_Web_Plugin_v1.8.3_IDENTITY_ALIAS_DOWNLOAD');
const results=require(path.join(root,'result-core.js'));
const code=fs.readFileSync(path.join(root,'page-engine.js'),'utf8');
const start=code.indexOf('  async function ensureOpenEye(detail)');
const end=code.indexOf("  window.addEventListener('FLOW_STUDIO_MAIN_COMMAND'",start);
function signal(value){const f=()=>value;f.set=v=>value=v;return f;}
function setup(){
 const catalog=[{id:'original-id',type:'IMAGE',displayName:'source.png',url:'https://example.test/source'}];
 const mode=signal('VIDEO_FRAMES'),model=signal('veo_3_1_lite_low_priority'),editor=signal({blocks:[]});
 const ledger=new Map();let clicks=0;
 const context={console,JSON,Date,Map,Set,Error,
   context:()=>({instance:{},service:{clear(){},setAspectRatio(){}}}),
   modes:['VIDEO_FRAMES','IMAGE_EDIT','IMAGE'],models:['banana2','veo_3_1_lite_low_priority'],
   signal:(s,p)=>p(mode())?mode:model,constructorSignal:()=>signal(1),
   localStorage:{getItem:k=>ledger.get(k)||null,setItem:(k,v)=>ledger.set(k,v)},
   mediaList:()=>catalog,FlowStudioResults:results,
   flowAssetFlags:x=>({ready:x.status==='ready',loading:x.status==='pending',error:x.status==='failed'}),
   mediaURL:x=>x.url||'',waitExistingFlowImageAssetReady:async(i,x)=>x,
   attachmentIdentities:x=>new Set([x.id]),composerPreviews:()=>[],composerContext:()=>({}),
   aspectValue:x=>x,selectMethod:()=>async()=>{},editorSignal:()=>editor,
   syncComposerUi:async()=>{},waitGenerateButton:async()=>{},
   stateSnapshot:()=>new Map([['ref',{data:'original-id'}]]),hasTarget:(v,ids)=>ids.has(v),
   referencePreview:()=>false,safeGenerateClick:async()=>{clicks++;}
 };
 vm.createContext(context);vm.runInContext(code.slice(start,end)+'\nglobalThis.run=ensureOpenEye;',context);
 return {run:context.run,catalog,ledger,clicks:()=>clicks};
}
(async()=>{
 const detail={eye_key:'a'.repeat(64),prompt:'Open both eyes while preserving the identity of reference a',image_id:'original-id',aspect_ratio:'9:16'};
 const s=setup();assert.equal((await s.run(detail)).ready,false);assert.equal(s.clicks(),1);
 assert.equal((await s.run(detail)).ready,false);assert.equal(s.clicks(),1,'uncertain submission must not repeat');
 s.catalog.push({id:'new-image',type:'IMAGE',prompt:detail.prompt,status:'pending',url:'https://example.test/new'});
 assert.equal((await s.run(detail)).ready,false,'pending placeholder must not unblock video');
 s.catalog[1].status='ready';assert.equal((await s.run(detail)).image_id,'new-image');assert.equal(s.clicks(),1);
 s.catalog[1].status='failed';await assert.rejects(s.run(detail),/生成失败/);assert.equal(s.clicks(),1);
 const wrong=setup();await assert.rejects(wrong.run({...detail,image_id:'other-host'}),/SOURCE_MISSING/);assert.equal(wrong.clicks(),0);
 const rows=[{id:'image',type:'IMAGE',prompt:'A sufficiently long exact test prompt for identity'},{id:'video',type:'VIDEO',prompt:'A sufficiently long exact test prompt for identity'}];
 assert.deepEqual(results.exactPromptVideoIds(rows,'A sufficiently long exact test prompt for identity'),['video']);
 assert.deepEqual(results.exactPromptVideoIds(rows,'A sufficiently long exact test prompt for identity',[],'IMAGE'),['image']);
 assert.deepEqual(results.exactPromptVideoIds(rows,'A sufficiently long exact test prompt for identity',['image'],'IMAGE'),[]);
 console.log('Open-eye prerequisite: 10 lifecycle and identity checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
