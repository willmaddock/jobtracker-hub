"""Repeatable Chrome regressions: synthetic server, profiles, downloads and DB only."""
import base64, json, os, socket, struct, subprocess, tempfile, time, urllib.request
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
 def command(self,method,params=None):
  self.ident+=1;data=json.dumps({'id':self.ident,'method':method,'params':params or {}}).encode();mask=os.urandom(4)
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
 return c,profile
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
 deadline=time.monotonic()+240
 while time.monotonic()<deadline:
  if primary.evaluate('document.title')=='AUDIT_DONE':break
  time.sleep(.5)
 else:raise RuntimeError('Browser harness deadline')
 results=json.loads(primary.evaluate('document.querySelector("#results").textContent'))
 identity=isolated.evaluate("""fetch('/api/auth/me',{headers:{'X-JTH-Context':window.isolatedBinding}}).then(r=>r.json()).then(x=>x.username)""")
 results.append({'name':'Separate Chrome profile retains B across other profile logout, A B A and MFA transitions','passed':identity=='auditB'})
 downloads=list((profile/'downloads').glob('*.pdf'))
 results.append({'name':'Actual synthetic PDF download saved only in disposable profile directory','passed':len(downloads)==1 and downloads[0].read_bytes().startswith(b'%PDF-1.4')})
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
