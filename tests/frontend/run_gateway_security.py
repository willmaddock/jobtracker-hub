"""Repeatable Chrome regressions: synthetic server, profiles, downloads and DB only."""
import base64
import json
import os
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[2]
TEMP=tempfile.TemporaryDirectory(prefix='jth-gateway-chrome-')
D=Path(TEMP.name)
processes=[]
class CDP:
 def __init__(self,url):
  u=urlsplit(url);self.sock=socket.create_connection(('127.0.0.1',u.port));self.sock.settimeout(30);self.ident=0
  key=base64.b64encode(os.urandom(16)).decode();self.sock.sendall(f'GET {u.path} HTTP/1.1\r\nHost: 127.0.0.1:{u.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'.encode())
  b=b''
  while b'\r\n\r\n' not in b:b+=self.sock.recv(1)
  assert b'101' in b
 def exact(self,n):
  b=b''
  while len(b)<n:
   x=self.sock.recv(n-len(b))
   if not x:raise RuntimeError('Browser connection closed')
   b+=x
  return b
 def read(self):
  h=self.exact(2);length=h[1]&127
  if length==126:length=struct.unpack('!H',self.exact(2))[0]
  elif length==127:length=struct.unpack('!Q',self.exact(8))[0]
  mask=self.exact(4) if h[1]&128 else None;b=self.exact(length)
  if mask:b=bytes(c^mask[i%4] for i,c in enumerate(b))
  return json.loads(b)
 def command(self,method,params=None,session_id=None):
  self.ident+=1;message={'id':self.ident,'method':method,'params':params or {}}
  if session_id:message['sessionId']=session_id
  data=json.dumps(message).encode();mask=os.urandom(4)
  header=bytes([129,128|len(data)]) if len(data)<126 else bytes([129,254])+struct.pack('!H',len(data))
  self.sock.sendall(header+mask+bytes(c^mask[i%4] for i,c in enumerate(data)))
  while True:
   r=self.read()
   if r.get('id')==self.ident:
    if 'error' in r:raise RuntimeError(r)
    return r['result']
 def evaluate(self,code):
  r=self.command('Runtime.evaluate',{'expression':code,'returnByValue':True,'awaitPromise':True})
  if 'exceptionDetails' in r:raise RuntimeError(r)
  return r['result'].get('value')
 def navigate(self,path):
  self.command('Page.navigate',{'url':'http://127.0.0.1:18765'+path})
  for _ in range(100):
   time.sleep(.05)
   if self.evaluate('document.readyState')=='complete' and self.evaluate('location.pathname')==path:return
  raise RuntimeError('Navigation deadline')
def launch(name):
 profile=Path(tempfile.mkdtemp(prefix='chrome-'+name+'-',dir=D));log=open(profile/'chrome.log','wb')
 p=subprocess.Popen(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--disable-gpu','--disable-popup-blocking','--disable-background-timer-throttling','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-sync','--remote-debugging-port=0','--user-data-dir='+str(profile),'about:blank'],stdout=log,stderr=log);processes.append((p,log))
 for _ in range(100):
  if (profile/'DevToolsActivePort').exists():break
  time.sleep(.1)
 port=int((profile/'DevToolsActivePort').read_text().splitlines()[0]);target=json.load(urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}/json/new?about:blank',method='PUT')))
 c=CDP(target['webSocketDebuggerUrl']);c.command('Page.enable');c.command('Runtime.enable');c.command('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(profile/'downloads'),'eventsEnabled':True})
 c.port=port
 return c,profile

def click_docx_label(primary, stage):
 """Real mouse input into an opaque sandbox, located using privileged test tooling.

 No document-supplied script is evaluated. Runtime queries only inspect rendering.
 """
 targets=json.load(urllib.request.urlopen(f'http://127.0.0.1:{primary.port}/json/list'))
 target=next(t for t in targets if t.get('title')=='DOCX_SECURITY_TARGET')
 viewer=CDP(target['webSocketDebuggerUrl'])
 try:
  viewer.command('Page.enable');viewer.command('Runtime.enable')
  selector='#docx-defense' if stage=='defense' else 'iframe.viewer-frame'
  frame_rect=viewer.evaluate(f"(()=>{{const f=document.querySelector({json.dumps(selector)});f.scrollIntoView();const r=f.getBoundingClientRect();return {{x:r.x+f.clientLeft,y:r.y+f.clientTop}};}})()")
  viewer.command('DOM.enable')
  root_node=viewer.command('DOM.getDocument')['root']['nodeId']
  node=viewer.command('DOM.querySelector',{'nodeId':root_node,'selector':selector})['nodeId']
  description=viewer.command('DOM.describeNode',{'nodeId':node})['node']
  frame=description.get('frameId')
  session=None
  # Chrome may put the opaque sandbox in a separate renderer target. Inspect it
  # through CDP, never by weakening the production sandbox or same-origin policy.
  targets=viewer.command('Target.getTargets')['targetInfos']
  remote=next((t for t in targets if t['targetId']==frame and t['type']=='iframe'),None)
  if remote:
   session=viewer.command('Target.attachToTarget',{'targetId':remote['targetId'],'flatten':True})['sessionId']
   viewer.command('Page.enable',session_id=session)
  world=viewer.command('Page.createIsolatedWorld',{'frameId':frame,'worldName':'docx-test-inspection'},session_id=session)['executionContextId']
  expression="""(()=>{const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;while(n=walker.nextNode()){if(n.textContent.includes('Harmless attack label')){const range=document.createRange();range.selectNodeContents(n);const r=range.getBoundingClientRect();const x=r.x+r.width/2,y=r.y+r.height/2;return {x,y,hit:document.elementFromPoint(x,y)?.textContent.includes('Harmless attack label'),image:[...document.images].some(i=>i.complete&&i.naturalWidth>0)};}}return null;})()"""
  position=None
  deadline=time.monotonic()+10
  while time.monotonic()<deadline:
   result=viewer.command('Runtime.evaluate',{'expression':expression,'contextId':world,'returnByValue':True},session_id=session)
   position=result['result'].get('value')
   if position and position['hit'] and (stage=='defense' or position['image']):break
   time.sleep(.05)
  assert position and position['hit'],position
  if stage=='sanitized':assert position['image'],'Embedded PNG did not decode'
  for kind in ['mousePressed','mouseReleased']:
   viewer.command('Input.dispatchMouseEvent',{'type':kind,'button':'left','clickCount':1,'x':frame_rect['x']+position['x'],'y':frame_rect['y']+position['y']})
  # A round trip observes the completed input rather than a fixed sleep.
  viewer.evaluate('document.readyState')
  evidence=viewer.command('Runtime.evaluate',{'expression':'({url:location.href,scriptExecuted:!!document.documentElement.dataset.scriptExecuted,linkExecuted:!!document.documentElement.dataset.linkExecuted})','contextId':world,'returnByValue':True},session_id=session)['result']['value']
  position.update(evidence)
  primary.evaluate('window.__docxClickDone='+json.dumps(position))
 finally:viewer.sock.close()
try:
 server_log=open(D/'server.log','wb')
 server=subprocess.Popen([str(ROOT/'backend/venv/bin/python'),'-B',str(ROOT/'tests/frontend/serve_gateway_security.py')],cwd=ROOT,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'},stdout=server_log,stderr=server_log)
 processes.append((server,server_log))
 deadline=time.monotonic()+25
 while time.monotonic()<deadline:
  if server.poll() is not None:raise RuntimeError((D/'server.log').read_text())
  if 'READY http://' in (D/'server.log').read_text():break
  time.sleep(.1)
 else:raise RuntimeError('Disposable server startup timed out')
 isolated,otherProfile=launch('separate-profile');isolated.navigate('/__test/seen')
 separate=isolated.evaluate("""(async()=>{const html=await(await fetch('/')).text();let ctx=JSON.parse(html.match(/window.JTH_GATEWAY_PAGE = (\\{.*?\\});/)[1]).binding;const csrf=(await(await fetch('/api/auth/csrf')).json()).csrfToken;const response=await fetch('/api/auth/login',{method:'POST',headers:{'X-JTH-Context':ctx,'X-CSRFToken':csrf,'Content-Type':'application/json'},body:JSON.stringify({username:'auditB',password:'synthetic-test-password'})});window.isolatedBinding=response.headers.get('X-JTH-Context');return response.status;})()""")
 assert separate==200,separate
 primary,profile=launch('primary');primary.navigate('/__test/gateway-security')
 deadline=time.monotonic()+300
 clicked=set()
 while time.monotonic()<deadline:
  if primary.evaluate('document.title')=='AUDIT_DONE':break
  stage=primary.evaluate('window.__docxStage?.id')
  if stage and stage not in clicked:
   click_docx_label(primary,stage);clicked.add(stage)
  time.sleep(.5)
 else:raise RuntimeError('Browser harness deadline')
 results=json.loads(primary.evaluate('document.querySelector("#results").textContent'))
 results.append({'name':'Real mouse clicks exercised sanitized DOCX and independent sandbox defenses','passed':clicked=={'sanitized','defense'}})
 identity=isolated.evaluate("""fetch('/api/auth/me',{headers:{'X-JTH-Context':window.isolatedBinding}}).then(r=>r.json()).then(x=>x.username)""")
 results.append({'name':'Separate Chrome profile retains B across other profile logout, A B A and MFA transitions','passed':identity=='auditB'})
 downloads=list((profile/'downloads').glob('*.pdf'))
 results.append({'name':'Actual synthetic PDF download saved only in disposable profile directory','passed':len(downloads)==1 and downloads[0].read_bytes().startswith(b'%PDF-1.4')})
 docx_downloads=list((profile/'downloads').glob('*.docx'))
 import sys
 sys.path.insert(0,str(ROOT/'tests'))
 from test_docx_preview import make_docx
 results.append({'name':'Explicit DOCX download preserves original file bytes','passed':len(docx_downloads)==1 and docx_downloads[0].read_bytes()==make_docx()})
 (D/'final-browser-results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2),flush=True)
 print('TOTAL',len(results),'PASS',sum(x['passed'] for x in results),'FAIL',sum(not x['passed'] for x in results),flush=True)
 if not all(x['passed'] for x in results):raise SystemExit(1)
finally:
 for p,log in processes:
  p.terminate()
  try:p.wait(timeout=5)
  except subprocess.TimeoutExpired:p.kill();p.wait()
  log.close()
 TEMP.cleanup()
