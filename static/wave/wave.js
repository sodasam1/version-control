"use strict";
// Wave: draw and scrub a waveform on a <canvas class="wave">. Colours come from the CSS variables --accent (played part) and --muted
// (unplayed), so it follows light/dark and the accent choice. Lifted from riffbox's transport.js, made reusable.
//
//   <canvas class="wave" data-peaks="0,12,200,255,..."></canvas>        peaks: integers 0-255, from the server (kitaudio)
//   const w = Wave.attach(canvas, { peaks, duration, onSeek(seconds), onLoop(a, b) });
//   w.set({ time: 12.5, loop: {a: 4, b: 9, on: true}, marks: [{t: 3.2}, ...] });    // redraw with new state
// Shift-drag (or Alt-drag) selects a loop region A-B; a plain click or drag seeks. Arrow keys seek 5 s, Shift+arrow 1 s.
window.Wave = (function () {
  let colors = null;
  function css() {
    if (!colors) {
      const s = getComputedStyle(document.documentElement);
      colors = { accent: s.getPropertyValue("--accent").trim() || "#c8400b", muted: s.getPropertyValue("--muted").trim() || "#888" };
    }
    return colors;
  }
  const reset = () => { colors = null; };
  document.addEventListener("themechange", () => { reset(); document.querySelectorAll("canvas.wave").forEach((c) => c._wave && c._wave.draw()); });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { reset(); document.querySelectorAll("canvas.wave").forEach((c) => c._wave && c._wave.draw()); });

  function attach(canvas, opts) {
    opts = opts || {};
    const st = { peaks: opts.peaks || [], duration: opts.duration || 0, time: 0, loop: null, marks: [] };
    const ctx = canvas.getContext("2d");

    function draw() {
      const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
      if (!w || !h) return;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
      const { accent, muted } = css();
      const total = st.duration, progress = total > 0 ? Math.min(1, st.time / total) : 0;
      if (st.peaks.length) {
        const n = st.peaks.length, barW = w / n;
        for (let i = 0; i < n; i++) {
          const bh = Math.max(2, Math.pow(st.peaks[i] / 255, 0.75) * (h - 10)), played = (i + 0.5) / n <= progress;
          ctx.globalAlpha = played ? 1 : 0.55; ctx.fillStyle = played ? accent : muted;
          ctx.fillRect(i * barW + 0.5, (h - bh) / 2, Math.max(1, barW - 1), bh);
        }
      } else {
        ctx.globalAlpha = 0.55; ctx.fillStyle = muted; ctx.fillRect(0, h / 2 - 1, w, 2);
        ctx.globalAlpha = 1; ctx.fillStyle = accent; ctx.fillRect(0, h / 2 - 1, w * progress, 2);
      }
      ctx.globalAlpha = 1; ctx.fillStyle = accent;
      if (st.loop && total > 0) {
        const a = (st.loop.a / total) * w, b = ((st.loop.b == null ? st.loop.a : st.loop.b) / total) * w;
        if (st.loop.b != null) { ctx.globalAlpha = st.loop.on ? 0.22 : 0.1; ctx.fillRect(a, 0, b - a, h); }
        ctx.globalAlpha = 1; ctx.fillRect(a - 1, 0, 2, h); if (st.loop.b != null) ctx.fillRect(b - 1, 0, 2, h);
      }
      for (const m of st.marks) if (total > 0) { ctx.globalAlpha = 0.9; ctx.fillRect((m.t / total) * w - 1, 0, 2, 6); }
      ctx.globalAlpha = 1;
      if (total > 0) ctx.fillRect(progress * w - 1, 0, 2, h);
      canvas.setAttribute("aria-valuenow", String(Math.round(st.time)));
    }

    function at(ev) { const r = canvas.getBoundingClientRect(); return Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width)) * st.duration; }
    let drag = null, touch = null;
    // A finger must not be trapped by the waveform: it may be scrolling the page. touch-action pan-y leaves vertical drags to the browser (it then sends
    // pointercancel); a tap seeks when the finger lifts; a mostly horizontal drag scrubs. A mouse or pen seeks on press, as before.
    canvas.style.touchAction = "pan-y";
    canvas.addEventListener("pointerdown", (ev) => {
      if (!st.duration) return;
      if (ev.pointerType === "touch") { touch = { id: ev.pointerId, x: ev.clientX, y: ev.clientY, scrub: false, moved: false }; return; }
      canvas.setPointerCapture(ev.pointerId);
      drag = { loop: ev.shiftKey || ev.altKey, start: at(ev) };
      if (!drag.loop && opts.onSeek) opts.onSeek(drag.start);
    });
    canvas.addEventListener("pointermove", (ev) => {
      if (touch && ev.pointerId === touch.id) {
        const dx = Math.abs(ev.clientX - touch.x), dy = Math.abs(ev.clientY - touch.y);
        if (dx > 10 || dy > 10) touch.moved = true;                                    // past the tap slop: no longer a tap
        if (!touch.scrub && dx > 8 && dx > dy) { touch.scrub = true; canvas.setPointerCapture(ev.pointerId); }
        if (touch.scrub && opts.onSeek) opts.onSeek(at(ev));
        return;
      }
      if (!drag) return;
      const t = at(ev);
      if (drag.loop) { const a = Math.min(drag.start, t), b = Math.max(drag.start, t); st.loop = { a, b, on: true }; draw(); }
      else if (opts.onSeek) opts.onSeek(t);
    });
    const end = (ev) => {
      if (touch && ev && ev.pointerId === touch.id) {
        if (ev.type === "pointerup" && !touch.scrub && !touch.moved && opts.onSeek) opts.onSeek(at(ev));     // a tap
        touch = null;
        return;
      }
      if (drag && drag.loop && st.loop && opts.onLoop) opts.onLoop(st.loop.a, st.loop.b);
      drag = null;
    };
    canvas.addEventListener("pointerup", end); canvas.addEventListener("pointercancel", end);
    canvas.tabIndex = 0; canvas.setAttribute("role", "slider"); canvas.setAttribute("aria-label", opts.label || "Waveform: seek");
    canvas.setAttribute("aria-valuemin", "0");
    canvas.addEventListener("keydown", (ev) => {
      const step = ev.shiftKey ? 1 : 5;
      if (ev.key === "ArrowRight" && opts.onSeek) { ev.preventDefault(); opts.onSeek(Math.min(st.duration, st.time + step)); }
      if (ev.key === "ArrowLeft" && opts.onSeek) { ev.preventDefault(); opts.onSeek(Math.max(0, st.time - step)); }
    });
    if (window.ResizeObserver) new ResizeObserver(draw).observe(canvas);

    const api = {
      draw,
      set(p) {
        if (p.peaks) st.peaks = p.peaks; if (p.duration != null) { st.duration = p.duration; canvas.setAttribute("aria-valuemax", String(Math.round(p.duration))); }
        if (p.time != null) st.time = p.time; if ("loop" in p) st.loop = p.loop; if (p.marks) st.marks = p.marks;
        draw();
      },
    };
    canvas._wave = api;
    draw();
    return api;
  }

  // canvases with data-peaks (server-rendered lists and share pages) draw themselves, no extra request
  function auto() {
    document.querySelectorAll("canvas.wave[data-peaks]").forEach((c) => {
      if (c._wave) return;
      const peaks = c.dataset.peaks ? c.dataset.peaks.split(",").map(Number) : [];
      attach(c, { peaks, duration: Number(c.dataset.duration) || 0 });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", auto); else auto();
  return { attach, auto };
})();
