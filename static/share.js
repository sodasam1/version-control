"use strict";
// The page someone sees when you send them a link: listen, switch between versions, leave a comment.
(function () {
  const root = document.getElementById("root"), app = document.getElementById("app");
  const base = app.dataset.base, token = app.dataset.token, url = base + "/s/" + token;
  const headers = () => ({ "X-Commenter-Key": window.Panel.commenterKey() });
  async function call(path, method, body) {
    const r = await fetch(url + path, { method, credentials: "same-origin", headers: { "Content-Type": "application/json", ...headers() }, body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(r.status === 429 ? "You are commenting too fast. Try again in a few minutes." : data.error || "Something went wrong (" + r.status + ")");
    return data;
  }
  (async () => {
    let data;
    try { data = await call("/data", "GET"); } catch (e) { root.textContent = "This link is not available."; return; }
    if (data.song.notes) root.append(window.Panel.h("p", { class: "muted notes" }, data.song.notes));
    const holder = window.Panel.h("div", { class: "hero track" });
    root.append(holder);
    app._panel = window.Panel.create(holder, {   // kept on the element so the browser test can look at the player
      title: data.song.title, meta: data.versions.length + (data.versions.length === 1 ? " version" : " versions") + (data.versions.length ? " \u00b7 latest: " + data.versions[data.versions.length - 1].label : ""),
      versions: data.versions, comments: data.comments, allowComments: data.allow_comments, ownerView: data.owner,
      api: { post: (b) => call("/comments", "POST", b), edit: (id, body) => call("/comments/" + id, "PATCH", { body }), del: (id) => call("/comments/" + id, "DELETE") },
    });
  })();
})();
