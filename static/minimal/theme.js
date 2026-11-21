"use strict";
// Load this in <head> (a separate file: the apps' CSP forbids inline scripts) so the chosen look is there from the first paint.
// Two choices, shared by every app on the site (same origin, same localStorage keys):
//   site.colors : "auto" (default, follows the device), "light", "dark"  -> <html data-colors="light|dark">
//   site.accent : blue (default, the same on every app of the site), teal, green, purple, pink, ink, orange   -> <html data-accent="...">
// There is one style (Minimal); it is the default look of the page, so there is no style switch.
try {
  const c = localStorage.getItem("site.colors") || localStorage.getItem("riffbox.colors");
  if (c === "light" || c === "dark") document.documentElement.dataset.colors = c;
  const a = localStorage.getItem("site.accent") || localStorage.getItem("riffbox.accent");
  if (a && /^[a-z]+$/.test(a)) document.documentElement.dataset.accent = a;
} catch (e) { /* storage blocked: device colours, default accent */ }
