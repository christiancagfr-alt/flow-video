const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../content.js'),'utf8');
assert.match(source,/const readyNow=imageTotalNow>0 && imageCountNow>=imageTotalNow && readyTasks\.length>0 && readyMatched===readyTasks\.length;/,
  'READY stability gate must be based on authoritative Flow media + task mapping');
assert.doesNotMatch(source,/const readyNow=.*!isFlowUploading\(\)/,
  'stale Flow processing UI must not block READY');
assert.match(source,/allImagesReady && allTasksMapped[\s\S]*稳定确认/,
  'fully recognized media should enter stability confirmation even if upload UI is stale');
assert.match(source,/\$\{missingCount\?'拖拽上传缺失图片':'重新验证图片'\}/,
  'manual button remains actionable after all images are present but READY has not latched');
assert.match(source,/uploading\|正在上传\|上传中\|上传图片/,
  'busy detector should be upload-specific');
assert.doesNotMatch(source,/uploading\|processing\|正在上传\|上传中\|正在处理\|处理中/,
  'generic processing labels must not be treated as image upload activity');
console.log('PASS: stale processing UI cannot block READY; manual revalidation stays available');
