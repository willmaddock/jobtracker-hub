/* Gateway context transport. Never grants authentication, CSRF or MFA authority. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;else {
    root.JTHGatewaySession = api;
    root.jthGatewaySession = api.install(root);
  }
})(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';

  const HEADER = 'X-JTH-Context',
    EVENT = 'jth-session-change',
    CACHE = 'jth_cache_v1';
  const PUBLIC = new Set(['/api/health', '/api/auth/options', '/api/auth/csrf']);
  const TRANSITIONS = new Set(['/api/auth/login', '/api/auth/email/verify', '/api/auth/mfa/verify', '/api/auth/mfa/passkey/verify', '/api/auth/mfa/email/verify', '/api/auth/mfa/enroll/confirm', '/api/auth/logout']);
  function requestDeadline(path) {
    return path.startsWith('/api/auth/') || path.startsWith('/api/account/') ||
      path.startsWith('/api/gateway/') || path === '/api/workspaces/' ? 30000 : 600000;
  }
  function clearCache(env) {
    try {
      env.localStorage.removeItem(CACHE);
    } catch (_) {}
  }
  function announce(env) {
    try {
      env.localStorage.setItem(EVENT, Date.now() + ':' + Math.random());
    } catch (_) {}
  }
  function canceled(signal) {
    if (signal?.aborted) throw new DOMException('Document request canceled.', 'AbortError');
  }
  // A canceled reader need not wait for an uncooperative body or a shared
  // completion check. Its result is discarded; other readers retain their proof.
  function cancellable(task, signal) {
    return new Promise((resolve, reject) => {
      const abort = () => { signal.removeEventListener('abort', abort); reject(new DOMException('Document request canceled.', 'AbortError')); };
      signal.addEventListener('abort', abort, {once:true});
      Promise.resolve(task).then(value => { signal.removeEventListener('abort', abort); resolve(value); },
        error => { signal.removeEventListener('abort', abort); reject(error); });
      if (signal.aborted) abort();
    });
  }
  function create(env, initial) {
    // React portals live outside #root. Conceal those too while checking, and
    // keep any residual portal hidden even if an unmount cleanup throws.
    const curtain = env.document.createElement('style');
    curtain.textContent = 'html.jth-gateway-concealed body>*{visibility:hidden!important}' +
      'html.jth-gateway-ended body>*:not(#root){display:none!important}';
    env.document.head?.append(curtain);
    let context = Object.freeze({
        ...initial
      }),
      generation = 0,
      ended = false,
      suspended = false,
      transition = false, intent = false;
    const nativeFetch = env.fetch.bind(env),
      pending = new Set(),
      listeners = new Set(),
      blobs = new Set(), responses = new WeakMap(), idleTimers = new Set();
    let batch = [],
      scheduled = false,
      timer = null,
      lastCheck = Date.now(),
      channel = null,
      lifecycle = 0,
      checking = 0;
    const error = () => Object.assign(new Error('Session context changed. Reload to continue.'), {
      code: 'gateway_session_changed'
    });
    function current(g, binding) {
      if (ended || g !== generation || binding !== context.binding) throw error();
    }
    function node() {
      return env.document.getElementById('root');
    }
    function hide() {
      env.document.documentElement?.classList.add('jth-gateway-concealed');
      if (node()) node().style.visibility = 'hidden';
    }
    function show() {
      if (!ended && !suspended && !transition && !intent && env.document.visibilityState !== 'hidden' && node()) {
        env.document.documentElement?.classList.remove('jth-gateway-concealed');
        node().style.visibility = '';
      }
    }
    function message(text) {
      env.document.documentElement?.classList.add('jth-gateway-ended');
      env.document.documentElement?.classList.remove('jth-gateway-concealed');
      if (!node()) return;
      node().replaceChildren();
      node().style.visibility = '';
      const p = env.document.createElement('p');
      p.setAttribute('role', 'alert');
      p.textContent = text;
      const b = env.document.createElement('button');
      b.textContent = 'Reload and check session';
      b.onclick = () => env.location.reload();
      node().append(p, b);
    }
    function end(text = 'Session context changed. Reload to continue.', reload = false) {
      if (ended) return;
      ended = true;
      generation++;
      hide();
      clearCache(env);
      env.clearInterval(timer);
      for (const deadline of idleTimers) env.clearTimeout(deadline);
      idleTimers.clear();
      try { channel?.close(); } catch (_) {}
      for (const cancel of pending) cancel();
      pending.clear();
      for (const listener of listeners) { try { listener(); } catch (_) {} }
      for (const url of blobs) env.URL.revokeObjectURL(url);
      blobs.clear();
      message(text);
      if (reload) env.location.reload();
    }
    function notify() {
      try {
        channel?.postMessage('changed');
      } catch (_) {}
      announce(env);
    }
    async function bounded(task, cancel, milliseconds = 30000, valid = () => true) {
      let deadline;
      try {
        return await Promise.race([task, new Promise((_, reject) => {
          deadline = env.setTimeout(() => {
            cancel();
            if (valid()) end('The request timed out. Reload to check your session.');
            reject(error());
          }, milliseconds);
        })]);
      } finally {
        env.clearTimeout(deadline);
      }
    }
    async function probe(binding) {
      const controller = new AbortController();
      let deadline;
      const cancel = () => controller.abort();
      pending.add(cancel);
      checking++;
      const timeout = new Promise((_, reject) => {
        deadline = env.setTimeout(() => {
          cancel();
          reject(error());
        }, 5000);
      });
      try {
        const response = await Promise.race([nativeFetch('/api/gateway/context', {
          headers: {
            [HEADER]: binding
          },
          credentials: 'same-origin',
          cache: 'no-store',
          signal: controller.signal
        }), timeout]);
        if (response.status !== 204 || response.headers.get(HEADER) !== binding) throw error();
        lastCheck = Date.now();
      } finally {
        env.clearTimeout(deadline);
        pending.delete(cancel);
        checking--;
      }
    }
    // Only completions queued BEFORE dispatch may share a check. Later bodies
    // cannot join an authentication snapshot older than their own completion.
    function completion(binding, g = generation) {
      return new Promise((resolve, reject) => {
        batch.push({
          binding,
          g,
          resolve,
          reject
        });
        if (scheduled) return;
        scheduled = true;
        queueMicrotask(async () => {
          scheduled = false;
          const group = batch.filter(item => item.g === generation);
          for (const item of batch) {
            if (item.g !== generation) item.reject(error());
          }
          batch = [];
          if (!group.length) return;
          const expected = group[0].binding;
          try {
            await probe(expected);
            for (const item of group) {
              if (item.binding !== expected) item.reject(error());else item.resolve();
            }
          } catch (e) {
            for (const item of group) item.reject(e);
            if (!ended && group.some(item => item.g === generation)) end('Your session could not be verified. Reload to check it.');
          }
        });
      });
    }
    async function verify(conceal = true) {
      const g = generation,
        binding = context.binding,
        ticket = ++lifecycle;
      current(g, binding);
      if (conceal) {
        suspended = true;
        hide();
      }
      try {
        await completion(binding, g);
        current(g, binding);
        if (ticket === lifecycle) {
          suspended = false;
          show();
        }
      } catch (e) {
        if (!ended && g === generation) end('Your session could not be verified. Reload to check it.');
        throw e;
      }
    }
    function candidate(response) {
      const binding = response.headers.get(HEADER),
        phase = response.headers.get('X-JTH-Phase'),
        raw = response.headers.get('X-JTH-Actor');
      const actor = raw === '' ? null : Number(raw);
      if (!binding || !['anonymous', 'pending', 'mfa', 'enrollment', 'verified'].includes(phase) || raw === null || actor !== null && !Number.isSafeInteger(actor)) throw error();
      return Object.freeze({
        binding,
        phase,
        actor
      });
    }
    function inspect(response, path, method, g, binding) {
      current(g, binding);
      if (path === '/api/auth/logout' && !response.ok) {
        end('Sign-out could not be confirmed. Reload to check your session.');
        throw error();
      }
      if (response.status === 401 && context.phase === 'verified') {
        end('Authentication failed. Reload to check your session.');
        throw error();
      }
      let next;
      try {
        next = candidate(response);
      } catch (e) {
        end();
        throw e;
      }
      const changed = next.binding !== binding;
      if (changed && !(method === 'POST' && TRANSITIONS.has(path) && response.ok)) {
        end();
        throw error();
      }
      return {next, changed};
    }
    async function receive(response, path, method, g, binding, reader, signal) {
      const {next, changed} = inspect(response, path, method, g, binding);
      let value, failure;
      try { value = await reader(); }
      catch (e) {
        // Native validation errors are raised only after current-session proof.
        // A broken stream/parser during a transition has uncertain server state.
        if (!response.ok && e.status === response.status && e.code !== 'unexpected_response') failure = e;
        else {
          if (g === generation && !(e.name === 'AbortError' && ['GET','HEAD'].includes(method)))
            end('The response could not be confirmed. Reload to check your session.');
          throw e;
        }
      }
      current(g, binding);
      canceled(signal);
      await completion(next.binding, g);
      current(g, binding);
      canceled(signal);
      if (changed) {
        // Candidate comes only from our explicit transition, then is checked
        // against the CURRENT cookie session before the UI receives its result.
        const replacingVerifiedSession = context.phase === 'verified' && path !== '/api/auth/logout';
        for (const url of blobs) env.URL.revokeObjectURL(url);
        blobs.clear();
        context = next;
        generation++;
        notify();
        if (replacingVerifiedSession) {
          end('Your session was replaced. Reload to continue.', true);
          throw error();
        }
        if (path === '/api/auth/logout') end('Signed out.', true);
      }
      if (failure) throw failure;
      return value;
    }
    function wrap(response, path, method, g, binding, abort, cleanup, signal) {
      try { inspect(response, path, method, g, binding); }
      catch(e) { cleanup(); throw e; }
      const safeRead = ['GET', 'HEAD'].includes(method);
      if (safeRead) canceled(signal);
      const idle = env.setTimeout(() => { idleTimers.delete(idle); cleanup(); abort(); if (g === generation) end('Response handling timed out. Reload to check your session.'); }, requestDeadline(path));
      idleTimers.add(idle);
      const discard = () => { env.clearTimeout(idle); idleTimers.delete(idle); cleanup(); };
      if (safeRead) signal.addEventListener('abort', discard, {once:true});
      const consume = reader => {
        if (safeRead) signal.removeEventListener('abort', discard);
        env.clearTimeout(idle); idleTimers.delete(idle);
        const task = receive(response, path, method, g, binding,
          () => bounded(safeRead ? cancellable(reader(response), signal) : reader(response),
            abort, requestDeadline(path), () => g === generation), safeRead ? signal : null);
        return (safeRead ? cancellable(task, signal) : task)
          .finally(() => { cleanup(); if (transition === g) transition = false; });
      };
      const wrapped = new Proxy(response, {
        get(target, key) {
          if (key === 'clone') return () => wrap(target.clone(), path, method, g, binding, abort, cleanup, signal);
          if (['json', 'text', 'blob', 'arrayBuffer', 'formData'].includes(key)) return () => consume(raw => raw[key]());
          if (key === 'body') throw new Error('Use a validated response body reader.');
          const value = Reflect.get(target, key, target);
          return typeof value === 'function' ? value.bind(target) : value;
        }
      });
      responses.set(wrapped, consume);
      return wrapped;
    }
    function consume(response, reader) {
      const validated = responses.get(response);
      return validated ? validated(reader) : reader(response);
    }
    async function fetch(input, options = {}) {
      const url = new URL(typeof input === 'string' ? input : input.url, env.location.href),
        method = (options.method || input.method || 'GET').toUpperCase();
      if (url.origin !== env.location.origin || !url.pathname.startsWith('/api/')) return nativeFetch(input, options);
      let g = generation;
      const binding = context.binding;
      current(g, binding);
      if (PUBLIC.has(url.pathname) && (method === 'GET' || method === 'HEAD' && url.pathname === '/api/health')) {
        const controller = new AbortController();
        const abort = () => controller.abort(),
          valid = () => g === generation;
        pending.add(abort);
        try {
          const response = await bounded(nativeFetch(input, {
            ...options,
            credentials: 'same-origin',
            cache: 'no-store',
            signal: controller.signal
          }), abort, 5000, valid);
          return new Proxy(response, {
            get(target, key) {
              if (['json', 'text', 'blob', 'arrayBuffer', 'formData'].includes(key)) return () => bounded(target[key](), abort, 5000, valid).finally(() => pending.delete(abort));
              const value = Reflect.get(target, key, target);
              return typeof value === 'function' ? value.bind(target) : value;
            }
          });
        } catch (e) {
          pending.delete(abort);
          throw e;
        }
      }
      if (transition) throw error();
      const changing = TRANSITIONS.has(url.pathname) && method === 'POST';
      if (changing) {
        // Retire earlier readers/checks before an intentional phase transition.
        // Their failures must not invalidate the newer, explicitly started flow.
        g = ++generation;
        transition = g;
        lifecycle++;
        for (const cancel of pending) cancel();
        pending.clear();
        if (context.phase === 'verified' || url.pathname === '/api/auth/logout') {
          suspended = true;
          hide();
        } else {
          suspended = false;
          show();
        }
      }
      const headers = new Headers(options.headers || (typeof input !== 'string' ? input.headers : undefined));
      headers.set(HEADER, binding);
      const controller = new AbortController(),
        signal = options.signal || (typeof input !== 'string' ? input.signal : null),
        abort = () => controller.abort();
      if (signal?.aborted) abort();
      signal?.addEventListener('abort', abort, {
        once: true
      });
      pending.add(abort);
      const cleanup = () => {
        pending.delete(abort);
        signal?.removeEventListener('abort', abort);
      };
      try {
        const request = nativeFetch(input, {
          ...options,
          headers,
          credentials: 'same-origin',
          cache: 'no-store',
          signal: controller.signal
        });
        const response = await bounded(['GET','HEAD'].includes(method) ? cancellable(request, controller.signal) : request,
          abort, requestDeadline(url.pathname), () => g === generation);
        current(g, binding);
        return wrap(response, url.pathname, method, g, binding, abort, cleanup, controller.signal);
      } catch (e) {
        if (changing && transition === g) {
          end('Sign-in state could not be confirmed. Reload to check it.');
          transition = false;
        }
        cleanup();
        throw e;
      }
    }
    async function upload(url, form, formatError = () => 'Upload failed.') {
      const g = generation,
        binding = context.binding;
      current(g, binding);
      const target = new URL(url, env.location.href);
      if (target.origin !== env.location.origin || !target.pathname.startsWith('/api/')) throw error();
      return new Promise((resolve, reject) => {
        const xhr = new env.XMLHttpRequest(),
          abort = () => {
            xhr.abort();
            reject(error());
          };
        pending.add(abort);
        if (transition) {
          pending.delete(abort);
          reject(error());
          return;
        }
        xhr.open('POST', url);
        xhr.timeout = 600000;
        xhr.setRequestHeader(HEADER, binding);
        xhr.onload = async () => {
          try {
            const headers = new Headers();
            for (const name of [HEADER, 'X-JTH-Phase', 'X-JTH-Actor']) {
              const value = xhr.getResponseHeader(name);
              if (value !== null) headers.set(name, value);
            }
            const response = new Response(xhr.responseText || null, {
              status: xhr.status,
              headers
            });
            const text = await receive(response, target.pathname, 'POST', g, binding, async () => xhr.responseText);
            if (xhr.status < 200 || xhr.status >= 300) throw new Error(formatError(text));
            let data = null;
            try {
              data = JSON.parse(text);
            } catch (_) {}
            resolve(data);
          } catch (e) {
            reject(e);
          } finally {
            pending.delete(abort);
          }
        };
        xhr.onerror = () => {
          pending.delete(abort);
          reject(new Error('Network error during upload.'));
        };
        xhr.onabort = () => {
          pending.delete(abort);
          reject(error());
        };
        xhr.send(form);
        xhr.ontimeout = () => {
          pending.delete(abort);
          end('The upload timed out. Reload to check your session.');
          reject(error());
        };
      });
    }
    async function file(url, {signal} = {}) {
      const g = generation, binding = context.binding;
      canceled(signal);
      const response = await fetch(url, {signal});
      const blob = await response.blob();
      if (!response.ok) throw new Error('Document unavailable.');
      current(g, binding);
      canceled(signal);
      const object = env.URL.createObjectURL(blob);
      blobs.add(object);
      return object;
    }
    function release(url) {
      if (blobs.delete(url)) env.URL.revokeObjectURL(url);
    }
    async function logout() {
      const g = generation,
        binding = context.binding;
      current(g, binding);
      intent = true;
      suspended = true;
      hide();
      try {
        const csrf = await fetch('/api/auth/csrf');
        if (!csrf.ok) throw error();
        const token = (await bounded(csrf.json(), () => {}, 5000)).csrfToken;
        current(g, binding);
        const response = await fetch('/api/auth/logout', {
          method: 'POST',
          headers: {
            'X-CSRFToken': token
          }
        });
        await response.text();
        if (!response.ok) throw error();
        if (ended) return;  // validated logout already cleared/reloaded the page
        end('Signed out.');
        notify();
        env.location.reload();
      } catch (_) {
        end('Sign-out could not be confirmed. Reload to check your session.');
        notify();
      }
    }
    const recheck = () => {
      if (!ended && !transition && !intent) verify().catch(() => {});
    };
    env.addEventListener('focus', recheck);
    env.addEventListener('storage', e => {
      if (e.key === EVENT) recheck();
    });
    env.document.addEventListener('visibilitychange', () => {
      if (env.document.visibilityState === 'hidden') hide();else recheck();
    });
    env.addEventListener('pagehide', () => end());
    env.addEventListener('pageshow', e => {
      if (e.persisted) {
        end();
        env.location.reload();
      }
    });
    if (env.BroadcastChannel) {
      try {
        channel = new env.BroadcastChannel(EVENT);
        channel.onmessage = recheck;
      } catch (_) {}
    }
    timer = env.setInterval(() => {
      if (!checking && env.document.visibilityState !== 'hidden' && Date.now() - lastCheck >= 15000) recheck();
    }, 15000);
    clearCache(env);
    return {
      fetch,
      consume,
      upload,
      file,
      release,
      logout,
      verify,
      end,
      onEnd(fn) {
        listeners.add(fn);
        if (ended) fn();
        return () => listeners.delete(fn);
      },
      get ended() {
        return ended;
      },
      get context() {
        return context;
      }
    };
  }
  function install(env) {
    if (!env.JTH_GATEWAY && !env.JTH_GATEWAY_LOGIN) return null;
    clearCache(env);
    const guard = create(env, env.JTH_GATEWAY_PAGE);
    env.fetch = guard.fetch;
    return guard;
  }
  return {
    create,
    install,
    announce
  };
});
