import json
import shutil
import threading

import pytest

from conftest import ROOT, Wall, owner_cookie, upload, wav_bytes

B = "/version-control"
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
KEY = "k" * 32                       # a commenter's browser-kept random key (16-128 characters)


def song(owner, title="Night Drive"):
    r = owner.post(f"{B}/api/songs", json={"title": title})
    assert r.status_code == 201, r.data
    return r.json


def version(owner, sid, label=None, seed=0, name="mix.wav", data=None):
    r = upload(owner, sid, name, data or wav_bytes(seed=seed), label)
    assert r.status_code == 201, r.data
    return r.json


def link(owner, sid, **kw):
    r = owner.post(f"{B}/api/songs/{sid}/links", json=kw)
    assert r.status_code == 201, r.data
    return r.json


def comment(guest, token, body="nice", t_ms=1000, name="Dana", key=KEY, **kw):
    return guest.post(f"{B}/s/{token}/comments", json={"name": name, "body": body, "t_ms": t_ms, "key": key, **kw})


# ---- access ------------------------------------------------------------------------------------------------------------
def test_owner_api_needs_the_owner(guest):
    for method, url in (("get", "/api/songs"), ("post", "/api/songs"), ("get", "/api/songs/1"), ("delete", "/api/songs/1"), ("post", "/api/songs/1/versions"),
                        ("get", "/api/versions/1/audio"), ("get", "/api/versions/1/slice"), ("post", "/api/songs/1/links"), ("delete", "/api/links/1"),
                        ("delete", "/api/comments/1"), ("post", "/api/backup"), ("post", "/api/restore"), ("get", "/api/backup")):
        assert getattr(guest, method)(B + url).status_code == 401, url
    assert guest.get(B + "/").status_code == 401
    assert guest.get(B + "/", headers={"Accept": "text/html"}).status_code == 303


def test_every_route_is_declared(app):
    from siteauth import undeclared_routes
    assert undeclared_routes(app) == []


def test_another_apps_cookie_does_not_open_this_app(app, site):
    c = app.test_client()
    c.set_cookie("site_versioncontrol", owner_cookie(site, "riffbox"))
    assert c.get(B + "/api/songs").status_code == 401


def test_a_link_opens_only_its_own_song(owner, guest):
    a, b = song(owner, "A"), song(owner, "B")
    va, vb = version(owner, a["id"]), version(owner, b["id"], seed=3)
    la = link(owner, a["id"])
    assert guest.get(f"{B}/s/{la['token']}/audio/{va['id']}").status_code == 200
    assert guest.get(f"{B}/s/{la['token']}/audio/{vb['id']}").status_code == 404
    assert guest.get(f"{B}/s/nonsense/data").status_code == 404
    assert guest.get(f"{B}/s/{la['token']}/data").status_code == 200


def test_tokens_are_unguessable(owner):
    s = song(owner)
    t1, t2 = link(owner, s["id"])["token"], link(owner, s["id"])["token"]
    assert t1 != t2 and len(t1) >= 21


def test_share_pages_are_noindex_with_a_strict_csp(owner, guest):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    for url in (f"{B}/s/{l['token']}", f"{B}/s/{l['token']}/data"):
        r = guest.get(url)
        assert "noindex" in r.headers["X-Robots-Tag"]
        assert "script-src 'self'" in r.headers["Content-Security-Policy"] and "'unsafe-inline'" not in r.headers["Content-Security-Policy"]
    assert b"<script>" not in guest.get(f"{B}/s/{l['token']}").data.replace(b"<script src", b"")


# ---- songs and versions ------------------------------------------------------------------------------------------------------
def test_versions_keep_order_labels_and_offsets(owner):
    s = song(owner)
    v1 = version(owner, s["id"]); v2 = version(owner, s["id"], label="Remaster", seed=1)
    assert [v["label"] for v in owner.get(f"{B}/api/songs/{s['id']}").json["versions"]] == ["v1", "Remaster"]
    assert owner.patch(f"{B}/api/versions/{v2['id']}", json={"offset_ms": -120, "note": "brighter"}).json["offset_ms"] == -120
    assert owner.patch(f"{B}/api/versions/{v2['id']}", json={"offset_ms": 10**9}).status_code == 400
    assert owner.patch(f"{B}/api/versions/{v2['id']}", json={"offset_ms": True}).status_code == 400
    assert v1["id"] != v2["id"]


def test_upload_rejects_non_audio_and_sniffs_missing_extension(owner):
    s = song(owner)
    assert upload(owner, s["id"], "notes.txt", b"just some text, nothing musical").status_code == 415
    assert upload(owner, s["id"], "no_extension", wav_bytes()).status_code == 201


def test_upload_path_tricks_cannot_escape(owner, tmp_path):
    s = song(owner)
    r = upload(owner, s["id"], "../../etc/passwd.wav", wav_bytes())
    assert r.status_code == 201 and r.json["orig_filename"] == "passwd.wav"
    assert not (tmp_path / "etc").exists()


def test_delete_version_and_song_need_the_exact_text_and_remove_audio(owner, tmp_path):
    s = song(owner, "Gone")
    v = version(owner, s["id"], label="v1")
    files = list((tmp_path / "data" / "audio").iterdir())
    assert len(files) == 1
    assert owner.delete(f"{B}/api/versions/{v['id']}", json={"confirm": "nope"}).status_code == 409
    assert files[0].exists()
    assert owner.delete(f"{B}/api/versions/{v['id']}", json={"confirm": "v1"}).status_code == 200 and not files[0].exists()
    v2 = version(owner, s["id"], label="again", seed=4)
    assert owner.delete(f"{B}/api/songs/{s['id']}", json={"confirm": "wrong"}).status_code == 409
    assert owner.delete(f"{B}/api/songs/{s['id']}", json={"confirm": "Gone"}).status_code == 200
    assert not any((tmp_path / "data" / "audio").iterdir()) and owner.get(f"{B}/api/songs").json == []


def test_archive_and_unarchive(owner):
    s = song(owner)
    assert owner.post(f"{B}/api/songs/{s['id']}/archive").json["archived"] is True
    assert owner.get(f"{B}/api/songs").json == [] and len(owner.get(f"{B}/api/songs?archived=1").json) == 1
    owner.post(f"{B}/api/songs/{s['id']}/unarchive")
    assert len(owner.get(f"{B}/api/songs").json) == 1


@needs_ffmpeg
def test_analysis_measures_peaks_duration_format_and_loudness(owner, tone):
    s = song(owner)
    quiet = owner.post(f"{B}/api/songs/{s['id']}/versions", data={"file": (open(tone("q.wav", 3, 440, -20), "rb"), "q.wav"), "label": "quiet"}, content_type="multipart/form-data").json
    loud = owner.post(f"{B}/api/songs/{s['id']}/versions", data={"file": (open(tone("l.wav", 3, 440, -6), "rb"), "l.wav"), "label": "loud"}, content_type="multipart/form-data").json
    vs = {v["label"]: v for v in owner.get(f"{B}/api/songs/{s['id']}").json["versions"]}
    assert vs["quiet"]["analysis_status"] == "ready" and abs(vs["quiet"]["duration"] - 3) < 0.2 and vs["quiet"]["peaks"]
    assert vs["quiet"]["sample_rate"] == 44100 and vs["quiet"]["channels"] == 2
    assert vs["loud"]["lufs"] - vs["quiet"]["lufs"] > 10


def test_audio_supports_range_requests(owner, guest):
    s = song(owner); v = version(owner, s["id"]); l = link(owner, s["id"])
    r = guest.get(f"{B}/s/{l['token']}/audio/{v['id']}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.data) == 100 and r.headers["Content-Range"].startswith("bytes 0-99/")


@needs_ffmpeg
def test_slice_returns_just_the_requested_region(owner, guest, tone):
    s = song(owner)
    owner.post(f"{B}/api/songs/{s['id']}/versions", data={"file": (open(tone("t.wav", 4), "rb"), "t.wav")}, content_type="multipart/form-data")
    v = owner.get(f"{B}/api/songs/{s['id']}").json["versions"][0]; l = link(owner, s["id"])
    r = guest.get(f"{B}/s/{l['token']}/slice/{v['id']}?start=1&end=2.5&bits=24")
    assert r.status_code == 200 and r.data[:4] == b"RIFF" and r.headers["Cache-Control"] == "no-store"
    assert 1.4 * 44100 * 6 < len(r.data) - 44 < 1.6 * 44100 * 6                     # 1.5 s of 24-bit stereo
    for q in ("start=2&end=1", "start=0&end=999", "start=x&end=2", "start=0&end=1&bits=8", ""):
        assert guest.get(f"{B}/s/{l['token']}/slice/{v['id']}?{q}").status_code == 400
    assert guest.get(f"{B}/api/versions/{v['id']}/slice?start=0&end=1").status_code == 401


@needs_ffmpeg
def test_slice_is_rate_limited_for_strangers_but_not_the_owner(owner, guest, tone):
    s = song(owner)
    owner.post(f"{B}/api/songs/{s['id']}/versions", data={"file": (open(tone("t.wav", 2), "rb"), "t.wav")}, content_type="multipart/form-data")
    v = owner.get(f"{B}/api/songs/{s['id']}").json["versions"][0]; l = link(owner, s["id"])
    codes = [guest.get(f"{B}/s/{l['token']}/slice/{v['id']}?start=0&end=1").status_code for _ in range(32)]
    assert codes[:30] == [200] * 30 and codes[30:] == [429, 429]
    assert owner.get(f"{B}/api/versions/{v['id']}/slice?start=0&end=1").status_code == 200


# ---- link settings -------------------------------------------------------------------------------------------------------------------
def test_latest_mode_shows_only_the_newest_version(owner, guest):
    s = song(owner); v1 = version(owner, s["id"], "old"); v2 = version(owner, s["id"], "new", seed=2)
    all_l, latest = link(owner, s["id"]), link(owner, s["id"], versions_mode="latest")
    assert [v["label"] for v in guest.get(f"{B}/s/{all_l['token']}/data").json["versions"]] == ["old", "new"]
    assert [v["label"] for v in guest.get(f"{B}/s/{latest['token']}/data").json["versions"]] == ["new"]
    assert guest.get(f"{B}/s/{latest['token']}/audio/{v1['id']}").status_code == 404
    assert guest.get(f"{B}/s/{latest['token']}/audio/{v2['id']}").status_code == 200


def test_public_data_never_leaks_server_file_names(owner, guest):
    s = song(owner); v = version(owner, s["id"], name="secret_filename.wav"); l = link(owner, s["id"])
    raw = guest.get(f"{B}/s/{l['token']}/data").get_data(as_text=True)
    assert "secret_filename" not in raw and "filename" not in raw and "sha256" not in raw


def test_deleting_a_link_kills_it_but_keeps_the_song_and_comments(owner, guest):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    comment(guest, l["token"], "stays")
    assert owner.delete(f"{B}/api/links/{l['id']}").status_code == 200
    assert guest.get(f"{B}/s/{l['token']}/data").status_code == 404
    assert [c["body"] for c in owner.get(f"{B}/api/songs/{s['id']}").json["comments"]] == ["stays"]


def test_link_counts_guest_opens_not_owner_opens(owner, guest):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"], label="Dana")
    owner.get(f"{B}/s/{l['token']}"); guest.get(f"{B}/s/{l['token']}"); guest.get(f"{B}/s/{l['token']}")
    row = owner.get(f"{B}/api/songs/{s['id']}").json["links"][0]
    assert row["open_count"] == 2 and row["label"] == "Dana" and row["first_opened_at"]


# ---- comments ------------------------------------------------------------------------------------------------------------------------------
def test_anyone_with_the_link_can_comment_with_a_name_and_everyone_sees_it(owner, guest, app):
    s = song(owner); v = version(owner, s["id"]); l = link(owner, s["id"])
    r = comment(guest, l["token"], "the bass is muddy here", 83500, "Dana", version_id=v["id"])
    assert r.status_code == 201 and r.json["name"] == "Dana" and r.json["t_ms"] == 83500 and r.json["mine"] is True
    other = app.test_client()
    seen = other.get(f"{B}/s/{l['token']}/data").json["comments"]
    assert [(c["name"], c["body"], c["t_ms"], c["mine"]) for c in seen] == [("Dana", "the bass is muddy here", 83500, False)]
    assert seen[0]["version_id"] == v["id"] and "key_hash" not in seen[0] and "key" not in seen[0]


def test_comments_sort_by_time_in_the_song(owner, guest):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    for t, body in ((9000, "c"), (1000, "a"), (5000, "b")):
        comment(guest, l["token"], body, t)
    assert [c["body"] for c in guest.get(f"{B}/s/{l['token']}/data").json["comments"]] == ["a", "b", "c"]


def test_comments_off_means_no_posting_and_no_list(owner, guest):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"], allow_comments=False)
    assert comment(guest, l["token"]).status_code == 403
    data = guest.get(f"{B}/s/{l['token']}/data").json
    assert data["allow_comments"] is False and data["comments"] == []


@pytest.mark.parametrize("payload", [{"name": "", "body": "x", "t_ms": 0}, {"name": "x" * 41, "body": "x", "t_ms": 0}, {"name": "A", "body": "", "t_ms": 0},
                                     {"name": "A", "body": "y" * 2001, "t_ms": 0}, {"name": "A", "body": "x", "t_ms": -1}, {"name": "A", "body": "x", "t_ms": "5"},
                                     {"name": "A", "body": "x", "t_ms": 1.5}, {"name": "A", "body": "x", "t_ms": True}, {"name": "A", "body": "x", "t_ms": 10**12},
                                     {"name": "A", "body": "x", "t_ms": 0, "version_id": 9999}, {"name": ["A"], "body": "x", "t_ms": 0}])
def test_bad_comments_are_refused(owner, guest, payload):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    assert guest.post(f"{B}/s/{l['token']}/comments", json=payload).status_code == 400


def test_a_version_of_another_song_cannot_be_attached(owner, guest):
    s1, s2 = song(owner, "one"), song(owner, "two")
    version(owner, s1["id"]); other = version(owner, s2["id"], seed=2); l = link(owner, s1["id"])
    assert comment(guest, l["token"], version_id=other["id"]).status_code == 400


def test_comment_text_is_plain_text_and_stored_as_typed(owner, guest):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    evil = "<script>alert(1)</script> & <img src=x onerror=alert(2)>"
    c = comment(guest, l["token"], evil, name="<b>Eve</b>")
    assert c.status_code == 201
    got = guest.get(f"{B}/s/{l['token']}/data").json["comments"][0]
    assert got["body"] == evil and got["name"] == "<b>Eve</b>"           # the server never rewrites it; the page uses textContent (see the browser test)
    assert guest.get(f"{B}/s/{l['token']}").data.count(b"alert") == 0     # and the page itself never contains it


def test_control_characters_are_removed_but_newlines_kept_in_comments(owner, guest):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    c = comment(guest, l["token"], "line one\nline two\x00\x07", name="Da\nna")
    assert c.json["body"] == "line one\nline two" and c.json["name"] == "Da na"


def test_the_owners_name_is_reserved_for_the_owner(owner, guest):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    assert comment(guest, l["token"], name="owner").status_code == 409 and comment(guest, l["token"], name="OWNER").status_code == 409
    r = comment(owner, l["token"], "my own note", name="whatever")
    assert r.status_code == 201 and r.json["owner"] is True and r.json["name"] == "Owner"


def test_honeypot_comments_are_dropped_silently(owner, guest):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    assert comment(guest, l["token"], "buy now", website="http://spam.example").status_code == 201
    assert owner.get(f"{B}/api/songs/{s['id']}").json["comments"] == []


def test_comment_flood_from_one_client_is_slowed_but_others_and_the_owner_are_not(owner, guest, app):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    codes = [comment(guest, l["token"], f"c{i}").status_code for i in range(12)]
    assert codes[:10] == [201] * 10 and codes[10:] == [429, 429]
    assert comment(guest, l["token"]).headers.get("Retry-After")
    other = app.test_client()
    assert other.post(f"{B}/s/{l['token']}/comments", json={"name": "Eve", "body": "hi", "t_ms": 0}, headers={"X-Forwarded-For": "5.5.5.5"},
                      environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 201
    assert comment(owner, l["token"], "still fine").status_code == 201


def test_a_commenter_can_edit_and_delete_their_own_comment_for_15_minutes(owner, guest, app):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    cid = comment(guest, l["token"], "first draft").json["id"]
    url = f"{B}/s/{l['token']}/comments/{cid}"
    stranger = app.test_client()
    assert stranger.patch(url, json={"body": "hacked"}, headers={"X-Commenter-Key": "z" * 32}).status_code == 403
    assert stranger.patch(url, json={"body": "hacked"}).status_code == 403
    mine = guest.patch(url, json={"body": "better"}, headers={"X-Commenter-Key": KEY})
    assert mine.status_code == 200 and mine.json["body"] == "better" and mine.json["edited_at"]
    assert stranger.delete(url, headers={"X-Commenter-Key": "z" * 32}).status_code == 403
    assert guest.delete(url, headers={"X-Commenter-Key": KEY}).status_code == 200
    assert guest.get(f"{B}/s/{l['token']}/data").json["comments"] == []


def test_the_edit_window_closes(tmp_path, site):
    from conftest import Wall
    from versioncontrol import create_app
    wall = Wall()
    app = create_app({"TESTING": True, "JOBS_SYNC": True, "VERSIONCONTROL_DATA_DIR": str(tmp_path / "d"), "VERSIONCONTROL_BASE_PATH": "/version-control",
                      "VERSIONCONTROL_STATIC_DIR": str(ROOT / "static"), "VERSIONCONTROL_SITE_KEY_FILE": str(site / "keys" / "versioncontrol.key"),
                      "VERSIONCONTROL_INSECURE_COOKIES": "1", "clock": wall})
    import calendar, time
    o = app.test_client(); o.set_cookie("site_versioncontrol", owner_cookie(site))
    s = song(o); version(o, s["id"]); l = link(o, s["id"])
    g = app.test_client()
    wall.t = calendar.timegm(time.gmtime())                    # comments are stamped with the real UTC time
    cid = comment(g, l["token"]).json["id"]
    wall.t += 14 * 60
    assert g.patch(f"{B}/s/{l['token']}/comments/{cid}", json={"body": "x"}, headers={"X-Commenter-Key": KEY}).status_code == 200
    wall.t += 2 * 60
    assert g.patch(f"{B}/s/{l['token']}/comments/{cid}", json={"body": "y"}, headers={"X-Commenter-Key": KEY}).status_code == 403
    assert o.delete(f"{B}/s/{l['token']}/comments/{cid}").status_code == 200       # the owner can always remove one


def test_owner_can_delete_any_comment_and_add_their_own(owner, guest):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    cid = comment(guest, l["token"], "rude").json["id"]
    assert owner.delete(f"{B}/api/comments/{cid}").status_code == 200
    assert owner.post(f"{B}/api/songs/{s['id']}/comments", json={"body": "fixed it", "t_ms": 4000}).json["owner"] is True
    assert owner.post(f"{B}/api/songs/{s['id']}/comments", json={"body": "x", "t_ms": -5}).status_code == 400


def test_cross_origin_comment_posts_are_refused(owner, guest):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    assert guest.post(f"{B}/s/{l['token']}/comments", json={"name": "A", "body": "x", "t_ms": 0}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_oversize_comment_bodies_are_refused_before_reading(owner, guest):
    s = song(owner); version(owner, s["id"]); l = link(owner, s["id"])
    r = guest.post(f"{B}/s/{l['token']}/comments", data=b'{"name":"A","body":"' + b"x" * 40000 + b'","t_ms":0}', content_type="application/json")
    assert r.status_code == 413


# ---- storage guard, backup, restore -------------------------------------------------------------------------------------------------------------
def test_refuses_to_start_when_the_volume_is_not_mounted(tmp_path, site):
    from versioncontrol import create_app
    base = {"TESTING": True, "JOBS_SYNC": True, "VERSIONCONTROL_DATA_DIR": str(tmp_path / "vol"), "VERSIONCONTROL_REQUIRE_VOLUME": "1",
            "VERSIONCONTROL_STATIC_DIR": str(ROOT / "static"), "VERSIONCONTROL_SITE_KEY_FILE": str(site / "keys" / "versioncontrol.key")}
    with pytest.raises(RuntimeError, match="volume"):
        create_app(base)
    assert not (tmp_path / "vol").exists() or not any((tmp_path / "vol").iterdir())          # and it wrote nothing before refusing
    (tmp_path / "vol").mkdir(exist_ok=True); (tmp_path / "vol" / ".volume-ok").write_text("")
    create_app(base)


def test_backup_hard_links_audio_so_it_costs_no_space_and_survives_delete_forever(owner, tmp_path):
    s = song(owner, "Keep"); v = version(owner, s["id"], "v1")
    r = owner.post(f"{B}/api/backup").json
    assert r["ok"] and r["audio_added"] == 1 and r["problems"] == []
    orig = next((tmp_path / "data" / "audio").iterdir()); copy = tmp_path / "backup" / "audio" / orig.name
    assert orig.stat().st_ino == copy.stat().st_ino                                     # one file on disk, two names
    assert owner.post(f"{B}/api/backup").json["audio_added"] == 0
    owner.delete(f"{B}/api/songs/{s['id']}", json={"confirm": "Keep"})
    assert not orig.exists() and copy.exists()                                          # the backup name still holds the audio


def test_backup_then_restore_reproduces_songs_versions_links_comments(owner, guest, tmp_path, site):
    import hashlib
    from versioncontrol import create_app
    s = song(owner, "Restore me"); v1 = version(owner, s["id"], "v1"); v2 = version(owner, s["id"], "v2", seed=9)
    l = link(owner, s["id"], label="Dana"); comment(guest, l["token"], "a note", 2500, version_id=v1["id"])
    assert owner.post(f"{B}/api/backup").status_code == 200
    shutil.copytree(tmp_path / "backup", tmp_path / "restore")
    app2 = create_app({"TESTING": True, "JOBS_SYNC": True, "VERSIONCONTROL_DATA_DIR": str(tmp_path / "new"), "VERSIONCONTROL_BASE_PATH": "/version-control",
                       "VERSIONCONTROL_STATIC_DIR": str(ROOT / "static"), "VERSIONCONTROL_SITE_KEY_FILE": str(site / "keys" / "versioncontrol.key"),
                       "VERSIONCONTROL_INSECURE_COOKIES": "1", "VERSIONCONTROL_RESTORE_DIR": str(tmp_path / "restore"), "clock": Wall()})
    o2 = app2.test_client(); o2.set_cookie("site_versioncontrol", owner_cookie(site))
    assert o2.get(f"{B}/api/backup").json["restore"]["versions"] == 2
    done = o2.post(f"{B}/api/restore").json
    assert done["ok"] and done["versions"] == 2 and done["problems"] == []
    got = o2.get(f"{B}/api/songs/{s['id']}").json
    assert [v["label"] for v in got["versions"]] == ["v1", "v2"] and got["links"][0]["token"] == l["token"] and got["comments"][0]["body"] == "a note"
    g2 = app2.test_client()
    assert g2.get(f"{B}/s/{l['token']}/data").json["comments"][0]["name"] == "Dana"             # the same link works on the rebuilt server
    for v in got["versions"]:
        data = o2.get(v["audio"]).data
        assert hashlib.sha256(data).hexdigest() in {hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp_path / "new" / "audio").iterdir()}
    assert o2.post(f"{B}/api/restore").status_code == 409                                         # never into a library that has songs


def test_restore_reports_damage_instead_of_hiding_it(owner, tmp_path):
    from versioncontrol import backup
    s = song(owner); version(owner, s["id"])
    owner.post(f"{B}/api/backup")
    f = next((tmp_path / "backup" / "audio").iterdir())
    f.unlink(); f.write_bytes(b"corrupted")                       # replace the hard link with a damaged copy; the original is untouched
    n, problems = backup.restore(tmp_path / "backup", tmp_path / "fresh")
    assert n == 1 and len(problems) == 1 and "checksum mismatch" in problems[0]
