// Stage 2: turn the storyboard and the captured steps into timeline.json, every moment of the film as data.
// The film (src/) and the score (score/) both read it, which is what keeps picture and music on the same beat.
//
// Every scene starts on a downbeat and lasts whole bars. A scene is always at least long enough to read its words.
import fs from "node:fs";
import path from "node:path";

export const FRAME = { width: 1920, height: 1080 };
const READING_WPS = 3.5; // words a second, unhurried
const CHROME = { browser: 46, plain: 0 };

const words = (s) => (s ? s.trim().split(/\s+/).length : 0);
const readingTime = (...texts) => 0.5 + texts.reduce((n, s) => n + words(s), 0) / READING_WPS;
const round = (v) => Math.round(v * 1000) / 1000;

/** Where the app window sits in the 1920 × 1080 frame when the camera is at rest. */
export function windowLayout(cfg) {
  const chrome = CHROME[cfg.window.chrome] ?? 0;
  const { width: appW, height: appH } = cfg.app.viewport;
  const top = 214;
  const bottom = 44;
  const maxH = FRAME.height - top - bottom - chrome;
  const w = Math.min(1560, (maxH * appW) / appH);
  const h = (w * appH) / appW;
  return { x: (FRAME.width - w) / 2, y: top, w: round(w), h: round(h), chrome, s: round(w / appW), appW, appH };
}

function makeCamera(win) {
  const { width: W, height: H } = FRAME;
  const fullH = win.h + win.chrome;
  const rest = { cx: W / 2, cy: H / 2, z: 1 };
  const clampView = (cx, cy, z) => {
    const m = 28;
    const hw = W / 2 / z;
    const hh = H / 2 / z;
    const clampAxis = (c, lo, hi, half) => (hi - lo + 2 * m <= 2 * half ? (lo + hi) / 2 : Math.min(hi + m - half, Math.max(lo - m + half, c)));
    return { cx: round(clampAxis(cx, win.x, win.x + win.w, hw)), cy: round(clampAxis(cy, win.y, win.y + fullH, hh)), z: round(z) };
  };
  /** The camera that frames an app-space rectangle, no closer than it fits and no closer than maxZoom. */
  const frameRect = (rect, maxZoom) => {
    const a = toWorld(win, rect.x, rect.y);
    const w = rect.w * win.s;
    const h = rect.h * win.s;
    const z = Math.max(1.12, Math.min(maxZoom, (W * 0.74) / Math.max(w, 1), (H * 0.66) / Math.max(h, 1)));
    return clampView(a.x + w / 2, a.y + h / 2, z);
  };
  const seesRect = (cam, rect) => {
    const a = toWorld(win, rect.x, rect.y);
    const hw = W / 2 / cam.z;
    const hh = H / 2 / cam.z;
    const m = 60 / cam.z;
    return a.x > cam.cx - hw + m && a.x + rect.w * win.s < cam.cx + hw - m && a.y > cam.cy - hh + m && a.y + rect.h * win.s < cam.cy + hh - m;
  };
  return { rest, frameRect, seesRect };
}

const toWorld = (win, x, y) => ({ x: round(win.x + x * win.s), y: round(win.y + win.chrome + y * win.s) });

/** The moves of one scene, from `t` on. `extra` stretches the opening look and the closing rest to fill the bar. */
function layScene(scene, events, win, camera, t0, tl, extra, cfg) {
  const opening = Math.max(1.7, readingTime(scene.title, scene.body)) + extra.open;
  let t = t0;
  let cam = camera.rest;
  const cue = (name, at) => tl.cues[name].push(round(at));
  const moveCam = (at, target, seconds = 1.15) => {
    tl.camera.push({ t: round(at), v: cam });
    tl.camera.push({ t: round(at + seconds), v: target });
    cam = target;
  };
  const addShot = (at, src, fade) => tl.shots.push({ t: round(at), src, fade });
  const addNote = (start, end, text) => text && tl.notes.push({ t0: round(start), t1: round(end), text });
  const autoCam = (rect, at, opt) => {
    if (opt === false || !cfg.film.autoCamera) return 0;
    if (cam.z > 1.02 && camera.seesRect(cam, rect)) return 0;
    moveCam(at, camera.frameRect({ x: rect.x - 120, y: rect.y - 90, w: rect.w + 240, h: rect.h + 180 }, cfg.film.autoZoom));
    return 0.45; // the cursor sets off when the camera is under way
  };
  let pointer = null; // where the cursor is in this scene; it enters from just beside its first target
  const glide = (x, y, seconds, straight = false) => {
    const p = toWorld(win, x, y);
    const from = pointer ?? { x: p.x + 170, y: p.y + 120 };
    tl.cursor.push({ t: round(t), move: seconds, x0: from.x, y0: from.y, x: p.x, y: p.y, straight, fadeIn: !pointer });
    pointer = p;
    t += seconds;
    return p;
  };
  const glideTime = (x, y) => {
    if (!pointer) return 0.85;
    const p = toWorld(win, x, y);
    return Math.max(0.55, Math.min(1.05, 0.45 + Math.hypot(p.x - pointer.x, p.y - pointer.y) / 1600));
  };

  // the previous scene's pull-back lands at t0 + 0.2
  tl.camera.push({ t: round(t0 + 0.2), v: cam });
  let firstCut = true;
  for (const e of events) {
    switch (e.type) {
      case "cut":
        addShot(t, e.src, firstCut ? 0.5 : 0.4);
        if (firstCut) {
          firstCut = false;
          t += opening;
        } else t += 0.5;
        t += e.hold ?? 0;
        break;
      case "click":
      case "hover":
      case "type": {
        t += autoCam(e.rect, t, e.camera);
        const start = t;
        const travel = glideTime(e.x, e.y);
        addShot(t + travel * 0.75, e.before ?? e.src, 0.14); // its hover state, as the cursor arrives
        const p = glide(e.x, e.y, travel);
        if (e.type === "hover") {
          t += e.hold ?? 0.9;
          addNote(start, t, e.note);
          break;
        }
        tl.clicks.push({ t: round(t), x: p.x, y: p.y });
        cue("click", t);
        t += 0.14;
        if (e.type === "click") {
          addShot(t, e.after, 0.22);
          t += 0.3 + (e.hold ?? 0.85);
          addNote(start, t, e.note);
          break;
        }
        const seconds = Math.min(cfg.film.maxTyping, e.chars / (e.cps ?? cfg.film.typingSpeed));
        e.frames.forEach((src, i) => {
          const at = t + (seconds * i) / Math.max(1, e.frames.length - 1);
          addShot(at, src, 0);
          if (i) cue("key", at);
        });
        t += seconds + (e.hold ?? 0.5);
        addNote(start, t, e.note);
        break;
      }
      case "press":
        if (e.show) tl.keys.push({ t0: round(t - 0.1), t1: round(t + 1.0), label: e.key });
        cue("click", t);
        t += 0.12;
        addShot(t, e.after, 0.25);
        t += 0.3 + (e.hold ?? 0.8);
        break;
      case "scroll":
        e.frames.forEach((src, i) => addShot(t + (e.seconds * i) / e.frames.length, src, 0));
        t += e.seconds + (e.hold ?? 0.5);
        break;
      case "drag": {
        const travel = glideTime(e.from.x, e.from.y);
        addShot(t + travel * 0.75, e.before, 0.14);
        const a = glide(e.from.x, e.from.y, travel);
        tl.clicks.push({ t: round(t), x: a.x, y: a.y });
        cue("click", t);
        t += 0.14;
        e.frames.forEach((src, i) => addShot(t + (e.seconds * i) / e.frames.length, src, 0));
        glide(e.to.x, e.to.y, e.seconds, true);
        addShot(t, e.after, 0.2);
        cue("click", t);
        t += 0.3 + (e.hold ?? 0.7);
        break;
      }
      case "lapse": {
        const total = e.times.at(-1) || 1;
        const seconds = e.seconds ?? Math.min(total, 4);
        const start = t;
        e.frames.forEach((src, i) => addShot(t + (e.times[i] / total) * seconds, src, Math.min(0.18, seconds / e.frames.length)));
        t += seconds + (e.hold ?? 0.6);
        addNote(start, t, e.note);
        break;
      }
      case "focus":
      case "spotlight": {
        addShot(t, e.src, 0.3);
        const start = t;
        moveCam(t, camera.frameRect(pad(e.rect, 28), e.zoom ?? cfg.film.focusZoom));
        const look = Math.max(e.hold ?? 1.6, e.note ? readingTime(e.note) : 0);
        const seconds = 1.15 + look;
        if (e.type === "spotlight") tl.spots.push({ t0: round(t + 0.35), t1: round(t + seconds), rect: appRect(e.rect) });
        else if (e.ring) tl.rings.push({ t0: round(t + 0.55), t1: round(t + seconds), rect: appRect(e.rect) });
        t += seconds;
        addNote(start + 0.5, t, e.note);
        break;
      }
      case "pull":
        moveCam(t, camera.rest);
        t += 1.15 + (e.hold ?? 0.4);
        break;
      case "hold":
        t += e.seconds;
        break;
      default:
        throw new Error(`Unknown captured step: ${e.type}`);
    }
  }
  if (cam.z !== 1) t += 0.75; // room for the pull-back before the next headline
  t += extra.close;
  return { end: t, cam };
}

const pad = (r, m) => ({ x: r.x - m, y: r.y - m, w: r.w + 2 * m, h: r.h + 2 * m });
const appRect = (r) => ({ x: round(r.x), y: round(r.y), w: round(r.w), h: round(r.h) });

function emptyLists() {
  return { shots: [], camera: [], cursor: [], clicks: [], spots: [], rings: [], notes: [], keys: [], cues: { click: [], key: [], scene: [] } };
}

/** Pure: storyboard + captured events → timeline. Separate from disk so it can be tested. */
export function buildTimeline(cfg, manifests) {
  const bar = 240 / cfg.music.bpm;
  const win = windowLayout(cfg);
  const camera = makeCamera(win);
  const warnings = [];
  const tl = {
    ...emptyLists(),
    fps: cfg.film.fps,
    frame: FRAME,
    bpm: cfg.music.bpm,
    bar,
    brand: cfg.brand,
    window: { ...win, chrome: cfg.window.chrome, chromeHeight: win.chrome, address: cfg.window.address },
    music: cfg.music,
    titles: [],
    chapters: [],
    arrangement: [],
  };

  // Intro: enough bars to read the line, then the dive into the app on a downbeat.
  const introBars = Math.ceil((readingTime(cfg.intro.headline, cfg.intro.accent, cfg.intro.sub) + 3.2) / bar);
  const introEnd = introBars * bar;
  tl.intro = { t0: 0, t1: introEnd, dive: 1.5, ...cfg.intro };
  tl.chapters.push({ t: 0, title: "Intro" });
  for (let i = 0; i < introBars; i++) tl.arrangement.push("intro");

  let start = introEnd;
  cfg.scenes.forEach((scene, index) => {
    if (words(scene.title) > 9) warnings.push(`Scene "${scene.id}": the title has ${words(scene.title)} words. Nine at most fits on one line and reads like a headline.`);
    if (words(scene.body) > 18) warnings.push(`Scene "${scene.id}": the body has ${words(scene.body)} words. Keep it under 18.`);
    const events = manifests[scene.id];
    if (!events) throw new Error(`Scene "${scene.id}" has not been captured yet.`);

    // A first pass finds the length, the second fills the scene out to a whole number of bars.
    const trial = emptyLists();
    const { end } = layScene(scene, events, win, camera, start, trial, { open: 0, close: 0.35 }, cfg);
    const bars = Math.max(scene.minBars ?? 2, Math.ceil((end - start) / bar - 1e-6));
    const slack = bars * bar - (end - start);
    layScene(scene, events, win, camera, start, tl, { open: slack * 0.45, close: 0.35 + slack * 0.55 }, cfg);

    const t1 = start + bars * bar;
    tl.titles.push({ id: scene.id, t0: round(start), t1: round(t1), eyebrow: scene.eyebrow, title: scene.title, body: scene.body, openEnd: round(start + Math.max(1.7, readingTime(scene.title, scene.body)) + slack * 0.45) });
    tl.chapters.push({ t: round(start), title: scene.chapter ?? scene.eyebrow ?? scene.title });
    if (index > 0) tl.cues.scene.push(round(start));
    tl.cursor.filter((c) => c.t >= start && c.t < t1).forEach((c) => (c.sceneEnd = round(t1 - 0.5)));
    const energy = scene.energy ?? defaultEnergy(index, cfg.scenes.length);
    for (let i = 0; i < bars; i++) tl.arrangement.push(energy);
    // back to the whole window for the next scene's headline
    const finalCam = tl.camera.at(-1).v;
    if (finalCam.z !== 1) {
      tl.camera.push({ t: round(t1 - 0.95), v: finalCam });
      tl.camera.push({ t: round(t1 + 0.2), v: camera.rest });
    }
    start = t1;
  });

  const outroBars = Math.max(4, Math.ceil((readingTime(cfg.outro.headline, cfg.outro.accent, cfg.outro.sub) + 3.4) / bar));
  tl.outro = { t0: round(start), t1: round(start + outroBars * bar), collapse: 1.3, ...cfg.outro };
  tl.cues.scene.push(round(start));
  tl.chapters.push({ t: round(start), title: cfg.outro.chapter ?? "Outro" });
  for (let i = 0; i < outroBars; i++) tl.arrangement.push("outro");
  // Two beats of ring-out before the picture ends
  tl.duration = round(tl.outro.t1 + bar / 2);
  if (tl.arrangement.includes("high") && tl.arrangement.length > 10) {
    const firstOutro = tl.arrangement.indexOf("outro");
    if (firstOutro >= 2) tl.arrangement[firstOutro - 1] = "build";
  }

  tl.audio = { music: cfg.music.file ? `track${path.extname(cfg.music.file)}` : "music.wav", sfx: "sfx.wav", musicGain: cfg.music.gain };
  tl.shots.sort((a, b) => a.t - b.t);
  tl.camera.sort((a, b) => a.t - b.t);
  tl.warnings = warnings;
  return tl;
}

/** The shape of a film: quiet, rise, a breath in the middle, full, then home. */
function defaultEnergy(index, count) {
  const p = (index + 0.5) / count;
  if (p < 0.25) return "low";
  if (p < 0.5) return "mid";
  if (Math.abs(p - 0.55) < 0.5 / count && count >= 5) return "breath";
  return "high";
}

export function compile(cfg, { workDir }) {
  const manifests = {};
  for (const scene of cfg.scenes) {
    const file = path.join(workDir, "public", scene.id, "manifest.json");
    if (!fs.existsSync(file)) throw new Error(`Scene "${scene.id}" has no capture. Run the capture stage first.`);
    manifests[scene.id] = JSON.parse(fs.readFileSync(file, "utf8"));
  }
  const tl = buildTimeline(cfg, manifests);
  fs.writeFileSync(path.join(workDir, "public", "timeline.json"), JSON.stringify(tl));
  for (const w of tl.warnings) console.warn(`  Note: ${w}`);
  const mm = Math.floor(tl.duration / 60);
  const ss = String(Math.round(tl.duration % 60)).padStart(2, "0");
  console.log(`  ${cfg.scenes.length} scenes, ${mm}:${ss}, ${tl.shots.length} frames placed, ${tl.arrangement.length} bars at ${cfg.music.bpm} BPM`);
  return tl;
}
