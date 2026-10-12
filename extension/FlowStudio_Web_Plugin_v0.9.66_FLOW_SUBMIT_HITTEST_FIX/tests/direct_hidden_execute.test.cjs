const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../page-engine.js'),'utf8');
const execute=source.slice(source.indexOf('  async function execute(detail)'),source.indexOf("  window.addEventListener('FLOW_STUDIO_MAIN_COMMAND'"));
(async()=>{
 for(const mode of ['VIDEO_FRAMES','VIDEO_REFERENCES']){
  let blocks={main:[]},clicks=0,sleeps=0;const order=[],storage=new Map();
  const image={id:'image-12345678',displayName:'asset.png',type:'IMAGE'};
  const editor=()=>blocks;editor.set=x=>{blocks=x;order.push('prompt')};
  const ctx=vm.createContext({normal:x=>x,context:()=>({instance:{},service:{clear:()=>order.push('clear')}}),validateDuration:()=>{},mediaList:()=>[image],selectMethod:()=>async()=>order.push('select'),configure:()=>order.push('configure'),editorSignal:()=>editor,stateSnapshot:()=>new Map(),attachmentIdentities:()=>new Set([image.id]),firstFrameMatches:()=>true,signal:()=>()=>mode,modes:[mode],verifySettings:async()=>({duration:mode==='VIDEO_REFERENCES'?8:4}),waitExistingFlowImageAssetReady:async()=>image,selectMaterialAssetLikeFrame:async()=>{order.push('select');return {selectedKey:'native',attempt:1}},captureMaterialBinding:()=>({ids:new Set([image.id]),shapes:[]}),sleep:async()=>{sleeps++;throw Error('unnecessary wait')},Date,Set,sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},ticketKey:x=>x,FlowStudioResults:{exactPromptVideoIds:()=>[]},document:{hidden:true,visibilityState:'hidden',hasFocus:()=>false},pending:null});
  const button={isConnected:true,disabled:false,matches:()=>true,getAttribute:()=>null,click:()=>{clicks++;order.push('submit');ctx.pending.accepted=['result-identity']}};
  ctx.document.querySelector=()=>button;
ctx.composerContext=()=>null;ctx.composerPreviews=()=>[];ctx.referencePreview=()=>null;ctx.waitGenerateButton=async()=>ctx.document.querySelector();
  vm.runInContext(execute,ctx);
  const result=await vm.runInContext(`execute({mode:'${mode}',image_id:'image-12345678',image_name:'asset.png',prompt:'exact words',recovery_key:'task:1'})`,ctx);
  assert.equal(clicks,1);assert.equal(sleeps,0);assert.deepEqual(order,['clear','configure','select','prompt','submit']);assert.equal(result.generation_ids[0],'result-identity');
  await assert.rejects(vm.runInContext(`execute({mode:'${mode}',image_id:'image-12345678',image_name:'asset.png',prompt:'exact words',recovery_key:'task:1'})`,ctx),/SUBMISSION_UNCONFIRMED/);
  assert.equal(clicks,1,'replayed task cannot click twice');
 }
 console.log('PASS actual execute in hidden/unfocused mock: FRAME and MATERIAL submit once without pre-submit sleeps; recovery record blocks replay');
})().catch(e=>{console.error(e);process.exitCode=1});
