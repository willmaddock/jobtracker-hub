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
