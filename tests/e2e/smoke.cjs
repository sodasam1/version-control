// Browser test: owner page, share page, A/B switching, loop, comments. Chromium via Playwright; needs ffmpeg and python with Flask.
//   VC_PY=/path/to/python node tests/e2e/smoke.cjs
// Fails on any console or page error (which includes Content-Security-Policy violations).
// What it cannot judge: how it sounds, and phones (iOS Safari). Those are for your ears and your iPhone.
const { spawn, execFileSync } = require("child_process");
const fs = require("fs"), os = require("os"), path = require("path"), assert = require("assert");
const { chromium } = require("playwright");
const PY = process.env.VC_PY || "python3", ROOT = path.resolve(__dirname, "..", ".."), PORT = 8192;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "vc-e2e-"));
const auth = path.join(tmp, "site-auth"), data = path.join(tmp, "data"), keys = path.join(ROOT, "app", "siteauth", "keys.py");
execFileSync(PY, [keys, "init", "--dir", auth, "--no-chown"]);
execFileSync(PY, [keys, "ensure-app", "--dir", auth, "--app", "versioncontrol", "--path", "/version-control", "--no-chown"]);
const cookie = execFileSync(PY, ["-c", `
import importlib.util as u, time, sys
sp = u.spec_from_file_location("k", "${keys}"); k = u.module_from_spec(sp); sp.loader.exec_module(k)
sys.path.insert(0, "${path.join(ROOT, "app")}")
from siteauth import make_token
print(make_token(k.derive(open("${auth}/master").read().strip(), "versioncontrol", 1), time.time()))`]).toString().trim();
const tones = [["Mix A", 330, 0], ["Mix B", 440, -8]];
for (const [name, hz, vol] of tones) execFileSync("ffmpeg", ["-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", `sine=frequency=${hz}:duration=6:sample_rate=44100`, "-af", `volume=${vol}dB,pan=stereo|c0=c0|c1=c0`, path.join(tmp, name + ".wav")]);
const server = spawn(PY, ["-m", "waitress", `--listen=127.0.0.1:${PORT}`, "wsgi:app"], { cwd: path.join(ROOT, "app"), stdio: "inherit", env: { ...process.env,
  VERSIONCONTROL_DATA_DIR: data, VERSIONCONTROL_BASE_PATH: "/version-control", VERSIONCONTROL_STATIC_DIR: path.join(ROOT, "static"),
  VERSIONCONTROL_SITE_KEY_FILE: path.join(auth, "keys", "versioncontrol.key"), VERSIONCONTROL_INSECURE_COOKIES: "1", VERSIONCONTROL_CONFIG: "/nonexistent" } });
const B = `http://127.0.0.1:${PORT}/version-control/`;
const step = (m) => console.log("ok  " + m);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  for (let i = 0; i < 80; i++) { try { if ((await fetch(B + "health")).ok) break; } catch (e) {} await sleep(100); }
  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  const errors = [];
  const watch = (p, who) => { p.on("console", (m) => { if (m.type() === "error") errors.push(who + " console: " + m.text()); }); p.on("pageerror", (e) => errors.push(who + " pageerror: " + e.message)); };
  try {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 900 } });
    await ctx.addCookies([{ name: "site_versioncontrol", value: cookie, url: B }]);
    const page = await ctx.newPage(); watch(page, "owner");
    await page.goto(B);
    page.once("dialog", (d) => d.accept("Night Drive"));
    await page.getByRole("button", { name: "New song" }).click();
    await page.waitForSelector("text=Upload new version");
    for (const [name] of tones) {
      await page.locator('input[type=file]').setInputFiles(path.join(tmp, name + ".wav"));
      await page.locator('input[placeholder^="Label"]').fill(name);
      await page.getByRole("button", { name: "Upload new version" }).click();
      await page.waitForFunction((n) => document.body.textContent.includes(n) && document.querySelectorAll(".vrow strong").length >= 1, name);
    }
    await page.waitForFunction(() => document.querySelectorAll(".vrow strong").length === 2);
    await page.waitForFunction(() => (document.body.textContent.match(/LUFS/g) || []).length >= 2 && !document.body.textContent.includes("measuring"), null, { timeout: 30000 });
    step("two versions uploaded, measured (waveform, loudness)");
    await page.locator('input[placeholder^="Who is it for"]').fill("Dana");
    await page.getByRole("button", { name: "Create link" }).click();
    await page.waitForSelector("text=Copy link");
    const url = await page.locator("a.btn", { hasText: "Open" }).last().getAttribute("href");
    step("a share link was created: " + url.replace(/s\/.*/, "s/<secret>"));

    // ---- a stranger opens the link ----
    const gctx = await browser.newContext({ viewport: { width: 390, height: 900 } });
    const g = await gctx.newPage(); watch(g, "guest");
    await g.goto(new URL(url, B).toString());
    await g.waitForSelector("button.ver");
    assert.strictEqual(await g.locator("button.ver").count(), 2);
    step("share page shows both versions to someone with no account");
    const overflow = await g.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 0, "sideways scroll on a phone: " + overflow);
    step("phone width: no sideways scroll");
    const dbg = () => g.evaluate(() => document.getElementById("app")._panel.compare.debug());
    await g.getByRole("button", { name: "Play", exact: true }).click();
    await g.waitForFunction(() => document.getElementById("app")._panel.compare.debug().times.every((t) => t > 0.3), null, { timeout: 8000 });
    let d = await dbg();
    assert.strictEqual(d.mode, "sync"); assert.deepStrictEqual(d.gains.map((x) => Math.round(x)), [1, 0]);
    step("play starts every version in lockstep, only the first is audible (gains " + JSON.stringify(d.gains) + ")");
    await g.locator("button.ver").nth(1).click();
    await g.waitForFunction(() => { const x = document.getElementById("app")._panel.compare.debug(); return x.gains[1] > 0.99 && x.gains[0] < 0.01; });
    d = await dbg();
    assert.ok(Math.abs(d.times[0] - d.times[1]) < 0.15, "versions drifted apart: " + d.times);
    assert.ok(!d.paused[0] && !d.paused[1] && d.playing);
    step("switching to B is instant: gains swap with no pause, versions stay within " + Math.round(Math.abs(d.times[0] - d.times[1]) * 1000) + " ms of each other");
    const before = d.position;
    await g.keyboard.press("1");
    await g.waitForFunction(() => document.getElementById("app")._panel.compare.debug().gains[0] > 0.99);
    d = await dbg();
    assert.ok(d.position >= before - 0.05, "position jumped back when switching");
    step("keyboard 1/2 switches too, and the position keeps going");

    // loudness match: B is 8 dB quieter, so with matching on, A is turned down to B's level
    await g.locator("#match").check();
    await g.waitForFunction(() => document.getElementById("app")._panel.compare.debug().gains[0] < 0.6);
    d = await dbg();
    assert.ok(d.gains[0] > 0.3 && d.gains[0] < 0.5, "expected about -8 dB (0.40), got " + d.gains[0]);
    step("match loudness turns the louder version down (gain " + d.gains[0] + " is about -8 dB) and never boosts");
    await g.locator("#match").uncheck();

    // loop A-B from the buttons, then exact loop
    await g.getByRole("button", { name: "Pause", exact: true }).click();
    await g.evaluate(() => document.getElementById("app")._panel.compare.seek(1));
    await g.getByRole("button", { name: "Set A" }).click();
    await g.evaluate(() => document.getElementById("app")._panel.compare.seek(3));
    await g.getByRole("button", { name: "Set B" }).click();
    await g.evaluate(() => document.getElementById("app")._panel.compare.seek(1));
    await g.getByRole("button", { name: "Play", exact: true }).click();
    await g.waitForFunction(() => document.getElementById("app")._panel.compare.debug().position > 2.5, null, { timeout: 8000 });
    await g.waitForFunction(() => { const p = document.getElementById("app")._panel.compare.debug().position; return p < 2.0 && p >= 0.9; }, null, { timeout: 8000 });
    step("the loop jumps back from B to A and keeps playing");
    await g.locator("#loop-exact").check();
    await g.waitForFunction(() => document.getElementById("app")._panel.compare.debug().exact === true, null, { timeout: 15000 });
    await sleep(1200);
    d = await dbg();
    assert.ok(d.position >= 0.95 && d.position <= 3.05 && d.playing, "exact loop position " + d.position);
    await g.locator("button.ver").nth(0).click();
    await g.waitForFunction(() => document.getElementById("app")._panel.compare.debug().gains[0] > 0.99);
    step("exact loop (sample-locked slices of both versions) plays and still switches");
    await g.getByRole("button", { name: "Pause", exact: true }).click();

    // blind mode hides the names
    await g.locator("#blind").check();
    assert.ok(!(await g.locator(".versions").textContent()).includes("Mix"));
    await g.locator("#blind").uncheck();
    assert.ok((await g.locator(".versions").textContent()).includes("Mix"));
    step("blind mode hides the version names and shows them again");

    // comments
    await g.evaluate(() => document.getElementById("app")._panel.compare.seek(2.5));
    await g.locator('input[placeholder="Your name"]').fill("Dana <b>D</b>");
    await g.locator("textarea").focus();
    await g.locator("textarea").fill('Love the drums <script>alert("x")</script> <img src=x onerror=alert(1)>');
    await g.getByRole("button", { name: "Post comment" }).click();
    await g.waitForSelector(".comments li[data-id]");
    const text = await g.locator(".comments li").first().textContent();
    assert.ok(text.includes("<script>alert") && text.includes("Dana <b>D</b>") && text.includes("0:02"));
    assert.strictEqual(await g.locator(".comments b, .comments script, .comments img").count(), 0);
    step("a comment with a name and HTML is posted at 0:02 and shown as plain text");
    await g.reload(); await g.waitForSelector(".comments li[data-id]");
    assert.ok((await g.locator(".comments li").first().textContent()).includes("Love the drums"));
    assert.ok(await g.locator(".comments li .actions").count() >= 1);
    step("it is still there after a reload, and its author can still edit or delete it");
    const other = await (await browser.newContext()).newPage(); watch(other, "other");
    await other.goto(new URL(url, B).toString()); await other.waitForSelector(".comments li[data-id]");
    assert.strictEqual(await other.locator(".comments li .actions").count(), 0);
    step("a different visitor sees the comment but cannot edit or delete it");
    // the owner sees it, can click its time, and delete it
    await page.reload(); await page.waitForSelector(".comments li[data-id]");
    page.once("dialog", (dl) => dl.accept());
    await page.locator(".comments li .actions button", { hasText: "Delete" }).first().click();
    await page.waitForFunction(() => document.querySelectorAll(".comments li[data-id]").length === 0);
    step("the owner can delete any comment");

    // a stranger has no way into the owner side
    assert.strictEqual((await fetch(B + "api/songs")).status, 401);
    assert.strictEqual((await fetch(B)).status, 401);
    step("a stranger cannot reach the owner pages or API");
    assert.deepStrictEqual(errors, [], "console/page errors:\n" + errors.join("\n"));
    step("no console or page errors (so no Content-Security-Policy violations)");
    console.log("ALL PASSED");
  } catch (e) { console.error("FAILED:", e.message, "\n", errors.join("\n")); process.exitCode = 1; }
  finally { await browser.close(); server.kill(); fs.rmSync(tmp, { recursive: true, force: true }); }
})();
