"use strict";
// Compare: plays several versions of one song in lockstep so you can switch between them instantly, loop a section and keep switching,
// and match their loudness. Standard browser parts only (media elements + Web Audio gain nodes).
//
// How it works. Every version has its own <audio> element, all started together and kept in step (drift above 30 ms is corrected every
// quarter second). Each element feeds its own GainNode; only the chosen version has gain 1, the rest 0. Switching changes the gains with a
// ~10 ms ramp, so there is no gap and no click. Per-version `offset_ms` lines up files that start at different moments.
// Looping: the default checks the position every 15 ms and jumps back to A at B (about 20-50 ms of slack). "Exact loop" (precision mode)
// instead downloads the loop region of every version (at most 30 s) as WAV, decodes it, and loops all of them sample-locked.
// Loudness match: the louder versions are turned DOWN to the quietest one's integrated loudness (never boosted, so nothing clips).
// If the browser refuses to play several elements at once (some phones), it falls back to "swap" mode: one element, switching reloads
// the other version at the same position (a short gap).
window.Compare = (function () {
  const MAX_EXACT_S = 30;
  const RAMP = 0.003;                       // seconds: time constant of the gain change (~10 ms to settle)

  function Compare(versions, handlers) {
    this.v = versions;
    this.h = handlers || {};
    this.active = 0;
    this.playing = false;
    this.loop = null;                       // {a, b, on}
    this.match = false;
    this.exact = false;
    this.mode = "sync";                     // "sync" | "swap"
    this.ctx = null;
    this.els = [];
    this.gains = [];
    this.bufs = null;                       // exact loop: AudioBuffer per version
    this.srcs = null;
    this.anchor = null;                     // exact loop: {ctxTime, pos}
    this.timer = null;
    this.pausedPos = 0;
    this.version = 0;                       // bumped by every start so a late async step knows it was superseded
  }
  const P = Compare.prototype;

  P._emit = function () { if (this.h.onState) this.h.onState(this.state()); };
  P.state = function () { return { active: this.active, playing: this.playing, loop: this.loop, match: this.match, exact: this.exact, mode: this.mode }; };
  P.off = function (i) { return (this.v[i].offset_ms || 0) / 1000; };
  P.duration = function () { return Math.max(0, ...this.v.map((x) => x.duration || 0)); };

  P._ensure = function () {
    if (this.ctx) { if (this.ctx.state === "suspended") this.ctx.resume(); return; }
    const AC = window.AudioContext || window.webkitAudioContext;
    this.ctx = new AC();
    this.v.forEach((ver, i) => {
      const el = new Audio();
      el.preload = "auto"; el.src = ver.audio;
      el.addEventListener("ended", () => { if (i === this.active && this.mode === "sync" && !this._loopActive()) this._ended(); });
      this.els.push(el);
      const g = this.ctx.createGain();
      g.gain.value = 0;
      this.ctx.createMediaElementSource(el).connect(g);
      g.connect(this.ctx.destination);
      this.gains.push(g);
    });
    this._applyGains(true);
  };

  P._level = function (i) {
    if (!this.match) return 1;
    const l = this.v.map((x) => x.lufs).filter((x) => typeof x === "number");
    if (typeof this.v[i].lufs !== "number" || !l.length) return 1;
    return Math.pow(10, (Math.min(...l) - this.v[i].lufs) / 20);
  };
  P._applyGains = function (instant) {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.gains.forEach((g, i) => { const v = i === this.active ? this._level(i) : 0; if (instant) g.gain.setValueAtTime(v, t); else g.gain.setTargetAtTime(v, t, RAMP); });
  };

  P._loopActive = function () { return !!(this.loop && this.loop.on && this.loop.b != null && this.loop.b > this.loop.a); };

  // position in song time (the active version's own clock minus its offset)
  P.position = function () {
    if (this.srcs && this.anchor) {
      const len = this.loop.b - this.loop.a, e = Math.max(0, this.ctx.currentTime - this.anchor.ctxTime);
      return this.loop.a + (((this.anchor.pos - this.loop.a) + e) % len);
    }
    if (!this.els.length) return this.pausedPos;
    return Math.max(0, this.els[this.active].currentTime - this.off(this.active));
  };

  P._seekEls = function (t) { this.els.forEach((el, i) => { try { el.currentTime = Math.max(0, t + this.off(i)); } catch (e) { /* not loaded yet */ } }); };

  P.seek = function (t) {
    t = Math.max(0, Math.min(t, this.duration() || t));
    this.pausedPos = t;
    if (this.srcs) { this._stopExact(); if (this.playing) this._startExact(t); return; }
    if (this.mode === "swap") { if (this.els[0]) this.els[0].currentTime = t + this.off(this.active); return; }
    if (this.els.length) this._seekEls(t);
  };

  P.play = async function () {
    this._ensure();
    const myVersion = ++this.version;
    const t = this.pausedPos;
    this.playing = true;
    if (this._loopActive() && this.exact) { await this._startExact(t); this._emit(); this._tick(); return; }
    if (this.mode === "swap") { await this._swapPlay(t); this._emit(); this._tick(); return; }
    this._seekEls(t);
    try { await Promise.all(this.els.map((el) => el.play())); } catch (e) { this._fallbackToSwap(); await this._swapPlay(t); }
    if (myVersion !== this.version) return;
    setTimeout(() => { if (this.playing && this.mode === "sync" && this.els.some((el, i) => el.paused && !el.ended)) { const p = this.position(); this._fallbackToSwap(); this._swapPlay(p); } }, 800);
    this._emit(); this._tick();
  };

  P.pause = function () {
    this.pausedPos = this.position();
    this.playing = false;
    this.version++;
    this._stopExact();
    this.els.forEach((el) => el.pause());
    clearInterval(this.timer); this.timer = null;
    this._emit();
  };
  P.toggle = function () { return this.playing ? this.pause() : this.play(); };
  P._ended = function () { this.playing = false; this.pausedPos = 0; this.els.forEach((el) => el.pause()); this._seekEls(0); clearInterval(this.timer); this.timer = null; this._emit(); };

  P._tick = function () {
    clearInterval(this.timer);
    let n = 0;
    this.timer = setInterval(() => {
      if (!this.playing) return;
      const pos = this.position();
      if (this.h.onTime) this.h.onTime(pos);
      if (this.srcs) return;                                         // exact loop: the sources loop by themselves
      if (this._loopActive() && pos >= this.loop.b - 0.005) { this.seek(this.loop.a); return; }
      if (this.mode === "sync" && (++n % 16) === 0) {                // every ~250 ms: keep the silent versions in step
        this.els.forEach((el, i) => {
          if (i === this.active) return;
          const want = pos + this.off(i);
          if (Math.abs(el.currentTime - want) > 0.03) el.currentTime = Math.max(0, want);
        });
      }
    }, 15);
  };

  // ---- switching ---------------------------------------------------------------------------------------------------
  P.select = async function (i) {
    if (i < 0 || i >= this.v.length || i === this.active) return;
    const pos = this.position();
    this.active = i;
    if (this.mode === "swap" && this.els[0]) { await this._swapPlay(pos, !this.playing); }
    else {
      if (this.els.length && !this.srcs) { const el = this.els[i], want = pos + this.off(i); if (Math.abs(el.currentTime - want) > 0.02) el.currentTime = Math.max(0, want); }
      this._applyGains(false);
    }
    this._emit();
  };

  P.setMatch = function (on) { this.match = !!on; this._applyGains(false); this._emit(); };

  // ---- looping ---------------------------------------------------------------------------------------------------------
  P.setLoop = async function (a, b, on) {
    const was = this.playing, pos = this.position();
    this.loop = { a: Math.max(0, a), b: b == null ? null : Math.max(a, b), on: on !== false };
    if (this.exact) await this._rebuildExact(was, pos);
    this._emit();
  };
  P.clearLoop = async function () {
    const was = this.playing, pos = this.position();
    this._stopExact(); this.loop = null;
    if (was) { this.pausedPos = pos; await this.play(); }
    this._emit();
  };
  P.setLoopOn = async function (on) { if (this.loop) { const was = this.playing, pos = this.position(); this.loop.on = !!on; if (this.exact) await this._rebuildExact(was, pos); else if (!on) this._stopExact(); this._emit(); } };
  P.setExact = async function (on) {
    this.exact = !!on;
    if (!on) { const was = this.playing, pos = this.position(); this._stopExact(); this.bufs = null; if (was) { this.pausedPos = pos; await this.play(); } }
    else if (this._loopActive()) await this._rebuildExact(this.playing, this.position());
    this._emit();
  };
  P.exactAllowed = function () { return this._loopActive() && this.loop.b - this.loop.a <= MAX_EXACT_S; };

  P._rebuildExact = async function (was, pos) {
    this._stopExact(); this.bufs = null;
    if (!this.exactAllowed()) { if (was) { this.pausedPos = pos; this.els.forEach((el) => el.pause()); await this.play(); } return; }
    this._ensure();
    this.els.forEach((el) => el.pause());
    try {
      const { a, b } = this.loop;
      this.bufs = await Promise.all(this.v.map(async (ver, i) => {
        const url = ver.slice + (ver.slice.includes("?") ? "&" : "?") + "start=" + Math.max(0, a + this.off(i)).toFixed(4) + "&end=" + (b + this.off(i)).toFixed(4) + "&bits=24";
        const r = await fetch(url, { credentials: "same-origin" });
        if (!r.ok) throw new Error("slice " + r.status);
        return this.ctx.decodeAudioData(await r.arrayBuffer());
      }));
    } catch (e) { this.bufs = null; this.exact = false; if (this.h.onError) this.h.onError("Exact loop is not available here (" + e.message + "); using the normal loop."); }
    if (was) { this.pausedPos = Math.min(Math.max(pos, this.loop.a), this.loop.b); this.playing = true; if (this.bufs) await this._startExact(this.pausedPos); else await this.play(); }
  };

  P._startExact = async function (pos) {
    if (!this.bufs) return;
    this._stopExact();
    const { a, b } = this.loop, start = Math.min(Math.max(pos, a), b - 0.01);
    const when = this.ctx.currentTime + 0.05;
    this.srcs = this.bufs.map((buf, i) => {
      const s = this.ctx.createBufferSource();
      s.buffer = buf; s.loop = true; s.loopStart = 0; s.loopEnd = buf.duration;
      s.connect(this.gains[i]);
      s.start(when, start - a);
      return s;
    });
    this.anchor = { ctxTime: when, pos: start };
    this._applyGains(true);
  };
  P._stopExact = function () {
    if (this.srcs) for (const s of this.srcs) { try { s.stop(); } catch (e) { /* already stopped */ } try { s.disconnect(); } catch (e) { /* ok */ } }
    this.srcs = null; this.anchor = null;
  };

  // ---- swap mode (phones that will not play several elements at once) --------------------------------------------
  P._fallbackToSwap = function () {
    this.mode = "swap";
    this.els.forEach((el, i) => { if (i > 0) el.pause(); });
    if (this.h.onError) this.h.onError("This device cannot play several versions at once, so switching will pause briefly.");
  };
  P._swapPlay = async function (pos, keepPaused) {
    const el = this.els[0];
    if (!el) return;
    this.gains.forEach((g, i) => g.gain.setValueAtTime(i === 0 ? this._level(this.active) : 0, this.ctx.currentTime));
    el.src = this.v[this.active].audio;
    await new Promise((res) => { el.addEventListener("loadedmetadata", res, { once: true }); el.load(); });
    el.currentTime = Math.max(0, pos + this.off(this.active));
    if (!keepPaused) await el.play().catch(() => {});
  };

  P.debug = function () {
    return { active: this.active, mode: this.mode, playing: this.playing, exact: this.exact, loop: this.loop, position: this.position(),
             gains: this.gains.map((g) => Math.round(g.gain.value * 1000) / 1000), times: this.els.map((e) => e.currentTime), paused: this.els.map((e) => e.paused) };
  };
  P.destroy = function () { this.pause(); this.els.forEach((el) => { el.removeAttribute("src"); el.load(); }); if (this.ctx) this.ctx.close(); };
  return Compare;
})();
