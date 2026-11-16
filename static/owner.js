"use strict";
// The owner's page: songs, their versions, share links, comments, backup. Everything user-written is set with textContent.
(function () {
  const { h, fmt } = window.Panel;
  const $ = (s, r) => (r || document).querySelector(s);
  let tab = "songs", songId = null, panel = null, poll = null;

  const notice = (m) => { const n = $("#notice"); n.textContent = m || ""; n.hidden = !m; };
  async function api(path, opts) {
    const r = await fetch("api/" + path, { credentials: "same-origin", ...opts });
    if (r.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); throw new Error("signed out"); }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "error " + r.status);
    return data;
  }
  const send = (path, method, body) => api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  async function run(fn) { try { notice(""); await fn(); } catch (e) { if (e.message !== "signed out") notice(e.message); } }
  const full = (p) => location.origin + p;
  const size = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB");

  function tabs() {
    const nav = $("#tabs"); nav.textContent = "";
    for (const [k, label] of [["songs", "Songs"], ["archive", "Archive"], ["backup", "Backup"]]) {
      nav.append(h("button", { type: "button", "aria-pressed": String(tab === k && !songId), onclick: () => { tab = k; songId = null; history.replaceState(null, "", "#"); run(render); } }, label));
    }
  }

  async function render() {
    if (panel) { panel.destroy(); panel = null; }
    clearInterval(poll);
    tabs();
    const main = $("#main"); main.textContent = "";
    if (songId) return renderSong(main);
    if (tab === "backup") return renderBackup(main);
    const songs = await api("songs" + (tab === "archive" ? "?archived=1" : ""));
    if (tab === "songs") main.append(h("div", { class: "actions" }, h("button", { class: "primary", type: "button", onclick: () => run(async () => {
      const title = prompt("Song title"); if (!title) return; const s = await send("songs", "POST", { title }); open(s.id); }) }, "New song")));
    if (!songs.length) main.append(h("p", { class: "muted" }, tab === "songs" ? "No songs yet." : "Nothing archived."));
    for (const s of songs) {
      main.append(h("div", { class: "row song-row", tabindex: "0", role: "button", onclick: () => open(s.id), onkeydown: (e) => { if (e.key === "Enter") open(s.id); } },
        h("div", { class: "grow" }, h("div", { class: "title" }, s.title),
          h("div", { class: "muted small" }, [s.version_count + " version(s)", s.latest_label ? "latest " + s.latest_label : "", s.comment_count + " comment(s)", s.created_at.slice(0, 10)].filter(Boolean).join(" · ")))));
    }
  }
  function open(id) { songId = id; history.replaceState(null, "", "#song=" + id); run(render); }

  async function renderSong(main) {
    const s = await api("songs/" + songId);
    main.append(h("div", { class: "actions" }, h("button", { type: "button", onclick: () => { songId = null; history.replaceState(null, "", "#"); run(render); } }, "← All songs")),
      h("h2", null, s.title), s.notes ? h("p", { class: "muted notes" }, s.notes) : null,
      h("div", { class: "actions" },
        h("button", { type: "button", onclick: () => run(async () => { const title = prompt("Title", s.title); if (title == null) return; const notes = prompt("Notes (optional)", s.notes); await send("songs/" + s.id, "PATCH", { title, notes: notes == null ? s.notes : notes }); await render(); }) }, "Rename"),
        s.archived
          ? h("button", { type: "button", onclick: () => run(async () => { await send(`songs/${s.id}/unarchive`, "POST"); await render(); }) }, "Unarchive")
          : h("button", { type: "button", onclick: () => run(async () => { await send(`songs/${s.id}/archive`, "POST"); songId = null; await render(); }) }, "Archive"),
        h("button", { type: "button", onclick: () => run(async () => { const typed = prompt("This deletes the song, every version's audio and all comments, forever. Type the exact title to confirm:\n\n" + s.title); if (typed == null) return; await send("songs/" + s.id, "DELETE", { confirm: typed }); songId = null; await render(); }) }, "Delete forever")));

    // compare panel
    const holder = h("div", { class: "panel-box" });
    main.append(holder);
    panel = holder._panel = window.Panel.create(holder, { versions: s.versions, comments: s.comments, allowComments: true, ownerView: true,
      api: { post: (b) => send(`songs/${s.id}/comments`, "POST", { body: b.body, t_ms: b.t_ms, version_id: b.version_id }), edit: () => Promise.reject(new Error("not editable")), del: (id) => send("comments/" + id, "DELETE") } });

    // versions
    main.append(h("h2", null, "Versions"));
    const file = h("input", { type: "file", accept: "audio/*,.wav,.flac,.mp3,.m4a,.ogg,.aac,.aif,.aiff,.caf", "aria-label": "Audio file" });
    const label = h("input", { type: "text", placeholder: "Label (default v" + (s.versions.length + 1) + ")", maxlength: "80", "aria-label": "Label" });
    const note = h("input", { type: "text", placeholder: "Note (optional)", maxlength: "2000", "aria-label": "Note" });
    main.append(h("div", { class: "vrow" }, file, label, note, h("div", { class: "actions" }, h("button", { class: "primary", type: "button", onclick: () => run(async () => {
      if (!file.files.length) throw new Error("Choose an audio file first.");
      notice("Uploading… (a large file can take a while)");
      const fd = new FormData(); fd.append("file", file.files[0]); fd.append("label", label.value); fd.append("note", note.value);
      const r = await fetch(`api/songs/${s.id}/versions`, { method: "POST", body: fd, credentials: "same-origin" });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.error || "Upload failed (" + r.status + ")");
      notice("Uploaded. The waveform and loudness are measured in the background."); await render(); }) }, "Upload new version"))));
    for (const v of s.versions) {
      const off = h("input", { type: "text", value: String(v.offset_ms), size: "6", "aria-label": "Offset in milliseconds" });
      const state = v.analysis_status === "pending" ? "measuring…" : v.analysis_status === "failed" ? "could not be measured" : "";
      main.append(h("div", { class: "vrow" },
        h("div", null, h("strong", null, v.label), " ", h("span", { class: "muted small" }, [fmt(v.duration), size(v.size), v.sample_rate ? v.sample_rate / 1000 + " kHz" : "", v.channels ? v.channels + " ch" : "", v.codec || "",
          typeof v.lufs === "number" ? v.lufs.toFixed(1) + " LUFS" : "", state].filter(Boolean).join(" · "))),
        v.note ? h("div", { class: "muted notes" }, v.note) : null,
        h("div", { class: "actions" },
          h("label", { class: "inline", title: "Shifts this version against the others, in milliseconds, so they line up when you switch" }, "Offset ms ", off),
          h("button", { type: "button", onclick: () => run(async () => { await send("versions/" + v.id, "PATCH", { offset_ms: Number(off.value) }); await render(); }) }, "Save offset"),
          h("button", { type: "button", onclick: () => run(async () => { const l = prompt("Label", v.label); if (l == null) return; const n = prompt("Note", v.note); await send("versions/" + v.id, "PATCH", { label: l, note: n == null ? v.note : n }); await render(); }) }, "Edit"),
          h("a", { class: "btn", href: v.audio + "?download=1" }, "Download"),
          h("button", { type: "button", onclick: () => run(async () => { const typed = prompt("This deletes this version's audio forever. Type its exact label to confirm:\n\n" + v.label); if (typed == null) return; await send("versions/" + v.id, "DELETE", { confirm: typed }); await render(); }) }, "Delete forever"))));
    }
    if (s.versions.some((v) => v.analysis_status === "pending")) poll = setInterval(() => run(render), 4000);

    // links
    main.append(h("h2", null, "Share links"), h("p", { class: "muted small" }, "Anyone with a link can listen and comment (if you allow it). No account. Make one link per person to know who opened what."));
    const who = h("input", { type: "text", placeholder: "Who is it for? (your note)", maxlength: "80", "aria-label": "Link label" });
    const allow = h("input", { type: "checkbox", checked: true, id: "newallow" });
    const mode = h("select", { "aria-label": "Versions to show" }, h("option", { value: "all" }, "All versions"), h("option", { value: "latest" }, "Latest version only"));
    main.append(h("div", { class: "lrow" }, who, h("div", { class: "actions" }, h("label", { class: "inline", for: "newallow" }, allow, " Allow comments"), mode,
      h("button", { class: "primary", type: "button", onclick: () => run(async () => { await send(`songs/${s.id}/links`, "POST", { label: who.value, allow_comments: allow.checked, versions_mode: mode.value }); await render(); }) }, "Create link"))));
    for (const l of s.links) {
      const opened = l.open_count ? "opened " + l.open_count + "x, last " + (l.last_opened_at || "").slice(0, 10) : "not opened yet";
      main.append(h("div", { class: "lrow" },
        h("div", null, h("strong", null, l.label || "(no label)"), " ", h("span", { class: "muted small" }, [l.allow_comments ? "comments on" : "comments off", l.versions_mode === "latest" ? "latest only" : "all versions", opened].join(" · "))),
        h("div", { class: "actions" },
          h("button", { type: "button", onclick: () => run(async () => { await navigator.clipboard.writeText(full(l.url)); notice("Link copied."); }) }, "Copy link"),
          h("a", { class: "btn", href: l.url, target: "_blank", rel: "noopener" }, "Open"),
          h("button", { type: "button", onclick: () => run(async () => { await send("links/" + l.id, "PATCH", { allow_comments: !l.allow_comments }); await render(); }) }, l.allow_comments ? "Turn comments off" : "Turn comments on"),
          h("button", { type: "button", onclick: () => run(async () => { await send("links/" + l.id, "PATCH", { versions_mode: l.versions_mode === "all" ? "latest" : "all" }); await render(); }) }, l.versions_mode === "all" ? "Show latest only" : "Show all versions"),
          h("button", { type: "button", onclick: () => run(async () => { if (!confirm("Turn this link off for good? The song and its comments stay.")) return; await send("links/" + l.id, "DELETE"); await render(); }) }, "Turn off"))));
    }
  }

  async function renderBackup(main) {
    const b = await api("backup");
    if (!b.enabled) { main.append(h("p", { class: "muted" }, "No backup folder is set on the server (VERSIONCONTROL_BACKUP_DIR).")); return; }
    main.append(h("p", null, b.copies + " database copy(ies), newest: " + (b.newest || "none") + "; " + b.audio_files + " audio file(s) in the backup folder."),
      h("p", { class: "muted small" }, "On the server the backup folder shares the disk with your audio, so audio is hard-linked (no extra space; it survives \"Delete forever\"). It does not protect against losing the volume: also pull the folder to your computer."),
      h("button", { class: "primary", type: "button", onclick: () => run(async () => { const r = await send("backup", "POST"); notice("Backed up " + r.copy + ", " + r.audio_added + " new audio file(s)." + (r.problems.length ? " Problems: " + r.problems.join("; ") : "")); await render(); }) }, "Back up now"));
    if (b.restore && b.restore.ok) main.append(h("h2", null, "Restore"), h("p", null, "Found a backup with " + b.restore.songs + " song(s) and " + b.restore.versions + " version(s) in the restore folder. Restoring works only into an empty library."),
      h("button", { type: "button", onclick: () => run(async () => { const r = await send("restore", "POST"); notice("Restored " + r.versions + " version(s)." + (r.problems.length ? " Problems: " + r.problems.join("; ") : "")); tab = "songs"; await render(); }) }, "Restore from this folder"));
  }

  const m = /^#song=(\d+)$/.exec(location.hash);
  if (m) songId = Number(m[1]);
  run(render);
})();
