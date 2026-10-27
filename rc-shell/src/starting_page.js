// rc-shell/src/starting_page.js
//
// Page-side script of the launcher's starting view (starting.html, PKG-6). A
// plain browser script in the starting window, and a CommonJS module under node
// so rc-shell/test/launcher_wiring.test.js can drive it through a DOM stub.
//
// main.js calls window.__rcStarting(model) with launcher.startingModel output:
//   {view: "starting" | "error", title, detail, rows: [{name, row, word}]}
// Everything is written with textContent - the model never reaches an HTML
// parsing sink.
//
// ASCII only.

"use strict";

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  } else if (root && root.document) {
    root.__rcStarting = (model) => api.render(root.document, model);
  }
})(typeof window !== "undefined" ? window : null, function () {
  const MAX_ROWS = 32;

  function text(v) {
    return typeof v === "string" ? v : "";
  }

  function render(doc, model) {
    if (!doc || !model || typeof model !== "object") {
      return false;
    }
    const view = doc.getElementById("view");
    const title = doc.getElementById("title");
    const detail = doc.getElementById("detail");
    const rows = doc.getElementById("rows");
    if (view) {
      view.className = model.view === "error" ? "error" : "starting";
    }
    if (title) {
      title.textContent = text(model.title);
    }
    if (detail) {
      detail.textContent = text(model.detail);
    }
    if (rows) {
      while (rows.firstChild) {
        rows.removeChild(rows.firstChild);
      }
      const list = Array.isArray(model.rows) ? model.rows.slice(0, MAX_ROWS) : [];
      for (const r of list) {
        if (!r || typeof r !== "object") {
          continue;
        }
        const li = doc.createElement("li");
        li.textContent = text(r.row) + " " + text(r.name) + " ";
        const word = doc.createElement("span");
        word.className = "word";
        word.textContent = text(r.word);
        li.appendChild(word);
        rows.appendChild(li);
      }
    }
    return true;
  }

  return { render, MAX_ROWS };
});
