const {test}=require('node:test');
const assert=require('node:assert/strict');
const {create,key,docxDocument}=require('../../_app/frontend/document-preview.js');
const tick=()=>new Promise(r=>setImmediate(r));
const doc=(name='a.docx')=>({id:name,relpath:name,filename:name,ext:name.slice(name.lastIndexOf('.'))});
function fixture(gateway=true){
 const calls=[],states=[],released=[],timers=new Map(),deadlines=[];let ident=0,read=async()=>new Response(JSON.stringify({html:'<p>Safe</p>',warnings:[]})),file=async()=> 'blob:pdf',end;
 const env={fetch:(url,options)=>{calls.push({url,options});return read(url,options);},setTimeout:(f,ms)=>{deadlines.push(ms);timers.set(++ident,f);return ident;},clearTimeout:id=>timers.delete(id)};
 const guard=gateway?{file:(url,options)=>{calls.push({url,options});return file(url,options);},release:url=>released.push(url),onEnd:f=>{end=f;return()=>{end=null;};}}:null;
 const owner=create({env,guard,onState:s=>states.push(s)});
 return {owner,calls,states,released,timers,deadlines,setRead:f=>read=f,setFile:f=>file=f,end:()=>end?.()};
}
test('DOCX previews request conversion only; explicit download is authenticated and lazy',async()=>{
 const f=fixture();
 // Intentional downloads retain the gateway's ten-minute allowance; previews
 // have a shorter deadline and can always be canceled immediately.
 await f.owner.open(doc());assert.equal(f.calls.length,1);assert.match(f.calls[0].url,/preview-docx/);assert.equal(f.states.at(-1).html,'<p>Safe</p>');
 assert.equal(await f.owner.download(doc()),'blob:pdf');assert.match(f.calls[1].url,/api\/file/);assert.deepEqual(f.deadlines,[60000,600000]);f.owner.destroy();assert.deepEqual(f.released,['blob:pdf']);assert.equal(f.timers.size,0);
});
test('switching rejects late conversion even when the transport ignores abort',async()=>{
 const f=fixture();let first;f.setRead(()=>new Promise(r=>first=r));const old=f.owner.open(doc());await tick();
 f.setRead(async()=>new Response(JSON.stringify({html:'<p>New</p>'})));await f.owner.open(doc('b.docx'));assert.equal(f.calls[0].options.signal.aborted,true);
 first(new Response(JSON.stringify({html:'<p>Old</p>'})));await old;assert.equal(f.states.at(-1).key,key(doc('b.docx')));assert.equal(f.states.at(-1).html,'<p>New</p>');f.owner.destroy();
});
test('close cancels stalled preview and download and releases late ignored-abort blobs',async()=>{
 const f=fixture();let deliver;f.setFile(()=>new Promise(r=>deliver=r));const load=f.owner.open(doc('a.pdf'));await tick();f.owner.close();assert.equal(f.calls[0].options.signal.aborted,true);
 deliver('blob:late');await load;assert.deepEqual(f.released,['blob:late']);assert.equal(f.states.at(-1),null);
 await f.owner.open(doc());let resolve;f.setFile(()=>new Promise(r=>resolve=r));const download=f.owner.download(doc());download.catch(()=>{});await tick();f.owner.close();
 resolve('blob:late-download');await assert.rejects(download,{name:'AbortError'});assert.deepEqual(f.released,['blob:late','blob:late-download']);assert.equal(f.timers.size,0);f.owner.destroy();
});
test('gateway PDF/text blobs are reused for downloads and revoked on switch',async()=>{
 const f=fixture();await f.owner.open(doc('a.pdf'));assert.equal(await f.owner.download(doc('a.pdf')),'blob:pdf');assert.equal(f.calls.length,1);
 await f.owner.open(doc('notes.txt'));assert.deepEqual(f.released,['blob:pdf']);assert.equal(f.states.at(-1).kind,'text');f.owner.destroy();assert.equal(f.released.length,2);
});
test('returning to the same document cannot revive or reuse an older pending download',async()=>{
 const f=fixture(),release=[];await f.owner.open(doc());f.setFile(()=>new Promise(r=>release.push(r)));
 const old=f.owner.download(doc());old.catch(()=>{});await tick();await f.owner.open(doc('b.docx'));await f.owner.open(doc());
 const fresh=f.owner.download(doc());await tick();release[0]('blob:obsolete');await assert.rejects(old,{name:'AbortError'});
 assert.equal(f.owner.download(doc()),fresh);release[1]('blob:current');assert.equal(await fresh,'blob:current');assert.deepEqual(f.released,['blob:obsolete']);f.owner.destroy();assert.deepEqual(f.released,['blob:obsolete','blob:current']);
});
test('standalone PDF/text and downloads retain genuine native URLs',async()=>{
 const f=fixture(false);await f.owner.open(doc('resume.pdf'));assert.match(f.states.at(-1).src,/^\/api\/file\?relpath=resume.pdf$/);
 assert.equal(await f.owner.download(doc('resume.pdf')),f.states.at(-1).src);assert.equal(f.calls.length,0);await f.owner.open(doc('notes.tex'));assert.equal(f.states.at(-1).kind,'text');f.owner.destroy();
});
test('deadline stops stalled requests, reports timeout, and permits a fresh preview',async()=>{
 const f=fixture();f.setRead((url,o)=>new Promise((resolve,reject)=>o.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')))));
 const pending=f.owner.open(doc());await tick();[...f.timers.values()][0]();await pending;assert.match(f.states.at(-1).error,/timed out/i);assert.equal(f.timers.size,0);
 f.setRead(async()=>new Response(JSON.stringify({html:'Recovered'})));await f.owner.open(doc());assert.equal(f.states.at(-1).html,'Recovered');f.owner.destroy();
});
test('session invalidation closes owner; destroy removes its listener',async()=>{
 const f=fixture();await f.owner.open(doc('a.pdf'));f.end();assert.equal(f.states.at(-1),null);assert.deepEqual(f.released,['blob:pdf']);f.owner.destroy();
});
test('non-success conversion response produces an accessible error state without retry',async()=>{
 const f=fixture();f.setRead(async()=>new Response('Unavailable',{status:503}));await f.owner.open(doc());assert.match(f.states.at(-1).error,/503/);assert.equal(f.calls.length,1);f.owner.destroy();
});
test('fixed srcdoc CSP precedes content and permits only the trusted stylesheet and inline images',()=>{
 const html=docxDocument('<p>Visible</p>');assert.ok(html.indexOf('Content-Security-Policy')<html.indexOf('<p>Visible</p>'));
 for(const directive of ["default-src 'none'","script-src 'none'","img-src data:","base-uri 'none'","form-action 'none'","connect-src 'none'"])assert.ok(html.includes(directive));
 const css=html.match(/<style>([\s\S]*?)<\/style>/)[1],hash=require('node:crypto').createHash('sha256').update(css).digest('base64');assert.ok(html.includes(`'sha256-${hash}'`));assert.equal(html.includes("'unsafe-inline'"),false);
});
