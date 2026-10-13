const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
(async()=>{
 let attaches=0,detaches=0,listener;const updates=[],commands=[];
 const ctx={chrome:{tabs:{get:async()=>({url:'https://flow.google.com/project/test',autoDiscardable:true}),update:async(id,v)=>updates.push(v),onRemoved:{addListener(){}},onUpdated:{addListener(){}}},debugger:{attach:async()=>{attaches++},detach:async t=>{detaches++;listener(t,'canceled_by_user')},sendCommand:async(t,m,v)=>commands.push([m,v]),onDetach:{addListener(fn){listener=fn}}}}};
 vm.runInNewContext(fs.readFileSync(require('path').join(__dirname,'../background-runtime.js'),'utf8'),ctx);
 const api=ctx.FlowStudioBackground;
 await api.hold(1,'command');let running=0,max=0;
 await Promise.all([api.run(1,async()=>{max=Math.max(max,++running);await Promise.resolve();running--}),api.hold(1,'command'),api.run(1,async()=>{max=Math.max(max,++running);running--})]);
 assert.equal(attaches,1);assert.equal(detaches,0);assert.equal(max,1);
 assert.equal(api.diagnostics()[0].focus_emulated,true);
 await api.release(1);assert.equal(detaches,1);assert.equal(updates.at(-1).autoDiscardable,true);
 await api.hold(1,'next');assert.equal(attaches,2,'intentional release must allow next batch');
 listener({tabId:1},'canceled_by_user');await api.hold(1,'next');assert.equal(attaches,3,'user detach must allow the next action to reacquire');
 assert(updates.every(v=>!('active' in v)));console.log('PASS persistent session, serialized operations, restore, next batch and reacquire');
})().catch(e=>{console.error(e);process.exitCode=1});
