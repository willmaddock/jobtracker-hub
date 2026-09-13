/* Django transport only. Legacy URLs are never adapted or retried here. */
(function (root) {
  "use strict";
  class ApiError extends Error {
    constructor(code, message, status = 0, details = null, context = null) {
      super(message); this.code = code; this.status = status;
      this.details = details; this.context = context;
    }
  }
  function decode(status, text, context) {
    let data = null;
    if (text) {
      try { data = JSON.parse(text); }
      catch (_) { throw new ApiError("unexpected_response", "Unexpected server response.", status, null, context); }
    }
    if (status < 200 || status >= 300) {
      const message = data && typeof data.detail === "string" ? data.detail : "Request failed. Check your input and try again.";
      throw new ApiError(data && data.code || "request_failed", message, status, data, context);
    }
    if (!text && status !== 204) throw new ApiError("unexpected_response", "Unexpected empty response.", status, null, context);
    return data;
  }
  function createClient({ context, fetchImpl = root.fetch.bind(root), xhrFactory = () => new root.XMLHttpRequest() }) {
    let csrf = null;
    function check(c) {
      if (!context.current(c)) throw new ApiError("stale_response", "This request belongs to an earlier view.", 0, null, c);
    }
    function pathCheck(path) {
      if (!/^\/api\/(?!\/)/.test(path) || /[\\#]/.test(path) || path.split("/").includes("..")) {
        throw new ApiError("invalid_request", "Expected a same-origin API path.");
      }
    }
    async function request(path, { method = "GET", body, captured = context.capture() } = {}) {
      pathCheck(path); check(captured);
      const unsafe = !["GET", "HEAD", "OPTIONS"].includes(method);
      if (unsafe && !csrf) throw new ApiError("csrf_required", "Refresh authentication before trying again.");
      const controller = new AbortController();
      const release = !unsafe ? context.trackRead(() => controller.abort()) : () => {};
      const headers = { Accept: "application/json" };
      if (unsafe) headers["X-CSRFToken"] = csrf;
      const payload = body === undefined ? undefined : JSON.stringify(body);
      if (payload !== undefined) headers["Content-Type"] = "application/json";
      try {
        const response = await fetchImpl(path, { method, headers, body: payload, credentials: "same-origin", cache: "no-store", signal: controller.signal });
        const text = await response.text();
        check(captured);
        return decode(response.status, text, captured);
      } catch (e) {
        check(captured);
        if (e instanceof ApiError) throw e;
        throw new ApiError(e.name === "AbortError" ? "aborted" : "network_error", unsafe ? "Connection lost. The change may have completed. Refresh before trying again." : "Connection failed. Try again.", 0, null, captured);
      } finally { release(); }
    }
    return {
      request,
      clearCsrf() { csrf = null; },
      async bootstrap() {
        const result = await request("/api/auth/csrf");
        if (!result || typeof result.csrfToken !== "string") throw new ApiError("unexpected_response", "Missing CSRF token.");
        csrf = result.csrfToken;
      },
      // An explicit endpoint, not a generic legacy URL prefix adapter.
      readWorkspace(captured = context.capture()) {
        if (!captured.actor || !Number.isSafeInteger(captured.workspace) || captured.workspace < 1) throw new ApiError("workspace_required", "Select a workspace first.");
        return request(`/api/workspaces/${captured.workspace}/insights/`, { captured });
      },
      // Keep Safari's documented XHR multipart path. Browser sets the boundary.
      upload(path, form, captured = context.capture()) {
        pathCheck(path); check(captured);
        if (!csrf) return Promise.reject(new ApiError("csrf_required", "Refresh authentication before trying again."));
        return new Promise((resolve, reject) => {
          const xhr = xhrFactory();
          xhr.open("POST", path); xhr.timeout = 60000;
          xhr.setRequestHeader("Accept", "application/json");
          xhr.setRequestHeader("X-CSRFToken", csrf);
          const fail = (code, message) => { try { check(captured); reject(new ApiError(code, message, 0, null, captured)); } catch (e) { reject(e); } };
          xhr.onload = () => { try { check(captured); resolve(decode(xhr.status, xhr.responseText, captured)); } catch (e) { reject(e); } };
          xhr.onerror = xhr.ontimeout = () => fail("network_error", "Upload response unavailable. It may have completed; refresh before trying again.");
          xhr.onabort = () => fail("aborted", "Upload interrupted. It may have completed.");
          // Same-origin XHR sends session cookies by default.
          xhr.send(form);
        });
      },
    };
  }
  const api = { ApiError, createClient };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JTHApi = api;
})(typeof window === "undefined" ? globalThis : window);
