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

const reviewHelpers=(()=>{
  const scope={JTHApi:{ApiError},Number,Date,Set,AbortController};vm.createContext(scope);
  const app=html.split('// BEGIN DJANGO APPLICATION STATE')[1].split('// END DJANGO APPLICATION STATE')[0];
  const review=html.split('// BEGIN DJANGO REVIEW STATE')[1].split('// END DJANGO REVIEW STATE')[0];
  vm.runInContext(app+'\n'+review,scope);return scope;
})();
const reviewFixture=(id=7)=>({id,workspace_id:2,portable_id:uuid(id),initial_classification:'ambiguous',snapshot_version:1,
  candidate_count:9,relationship_count:1,attachment_status:'attached',subject:'<img src=x>',created_at:'2026-10-06T12:00:00Z',
  observed_at:'2026-10-05T12:00:00Z',originating_observation_id:4,disposition:{state:'active',dismissed_at:null,revision:999},
  retained_message:{id:3,portable_id:uuid(3),state:'retained',eligible:true,retained_at:'2026-10-05T12:00:01Z',representation_version:1,mailbox_id:99},
  candidates:[{id:5,application_id:8,application_portable_id:uuid(8),created_at:'2026-10-06T12:00:00Z',availability:'live',attachable:true,
    current_application:{company:'Current',role_label:'Role',section:'applications',trashed_at:null,lifecycle_revision:99}}],
  relationships:[{id:6,portable_id:uuid(6),application_id:8,origin:'manual',created_at:'2026-10-06T12:00:00Z',availability:'live'}],
  creation_results:{results:[{secret:'CREATION PRIVATE PAYLOAD'}],next_after:99},body:'private'});
test('review reads use exact scoped GETs, explicit cursor, captured context and abort',async()=>{
  const calls=[];const {client,context}=setup(async(p,o)=>{calls.push({p,o});return response(200,{});});
  await client.readApplicationReviews();await client.readApplicationReviews({after:50});await client.readApplicationReview(7);
  assert.deepEqual(calls.map(c=>c.p),['/api/workspaces/2/application-reviews/','/api/workspaces/2/application-reviews/?after=50','/api/workspaces/2/application-reviews/7/']);
  for(const c of calls){assert.equal(c.o.method,'GET');assert.equal(c.o.credentials,'same-origin');assert.equal(c.o.cache,'no-store');assert.equal(c.o.body,undefined);}
  for(const id of [0,-1,true,'7',1.1,9007199254740992,JSON.parse('9223372036854775807')]){
    assert.throws(()=>client.readApplicationReview(id),{code:'unsafe_identifier'});assert.throws(()=>client.readApplicationReviews({after:id}),{code:'unsafe_identifier'});
  }
  const abort=new AbortController();abort.abort();await assert.rejects(client.readApplicationReviews({signal:abort.signal}),{code:'aborted'});
  let release,signal;const pendingClient=createClient({context,fetchImpl:(p,o)=>{signal=o.signal;return new Promise(r=>release=r);}});
  const pending=pendingClient.readApplicationReview(7,{signal:abort.signal});await assert.rejects(pending,{code:'aborted'});
  const active=new AbortController();const running=pendingClient.readApplicationReview(7,{signal:active.signal});active.abort();assert(signal.aborted);release(response(200,{}));await running;
  const captured=context.capture();context.select(3);assert.throws(()=>client.readApplicationReviews({captured}),{code:'stale_response'});
  context.select(9007199254740992);assert.throws(()=>client.readApplicationReviews(),{code:'unsafe_identifier'});assert.equal(calls.length,3);
});
test('actual review projection distinguishes initial membership/current state and drops excluded payload',()=>{
  const h=reviewHelpers,row=reviewFixture(),detail=h.reviewRow(row,2,7),encoded=JSON.stringify(detail);
  assert.equal(detail.candidate_count,9);assert.equal(detail.candidates.length,1);assert.equal(detail.candidates[0].current_application.company,'Current');
  assert.equal(detail.subject,'<img src=x>');for(const key of ['attachable','creation_results','mailbox_id','body','secret'])assert(!encoded.includes('"'+key+'"'));
  assert.equal(h.reviewRow(row,2).candidates,undefined);
  const removed=structuredClone(row);Object.assign(removed.candidates[0],{application_id:null,current_application:null,availability:'removed'});assert.equal(h.reviewRow(removed,2,7).candidates[0].application_id,null);
  const trashed=structuredClone(row);trashed.candidates[0].availability='trashed';trashed.candidates[0].current_application.trashed_at='2026-10-06T12:00:00Z';h.reviewRow(trashed,2,7);
  const conflict=structuredClone(row);conflict.retained_message.state='conflict';conflict.retained_message.eligible=false;assert.equal(h.reviewRow(conflict,2,7).disposition.state,'active');
});
test('review projections reject scope/identity/version/lifecycle mismatches and unsafe nested IDs',()=>{
  const h=reviewHelpers;
  for(const mutate of [r=>r.workspace_id=3,r=>r.id=8,r=>r.snapshot_version=2,r=>r.initial_classification='accepted',
    r=>r.disposition.state='restored',r=>r.disposition.dismissed_at='2026-10-06T12:00:00Z',r=>r.retained_message.representation_version=2,
    r=>r.retained_message.eligible=false,r=>r.candidates[0].application_id=9007199254740992,r=>r.candidates[0].id=0,
    r=>r.relationships[0].application_id=9007199254740992,r=>r.relationships[0].origin='accepted',
    r=>r.relationships.push(r.relationships[0]),r=>r.candidates.push(r.candidates[0]),r=>r.candidates[0].current_application=null]){
    const row=reviewFixture();mutate(row);assert.throws(()=>h.reviewRow(row,2,7));
  }
});
test('review pages require ascending unique identities and progressive exact continuation',()=>{
  const h=reviewHelpers,rows=Array.from({length:50},(_,n)=>reviewFixture(n+1));
  const page=h.reviewPage({results:rows,next_after:50},2);assert.equal(page.rows.length,50);assert.equal(page.after,50);
  assert.equal(h.reviewPage({results:[reviewFixture(51)],next_after:null},2,50,page.rows).after,null);
  for(const bad of [{results:rows,next_after:49},{results:rows,next_after:9007199254740992},{results:[rows[1],rows[0]],next_after:null},{results:[rows[0],rows[0]],next_after:null},{results:rows.slice(0,1),next_after:1}])assert.throws(()=>h.reviewPage(bad,2));
  assert.throws(()=>h.reviewPage({results:[reviewFixture(51)],next_after:null},2,50,[reviewFixture(51)]));
  assert.throws(()=>h.reviewPage({results:[reviewFixture(50)],next_after:null},2,50));
});
test('review errors never expose raw server messages; restart preserves explicit choice',()=>{
  const h=reviewHelpers;
  for(const e of [{status:404,message:'private'},{status:500,message:'private'},{status:400,message:'private'},{code:'unexpected_review',message:'private'}])assert(!h.reviewFailure(e,true).message.includes('private'));
  assert.equal(h.reviewFailure({status:400},true).restart,true);assert.equal(h.reviewFailure({status:500},true).retry,true);
  assert.equal(h.reviewFailure({code:'stale_response'}),null);assert.equal(h.reviewFailure({status:401,code:'authentication_required'}).auth,true);
});

const categoryHelpers=(()=>{
  const scope={JTHApi:{ApiError},Number,Date,Set};vm.createContext(scope);
  const app=html.split('// BEGIN DJANGO APPLICATION STATE')[1].split('// END DJANGO APPLICATION STATE')[0];
  const categories=html.split('// BEGIN DJANGO CATEGORY STATE')[1].split('// END DJANGO CATEGORY STATE')[0];
  vm.runInContext(app+'\n'+categories,scope);return scope;
})();
const categoryFixture=(id=5)=>({id,workspace:2,portable_id:uuid(id),name:'  Same <img src=x>  ',section:'misc',archived:false,is_trashed:false,effective_trashed:false,trashed_at:null});
const memberFixture=(id=7)=>({...applicationFixture(id),category_id:5,override:{archived:true,notes:'private'}});
test('Category helpers issue exactly archived-inclusive scoped GETs and reject unsafe IDs before fetch',async()=>{
  const calls=[];const {client,context}=setup(async(p,o)=>{calls.push({p,o});return response(200,[]);});
  await client.readCategories();await client.readCategory(5);await client.readCategoryApplications(5);
  assert.deepEqual(calls.map(c=>c.p),['/api/workspaces/2/categories/?show_archived=true','/api/workspaces/2/categories/5/','/api/workspaces/2/categories/5/applications/?show_archived=true']);
  for(const c of calls){assert.equal(c.o.method,'GET');assert.equal(c.o.credentials,'same-origin');assert.equal(c.o.cache,'no-store');assert.equal(c.o.body,undefined);}
  for(const id of [0,true,'5',1.2,9007199254740992])for(const method of ['readCategory','readCategoryApplications'])assert.throws(()=>client[method](id),{code:'unsafe_identifier'});
  assert.equal(calls.length,3);context.select(9007199254740992);assert.throws(()=>client.readCategories(),{code:'unsafe_identifier'});
});
test('Category helpers preserve captured context and active/preaborted cancellation',async()=>{
  const {client,context}=setup();const old=context.capture();context.select(3);
  assert.throws(()=>client.readCategory(5,{captured:old}),{code:'stale_response'});
  assert.throws(()=>client.readCategories({captured:old}),{code:'stale_response'});
  assert.throws(()=>client.readCategoryApplications(5,{captured:old}),{code:'stale_response'});
  for(const method of ['readCategories','readCategory','readCategoryApplications']){
    let signal,release;const pending=setup(async(p,o)=>{signal=o.signal;return new Promise(r=>release=r);});
    const abort=new AbortController(),options={signal:abort.signal};
    const task=method==='readCategories'?pending.client[method](options):pending.client[method](5,options);
    abort.abort();assert(signal.aborted);release(response(200,[]));await task;
    await assert.rejects(method==='readCategories'?pending.client[method](options):pending.client[method](5,options),{code:'aborted'});
  }
});
test('Category projections preserve order, spelling and duplicate names but exclude write/provenance data',()=>{
  const h=categoryHelpers,row={...categoryFixture(),revision:9007199254740992,lifecycle_revision:3,provenance:{private:'secret'},extra:{private:'secret'}};
  const projected=h.categoryRow(row,2,row);assert.deepEqual(Object.keys(projected).sort(),['id','workspace','portable_id','name','section','archived','is_trashed','effective_trashed','trashed_at'].sort());
  assert.equal(projected.name,row.name);assert.equal(JSON.stringify(projected).includes('secret'),false);
  const rows=h.categoryList([categoryFixture(6),categoryFixture(5)],2);assert.equal(rows[0].id,6);assert.equal(rows.length,2);
  assert.equal(h.categoryRow({...row,portable_id:row.portable_id.toUpperCase()},2,row).id,5);
  assert.throws(()=>h.categoryRow({...row,portable_id:uuid(20)},2,row));
  for(const change of [{workspace:3},{id:9007199254740992},{portable_id:'bad'},{section:'applications'},{name:null},{archived:null},{effective_trashed:true},{trashed_at:'bad'}])assert.throws(()=>h.categoryRow({...row,...change},2,row));
  const trashed={...row,is_trashed:true,effective_trashed:true,trashed_at:'2026-10-06T12:00:00Z'};assert(h.categoryRow(trashed,2).is_trashed);assert.throws(()=>h.categoryList([trashed],2));
  assert.throws(()=>h.categoryList([row,row],2));assert.throws(()=>h.categoryList([row,{...row,id:8}],2));assert.throws(()=>h.categoryList({results:[row]},2));
});
test('Category member projection validates parent, scope, portable identity and complete live membership',()=>{
  const h=categoryHelpers,row=memberFixture();const result=h.categoryMembers([row,memberFixture(8)],2,5);
  assert.equal(result[0].override.archived,true);assert.equal(result[0].section,'applications');
  assert.equal(JSON.stringify(result).includes('private'),false);assert.equal(result[0].effective_status,undefined);assert.equal(result[0].category_revision,undefined);
  assert.equal(Object.keys(result[0].override).join(','),'archived');assert.equal(h.categoryMembers([{...row,override:null}],2,5)[0].override,null);
  for(const change of [{id:9007199254740992},{workspace:3},{category_id:6},{category_id:null},{portable_id:'bad'},{section:'unknown'},{company:null},{role_label:null},{override:{}},{is_trashed:true,effective_trashed:true,trashed_at:'2026-10-06T12:00:00Z'}])assert.throws(()=>h.categoryMembers([{...row,...change}],2,5));
  assert.throws(()=>h.categoryMembers([row,row],2,5));assert.throws(()=>h.categoryMembers([row,{...row,id:8}],2,5));
  const many=Array.from({length:61},(_,n)=>memberFixture(n+10));assert.equal(h.categoryMembers(many,2,5).length,61);
});
test('Category errors distinguish unavailable membership from empty and hide raw backend details',()=>{
  const h=categoryHelpers;
  assert.equal(h.categoryFailure(new ApiError('resource_trashed','private SQL',409),'members').retry,true);
  assert.match(h.categoryFailure(new ApiError('resource_trashed','private SQL',409),'members').message,/now trashed/);
  for(const phase of ['list','detail','members'])assert.equal(h.categoryFailure(new ApiError('network_error','private SQL'),phase).message.includes('private'),false);
  assert.equal(h.categoryFailure(new ApiError('authentication_required','private',401),'detail').auth,true);
  assert.equal(h.categoryFailure(new ApiError('unexpected_category','private'),'members').retry,true);
  assert.equal(h.categoryFailure(new ApiError('unsafe_identifier','private'),'members').retry,true);
  assert.equal(h.categoryFailure(new ApiError('aborted','private'),'members'),null);
  assert.equal(h.categoryFailure(new ApiError('stale_response','private'),'detail'),null);
});

const assignmentHelpers=(()=>{
  const scope={JTHApi:{ApiError},Number,Date,Set};vm.createContext(scope);
  const parts=['APPLICATION','CATEGORY','ASSIGNMENT'].map(name=>html.split('// BEGIN DJANGO '+name+' STATE')[1].split('// END DJANGO '+name+' STATE')[0]);
  vm.runInContext(parts.join('\n'),scope);return scope;
})();
test('assignment PUT uses only scoped IDs, revision, session and CSRF; no replay header',async()=>{
  const calls=[];const {client}=setup(async(p,o)=>{calls.push({p,o});return response(200,p==='/api/auth/csrf'?{csrfToken:'fixture'}:{id:7,category_id:5,category_revision:1});});
  await client.bootstrap();await client.assignApplicationCategory(7,{categoryId:5,expectedRevision:0});await client.assignApplicationCategory(7,{categoryId:null,expectedRevision:1});
  assert.equal(calls[1].p,'/api/workspaces/2/applications/7/category/');
  assert.deepEqual(JSON.parse(calls[1].o.body),{category_id:5,expected_revision:0});assert.deepEqual(JSON.parse(calls[2].o.body),{category_id:null,expected_revision:1});
  assert.equal(calls[1].o.method,'PUT');assert.equal(calls[1].o.credentials,'same-origin');assert.equal(calls[1].o.cache,'no-store');assert.equal(calls[1].o.headers['X-CSRFToken'],'fixture');assert.equal(calls[1].o.headers['Idempotency-Key'],undefined);
});
test('assignment rejects unsafe or missing IDs/revisions without transmission',async()=>{
  let calls=0;const {client,context}=setup(async()=>{calls++;return response(200,{});});
  for(const bad of [undefined,0,-1,true,'5',1.2,Number.MAX_SAFE_INTEGER+1]) {
    assert.throws(()=>client.assignApplicationCategory(bad,{categoryId:5,expectedRevision:0}),{code:'unsafe_identifier'});
    assert.throws(()=>client.assignApplicationCategory(7,{categoryId:bad,expectedRevision:0}),{code:'unsafe_identifier'});
  }
  for(const bad of [undefined,-1,true,'0',1.2,Number.MAX_SAFE_INTEGER+1])assert.throws(()=>client.assignApplicationCategory(7,{categoryId:null,expectedRevision:bad}),{code:'unsafe_revision'});
  context.select(Number.MAX_SAFE_INTEGER+1);assert.throws(()=>client.assignApplicationCategory(7,{categoryId:null,expectedRevision:0}),{code:'unsafe_identifier'});assert.equal(calls,0);
});
test('assignment captured context, preabort and active abort do not retry',async()=>{
  let signal,release,calls=0;const {client,context}=setup(async(p,o)=>{if(p==='/api/auth/csrf')return response(200,{csrfToken:'fixture'});calls++;signal=o.signal;return new Promise(r=>release=r);});
  await client.bootstrap();const old=context.capture();context.select(3);assert.throws(()=>client.assignApplicationCategory(7,{categoryId:null,expectedRevision:0,captured:old}),{code:'stale_response'});
  const abort=new AbortController();const task=client.assignApplicationCategory(7,{categoryId:null,expectedRevision:0,signal:abort.signal});abort.abort();assert(signal.aborted);release(response(200,{id:7,category_id:null,category_revision:0}));await task;
  await assert.rejects(client.assignApplicationCategory(7,{categoryId:null,expectedRevision:0,signal:abort.signal}),{code:'aborted'});assert.equal(calls,1);
  const failed=setup(async(p)=>p==='/api/auth/csrf'?response(200,{csrfToken:'fixture'}):Promise.reject(new TypeError('lost')));await failed.client.bootstrap();await assert.rejects(failed.client.assignApplicationCategory(7,{categoryId:5,expectedRevision:0}),{code:'network_error'});
});
test('assignment observation retains only action authority; receipt is minimal and validated',()=>{
  const h=assignmentHelpers,row={...applicationFixture(),category_revision:4,private:'secret'};
  const projected=h.assignmentObservation(row,2,7,row.portable_id.toUpperCase());assert.equal(projected.category_revision,4);assert.equal(projected.section,undefined);assert.equal(projected.private,undefined);
  for(const change of [{workspace:3},{id:8},{portable_id:'bad'},{category_id:0},{category_revision:-1},{category_revision:Number.MAX_SAFE_INTEGER+1},{override:{}},{effective_trashed:true}])assert.throws(()=>h.assignmentObservation({...row,...change},2,7));
  const attempt={id:7,categoryId:5,revision:4,captured:{workspace:2}};
  for(const rev of [4,5])assert.equal(JSON.stringify(h.assignmentReceipt({id:7,category_id:5,category_revision:rev,private:'secret',workspace:2},attempt)),JSON.stringify({id:7,category_id:5,category_revision:rev}));
  for(const change of [{id:8},{category_id:null},{workspace:3},{workspace_id:3},{category_revision:6},{category_revision:-1},{category_revision:Number.MAX_SAFE_INTEGER+1}])assert.throws(()=>h.assignmentReceipt({id:7,category_id:5,category_revision:5,...change},attempt));
  assert.equal(h.assignmentReceipt({id:7,category_id:null,category_revision:5},{...attempt,categoryId:null}).category_id,null);
});
test('assignment outcomes distinguish rejection from uncertainty and normalize raw details',()=>{
  const h=assignmentHelpers;
  for(const [status,code,match] of [[409,'stale_revision',/observed membership changed/],[409,'resource_trashed',/unavailable/],[404,'not_found',/unavailable/],[503,'creation_busy',/database was busy/],[500,'request_failed',/may have completed/],[0,'network_error',/may have completed/],[0,'unexpected_response',/may have completed/],[401,'authentication_required',/session ended/]]) {
    const result=h.assignmentOutcome(new ApiError(code,'private request key SQL',status));assert.match(result,match);assert(!result.includes('private')&&!result.includes('request key'));
  }
  assert.match(h.assignmentReadMessage(new ApiError('unsafe_revision','private')),/cannot be represented safely/);
});

test('review disposition uses strict scoped desired-state POST and no replay',async()=>{
  const calls=[];const {client,context}=setup(async(p,o)=>{calls.push({p,o});return p==='/api/auth/csrf'?response(200,{csrfToken:'fixture'}):response(200,{});});
  await client.bootstrap();await client.dismissApplicationReview(7,{expectedRevision:0});await client.restoreApplicationReview(7,{expectedRevision:1});
  for(const [index,transition,revision] of [[1,'dismiss',0],[2,'restore',1]]) {
    const c=calls[index];assert.equal(c.p,`/api/workspaces/2/application-reviews/7/${transition}/`);
    assert.equal(c.o.method,'POST');assert.deepEqual(JSON.parse(c.o.body),{expected_revision:revision});
    assert.equal(c.o.credentials,'same-origin');assert.equal(c.o.cache,'no-store');assert.equal(c.o.headers['X-CSRFToken'],'fixture');assert.equal(c.o.headers['Idempotency-Key'],undefined);
  }
  const old=context.capture();context.select(3);assert.throws(()=>client.dismissApplicationReview(7,{expectedRevision:0,captured:old}),{code:'stale_response'});
  assert.equal(calls.length,3);
});
test('review disposition withholds unsafe identity/revision and preaborted requests',async()=>{
  let hits=0;const {client,context}=setup(async()=>{hits++;return response(200,{});});
  for(const method of [client.dismissApplicationReview,client.restoreApplicationReview]) {
    for(const id of [0,-1,true,'7',1.2,Number.MAX_SAFE_INTEGER+1])assert.throws(()=>method(id,{expectedRevision:0}),{code:'unsafe_identifier'});
    for(const revision of [undefined,-1,true,'0',0.1,Number.MAX_SAFE_INTEGER,Number.MAX_SAFE_INTEGER+1])assert.throws(()=>method(7,{expectedRevision:revision}),{code:'unsafe_revision'});
  }
  context.select(Number.MAX_SAFE_INTEGER+1);assert.throws(()=>client.dismissApplicationReview(7,{expectedRevision:0}),{code:'unsafe_identifier'});assert.equal(hits,0);
});
test('review disposition lost response sends once and caller abort cannot prove rollback',async()=>{
  let posts=0,release,signal;const {client}=setup(async(p,o)=>{if(p==='/api/auth/csrf')return response(200,{csrfToken:'t'});posts++;signal=o.signal;return new Promise(r=>release=r);});
  await client.bootstrap();const controller=new AbortController();const pending=client.dismissApplicationReview(7,{expectedRevision:0,signal:controller.signal});controller.abort();assert(signal.aborted);release(response(200,{}));await pending;
  await assert.rejects(client.dismissApplicationReview(7,{expectedRevision:0,signal:controller.signal}),{code:'aborted'});assert.equal(posts,1);
  let failures=0;const lost=setup(async p=>p==='/api/auth/csrf'?response(200,{csrfToken:'t'}):(failures++,Promise.reject(new TypeError('lost'))));await lost.client.bootstrap();await assert.rejects(lost.client.restoreApplicationReview(7,{expectedRevision:1}),{code:'network_error'});assert.equal(failures,1);
});
test('review authority projection and receipts reject unsafe or incoherent disposition',()=>{
  const h=reviewHelpers,row=reviewFixture();assert.equal(h.reviewRow(row,2,7).disposition.revision,999);
  for(const revision of [undefined,null,-1,true,'1',0.1,Number.MAX_SAFE_INTEGER+1])assert.throws(()=>h.reviewRow({...row,disposition:{...row.disposition,revision}},2,7));
  const attempt={id:7,captured:{workspace:2},desired:'dismissed',revision:0};const receipt={id:7,workspace_id:2,disposition:{state:'dismissed',revision:1,dismissed_at:'2026-10-07T12:00:00Z'}};
  assert.equal(h.reviewReceipt(receipt,attempt).disposition.revision,1);
  for(const change of [{id:8},{workspace_id:3},{disposition:{...receipt.disposition,revision:0}},{disposition:{...receipt.disposition,revision:2}},{disposition:{...receipt.disposition,state:'active'}},{disposition:{...receipt.disposition,dismissed_at:null}},{disposition:{...receipt.disposition,revision:true}}])assert.throws(()=>h.reviewReceipt({...receipt,...change},attempt));
  assert.equal(h.reviewReceipt({id:7,workspace_id:2,disposition:{state:'active',revision:2,dismissed_at:null}},{...attempt,desired:'active',revision:1}).disposition.state,'active');
});
test('review outcome distinguishes refusal and uncertainty without raw message exposure',()=>{
  const h=reviewHelpers;
  for(const [code,status,pattern] of [['stale_revision',409,/revision changed/],['lifecycle_busy',503,/database was busy/],['csrf_failed',403,/rejected/],['unexpected_response',200,/may have completed/],['unexpected_review',0,/may have completed/],['network_error',0,/may have completed/],['request_failed',500,/may have completed/]]){
    const message=h.reviewOutcome(new ApiError(code,'PRIVATE SQL',status));assert.match(message,pattern);assert(!message.includes('PRIVATE'));
  }
});
