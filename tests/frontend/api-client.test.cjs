const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createContext} = require('../../_app/frontend/workspace-context.js');
const {createClient} = require('../../_app/frontend/api-client.js');
const response=(status,data)=>({status,text:async()=>typeof data==='string'?data:JSON.stringify(data)});
function setup(fetchImpl) {const context=createContext(); context.setActor(1); context.select(2); return {context,client:createClient({context,fetchImpl})};}
test('session transport, CSRF, 204 and no mutation replay',async()=>{
  const calls=[]; const {client}=setup(async(path,options)=>{calls.push({path,options});return path.endsWith('csrf')?response(200,{csrfToken:'token'}):response(204,'');});
  await client.bootstrap(); assert.equal(await client.request('/api/auth/logout',{method:'POST'}),null);
  assert.equal(calls[1].options.credentials,'same-origin'); assert.equal(calls[1].options.headers['X-CSRFToken'],'token');
  assert.equal(calls[1].options.cache,'no-store'); assert.equal(calls.length,2);
});
test('workspace read requires selection and uses captured route',async()=>{
  const calls=[]; const {client,context}=setup(async p=>{calls.push(p); return response(200,{});});
  await client.readWorkspace(); assert.deepEqual(calls,['/api/workspaces/2/insights/']);
  context.select(null); assert.throws(()=>client.readWorkspace(),{code:'workspace_required'});
});
test('late success and late authentication failure are stale after navigation',async()=>{
  for(const status of [200,401]) {
    let resolve;const {client,context}=setup(()=>new Promise(r=>resolve=r));
    const pending=client.readWorkspace();context.select(3);resolve(response(status,{code:'authentication_required'}));
    await assert.rejects(pending,{code:'stale_response'});
  }
});
test('unsafe request retains original URL and body with no retry on uncertain response',async()=>{
  let resolve, observed;const {client,context}=setup(async(p,o)=>{
    if(p.endsWith('csrf'))return response(200,{csrfToken:'t'});
    observed={p,o};return new Promise(r=>resolve=r);
  });
  await client.bootstrap();const body={name:'original'};const pending=client.request('/api/workspaces/',{method:'POST',body});
  body.name='changed';context.select(3);resolve(response(201,{id:4}));
  await assert.rejects(pending,{code:'stale_response'});assert.equal(observed.o.body,'{"name":"original"}');assert.equal(observed.p,'/api/workspaces/');
});
test('structured failures, invalid JSON, empty response and network failure',async()=>{
  for(const [status,data,code] of [[403,{code:'csrf_failed',detail:'Refresh'},'csrf_failed'],[400,{code:'validation_error',name:['Required']},'validation_error'],[500,'<html>','unexpected_response'],[200,'','unexpected_response']]) {
    const {client}=setup(async()=>response(status,data));await assert.rejects(client.request('/api/auth/me'),{code});
  }
  let count=0;const {client}=setup(async()=>{count++;throw Error('offline');});
  await assert.rejects(client.request('/api/auth/me'),{code:'network_error'});assert.equal(count,1);
  await assert.rejects(client.request('https://foreign.example/api/'),{code:'invalid_request'});
});
test('XHR retains multipart, CSRF, errors and stale response semantics',async()=>{
  const context=createContext();context.setActor(1);context.select(2);let xhr;
  const client=createClient({context,fetchImpl:async()=>response(200,{csrfToken:'t'}),xhrFactory:()=>xhr={headers:{},open(m,p){this.path=p;},setRequestHeader(k,v){this.headers[k]=v;},send(f){this.form=f;}}});
  await client.bootstrap();const form={file:'fixture'};let pending=client.upload('/api/test-only/',form);
  assert.equal(xhr.form,form);assert.equal(xhr.headers['X-CSRFToken'],'t');assert.equal(xhr.headers['Content-Type'],undefined);
  xhr.status=204;xhr.responseText='';xhr.onload();assert.equal(await pending,null);
  pending=client.upload('/api/test-only/',form);xhr.status=403;xhr.responseText='{"code":"csrf_failed"}';xhr.onload();await assert.rejects(pending,{code:'csrf_failed'});
  pending=client.upload('/api/test-only/',form);context.select(3);xhr.status=200;xhr.responseText='{}';xhr.onload();await assert.rejects(pending,{code:'stale_response'});
  pending=client.upload('/api/test-only/',form);xhr.onerror();await assert.rejects(pending,{code:'network_error'});
});

// Exercise the actual Django-only pure block, not a test-side reimplementation.
const fs = require('node:fs');
const vm = require('node:vm');
const {ApiError} = require('../../_app/frontend/api-client.js');
const html = fs.readFileSync(require('node:path').join(__dirname,'../../_app/frontend/index.html'),'utf8');
const begin = '// BEGIN DJANGO EVIDENCE STATE';
const end = '// END DJANGO EVIDENCE STATE';
assert.equal(html.split(begin).length,2); assert.equal(html.split(end).length,2);
const block = html.slice(html.indexOf(begin),html.indexOf(end));
const sandbox = {JTHApi:{ApiError}, AbortController, Date, Set};
vm.createContext(sandbox);
vm.runInContext(block + '\nthis.evidenceHelpers={evidenceInitialState,evidenceTransition,evidenceSources,evidencePage,evidenceFailure,createEvidenceLane};',sandbox);
const h = sandbox.evidenceHelpers;
const plain = value => JSON.parse(JSON.stringify(value));
const uuid = n => '00000000-0000-4000-8000-' + String(n).padStart(12,'0');
const sourceRow = (id=1) => ({id,portable_id:uuid(id),eligible:true,state:'retained',retained_at:'2026-10-05T12:00:00Z'});
const evidence = () => ({source:{workspace_id:2,retained_message_id:1,retained_message_portable_id:uuid(1),source_eligible:true},
  operations:[{operation_id:uuid(10),extractor_method:'job_alert_rules',extractor_version:'1',extracted_at:'2026-10-05T12:00:00Z',recorded_at:'2026-10-05T12:00:01Z',output_count:0,outputs:[]}],
  has_more:false,next_cursor:null,consistency:'advisory'});

test('retained helpers use captured Workspace, encoded opaque navigation and GET only',async()=>{
  const calls=[]; const {client,context}=setup(async(p,o)=>{calls.push({p,o});return response(200,{});});
  await client.readRetainedMessages();
  await client.readRetainedMessages({after:50});
  await client.readRetainedExtractionEvidence(7);
  const cursor='opaque +/&=?'; await client.readRetainedExtractionEvidence(7,{cursor});
  assert.equal(calls[0].p,'/api/workspaces/2/retained-messages/');
  assert.equal(calls[1].p,'/api/workspaces/2/retained-messages/?after=50');
  assert.equal(calls[2].p,'/api/workspaces/2/retained-messages/7/posting-extractions/');
  assert.equal(new URL(calls[3].p,'http://test').searchParams.get('cursor'),cursor);
  for(const call of calls){assert.equal(call.o.method,'GET');assert.equal(call.o.credentials,'same-origin');assert.equal(call.o.cache,'no-store');assert.equal(call.o.headers['X-CSRFToken'],undefined);assert.equal(new URL(call.p,'http://test').searchParams.has('limit'),false);}
  const captured=context.capture(); context.select(3);
  assert.throws(()=>client.readRetainedMessages({captured}),{code:'stale_response'});
  await client.readRetainedMessages(); assert.equal(calls.at(-1).p,'/api/workspaces/3/retained-messages/');
});
test('unsafe source, Workspace and continuation identities never reach fetch',async()=>{
  let calls=0;const {client,context}=setup(async()=>{calls++;return response(200,{});});
  for(const value of [0,-1,true,'1',1.1,9007199254740992,JSON.parse('9223372036854775807')]){
    assert.throws(()=>client.readRetainedExtractionEvidence(value),{code:'unsafe_identifier'});
    assert.throws(()=>client.readRetainedMessages({after:value}),{code:'unsafe_identifier'});
  }
  context.select(9007199254740992);assert.throws(()=>client.readRetainedMessages(),{code:'unsafe_identifier'});
  assert.equal(calls,0);
  const raw=JSON.parse('{"results":[{"id":9223372036854775807,"portable_id":"'+uuid(1)+'","eligible":true,"state":"retained","retained_at":"2026-10-05T12:00:00Z"}],"next_after":null}');
  assert.equal(Number.isSafeInteger(raw.results[0].id),false);
  assert.throws(()=>h.evidenceSources(raw),{code:'unsafe_identifier'});
  assert.throws(()=>h.evidenceSources({results:[sourceRow()],next_after:9007199254740992}),{code:'unsafe_identifier'});
  const page=evidence();page.source.workspace_id=9007199254740992;
  assert.throws(()=>h.evidencePage(page,2,1),{code:'unsafe_identifier'});
});
test('external cancellation, pre-abort, context cancellation and listener cleanup',async()=>{
  const context=createContext();context.setActor(1);context.select(2);
  let calls=0,seen;
  const client=createClient({context,fetchImpl:async(p,o)=>{calls++;seen=o.signal;return new Promise((resolve,reject)=>o.signal.addEventListener('abort',()=>reject(Object.assign(Error(),{name:'AbortError'})),{once:true}));}});
  let controller=new AbortController();controller.abort();
  await assert.rejects(client.readRetainedMessages({signal:controller.signal}),{code:'aborted'});assert.equal(calls,0);
  controller=new AbortController();let added=0,removed=0;
  const signal={get aborted(){return controller.signal.aborted;},addEventListener(...a){added++;controller.signal.addEventListener(...a);},removeEventListener(...a){removed++;controller.signal.removeEventListener(...a);}};
  const pending=client.readRetainedMessages({signal});controller.abort();await assert.rejects(pending,{code:'aborted'});
  assert.equal(seen.aborted,true);assert.equal(added,1);assert.equal(removed,1);
  controller=new AbortController();const other=client.readRetainedExtractionEvidence(1,{signal:controller.signal});context.select(3);
  await assert.rejects(other,{code:'stale_response'});assert.equal(seen.aborted,true);
  const done=setup(async()=>response(200,{})).client;let cleanup=0;
  await done.readRetainedMessages({signal:{aborted:false,addEventListener(){},removeEventListener(){cleanup++;}}});assert.equal(cleanup,1);
});
test('source generations guard success, error and loading finalization and abort on reset',()=>{
  const {context}=setup(async()=>response(200,{}));const lane=h.createEvidenceLane(context);
  const a=lane.start(1),b=lane.start(2);assert.equal(a.signal.aborted,true);
  for(const phase of ['success','error','finish']){assert.equal(lane.current(a,2),false,phase);assert.equal(lane.current(b,2),true,phase);}
  context.select(3);assert.equal(lane.current(b,2),false);
  const c=lane.start(2);lane.dispose();assert.equal(c.signal.aborted,true);assert.equal(lane.current(c,2),false);
});
test('state reset, ordered append, selection and bounded disclosure preserve evidence',()=>{
  let state=h.evidenceInitialState();
  state=h.evidenceTransition(state,{type:'sources',page:{results:[sourceRow(1)],after:1}});
  state=h.evidenceTransition(state,{type:'sources',page:{results:[sourceRow(2)],after:null},more:true});
  assert.deepEqual(plain(state.sources.map(s=>s.id)),[1,2]);
  state=h.evidenceTransition(state,{type:'select',source:sourceRow()});
  state=h.evidenceTransition(state,{type:'page',page:{operations:[{operation_id:uuid(3)}],cursor:'opaque',eligible:true}});
  state=h.evidenceTransition(state,{type:'start',lane:'evidence',more:true});assert.equal(state.operations.length,1);
  state=h.evidenceTransition(state,{type:'page',page:{operations:[{operation_id:uuid(4)}],cursor:null,eligible:false},more:true});
  assert.deepEqual(plain(state.operations.map(o=>o.operation_id)),[uuid(3),uuid(4)]);
  state=h.evidenceTransition(state,{type:'expand',id:uuid(3)});assert.equal(state.visible,50);
  state=h.evidenceTransition(state,{type:'reveal',total:1000});assert.equal(state.visible,100);
  state=h.evidenceTransition(state,{type:'expand',id:uuid(4)});assert.equal(state.expanded,uuid(4));assert.equal(state.visible,50);
  state=h.evidenceTransition(state,{type:'select',source:sourceRow(2)});assert.equal(state.cursor,null);assert.equal(state.operations.length,0);assert.equal(state.expanded,null);
  assert.deepEqual(plain(h.evidenceTransition(state,{type:'reset'})),plain(h.evidenceInitialState()));
});
test('defensive page validation, context matching and non-displayed int64 IDs',()=>{
  assert.deepEqual(plain(h.evidenceSources({results:[sourceRow()],next_after:null})).results,[sourceRow()]);
  assert.equal(h.evidencePage(evidence(),2,1).operations[0].output_count,0);
  const bad=[{...evidence(),has_more:true}, {...evidence(),next_cursor:'poison'}, {...evidence(),operations:null}, {...evidence(),source:{...evidence().source,retained_message_id:2}}];
  for(const page of bad)assert.throws(()=>h.evidencePage(page,2,1),{code:'unexpected_response'});
  const page=evidence();page.operations[0].extraction_id=JSON.parse('9223372036854775807');
  const output={portable_id:uuid(9),output_id:JSON.parse('9223372036854775807'),source:'linkedin',title:'<script>literal</script>',company:'',location:null,salary:'',employment_type:null};
  page.operations[0].outputs=[output];page.operations[0].output_count=1;
  const result=h.evidencePage(page,2,1);assert.equal('extraction_id' in result.operations[0],false);assert.equal('output_id' in result.operations[0].outputs[0],false);
  assert.equal(result.operations[0].outputs[0].title,output.title);
  assert.throws(()=>h.evidenceSources({results:[sourceRow()],next_after:2}),{code:'unexpected_response'});
});
test('safe errors never disclose server details; structural errors clear, retries preserve navigation',()=>{
  for(const [status,code] of [[400,'validation_error'],[401,'authentication_required'],[404,'not_found'],[409,'retained_source_invalid'],[409,'posting_extraction_evidence_invalid'],[500,'request_failed'],[0,'network_error'],[0,'unexpected_response']]){
    const error=h.evidenceFailure(new ApiError(code,'SQL private-secret',status));assert.equal(JSON.stringify(error).includes('private-secret'),false);
  }
  assert.equal(h.evidenceFailure(new ApiError('aborted','private')),null);
  assert.equal(h.evidenceFailure(new ApiError('stale_response','private')),null);
  let state={...h.evidenceInitialState(),operations:[{}],cursor:'opaque',source:sourceRow()};
  state=h.evidenceTransition(state,{type:'error',lane:'evidence',error:h.evidenceFailure(new ApiError('network_error','')),navigation:'opaque'});
  assert.equal(state.operations.length,1);assert.equal(state.evidenceError.navigation,'opaque');
  state=h.evidenceTransition(state,{type:'error',lane:'evidence',error:h.evidenceFailure(new ApiError('validation_error','',400)),navigation:'opaque'});
  assert.equal(state.operations.length,0);assert.equal(state.cursor,null);assert.equal(state.evidenceError.retry,'restart');
});


test('body serialization fails before registering an external abort listener',async()=>{
  let fetched=0,added=0,removed=0;
  const {client}=setup(async()=>{fetched++;return response(200,{csrfToken:'test-token'});});
  await client.bootstrap();
  const body={};body.self=body;
  const signal={aborted:false,addEventListener(){added++;},removeEventListener(){removed++;}};
  await assert.rejects(client.request('/api/auth/logout',{method:'POST',body,signal}),TypeError);
  assert.equal(fetched,1,'failed body must not reach fetch');
  assert.equal(added,0);assert.equal(removed,0);
});


const applicationHelpers = (()=>{
  const html=require('node:fs').readFileSync(require('node:path').join(__dirname,'../../_app/frontend/index.html'),'utf8');
  const code=html.split('// BEGIN DJANGO APPLICATION STATE')[1].split('// END DJANGO APPLICATION STATE')[0];
  const vm=require('node:vm');const scope={JTHApi:{ApiError},Number,Date,Set};
  vm.createContext(scope);vm.runInContext(code,scope);return scope;
})();
const applicationFixture = (id=7) => ({id,workspace:2,portable_id:uuid(id),company:'Repeat',role_label:'Role',section:'applications',
  effective_status:'interviewing',effective_date_applied:null,is_trashed:false,effective_trashed:false,trashed_at:null,override:null,
  first_activity:null,last_activity:null,first_activity_date:null,last_activity_date:null,activity_provenance:{},derivation_state:'pending',category_id:null});
test('Application GET helpers use captured scope, safe IDs and cancellation only',async()=>{
  const calls=[];const {client,context}=setup(async(p,o)=>{calls.push({p,o});return response(200,[]);});
  await client.readApplications();await client.readApplication(7);
  assert.deepEqual(calls.map(c=>c.p),['/api/workspaces/2/applications/','/api/workspaces/2/applications/7/']);
  for(const c of calls){assert.equal(c.o.method,'GET');assert.equal(c.o.credentials,'same-origin');assert.equal(c.o.cache,'no-store');}
  for(const id of [0,true,'7',1.2,9007199254740992]) assert.throws(()=>client.readApplication(id),{code:'unsafe_identifier'});
  assert.equal(calls.length,2);
  context.select(9007199254740992);assert.throws(()=>client.readApplications(),{code:'unsafe_identifier'});
  context.select(2);const abort=new AbortController();abort.abort();await assert.rejects(client.readApplication(7,{signal:abort.signal}),{code:'aborted'});
  assert.equal(calls.length,2);
});
test('Application projections validate identities and discard unrelated serializer fields',()=>{
  const h=applicationHelpers,row=applicationFixture();
  row.source_relpath='private';row.date_candidate={secret:'private'};row.derivation_fingerprint='private';
  assert.equal(JSON.stringify(h.applicationRow(row,2,7)).includes('private'),false);
  assert.equal(h.applicationList([row,applicationFixture(8)],2).length,2);
  for(const change of [{workspace:3},{id:8},{company:null},{effective_status:null},{effective_trashed:true},{effective_date_applied:'2026-02-30'},
    {portable_id:'bad'},{activity_provenance:[]},{override:{}},{category_id:9007199254740992}]){
    assert.throws(()=>h.applicationRow({...row,...change},2,7));
  }
  assert.throws(()=>h.applicationList([row,row],2),{code:'unexpected_response'});
  assert.throws(()=>h.applicationList({results:[]},2),{code:'unexpected_response'});
  assert.throws(()=>h.applicationList([{...row,id:JSON.parse('9223372036854775807')}],2),{code:'unsafe_identifier'});
  assert.equal(h.applicationFailure(new ApiError('network_error','SQL secret')).message.includes('secret'),false);
});
