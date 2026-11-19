"""Version Control: songs with many versions, instant A/B comparison, loops, and timestamped comments from anyone holding a link.

Owner (site login):  /            the page you manage songs, versions and links from;  /api/...  its JSON
Anyone with a link:  /s/<token>   the song's page: listen, switch between versions, leave a comment (a name, no account)
                     /s/<token>/data, /comments, /audio/<version>, /slice/<version>
Every route is declared @public, @owner or @token; one with no declaration is owner-only (see siteauth).
"""
import gzip
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from flask import Blueprint, Flask, Response, abort, g, jsonify, redirect, render_template, request, send_file
from kitaudio import extras, media
from siteauth import SiteAuth
from siteauth.ratelimit import Limiter

from . import backup as backupmod
from . import db, jobs
from .config import settings

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'")
MIME = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".flac": "audio/flac", ".ogg": "audio/ogg",
        ".aac": "audio/aac", ".aif": "audio/aiff", ".aiff": "audio/aiff", ".caf": "audio/x-caf"}
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
LINE_CTRL = re.compile(r"[\x00-\x1f\x7f]")
MAX_TITLE, MAX_NOTES, MAX_LABEL, MAX_NAME, MAX_COMMENT = 200, 2000, 80, 40, 2000
EDIT_WINDOW = 15 * 60                    # a commenter can fix or remove their own comment for 15 minutes
MAX_SLICE_S = 60.0                       # precision-mode loop region, server-side cap
LOOPBACK = ("127.0.0.1", "::1")
TEXT_TYPES = ("text/css", "text/javascript", "application/javascript", "image/svg+xml", "text/html")


class Invalid(Exception):
    pass


def text(value, limit, field, required=False, multiline=False):
    if not isinstance(value, str):
        raise Invalid(f"{field} must be text")
    value = (CTRL if multiline else LINE_CTRL).sub(" ", value.replace("\r", "")).strip()
    if required and not value:
        raise Invalid(f"{field} cannot be empty")
    if len(value) > limit:
        raise Invalid(f"{field} can be at most {limit} characters")
    return value


def create_app(overrides=None):
    cfg = settings(overrides)
    app = Flask(__name__, static_folder=None, template_folder=str(Path(__file__).parent / "templates"))
    raw_base = cfg.get("VERSIONCONTROL_BASE_PATH", "").strip("/")
    base = "/" + raw_base if raw_base else ""
    data_dir = Path(cfg.get("VERSIONCONTROL_DATA_DIR", "/var/version-control"))
    static_dir = Path(cfg.get("VERSIONCONTROL_STATIC_DIR", str(Path(__file__).resolve().parents[2] / "static")))
    backup_dir = cfg.get("VERSIONCONTROL_BACKUP_DIR", "")
    restore_dir = cfg.get("VERSIONCONTROL_RESTORE_DIR", "/var/version-control-restore")
    owner_name = cfg.get("VERSIONCONTROL_OWNER_NAME", "Owner")
    ffmpeg = cfg["ffmpeg"] if "ffmpeg" in cfg else shutil.which("ffmpeg")
    ffprobe = cfg["ffprobe"] if "ffprobe" in cfg else shutil.which("ffprobe")
    app.config.update(MAX_CONTENT_LENGTH=int(cfg.get("VERSIONCONTROL_MAX_UPLOAD_MB", "1024")) * 1024 * 1024, TESTING=bool(cfg.get("TESTING")))
    # The big volume must be mounted, or audio would silently fill the small boot disk under an empty mount point.
    # The marker is normally the volume's own root file (VERSIONCONTROL_VOLUME_MARKER=/mnt/data/.volume-ok, shared by every app on the volume);
    # without that setting it is .volume-ok inside the data folder, as before.
    marker = Path(cfg.get("VERSIONCONTROL_VOLUME_MARKER") or (data_dir / ".volume-ok"))
    if cfg.get("VERSIONCONTROL_REQUIRE_VOLUME") == "1" and not marker.is_file():
        raise RuntimeError(f"{marker} is missing: the storage volume is probably not mounted. Refusing to start. (see RESTORE.html, storage steps)")
    os.umask(0o027)                                           # files this service creates (the database holds link secrets) are not readable by other users
    (data_dir / "audio").mkdir(mode=0o750, parents=True, exist_ok=True)
    (data_dir / "tmp").mkdir(mode=0o750, parents=True, exist_ok=True)
    # Werkzeug parks a big upload (up to VERSIONCONTROL_MAX_UPLOAD_MB, 1 GB by default) in a temp file while it parses the form. Keep that on the
    # data volume, not in the system /tmp on the small boot disk.
    tempfile.tempdir = str(data_dir / "tmp")
    db_path = data_dir / "versioncontrol.db"
    db.init(db_path)
    worker = jobs.Worker(data_dir, ffmpeg, ffprobe, inline=bool(cfg.get("JOBS_SYNC")))
    if not cfg.get("JOBS_SYNC"):
        worker.backfill()
    clock = cfg.get("clock") or time.time
    comment_limit = Limiter(clock, per_key_max=10, window=600)       # per client: 10 comments per 10 minutes
    slice_limit = Limiter(clock, per_key_max=30, window=600)
    slice_lock = threading.Semaphore(1)                               # one ffmpeg slice at a time

    auth = SiteAuth(app, name="versioncontrol", key_file=cfg.get("VERSIONCONTROL_SITE_KEY_FILE", "/etc/site-auth/keys/versioncontrol.key"),
                    cookie_path=base or "/", login_url=cfg.get("VERSIONCONTROL_SITE_LOGIN_URL", "/login"), clock=clock,
                    secure=cfg.get("VERSIONCONTROL_INSECURE_COOKIES") != "1", api_prefixes=(base + "/api/", base + "/s/"))
    bp = Blueprint("vc", __name__)

    def conn():
        if "db" not in g:
            g.db = db.connect(db_path)
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        c = g.pop("db", None)
        if c is not None:
            c.close()

    @app.before_request
    def start_timer():
        g.t0 = time.perf_counter()

    @app.after_request
    def timing_and_gzip(resp):
        """Server-Timing: how long this server spent on the request (browsers show it under Network > Timing), so a slow page can be told
        apart as "slow server/disk" or "slow network". Also gzip for JSON and HTML answers (the song data carries waveforms)."""
        t0 = g.get("t0")
        if t0 is not None:
            resp.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - t0) * 1000:.1f}"
        if (resp.status_code == 200 and not resp.direct_passthrough and resp.mimetype in ("application/json", "text/html")
                and "Content-Encoding" not in resp.headers and "gzip" in request.headers.get("Accept-Encoding", "")):
            body = resp.get_data()
            if len(body) > 1000:
                resp.set_data(gzip.compress(body, 5))
                resp.headers["Content-Encoding"] = "gzip"
                resp.vary.add("Accept-Encoding")
        return resp

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        rel = request.path[len(base):] if base and request.path.startswith(base) else request.path
        if rel.startswith("/s/"):
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        if resp.mimetype in ("application/json", "text/html"):
            resp.headers.setdefault("Cache-Control", "private, no-cache")
        return resp

    def err(message, status=400):
        return jsonify(error=message), status

    def client_key():
        addr = request.remote_addr or "?"
        if addr in LOOPBACK:
            last = request.headers.get("X-Forwarded-For", "").split(",")[-1].strip()
            if last:
                return last
        return addr

    def json_body():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise Invalid("send a JSON object")
        return body

    # ---- shapes -------------------------------------------------------------------------------------------------
    def version_public(v, token=None):
        d = {"id": v["id"], "label": v["label"], "note": v["note"], "duration": v["duration_s"] or 0, "peaks": json.loads(v["peaks"]) if v["peaks"] else [],
             "lufs": v["lufs"], "offset_ms": v["offset_ms"], "sample_rate": v["sample_rate"], "channels": v["channels"], "analysis_status": v["analysis_status"]}
        root = f"{base}/s/{token}" if token else f"{base}/api/versions/{v['id']}"
        d["audio"] = f"{root}/audio/{v['id']}" if token else f"{root}/audio"
        d["slice"] = f"{root}/slice/{v['id']}" if token else f"{root}/slice"
        return d

    def version_owner(v):
        d = version_public(v)
        d.update(created_at=v["created_at"], size=v["size"], orig_filename=v["orig_filename"], codec=v["codec"])
        return d

    def comment_dict(c, key_hash=None):
        return {"id": c["id"], "t_ms": c["t_ms"], "name": c["name"], "body": c["body"], "owner": bool(c["is_owner"]), "version_id": c["version_id"],
                "created_at": c["created_at"], "edited_at": c["edited_at"], "mine": bool(key_hash and c["key_hash"] == key_hash)}

    def link_dict(l):
        return {"id": l["id"], "token": l["token"], "label": l["label"], "allow_comments": bool(l["allow_comments"]), "versions_mode": l["versions_mode"],
                "created_at": l["created_at"], "url": f"{base}/s/{l['token']}", "open_count": l["open_count"], "first_opened_at": l["first_opened_at"],
                "last_opened_at": l["last_opened_at"]}

    def song_row(sid):
        row = conn().execute("SELECT * FROM songs WHERE id = ?", (sid,)).fetchone()
        if row is None:
            abort(404)
        return row

    def version_row(vid):
        row = conn().execute("SELECT * FROM versions WHERE id = ?", (vid,)).fetchone()
        if row is None:
            abort(404)
        return row

    def song_versions(sid):
        return conn().execute("SELECT * FROM versions WHERE song_id = ? ORDER BY created_at, id", (sid,)).fetchall()

    def song_dict(s, full=False):
        vs = song_versions(s["id"])
        d = {"id": s["id"], "title": s["title"], "notes": s["notes"], "created_at": s["created_at"], "archived": s["archived_at"] is not None,
             "version_count": len(vs), "latest_label": vs[-1]["label"] if vs else None,
             "comment_count": conn().execute("SELECT COUNT(*) FROM comments WHERE song_id = ?", (s["id"],)).fetchone()[0]}
        if full:
            d["versions"] = [version_owner(v) for v in vs]
            d["links"] = [link_dict(l) for l in conn().execute("SELECT * FROM links WHERE song_id = ? ORDER BY id", (s["id"],))]
            d["comments"] = [comment_dict(c) for c in conn().execute("SELECT * FROM comments WHERE song_id = ? ORDER BY t_ms, id", (s["id"],))]
        return d

    def serve_audio(row):
        play = row["play_filename"] if row["play_filename"] else None
        name, mime = (play, "audio/flac") if play and (data_dir / "audio" / play).is_file() else (row["filename"], row["mime"])
        path = data_dir / "audio" / name
        if not path.is_file():
            abort(404)
        resp = send_file(path, mimetype=mime, conditional=True, max_age=0, download_name=row["orig_filename"],
                         as_attachment=request.args.get("download") == "1" and auth.is_owner())
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Cache-Control"] = "private, max-age=600"
        return resp

    def serve_slice(row):
        """A WAV cut out of one version, for sample-accurate looping in the browser (precision mode)."""
        try:
            start, end = float(request.args.get("start", "")), float(request.args.get("end", ""))
            bits = int(request.args.get("bits", "24"))
        except ValueError:
            return err("start, end (seconds) and bits are required numbers")
        if not (0 <= start < end) or end - start > MAX_SLICE_S or bits not in (16, 24):
            return err(f"the region must be at most {int(MAX_SLICE_S)} seconds, start before end, bits 16 or 24")
        if not ffmpeg:
            return err("slicing needs ffmpeg on the server", 501)
        if not auth.is_owner():
            wait = slice_limit.wait_for(client_key())
            if wait:
                return err("too many requests, try again later", 429)
            slice_limit.failed(client_key())
        if not slice_lock.acquire(timeout=20):                       # one ffmpeg at a time: a second request waits its turn (the page asks for one slice per version at once)
            return err("busy, try again in a moment", 429)
        out = data_dir / "tmp" / (db.new_token() + ".wav")
        try:
            src = data_dir / "audio" / (row["play_filename"] or row["filename"])
            ok, message = extras.slice_wav(ffmpeg, src, out, start, end, bits)
        finally:
            slice_lock.release()
        if not ok:
            out.unlink(missing_ok=True)
            return err("could not cut that region: " + message[-120:], 500)
        resp = send_file(out, mimetype="audio/wav", max_age=0)
        resp.call_on_close(lambda: out.unlink(missing_ok=True))
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def link_by_token(token):
        row = conn().execute("SELECT * FROM links WHERE token = ?", (token,)).fetchone()
        if row is None:
            abort(404)
        return row

    def visible_versions(link):
        vs = song_versions(link["song_id"])
        return vs[-1:] if link["versions_mode"] == "latest" else vs

    def key_hash_from_request():
        key = request.headers.get("X-Commenter-Key", "")
        return hashlib.sha256(key.encode()).hexdigest() if 16 <= len(key) <= 128 else None

    # ---- static + health ------------------------------------------------------------------------------------------
    @bp.get("/health")
    @auth.public
    def health():
        return jsonify(ok=True)

    # Static files: each is read once, compressed once, and kept in memory. Pages refer to them as /static/x.css?v=<hash of the content>,
    # which may be cached for a year (the address changes when the file does); a bare address is revalidated with its ETag.
    assets = {}

    def load_asset(name):
        path = (static_dir / name).resolve()
        if name.startswith(".") or "/." in name or static_dir.resolve() not in path.parents or not path.is_file():
            return None
        st = path.stat()
        hit = assets.get(name)
        if hit is None or hit["stamp"] != (st.st_mtime_ns, st.st_size):
            raw = path.read_bytes()
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            hit = {"stamp": (st.st_mtime_ns, st.st_size), "raw": raw, "mime": mime, "etag": '"' + hashlib.sha1(raw).hexdigest()[:16] + '"',
                   "gz": gzip.compress(raw, 9) if mime in TEXT_TYPES and len(raw) > 600 else None}
            assets[name] = hit
        return hit

    def asset(name):
        a = load_asset(name)
        return f"{base}/static/{name}" + (f"?v={a['etag'][1:9]}" if a else "")

    app.jinja_env.globals["asset"] = asset

    @bp.get("/static/<path:name>")
    @auth.public
    def static_files(name):
        a = load_asset(name)
        if a is None:
            abort(404)
        cache = "public, max-age=31536000, immutable" if request.args.get("v") else "no-cache"
        if request.headers.get("If-None-Match") == a["etag"]:
            return Response(status=304, headers={"ETag": a["etag"], "Cache-Control": cache})
        use_gz = a["gz"] is not None and "gzip" in request.headers.get("Accept-Encoding", "")
        resp = Response(a["gz"] if use_gz else a["raw"], mimetype=a["mime"])
        resp.headers["ETag"] = a["etag"]
        resp.headers["Cache-Control"] = cache
        resp.vary.add("Accept-Encoding")
        if use_gz:
            resp.headers["Content-Encoding"] = "gzip"
        return resp

    # ---- anyone with a link -----------------------------------------------------------------------------------------
    @bp.get("/s/<token>")
    @auth.public
    def share_page(token):
        link = link_by_token(token)
        song = song_row(link["song_id"])
        if not auth.is_owner():
            now = db.now_iso()
            conn().execute("UPDATE links SET open_count = open_count + 1, last_opened_at = ?, first_opened_at = COALESCE(first_opened_at, ?) WHERE id = ?", (now, now, link["id"]))
            conn().commit()
        return render_template("share.html", base=base, token=token, title=song["title"])

    @bp.get("/s/<token>/data")
    @auth.public
    def share_data(token):
        link = link_by_token(token)
        song = song_row(link["song_id"])
        kh = key_hash_from_request()
        comments = conn().execute("SELECT * FROM comments WHERE song_id = ? ORDER BY t_ms, id", (song["id"],)).fetchall() if link["allow_comments"] else []
        return jsonify(song={"title": song["title"], "notes": song["notes"]}, allow_comments=bool(link["allow_comments"]), owner=auth.is_owner(),
                       versions=[version_public(v, token) for v in visible_versions(link)], comments=[comment_dict(c, kh) for c in comments])

    def share_version(token, vid):
        link = link_by_token(token)
        row = conn().execute("SELECT * FROM versions WHERE id = ? AND song_id = ?", (vid, link["song_id"])).fetchone()
        if row is None or row["id"] not in [v["id"] for v in visible_versions(link)]:
            abort(404)
        return row

    @bp.get("/s/<token>/audio/<int:vid>")
    @auth.public
    def share_audio(token, vid):
        return serve_audio(share_version(token, vid))

    @bp.get("/s/<token>/slice/<int:vid>")
    @auth.public
    def share_slice(token, vid):
        return serve_slice(share_version(token, vid))

    @bp.post("/s/<token>/comments")
    @auth.public
    def post_comment(token):
        link = link_by_token(token)
        if not link["allow_comments"]:
            return err("comments are switched off on this link", 403)
        request.max_content_length = 16 * 1024
        try:
            body = json_body()
            if body.get("website"):                                    # a honeypot field real people never see: bots fill it in
                return jsonify(ok=True), 201
            text_body = text(body.get("body", ""), MAX_COMMENT, "comment", True, multiline=True)
            t_ms = body.get("t_ms")
            if not isinstance(t_ms, int) or isinstance(t_ms, bool) or not 0 <= t_ms <= 24 * 3600 * 1000:
                raise Invalid("t_ms must be a whole number of milliseconds")
            vid = body.get("version_id")
            if vid is not None and (not isinstance(vid, int) or conn().execute("SELECT 1 FROM versions WHERE id = ? AND song_id = ?", (vid, link["song_id"])).fetchone() is None):
                raise Invalid("unknown version")
            owner = auth.is_owner()
            name = owner_name if owner else text(body.get("name", ""), MAX_NAME, "name", True)
            if not owner and name.casefold() == owner_name.casefold():
                return err("that name is reserved", 409)
            key = body.get("key", "")
            kh = hashlib.sha256(key.encode()).hexdigest() if isinstance(key, str) and 16 <= len(key) <= 128 else None
        except Invalid as exc:
            return err(str(exc))
        who = client_key()
        if not owner:
            wait = comment_limit.wait_for(who)
            if wait:
                resp = err("you are commenting too fast; try again in a few minutes", 429)
                resp[0].headers["Retry-After"] = str(wait)
                return resp
            comment_limit.failed(who)
        cur = conn().execute("INSERT INTO comments (song_id, version_id, t_ms, name, body, key_hash, is_owner, created_at, link_id) VALUES (?,?,?,?,?,?,?,?,?)",
                             (link["song_id"], vid, t_ms, name, text_body, kh, int(owner), db.now_iso(), link["id"]))
        conn().commit()
        row = conn().execute("SELECT * FROM comments WHERE id = ?", (cur.lastrowid,)).fetchone()
        return jsonify(comment_dict(row, kh)), 201

    def own_comment(token, cid):
        link = link_by_token(token)
        row = conn().execute("SELECT * FROM comments WHERE id = ? AND song_id = ?", (cid, link["song_id"])).fetchone()
        if row is None:
            abort(404)
        kh = key_hash_from_request()
        if auth.is_owner():
            return row
        age = clock() - __import__("calendar").timegm(time.strptime(row["created_at"], "%Y-%m-%dT%H:%M:%SZ"))
        if not kh or row["key_hash"] != kh or age > EDIT_WINDOW:
            abort(403)
        return row

    @bp.patch("/s/<token>/comments/<int:cid>")
    @auth.public
    def edit_comment(token, cid):
        row = own_comment(token, cid)
        try:
            new = text(json_body().get("body", ""), MAX_COMMENT, "comment", True, multiline=True)
        except Invalid as exc:
            return err(str(exc))
        conn().execute("UPDATE comments SET body = ?, edited_at = ? WHERE id = ?", (new, db.now_iso(), row["id"]))
        conn().commit()
        return jsonify(comment_dict(conn().execute("SELECT * FROM comments WHERE id = ?", (cid,)).fetchone(), key_hash_from_request()))

    @bp.delete("/s/<token>/comments/<int:cid>")
    @auth.public
    def delete_own_comment(token, cid):
        row = own_comment(token, cid)
        conn().execute("DELETE FROM comments WHERE id = ?", (row["id"],))
        conn().commit()
        return jsonify(ok=True)

    # ---- the owner's page --------------------------------------------------------------------------------------------
    @bp.get("/")
    @auth.owner
    def owner_page():
        return render_template("owner.html", base=base)

    @bp.get("/api/session")
    @auth.owner
    def session_status():
        return jsonify(ok=True, base=base, owner_name=owner_name)

    @bp.get("/api/songs")
    @auth.owner
    def list_songs():
        archived = request.args.get("archived") == "1"
        rows = conn().execute(f"SELECT * FROM songs WHERE archived_at IS {'NOT ' if archived else ''}NULL ORDER BY created_at DESC, id DESC").fetchall()
        return jsonify([song_dict(s) for s in rows])

    @bp.post("/api/songs")
    @auth.owner
    def create_song():
        try:
            body = json_body()
            title = text(body.get("title", ""), MAX_TITLE, "title", True)
            notes = text(body.get("notes", ""), MAX_NOTES, "notes", multiline=True)
        except Invalid as exc:
            return err(str(exc))
        cur = conn().execute("INSERT INTO songs (title, notes, created_at) VALUES (?,?,?)", (title, notes, db.now_iso()))
        conn().commit()
        return jsonify(song_dict(song_row(cur.lastrowid), True)), 201

    @bp.get("/api/songs/<int:sid>")
    @auth.owner
    def get_song(sid):
        return jsonify(song_dict(song_row(sid), True))

    @bp.patch("/api/songs/<int:sid>")
    @auth.owner
    def edit_song(sid):
        song_row(sid)
        try:
            body = json_body()
            sets, vals = [], []
            if "title" in body:
                sets.append("title = ?"); vals.append(text(body["title"], MAX_TITLE, "title", True))
            if "notes" in body:
                sets.append("notes = ?"); vals.append(text(body["notes"], MAX_NOTES, "notes", multiline=True))
        except Invalid as exc:
            return err(str(exc))
        if sets:
            conn().execute(f"UPDATE songs SET {', '.join(sets)} WHERE id = ?", (*vals, sid))
            conn().commit()
        return jsonify(song_dict(song_row(sid), True))

    @bp.post("/api/songs/<int:sid>/archive")
    @auth.owner
    def archive_song(sid):
        song_row(sid)
        conn().execute("UPDATE songs SET archived_at = ? WHERE id = ? AND archived_at IS NULL", (db.now_iso(), sid))
        conn().commit()
        return jsonify(song_dict(song_row(sid)))

    @bp.post("/api/songs/<int:sid>/unarchive")
    @auth.owner
    def unarchive_song(sid):
        song_row(sid)
        conn().execute("UPDATE songs SET archived_at = NULL WHERE id = ?", (sid,))
        conn().commit()
        return jsonify(song_dict(song_row(sid)))

    @bp.delete("/api/songs/<int:sid>")
    @auth.owner
    def delete_song(sid):
        """Delete forever: every version's audio goes. Needs the exact title typed back."""
        song = song_row(sid)
        if (request.get_json(silent=True) or {}).get("confirm") != song["title"]:
            return err("to delete forever, send the exact title as 'confirm'", 409)
        for v in song_versions(sid):
            for name in (v["filename"], v["play_filename"]):
                if name:
                    (data_dir / "audio" / name).unlink(missing_ok=True)
        conn().execute("DELETE FROM songs WHERE id = ?", (sid,))
        conn().commit()
        return jsonify(ok=True)

    # ---- versions -------------------------------------------------------------------------------------------------------
    @bp.post("/api/songs/<int:sid>/versions")
    @auth.owner
    def upload_version(sid):
        song_row(sid)
        f = request.files.get("file")
        if f is None:
            return err("send the audio in the 'file' field")
        orig = LINE_CTRL.sub("", os.path.basename((f.filename or "").replace("\\", "/")))[:255] or "untitled"
        tmp = data_dir / "tmp" / (db.new_token() + ".part")
        f.save(tmp)
        try:
            with open(tmp, "rb") as fh:
                head = fh.read(16)
            ext = Path(orig).suffix.lower()
            if ext not in media.INPUT_FORMAT:
                ext = media.sniff_audio_ext(head) or ""
            if ext not in media.INPUT_FORMAT:
                return err("that is not a supported audio file", 415)
            try:
                n = conn().execute("SELECT COUNT(*) FROM versions WHERE song_id = ?", (sid,)).fetchone()[0] + 1
                label = text(request.form.get("label") or f"v{n}", MAX_LABEL, "label", True)
                note = text(request.form.get("note", ""), MAX_NOTES, "note", multiline=True)
                offset = int(request.form.get("offset_ms", "0") or 0)
            except (Invalid, ValueError) as exc:
                return err(str(exc))
            digest = hashlib.sha256()
            with open(tmp, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
            stored = db.new_token().replace("-", "x").replace("_", "y") + ext
            shutil.move(str(tmp), data_dir / "audio" / stored)
            cur = conn().execute("INSERT INTO versions (song_id, label, note, created_at, filename, orig_filename, mime, size, sha256, offset_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (sid, label, note, db.now_iso(), stored, orig, MIME[ext], (data_dir / "audio" / stored).stat().st_size, digest.hexdigest(), offset))
            conn().commit()
            worker.submit(cur.lastrowid)
            return jsonify(version_owner(version_row(cur.lastrowid))), 201
        finally:
            tmp.unlink(missing_ok=True)

    @bp.patch("/api/versions/<int:vid>")
    @auth.owner
    def edit_version(vid):
        version_row(vid)
        try:
            body = json_body()
            sets, vals = [], []
            if "label" in body:
                sets.append("label = ?"); vals.append(text(body["label"], MAX_LABEL, "label", True))
            if "note" in body:
                sets.append("note = ?"); vals.append(text(body["note"], MAX_NOTES, "note", multiline=True))
            if "offset_ms" in body:
                o = body["offset_ms"]
                if not isinstance(o, int) or isinstance(o, bool) or abs(o) > 60000:
                    raise Invalid("offset_ms must be a whole number of milliseconds, within a minute")
                sets.append("offset_ms = ?"); vals.append(o)
        except Invalid as exc:
            return err(str(exc))
        if sets:
            conn().execute(f"UPDATE versions SET {', '.join(sets)} WHERE id = ?", (*vals, vid))
            conn().commit()
        return jsonify(version_owner(version_row(vid)))

    @bp.delete("/api/versions/<int:vid>")
    @auth.owner
    def delete_version(vid):
        row = version_row(vid)
        if (request.get_json(silent=True) or {}).get("confirm") != row["label"]:
            return err("to delete forever, send the exact label as 'confirm'", 409)
        for name in (row["filename"], row["play_filename"]):
            if name:
                (data_dir / "audio" / name).unlink(missing_ok=True)
        conn().execute("DELETE FROM versions WHERE id = ?", (vid,))
        conn().commit()
        return jsonify(ok=True)

    @bp.get("/api/versions/<int:vid>/audio")
    @auth.owner
    def owner_audio(vid):
        return serve_audio(version_row(vid))

    @bp.get("/api/versions/<int:vid>/slice")
    @auth.owner
    def owner_slice(vid):
        return serve_slice(version_row(vid))

    # ---- links -------------------------------------------------------------------------------------------------------------
    @bp.post("/api/songs/<int:sid>/links")
    @auth.owner
    def create_link(sid):
        song_row(sid)
        try:
            body = json_body()
            label = text(body.get("label", ""), MAX_LABEL, "label")
            mode = body.get("versions_mode", "all")
            if mode not in ("all", "latest"):
                raise Invalid("versions_mode must be all or latest")
            allow = 1 if body.get("allow_comments", True) else 0
        except Invalid as exc:
            return err(str(exc))
        cur = conn().execute("INSERT INTO links (song_id, token, label, allow_comments, versions_mode, created_at) VALUES (?,?,?,?,?,?)", (sid, db.new_token(), label, allow, mode, db.now_iso()))
        conn().commit()
        return jsonify(link_dict(conn().execute("SELECT * FROM links WHERE id = ?", (cur.lastrowid,)).fetchone())), 201

    @bp.patch("/api/links/<int:lid>")
    @auth.owner
    def edit_link(lid):
        row = conn().execute("SELECT * FROM links WHERE id = ?", (lid,)).fetchone()
        if row is None:
            abort(404)
        try:
            body = json_body()
            sets, vals = [], []
            if "label" in body:
                sets.append("label = ?"); vals.append(text(body["label"], MAX_LABEL, "label"))
            if "allow_comments" in body:
                sets.append("allow_comments = ?"); vals.append(1 if body["allow_comments"] else 0)
            if "versions_mode" in body:
                if body["versions_mode"] not in ("all", "latest"):
                    raise Invalid("versions_mode must be all or latest")
                sets.append("versions_mode = ?"); vals.append(body["versions_mode"])
        except Invalid as exc:
            return err(str(exc))
        if sets:
            conn().execute(f"UPDATE links SET {', '.join(sets)} WHERE id = ?", (*vals, lid))
            conn().commit()
        return jsonify(link_dict(conn().execute("SELECT * FROM links WHERE id = ?", (lid,)).fetchone()))

    @bp.delete("/api/links/<int:lid>")
    @auth.owner
    def delete_link(lid):
        """Turn a link off for good. The song and its comments stay."""
        if conn().execute("SELECT 1 FROM links WHERE id = ?", (lid,)).fetchone() is None:
            abort(404)
        conn().execute("DELETE FROM links WHERE id = ?", (lid,))
        conn().commit()
        return jsonify(ok=True)

    # ---- comments (owner) --------------------------------------------------------------------------------------------------------
    @bp.post("/api/songs/<int:sid>/comments")
    @auth.owner
    def owner_comment(sid):
        song_row(sid)
        try:
            body = json_body()
            text_body = text(body.get("body", ""), MAX_COMMENT, "comment", True, multiline=True)
            t_ms = body.get("t_ms")
            if not isinstance(t_ms, int) or isinstance(t_ms, bool) or t_ms < 0:
                raise Invalid("t_ms must be a whole number of milliseconds")
            vid = body.get("version_id")
            if vid is not None and (not isinstance(vid, int) or conn().execute("SELECT 1 FROM versions WHERE id = ? AND song_id = ?", (vid, sid)).fetchone() is None):
                raise Invalid("unknown version")
        except Invalid as exc:
            return err(str(exc))
        cur = conn().execute("INSERT INTO comments (song_id, version_id, t_ms, name, body, is_owner, created_at) VALUES (?,?,?,?,?,1,?)", (sid, vid, t_ms, owner_name, text_body, db.now_iso()))
        conn().commit()
        return jsonify(comment_dict(conn().execute("SELECT * FROM comments WHERE id = ?", (cur.lastrowid,)).fetchone())), 201

    @bp.delete("/api/comments/<int:cid>")
    @auth.owner
    def owner_delete_comment(cid):
        if conn().execute("SELECT 1 FROM comments WHERE id = ?", (cid,)).fetchone() is None:
            abort(404)
        conn().execute("DELETE FROM comments WHERE id = ?", (cid,))
        conn().commit()
        return jsonify(ok=True)

    # ---- backup and restore --------------------------------------------------------------------------------------------------------------
    @bp.get("/api/backup")
    @auth.owner
    def backup_status():
        return jsonify(enabled=bool(backup_dir), **(backupmod.status(backup_dir) if backup_dir else {}),
                       restore=backupmod.inspect(restore_dir) if Path(restore_dir).is_dir() else {"ok": False, "error": "no restore folder"})

    @bp.post("/api/backup")
    @auth.owner
    def backup_now():
        if not backup_dir:
            return err("no backup folder is set (VERSIONCONTROL_BACKUP_DIR)", 409)
        try:
            target, placed, problems = backupmod.backup(data_dir, backup_dir)
        except (ValueError, OSError, sqlite3.Error) as exc:
            return err(str(exc), 500)
        return jsonify(ok=True, copy=target.name, audio_added=placed, problems=problems)

    @bp.post("/api/restore")
    @auth.owner
    def restore_now():
        try:
            n, problems = backupmod.restore(restore_dir, data_dir)
        except (ValueError, OSError, sqlite3.Error) as exc:
            return err(str(exc), 409)
        worker.backfill()
        return jsonify(ok=True, versions=n, problems=problems)

    app.register_blueprint(bp, url_prefix=base or None)
    if base:
        app.add_url_rule(base, "base_redirect", auth.public(lambda: redirect(base + "/")))
    app.extensions["versioncontrol_worker"] = worker
    return app
