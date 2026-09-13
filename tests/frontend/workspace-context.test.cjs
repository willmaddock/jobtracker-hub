const {test} = require('node:test');
const assert = require('node:assert/strict');
const {parseRoute, createContext} = require('../../_app/frontend/workspace-context.js');
test('only explicit valid workspace routes select', () => {
  for (const hash of ['', '#', '#/workspaces/0', '#/workspaces/1/extra', '#/workspaces/9007199254740993']) assert.equal(parseRoute(hash), null);
  assert.equal(parseRoute('#/workspaces/12'), 12);
});
test('independent tabs, immutable snapshots, navigation and actor invalidation', () => {
  const a=createContext(), b=createContext(); a.setActor(1); b.setActor(1);
  assert.equal(a.capture().workspace, null);
  a.select(10); b.select(20); const old=a.capture(); let aborted=0;
  a.trackRead(()=>aborted++); a.select(30);
  assert.equal(old.workspace,10); assert.equal(Object.isFrozen(old),true);
  assert.equal(a.current(old),false); assert.equal(aborted,1); assert.equal(b.capture().workspace,20);
  a.setActor(2); assert.equal(a.capture().workspace,null);
  b.setActor(null); assert.equal(b.capture().workspace,null);
});
