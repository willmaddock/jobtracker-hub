/* Preview-owned requests/resources. Authentication remains in gateway-session. */
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JTHDocumentPreview = api;
})(typeof window === 'undefined' ? globalThis : window, function() {
  'use strict';
  const CSS = 'body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:760px;margin:24px auto;padding:0 24px 40px;line-height:1.55;color:#1e293b;background:#fff}img{max-width:100%;height:auto}table{border-collapse:collapse}td,th{border:1px solid #cbd5e1;padding:4px 8px}pre{white-space:pre-wrap}';
  const CSP = "default-src 'none'; script-src 'none'; style-src 'sha256-Wrv+SW967SImQm9zc30GAxKx2dS2+So1N/8DGwchlLI='; img-src data:; connect-src 'none'; font-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";
  // html is the server-sanitized fragment, never parsed in the parent document.
  // The caller MUST also set sandbox="" on the containing iframe.
  function docxDocument(html) {
    return '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + CSP + '"><meta name="referrer" content="no-referrer"><style>' + CSS + '</style></head><body>' + html + '</body></html>';
  }
  const key = doc => JSON.stringify([doc?.workspace_id, doc?.id, doc?.relpath, doc?.ext]);
  const abortError = () => new DOMException('Document request canceled.', 'AbortError');
  function wait(task, signal) {
    return new Promise((resolve, reject) => {
      const abort = () => { signal.removeEventListener('abort', abort); reject(abortError()); };
      signal.addEventListener('abort', abort, {once:true});
      Promise.resolve(task).then(value => { signal.removeEventListener('abort', abort); resolve(value); },
        error => { signal.removeEventListener('abort', abort); reject(error); });
      if (signal.aborted) abort();
    });
  }
  function create({env = window, guard = null, base = '', onState, timeout = 60000, downloadTimeout = 600000}) {
    let generation = 0, selected = null, state = null, downloadTask = null, destroyed = false;
    const operations = new Set(), urls = new Set();
    const fileUrl = doc => base + '/api/file?relpath=' + encodeURIComponent(doc.relpath);
    function publish(value) { state = value; onState(value); }
    function close() {
      generation++; selected = null; downloadTask = null;
      for (const op of operations) { env.clearTimeout(op.timer); op.controller.abort(); }
      operations.clear();
      for (const url of urls) guard.release(url);
      urls.clear();
      publish(null);
    }
    function current(op) {
      if (destroyed || op.g !== generation || op.controller.signal.aborted) throw abortError();
    }
    async function run(work, milliseconds = timeout) {
      const op = {g:generation, controller:new AbortController(), timedOut:false};
      op.timer = env.setTimeout(() => { op.timedOut = true; op.controller.abort(); }, milliseconds);
      operations.add(op);
      try { return await wait(work(op), op.controller.signal); }
      catch (error) {
        if (op.timedOut) throw new Error('Document request timed out. Close and reopen the preview to try again.');
        throw error;
      } finally { env.clearTimeout(op.timer); operations.delete(op); }
    }
    async function loadFile(doc, op) {
      const url = await guard.file(fileUrl(doc), {signal:op.controller.signal});
      try { current(op); }
      catch (error) { guard.release(url); throw error; }
      urls.add(url);
      return url;
    }
    async function open(doc) {
      close();
      if (destroyed || !doc) return;
      selected = key(doc);
      const g = generation, ext = (doc.ext || '').toLowerCase();
      const kind = ext === '.docx' ? 'docx' : ext === '.pdf' ? 'pdf' :
        ['.txt','.md','.markdown','.tex'].includes(ext) ? 'text' : 'unsupported';
      const initial = {key:selected, kind, loading:true, error:''};
      publish(initial);
      try {
        const content = await run(async op => {
          if (kind === 'docx') {
            const response = await env.fetch(base + '/api/preview-docx?relpath=' + encodeURIComponent(doc.relpath), {signal:op.controller.signal});
            if (!response.ok) { await response.text(); throw new Error('DOCX preview unavailable (HTTP ' + response.status + '). Download the original instead.'); }
            const data = await response.json();
            current(op);
            if (typeof data.html !== 'string') throw new Error('Invalid DOCX preview response.');
            return {html:data.html, warnings:data.warnings || []};
          }
          if (kind === 'unsupported') return {};
          return {src:guard ? await loadFile(doc, op) : fileUrl(doc)};
        });
        if (g === generation) publish({...initial, ...content, loading:false});
      } catch (error) {
        if (g === generation && error.name !== 'AbortError') publish({...initial, loading:false, error:error.message});
      }
    }
    function download(doc) {
      if (destroyed || selected !== key(doc)) return Promise.reject(abortError());
      if (!guard) return Promise.resolve(fileUrl(doc)); // WKWebView needs the genuine URL.
      if (state?.src) return Promise.resolve(state.src);
      if (downloadTask) return downloadTask;
      const task = run(op => loadFile(doc, op), downloadTimeout);
      downloadTask = task;
      const done = () => { if (downloadTask === task) downloadTask = null; };
      task.then(done, done);
      return task;
    }
    const unsubscribe = guard?.onEnd(close);
    return {open, close, download, destroy() { close(); destroyed = true; unsubscribe?.(); }};
  }
  return {create, key, docxDocument};
});
