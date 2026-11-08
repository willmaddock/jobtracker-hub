(function () {
  var root = document.documentElement;
  var themeKey = "jth-theme", navKey = "jth-nav-collapsed";
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  var saved = get(themeKey);
  if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);

  function current() {
    return root.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  }
  function apply(mode) {
    if (mode === "system") { root.removeAttribute("data-theme"); set(themeKey, "system"); }
    else { root.setAttribute("data-theme", mode); set(themeKey, mode); }
    mark();
  }
  function mark() {
    var mode = get(themeKey) || "system";
    document.querySelectorAll("[data-theme-set]").forEach(function (b) {
      b.classList.toggle("on", b.getAttribute("data-theme-set") === mode);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (get(navKey) === "1") document.body.classList.add("collapsed");
    mark();
    document.querySelectorAll("[data-theme-set]").forEach(function (b) {
      b.addEventListener("click", function () { apply(b.getAttribute("data-theme-set")); });
    });
    var toggle = document.getElementById("theme-toggle");
    if (toggle) toggle.addEventListener("click", function () { apply(current() === "dark" ? "light" : "dark"); });
    var collapse = document.getElementById("nav-collapse");
    if (collapse) collapse.addEventListener("click", function () {
      var on = document.body.classList.toggle("collapsed");
      set(navKey, on ? "1" : "0");
    });
    // Cmd/Ctrl+K focuses the search box.
    document.addEventListener("keydown", function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        var s = document.getElementById("search-input");
        if (s) { e.preventDefault(); s.focus(); }
      }
    });

    // Kanban: dragging a card onto a column submits that card's hidden status form.
    // The Move select next to each card does the same thing without drag and drop.
    var dragged = null;
    document.querySelectorAll(".kc[draggable]").forEach(function (card) {
      card.addEventListener("dragstart", function (e) {
        dragged = card; card.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", card.getAttribute("data-id"));
      });
      card.addEventListener("dragend", function () { card.classList.remove("dragging"); dragged = null; });
      var sel = card.querySelector("select");
      if (sel) sel.addEventListener("change", function () { if (sel.value) { sel.form.elements.status.value = sel.value; sel.form.submit(); } });
    });
    document.querySelectorAll(".col[data-status]").forEach(function (col) {
      col.addEventListener("dragover", function (e) { if (dragged) { e.preventDefault(); col.classList.add("over"); } });
      col.addEventListener("dragleave", function () { col.classList.remove("over"); });
      col.addEventListener("drop", function (e) {
        e.preventDefault(); col.classList.remove("over");
        if (!dragged) return;
        var form = dragged.querySelector("form");
        if (!form) return;
        var status = col.getAttribute("data-status");
        if (dragged.getAttribute("data-status") === status) return;
        form.querySelector("[name=status]").value = status;
        form.submit();
      });
    });
    var sort = document.getElementById("sort-select");
    if (sort) sort.addEventListener("change", function () { sort.form.submit(); });
  });
})();
