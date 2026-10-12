const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../page-engine.js'),'utf8');
const listeners={},observers=[];let clones=0,requestClones=0;
class Observer{constructor(fn){this.fn=fn;this.active=false;observers.push(this)}observe(){this.active=true}disconnect(){this.active=false}}
class Request{constructor(){this.url='https://flow.google.com/project/test'}clone(){requestClones++;return {text:async()=>''}}}
class XHR{
 constructor(){this.handlers=new Map();this.responseText='{}';this.status=200}
 open(){} send(){}
 addEventListener(name,fn,options={}){const rows=this.handlers.get(name)||[];rows.push({fn,once:options.once});this.handlers.set(name,rows);options.signal?.addEventListener('abort',()=>this.removeEventListener(name,fn),{once:true})}
 removeEventListener(name,fn){this.handlers.set(name,(this.handlers.get(name)||[]).filter(x=>x.fn!==fn))}
 emit(name){for(const x of [...(this.handlers.get(name)||[])]){if(x.once)this.removeEventListener(name,x.fn);x.fn.call(this)}}
}
const window={addEventListener:(type,fn)=>listeners[type]=fn,fetch:async()=>({status:200,clone:()=>{clones++;return {text:async()=> '{}'}}})};
const ctx=vm.createContext({window,Request,XMLHttpRequest:XHR,AbortController,PerformanceObserver:Observer,performance:{getEntriesByType:()=>[]},
 FlowStudioResults:require('../result-core.js'),location:{pathname:'/project/test',href:'https://flow.google.com/project/test'},setTimeout,URL,console});
vm.runInContext(source,ctx);
(async()=>{
 assert.equal(observers[0].active,true);
 await window.fetch(new Request());assert.equal(requestClones,0,'no body clone without a submission ticket');assert.equal(clones,1);
 assert.equal(listeners.FLOW_STUDIO_POWER_STATE,undefined,'power-state must not disable network observation');
 await window.fetch(new Request());assert.equal(clones,2);assert.equal(observers[0].active,true);
 for(let i=0;i<1000;i++){const xhr=new XHR();xhr.open('GET','/media');xhr.send();xhr.emit('loadend');assert.equal([...xhr.handlers.values()].flat().length,0)}
 console.log('PASS network lifecycle: observer remains active without a power gate, no request body clone without a ticket, 1000 XHRs release listeners on loadend');
})().catch(e=>{console.error(e);process.exitCode=1});
