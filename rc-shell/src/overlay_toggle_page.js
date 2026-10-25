// rc-shell/src/overlay_toggle_page.js
//
// Page-side script of the overlay ON/OFF toggle icon (overlay_toggle.html). A
// plain browser script in the toggle window, and a CommonJS module under node so
// rc-shell/test/overlay_toggle.test.js can drive it through a DOM stub.
//
// It does as little as possible: render the ON/OFF state it is told, and turn
// the operator's pointer into press / move / release / cancel messages over the
// preload bridge (window.rcToggle, toggle_preload.js). main.js owns the drag
// math (it reads the real cursor screen point, which stays right across
// monitors and DPI) and the tap-vs-drag decision (overlay_toggle.makeToggleDrag).
//
// ASCII only.

"use strict";

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  } else if (root && root.document) {
    api.mount(root.document, root.rcToggle, root);
  }
})(typeof window !== "undefined" ? window : null, function () {
  const LABEL = "Overlay on/off";

  // Anything but a strict false renders ON (the default).
  function render(btn, visible) {
    if (!btn) {
      return;
    }
    const on = visible !== false;
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.setAttribute("aria-label", LABEL);
    btn.title = LABEL;
    btn.classList.toggle("off", !on);
  }

  function mount(doc, bridge, win) {
    const btn = doc && typeof doc.getElementById === "function" ? doc.getElementById("rc-toggle") : null;
    if (!btn) {
      return;
    }
    const b = bridge && typeof bridge === "object" ? bridge : null;
    const send = (action) => {
      try {
        if (b && typeof b.send === "function") {
          b.send(action);
        }
      } catch (_e) {
        // no bridge (plain browser preview) - best effort
      }
    };
    const raf =
      win && typeof win.requestAnimationFrame === "function"
        ? (fn) => win.requestAnimationFrame(fn)
        : (fn) => setTimeout(fn, 16);

    render(btn, true);
    try {
      if (b && typeof b.getState === "function") {
        Promise.resolve(b.getState())
          .then((s) => render(btn, s && s.visible))
          .catch(() => {});
      }
      if (b && typeof b.onState === "function") {
        b.onState((s) => render(btn, s && s.visible));
      }
    } catch (_e) {
      // bridge hiccup - keep the default ON render
    }

    let down = false;
    let pending = false;

    btn.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) {
        return; // primary button only; a right-click never toggles
      }
      down = true;
      try {
        btn.setPointerCapture(e.pointerId);
      } catch (_e) {
        // pointer already gone - harmless
      }
      if (typeof e.preventDefault === "function") {
        e.preventDefault();
      }
      btn.classList.add("pressing");
      send("press");
    });
    // A drag streams pointermoves; coalesce to one bridge message per frame.
    btn.addEventListener("pointermove", () => {
      if (!down || pending) {
        return;
      }
      pending = true;
      raf(() => {
        pending = false;
        if (down) {
          btn.classList.add("dragging");
          send("move");
        }
      });
    });
    const end = (action) => () => {
      if (!down) {
        return; // already ended (lostpointercapture follows a normal pointerup)
      }
      down = false;
      btn.classList.remove("pressing");
      btn.classList.remove("dragging");
      send(action);
    };
    btn.addEventListener("pointerup", end("release"));
    btn.addEventListener("pointercancel", end("cancel"));
    btn.addEventListener("lostpointercapture", end("cancel"));
    // Keyboard twin (the window is focusable:false, so this only matters if a
    // future build lets it take focus; the in-game key path is Ctrl+Shift+O).
    btn.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        if (typeof e.preventDefault === "function") {
          e.preventDefault();
        }
        send("activate");
      }
    });
  }

  return { LABEL, render, mount };
});
