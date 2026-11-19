"use strict";
// Panel: the listening screen shared by the owner's page and the share page: version buttons, waveform, transport, loop, loudness match,
// blind test, and the timestamped comments. Everything written by people goes on the page with textContent, never innerHTML.
window.Panel = (function () {
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const k in attrs || {}) {
      if (k === "class") el.className = attrs[k];
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== false && attrs[k] != null) el.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return el;
  }
  const fmt = (s) => { s = Math.max(0, s || 0); return Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0"); };
  const fmtMs = (ms) => fmt(ms / 1000);
  const parseTime = (txt) => { const m = /^\s*(\d+):(\d{1,2})(?:\.(\d+))?\s*$/.exec(txt) || /^\s*(\d+)\s*$/.exec(txt); if (!m) return null; return m[2] === undefined ? Number(m[1]) : Number(m[1]) * 60 + Number(m[2]) + (m[3] ? Number("0." + m[3]) : 0); };
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };
  function commenterKey() {
    let k = store.get("vc.key");
    if (!k || k.length < 16) { const a = new Uint8Array(16); crypto.getRandomValues(a); k = Array.from(a, (b) => b.toString(16).padStart(2, "0")).join(""); store.set("vc.key", k); }
    return k;
  }

  function create(root, o) {
    const versions = o.versions;
    root.textContent = "";
    if (!versions.length) { root.append(h("p", { class: "muted" }, "No versions yet.")); return { destroy() {} }; }
    let comments = (o.comments || []).slice();
    let blind = false, order = versions.map((_, i) => i);
    const compare = new window.Compare(versions, {
      onState: () => paint(), onTime: (t) => tick(t),
      onError: (m) => { msg.textContent = m; },
    });
    const msg = h("p", { class: "notice", role: "status" });
    msg.hidden = true;
    const setMsg = (m) => { msg.textContent = m || ""; msg.hidden = !m; };
    compare.h.onError = setMsg;

    // ---- versions ----
    const vbar = h("div", { class: "versions", role: "group", "aria-label": "Versions" });
    const label = (i) => (blind ? String.fromCharCode(65 + order.indexOf(i)) : versions[i].label);
    function drawVersionButtons() {
      vbar.textContent = "";
      const idx = blind ? order : versions.map((_, i) => i);
      idx.forEach((i, n) => {
        vbar.append(h("button", { type: "button", class: "ver", "data-i": String(i), "aria-pressed": String(compare.active === i), title: blind ? "" : versions[i].note || "",
          onclick: () => compare.select(i) }, h("span", { class: "key" }, String(n + 1)), " ", label(i)));
      });
    }

    // ---- waveform + transport ----
    const canvas = h("canvas", { class: "wave", "aria-label": "Waveform" });
    const playBtn = h("button", { type: "button", class: "play-btn big", "data-state": "play", "aria-label": "Play", onclick: () => compare.toggle() });
    const tNow = h("span", { class: "t t-now" }, "0:00"), tLen = h("span", { class: "t t-len" }, fmt(versions[0].duration));
    const head = h("div", { class: "track-head" }, playBtn, h("div", { class: "track-text" }, h("span", { class: "title" }, o.title || ""), o.meta ? h("div", { class: "track-meta" }, o.meta) : null));
    const loopLabel = h("span", { class: "muted small" });
    const setA = h("button", { type: "button", onclick: () => { const p = compare.position(); compare.setLoop(p, compare.loop && compare.loop.b != null && compare.loop.b > p ? compare.loop.b : null, true); } }, "Set A");
    const setB = h("button", { type: "button", onclick: () => { const p = compare.position(), a = compare.loop ? compare.loop.a : 0; if (p > a) compare.setLoop(a, p, true); } }, "Set B");
    const loopOn = h("input", { type: "checkbox", id: "loop-on", onchange: (e) => compare.setLoopOn(e.target.checked) });
    const clearLoop = h("button", { type: "button", onclick: () => compare.clearLoop() }, "Clear loop");
    const exact = h("input", { type: "checkbox", id: "loop-exact", onchange: (e) => compare.setExact(e.target.checked) });
    const match = h("input", { type: "checkbox", id: "match", onchange: (e) => compare.setMatch(e.target.checked) });
    const blindBox = h("input", { type: "checkbox", id: "blind", onchange: (e) => { blind = e.target.checked; if (blind) order = versions.map((_, i) => i).sort(() => Math.random() - 0.5); paint(); renderComments(); } });
    const wave = window.Wave.attach(canvas, { peaks: versions[0].peaks, duration: versions[0].duration, label: "Waveform: click to jump, Shift-drag to select a loop", onSeek: (t) => { compare.seek(t); tick(t); },
      onLoop: (a, b) => { if (b - a > 0.05) compare.setLoop(a, b, true); } });

    const fit = (p, n) => (p.length <= n ? p : Array.from({ length: n }, (_, i) => Math.max(...p.slice(Math.floor(i * p.length / n), Math.floor((i + 1) * p.length / n)))));
    const bars = (v) => fit(v.peaks, Math.max(24, Math.floor((canvas.clientWidth || 360) / 4)));
    if (window.ResizeObserver) new ResizeObserver(() => wave.set({ peaks: bars(versions[compare.active]) })).observe(canvas);
    function marks() { return comments.map((c) => ({ t: c.t_ms / 1000 })); }
    function tick(t) { wave.set({ time: t, marks: marks() }); tNow.textContent = fmt(t); highlight(t); }
    function paint() {
      const s = compare.state(), v = versions[s.active];
      drawVersionButtons();
      playBtn.dataset.state = s.playing ? "pause" : "play"; playBtn.setAttribute("aria-label", s.playing ? "Pause" : "Play");
      loopOn.checked = !!(s.loop && s.loop.on); loopOn.disabled = !s.loop;
      exact.checked = s.exact; exact.disabled = !compare.exactAllowed();
      match.checked = s.match; match.disabled = versions.every((x) => typeof x.lufs !== "number");
      loopLabel.textContent = s.loop ? "Loop " + fmt(s.loop.a) + (s.loop.b != null ? " to " + fmt(s.loop.b) : " from here (set B)") : "No loop. Shift-drag on the waveform, or use Set A / Set B.";
      wave.set({ peaks: bars(v), duration: v.duration, loop: s.loop ? { a: s.loop.a, b: s.loop.b, on: s.loop.on } : null, time: compare.position(), marks: marks() });
      tNow.textContent = fmt(compare.position()); tLen.textContent = fmt(v.duration);
    }
    const transport = h("div", { class: "transport" }, setA, setB, clearLoop);
    const waveBox = h("div", { class: "wave-box" }, canvas, tNow, tLen);
    const options = h("div", { class: "options" },
      h("label", { class: "inline", for: "loop-on" }, loopOn, " Loop"),
      h("label", { class: "inline", for: "loop-exact", title: "Downloads the looped section of every version (30 s at most) so they loop sample-locked" }, exact, " Exact loop"),
      h("label", { class: "inline", for: "match", title: "Turns the louder versions down to the quietest one, so loudness does not decide what sounds better" }, match, " Match loudness"),
      versions.length > 1 ? h("label", { class: "inline", for: "blind", title: "Hides the version names and shuffles their order" }, blindBox, " Blind") : null);

    // ---- comments ----
    const list = h("ol", { class: "comments" });
    const form = h("div", { class: "comment-form" });
    function renderComments() {
      list.textContent = "";
      if (!comments.length) list.append(h("li", { class: "muted" }, o.allowComments ? "No comments yet." : ""));
      for (const c of comments) {
        const vi = versions.findIndex((v) => v.id === c.version_id);
        const li = h("li", { "data-id": String(c.id), "data-t": String(c.t_ms / 1000) },
          h("button", { type: "button", class: "link stamp", title: "Jump here", onclick: () => { compare.seek(c.t_ms / 1000); tick(c.t_ms / 1000); } }, fmtMs(c.t_ms)),
          " ", h("strong", null, c.name), c.owner ? h("span", { class: "chip" }, "owner") : null,
          vi >= 0 && !blind && versions.length > 1 ? h("span", { class: "chip" }, versions[vi].label) : null,
          c.edited_at ? h("span", { class: "chip" }, "edited") : null,
          h("div", { class: "body" }, c.body));
        if (c.mine || o.ownerView) {
          li.append(h("div", { class: "actions" },
            c.mine ? h("button", { type: "button", class: "link", onclick: () => editComment(c) }, "Edit") : null,
            h("button", { type: "button", class: "link", onclick: () => removeComment(c) }, "Delete")));
        }
        list.append(li);
      }
      wave.set({ marks: marks() });
    }
    function highlight(t) {
      let cur = null;
      for (const li of list.children) { const lt = Number(li.dataset.t); if (lt <= t + 0.2) cur = li; li.classList.remove("now"); }
      if (cur && compare.playing) cur.classList.add("now");
    }
    async function editComment(c) {
      const next = prompt("Edit your comment", c.body);
      if (next == null || !next.trim()) return;
      try { const r = await o.api.edit(c.id, next); Object.assign(c, r); renderComments(); } catch (e) { setMsg(e.message); }
    }
    async function removeComment(c) {
      if (!confirm("Delete this comment?")) return;
      try { await o.api.del(c.id); comments = comments.filter((x) => x.id !== c.id); renderComments(); } catch (e) { setMsg(e.message); }
    }
    if (o.allowComments) {
      const name = h("input", { type: "text", maxlength: "40", placeholder: "Your name", "aria-label": "Your name", autocomplete: "nickname" });
      name.value = o.ownerView ? "" : store.get("vc.name") || "";
      if (o.ownerView) name.hidden = true;
      const when = h("input", { type: "text", class: "when", "aria-label": "Time in the song", value: "0:00", size: "6" });
      const body = h("textarea", { rows: "3", maxlength: "2000", placeholder: "A comment at this moment in the song…", "aria-label": "Comment" });
      const trap = h("input", { type: "text", name: "website", class: "trap", tabindex: "-1", autocomplete: "off", "aria-hidden": "true" });
      const useNow = h("button", { type: "button", class: "link", onclick: () => { when.value = fmt(compare.position()); } }, "use playhead");
      const post = h("button", { type: "button", class: "primary", onclick: async () => {
        const t = parseTime(when.value);
        if (t == null) { setMsg("Time should look like 1:23."); return; }
        if (!o.ownerView && !name.value.trim()) { setMsg("Please give your name."); name.focus(); return; }
        if (!body.value.trim()) { setMsg("Please write a comment."); body.focus(); return; }
        post.disabled = true; setMsg("");
        try {
          const c = await o.api.post({ name: name.value, body: body.value, t_ms: Math.round(t * 1000), version_id: versions[compare.active].id, website: trap.value, key: commenterKey() });
          if (!o.ownerView) store.set("vc.name", name.value.trim());
          comments.push(c); comments.sort((a, b) => a.t_ms - b.t_ms || a.id - b.id); body.value = ""; renderComments();
        } catch (e) { setMsg(e.message); } finally { post.disabled = false; }
      } }, "Post comment");
      form.append(name, h("div", { class: "row2" }, h("label", { class: "inline" }, "At ", when), useNow), body, trap, post);
      // typing a comment is a natural moment to freeze the time: pick up the playhead when the box gets focus
      body.addEventListener("focus", () => { if (when.value === "0:00" || !when.dataset.touched) when.value = fmt(compare.position()); });
      when.addEventListener("input", () => { when.dataset.touched = "1"; });
    }

    // ---- keys ----
    function onKey(e) {
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === " ") { e.preventDefault(); compare.toggle(); }
      else if (e.key >= "1" && e.key <= "9") { const n = Number(e.key) - 1, idx = blind ? order : versions.map((_, i) => i); if (idx[n] !== undefined) compare.select(idx[n]); }
      else if (e.key === "l" || e.key === "L") { if (compare.loop) compare.setLoopOn(!compare.loop.on); }
      else if (e.key === "m" || e.key === "M") { if (!match.disabled) compare.setMatch(!compare.match); }
    }
    document.addEventListener("keydown", onKey);

    root.append(head, vbar, waveBox, transport, loopLabel, options, msg,
      h("p", { class: "muted small" }, "Keys: space play/pause, 1-9 switch version, L loop, M match loudness."),
      h("h2", null, "Comments"), list, form);
    renderComments(); paint();
    return { compare, destroy() { document.removeEventListener("keydown", onKey); compare.destroy(); }, setComments(c) { comments = c; renderComments(); } };
  }
  return { create, h, fmt, fmtMs, commenterKey };
})();
