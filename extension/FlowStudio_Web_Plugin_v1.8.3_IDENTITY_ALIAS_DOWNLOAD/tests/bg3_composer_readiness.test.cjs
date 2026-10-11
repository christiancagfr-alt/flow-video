const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync(require('path').join(__dirname,'../page-engine.js'),'utf8');
const helpers=source.slice(source.indexOf('  const composerNodeOrder='),source.indexOf('  async function execute(detail)'));
function element(props={}){return {isConnected:true,nodeType:1,parentElement:null,hidden:false,attrs:{},style:{display:'block',visibility:'visible'},getAttribute(k){return this.attrs[k]??null},getBoundingClientRect(){return {x:0,y:0,width:80,height:40}},querySelectorAll(){return []},...props}}
let now=0,checks=0;const body=element(),root=element({parentElement:body});
const editor=element({parentElement:root,textContent:'exact prompt'}),button=element({parentElement:root,disabled:false});
let previews=[];root.querySelectorAll=s=>s==='img'?previews:[button];
const ctx=vm.createContext({document:{body,hidden:true,visibilityState:'hidden',hasFocus:()=>false,querySelectorAll:()=>[editor]},getComputedStyle:n=>n.style,mediaURL:i=>i.url,Date:{now:()=>now},sleep:async ms=>{now+=ms;checks++},WeakMap,Map,Set});vm.runInContext(helpers,ctx);
const pic=(src,x=0)=>element({src,currentSrc:src,complete:true,naturalWidth:100,parentElement:root,getBoundingClientRect:()=>({x,y:0,width:80,height:80})});
(async()=>{
 const ids=new Set(['id1','alias2']),item={id:'id1',url:'https://asset/current'};
 const stale=pic(item.url),hidden=pic(item.url),wrong=pic('https://asset/old'),near=pic(item.url,10),far=pic(item.url,100);
 hidden.style.display='none';previews=[hidden,wrong,stale,far,near];
 const before=new Map([[stale,stale.src]]);
 assert.equal(ctx.referencePreview(item,ids,before,'exact prompt').node,near,'two identity aliases, several previews: nearest current new image wins');
 near.attrs['aria-hidden']='true';assert.equal(ctx.referencePreview(item,ids,before).node,far);
 far.getBoundingClientRect=()=>({x:0,y:0,width:0,height:0});assert.equal(ctx.referencePreview(item,ids,before),null);
 hidden.style.display='block';root.style.visibility='hidden';assert.equal(ctx.referencePreview(item,ids,before),null);root.style.visibility='visible';
 assert.equal(await ctx.waitGenerateButton('exact prompt'),button,'hidden/unfocused tab still submits');
 button.disabled=true;ctx.sleep=async ms=>{now+=ms;checks++;if(checks===5)button.disabled=false};
 assert.equal(await ctx.waitGenerateButton('exact prompt'),button);assert.equal(checks,5);
 button.disabled=true;ctx.sleep=async ms=>{now+=ms};now=0;
 await assert.rejects(ctx.waitGenerateButton('exact prompt'),/FLOW_GENERATE_BUTTON_NOT_READY/);assert.equal(now,6500);
 console.log('PASS current Composer, multiple aliases, old/hidden/zero-size image exclusion, nearest preview, background execution, dynamic button wait');
})().catch(e=>{console.error(e);process.exitCode=1});
