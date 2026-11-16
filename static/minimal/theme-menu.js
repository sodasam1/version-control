"use strict";
// Optional: fills <div id="theme-menu"></div> with Colors (Auto/Light/Dark) and Accent swatches. Needs theme.js and minimal.css.
(function () {
  const host = document.getElementById("theme-menu");
  if (!host) return;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
  };
  const root = document.documentElement;
  function button(label, pressed, onclick, extra) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = label; b.setAttribute("aria-pressed", pressed ? "true" : "false");
    if (extra) for (const k in extra) b.setAttribute(k, extra[k]);
    b.addEventListener("click", onclick);
    return b;
  }
  function render() {
    host.textContent = "";
    const colors = root.dataset.colors || "auto";
    const accent = root.dataset.accent || "blue";
    const g1 = document.createElement("div"); g1.className = "theme-row"; g1.setAttribute("role", "group"); g1.setAttribute("aria-label", "Colors");
    for (const c of ["auto", "light", "dark"]) {
      g1.appendChild(button(c[0].toUpperCase() + c.slice(1), colors === c, () => {
        if (c === "auto") delete root.dataset.colors; else root.dataset.colors = c;
        store.set("site.colors", c); render(); document.dispatchEvent(new Event("themechange"));
      }));
    }
    const g2 = document.createElement("div"); g2.className = "accent-row"; g2.setAttribute("role", "group"); g2.setAttribute("aria-label", "Accent");
    for (const a of ["blue", "teal", "green", "purple", "pink", "ink", "orange"]) {
      const b = button("", accent === a, () => {
        root.dataset.accent = a; store.set("site.accent", a); render(); document.dispatchEvent(new Event("themechange"));
      }, { "data-a": a, "aria-label": a });
      g2.appendChild(b);
    }
    host.append(g1, g2);
  }
  render();
})();
