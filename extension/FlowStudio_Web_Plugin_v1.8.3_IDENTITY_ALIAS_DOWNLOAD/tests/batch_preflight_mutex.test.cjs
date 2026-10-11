const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
(async()=>{
 const src=fs.readFileSync(require('path').join(__dirname,'../content.js'),'utf8');
 const start=src.indexOf('  async function runNativeBatch(job)');
 const end=src.indexOf('    markStartedWave(executionKey);',start);
 let scans=0,release;const gate=new Promise(r=>release=r);const job={command_id:'x',auto_execute:true,dispatch_tasks:true};
 const ctx={state:{ready:true,job},jobExecutionKey:j=>j?.command_id,hasStartedWave:()=>false,confirmAllImagesInFlowBeforeSubmit:async()=>{scans++;await gate;return {ok:false}},render(){},startScanner(){},emit(){}};
 vm.runInNewContext(src.slice(start,end)+'}',ctx);
 const first=ctx.runNativeBatch(job);await ctx.runNativeBatch(job);assert.equal(scans,1);release();await first;assert.equal(ctx.state.commandClaimRunning,false);console.log('PASS concurrent wake cannot duplicate upload preflight or wave start');
})().catch(e=>{console.error(e);process.exitCode=1});
