const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const core=require('../result-core.js');
const source=fs.readFileSync(require('node:path').join(__dirname,'../page-engine.js'),'utf8');
const body=source.slice(source.indexOf('  async function execute(detail)'),source.indexOf("  window.addEventListener('FLOW_STUDIO_MAIN_COMMAND'"));
let clips=[{id:'image1',type:'IMAGE',displayName:'first.png'}],clicks=0,now=0,value={text:[]},mode='success';
const prompt='A complete exact prompt of this task, with full speech and camera instructions.';
const store=new Map();
const editor=()=>value;editor.set=v=>value=v;
const ctx=vm.createContext({FlowStudioResults:core,JSON,Object,Array,Set,Error,String,Date:{now:()=>now+=1000},pending:null,
 ticketKey:k=>'ticket:'+k,sessionStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},
 context:()=>({instance:{},service:{clear(){}}}),validateDuration(){},mediaList:()=>clips,normal:v=>String(v).toLowerCase(),selectMethod:()=>async()=>{},sleep:async()=>{},configure(){},editorSignal:()=>editor,stateSnapshot:()=>({}),attachmentIdentities:()=>new Set(['image1']),retainedReference:()=>null,firstFrameMatches:()=>true,signal:()=>()=> 'VIDEO_FRAMES',modes:[],verifySettings:async()=>({}),
 document:{querySelector:()=>({disabled:false,getAttribute:()=>null,click(){clicks++;if(mode==='success')clips.push({type:'VIDEO',id:'new',prompt});if(mode==='ambiguous')clips.push({type:'VIDEO',id:'new1',prompt},{type:'VIDEO',id:'new2',prompt});}})}
});
ctx.composerContext=()=>null;ctx.composerPreviews=()=>[];ctx.referencePreview=()=>null;ctx.waitGenerateButton=async()=>ctx.document.querySelector();
vm.runInContext(body,ctx);ctx.detail={recovery_key:'one',prompt,image_id:'image1',image_name:'first.png',mode:'VIDEO_FRAMES'};
(async()=>{
 let r=await vm.runInContext('execute(detail)',ctx);assert.deepEqual(Array.from(r.generation_ids),['new']);assert.equal(clicks,1);
 r=await vm.runInContext('execute(detail)',ctx);assert.equal(r.method,'recovered_catalog_identity');assert.equal(clicks,1);
 clips=[clips[0]];mode='ambiguous';ctx.detail.recovery_key='two';
 await assert.rejects(vm.runInContext('execute(detail)',ctx),/SUBMISSION_UNCONFIRMED/);assert.equal(clicks,2);
 await assert.rejects(vm.runInContext('execute(detail)',ctx),/SUBMISSION_UNCONFIRMED/);assert.equal(clicks,2);
 console.log('PASS: real execute recovers missing response from new exact-prompt record; retry does not click; ambiguity remains paused');
})().catch(e=>{console.error(e);process.exitCode=1});
