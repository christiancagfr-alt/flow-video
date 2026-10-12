const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../content.js'),'utf8');
assert.match(source,/function skipFailedUploadsAndContinue\(\)/,'manual skip action must exist');
assert.match(source,/dispatchCount\(name\)>=MAX_AUTO_UPLOAD_ATTEMPTS/,'only exhausted upload failures may be manually skipped');
assert.match(source,/activeGenerationTasks\(\)\.filter\(t=>t\.prompt\|\|t\.dialogue\)/,'generation must exclude skipped-image tasks');
assert.match(source,/图片上传失败，已在网页插件手动跳过/,'skipped task must report a real task-level failure to Studio');
assert.match(source,/上传失败图片（完整文件名）/,'panel must display full failed image names');
assert.match(source,/fs-skip-failed/,'panel must expose the manual skip button');
console.log('PASS: exhausted image uploads can be manually isolated while successful uploads continue');
