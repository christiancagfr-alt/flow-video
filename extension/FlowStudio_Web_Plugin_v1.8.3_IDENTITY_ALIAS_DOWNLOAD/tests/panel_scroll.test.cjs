const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'../content.js'),'utf8');
const start=source.indexOf('  function render() {'),end=source.indexOf('\n  async function exportDownloadDiagnostics',start);
const body=source.slice(start,end);let panel={scrollTop:425,addEventListener(){}};
const root={querySelector:()=>panel,set innerHTML(value){this.html=value;panel={scrollTop:0,addEventListener(){}}}};
const noop=()=>{};
const ctx=vm.createContext({root,shell:()=>root,state:{tasks:[],job:null,downloadCounts:{},open:true,bridgePort:17831},activeGenerationTasks:()=>[],expectedMediaTotal:()=>0,recognizedMediaCount:()=>0,missingImageNames:()=>[],exhaustedUploadNames:()=>[],renderUploadFailures:()=>'',esc:String,renderMedia:()=>'',renderRows:()=>'',hydrateThumbnails:noop,exportDownloadDiagnostics:noop,$:()=>({addEventListener:noop}),chrome:{runtime:{}},location:{pathname:"/test"},bind:noop,queueMicrotask:noop,console});
vm.runInContext(body,ctx);
for(let i=0;i<5;i++){vm.runInContext('render()',ctx);assert.equal(panel.scrollTop,425)}
assert(root.html.includes('fs-panel'));console.log('PASS: actual panel render preserves scroll across five DOM replacements');
