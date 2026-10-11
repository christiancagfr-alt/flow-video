const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const p=path.join(__dirname,'..'),src=fs.readFileSync(path.join(p,'page-engine.js'),'utf8');
const ctx=vm.createContext({});
function extract(name){const start=src.indexOf('  function '+name+'('),end=src.indexOf('\n  function ',start+3);return src.slice(start,end);}
vm.runInContext(extract('hasTarget')+'\n'+extract('firstFrameMatches'),ctx);
ctx.service={firstFrame:()=>({id:'correct'}),lastFrame:()=>({id:'other'})};ctx.ids=new Set(['correct']);
assert.equal(vm.runInContext('firstFrameMatches(service,ids)',ctx),true);
ctx.service={firstFrame:()=>null,lastFrame:()=>({id:'correct'})};assert.equal(vm.runInContext('firstFrameMatches(service,ids)',ctx),false);
const content=fs.readFileSync(path.join(p,'content.js'),'utf8');
assert.match(content,/duration:t.duration, needs_split:t.needs_split/);assert.match(content,/t\.generation_mode==='MATERIAL'\?'VIDEO_REFERENCES':'VIDEO_FRAMES'/);
assert.match(src,/FIRST_FRAME_NOT_CONFIRMED/);assert.match(src,/INVALID_VIDEO_DURATION/);
const results=require('../result-core.js');
for(const item of [{id:'task',type:'VIDEO',rb:{workflowId:'task',id:'file',status:{state:'FAILED'}}},{id:'task',type:'VIDEO',mediaStatus:{mediaGenerationStatus:'MEDIA_GENERATION_STATUS_FAILED'}},{id:'task',type:'VIDEO',result:{done:true,error:{message:'blocked by server'}}}]){
 assert.equal(results.catalogLinks(item).rows[0].id,'task');assert.equal(results.catalogLinks(item).rows[0].status,'failed');
}
assert.equal(results.catalogLinks({id:'new',type:'VIDEO',history:[{status:'FAILED'}],prompt:'FAILED'}).rows.length,0);
console.log('PASS: first-frame identity required; per-task timing and FRAME/MATERIAL mode forwarded; nested failures recognized; history excluded');

function asyncExtract(name){const start=src.indexOf('  async function '+name+'('),end=src.indexOf('\n  function ',start+3);return src.slice(start,end);}
const timing=vm.createContext({Date,Promise,console});
vm.runInContext(`const source=fn=>Function.prototype.toString.call(fn); const sleep=async()=>{};
const modes=['VIDEO_REFERENCES','VIDEO_FRAMES'];const models=['veo_3_1_lite_low_priority'];
function sig(v){const fn=()=>v;fn.set=x=>v=x;fn.update=f=>v=f(v);return fn;}
class Service {constructor(){this.outputs=sig(1);this.duration=sig(8);this.mode=sig('VIDEO_REFERENCES');this.model=sig('veo_3_1_lite_low_priority');this.aspectRatio=sig('PORTRAIT');}setAspectRatio(v){this.aspectRatio.set(v);}}
`+extract('signal')+'\n'+extract('constructorSignal')+'\n'+extract('aspectValue')+'\n'+asyncExtract('verifySettings')+'\n'+asyncExtract('configure'),timing);
(async()=>{for(const duration of [4,6,8]){timing.duration=duration;const actual=await vm.runInContext(`(async()=>{const s=new Service();const d={duration,mode:'VIDEO_FRAMES'};await configure(s,d);return (await verifySettings(s,d)).duration;})()`,timing);assert.equal(actual,duration);}console.log('PASS: real configure and verifySettings apply all three durations');})().catch(e=>{console.error(e);process.exitCode=1});
