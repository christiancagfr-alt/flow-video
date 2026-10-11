const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const src=fs.readFileSync(require('path').join(__dirname,'../content.js'),'utf8');
const body=src.slice(src.indexOf('  async function submitWithRecovery'),src.indexOf('  async function setPausedFromPlugin'));
const uncertain=src.slice(src.indexOf('  function isUncertainSubmissionError'),src.indexOf('  function claimSegment'));
(async()=>{
 for(const error of ['REFERENCE_STATE_NOT_DETECTED','FLOW_GENERATE_BUTTON_NOT_READY','FIRST_FRAME_NOT_CONFIRMED','MAIN_ENGINE_TIMEOUT','SUBMIT_NOT_CONFIRMED','SUBMISSION_UNCONFIRMED']){
  let calls=0;const waits=[];
  const ctx=vm.createContext({submitViaMainWorld:async()=>{calls++;throw Error(error)},state:{},render(){},emit(){},pageHealthSnapshot:()=>({}),sleep:async ms=>waits.push(ms)});
  vm.runInContext(uncertain+body,ctx);
  await assert.rejects(ctx.submitWithRecovery({},{}),new RegExp(error));
  const count=/TIMEOUT|SUBMIT_NOT|SUBMISSION_UN/.test(error)?1:37;
  assert.equal(calls,count,error);assert.equal(waits.length,count-1,error);
 }
 console.log('PASS pre-click transient failures wait through slow readiness (37 attempts maximum); ambiguous/post-click failures never repeat submission');
})().catch(e=>{console.error(e);process.exitCode=1});
