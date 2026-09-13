/* Route authority and request generations. No persistent payload or selection cache. */
(function (root) {
  "use strict";
  function parseRoute(hash) {
    const match = /^#\/workspaces\/([1-9]\d*)$/.exec(hash || "");
    return match && Number.isSafeInteger(Number(match[1])) ? Number(match[1]) : null;
  }
  function createContext() {
    let actor = null, workspace = null, generation = 0;
    const reads = new Set();
    function invalidate() {
      generation++;
      for (const abort of reads) abort();
      reads.clear();
    }
    return {
      setActor(id) {
        if (actor !== id) { invalidate(); actor = id; workspace = null; }
      },
      select(id) {
        if (workspace !== id) { invalidate(); workspace = id; }
      },
      invalidate,
      capture() { return Object.freeze({ actor, workspace, generation }); },
      current(c) { return actor === c.actor && workspace === c.workspace && generation === c.generation; },
      trackRead(abort) { reads.add(abort); return () => reads.delete(abort); },
    };
  }
  const api = { parseRoute, createContext };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JTHWorkspace = api;
})(typeof window === "undefined" ? globalThis : window);
