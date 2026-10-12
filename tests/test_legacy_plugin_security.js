const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('extension/FlowStudio_Web_Plugin_v0.9.66_FLOW_SUBMIT_HITTEST_FIX/background.js','utf8');
const context={URL,chrome:{runtime:{id:'test-extension'}}};vm.createContext(context);vm.runInContext(source.slice(0,source.indexOf('importScripts')),context);
assert.equal(context.trustedFlowSender({id:'test-extension',url:'https://flow.google.com/project/1'}),true);
for(const sender of [{id:'other',url:'https://flow.google.com/'},{id:'test-extension',url:'https://evil.test/'},{id:'test-extension',url:'https://flow.google.com.evil.test/'},{}])assert.equal(context.trustedFlowSender(sender),false);
console.log('Legacy plugin sender boundary: 5 checks passed');
