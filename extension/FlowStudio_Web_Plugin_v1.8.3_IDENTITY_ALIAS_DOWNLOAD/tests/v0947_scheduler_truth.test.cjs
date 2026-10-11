const fs=require('fs');
const src=fs.readFileSync(require('path').join(__dirname,'..','background.js'),'utf8');
if(!src.includes('const boundJob=await jobForTab(tab);')) throw new Error('heartbeat is not bound to current channel job');
if(!src.includes('idle_channel:idle')) throw new Error('heartbeat still hard-codes idle_channel');
if(!src.includes("command_id:actionable?String(boundJob.command_id||''):''")) throw new Error('heartbeat does not report active command');
if(src.includes("command_id:'',collection_url") && src.includes('idle_channel:true')) throw new Error('legacy unconditional idle heartbeat remains');
console.log('PASS: v0.9.47 scheduler-truth heartbeat present');
