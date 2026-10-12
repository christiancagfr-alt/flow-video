const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../page-engine.js'),'utf8');
const start=src.indexOf('  function validateDuration('),end=src.indexOf('  async function execute(',start);
const ctx=vm.createContext({});vm.runInContext(src.slice(start,end),ctx);
assert.doesNotThrow(()=>vm.runInContext('validateDuration({needs_split:true,duration:8})',ctx));
assert.doesNotThrow(()=>vm.runInContext('validateDuration({needs_split:true,force_submit:true,duration:8})',ctx));
for(const duration of [4,6,8])assert.doesNotThrow(()=>vm.runInContext(`validateDuration({duration:${duration}})`,ctx));
assert.throws(()=>vm.runInContext('validateDuration({force_submit:true,duration:12})',ctx),/INVALID_VIDEO_DURATION/);
console.log('PASS duration choice: explicit force accepts 8 seconds; unresolved long dialogue blocks; valid durations preserved');
