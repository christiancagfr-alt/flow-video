const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const p=path.join(__dirname,'..'); const content=fs.readFileSync(path.join(p,'content.js'),'utf8'); const page=fs.readFileSync(path.join(p,'page-engine.js'),'utf8');
assert.match(content,/generation_mode: String\(t\.generation_mode \|\| 'FRAME'\)/);
assert.match(content,/mode:\(t\.generation_mode==='MATERIAL'\?'VIDEO_REFERENCES':'VIDEO_FRAMES'\)/);
assert.match(content,/\$\{segment\}\|\$\{task\}\|\$\{image\}\|\$\{mode\}/);
assert.match(page,/mode==='VIDEO_REFERENCES'\?'REFERENCE_MATERIAL':'FIRST_FRAME'/);
console.log('PASS: shared generation_mode maps FRAME->VIDEO_FRAMES and MATERIAL->VIDEO_REFERENCES and participates in wave identity');
