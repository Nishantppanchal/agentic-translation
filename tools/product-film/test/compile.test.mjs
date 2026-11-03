import assert from "node:assert/strict";
import { test } from "node:test";
import { buildTimeline, windowLayout } from "../lib/compile.mjs";
import { chapterFiles } from "../lib/player.mjs";

const cfg = (over = {}) => ({
  app: { viewport: { width: 1440, height: 810 } },
  brand: { accent: "#0071e3", theme: "light" },
  window: { chrome: "browser" },
  music: { bpm: 96, gain: 1 },
  film: { fps: 60, autoCamera: true, autoZoom: 1.5, focusZoom: 2, typingSpeed: 24, maxTyping: 3.2 },
  intro: { headline: "Hello", accent: "there." },
  outro: { headline: "Good", accent: "bye." },
  scenes: [
    { id: "a", title: "First scene title here" },
    { id: "b", title: "Second", body: "With a line of body text under it" },
  ],
  ...over,
});
const rect = { x: 600, y: 300, w: 120, h: 40 };
const manifests = {
  a: [
    { type: "cut", src: "a/1.png" },
    { type: "click", rect, x: 660, y: 320, before: "a/2.png", after: "a/3.png" },
    { type: "type", rect, x: 660, y: 320, before: "a/4.png", frames: ["a/5.png", "a/6.png", "a/7.png"], chars: 4 },
    { type: "focus", rect, src: "a/8.png", hold: 1.2 },
  ],
  b: [
    { type: "cut", src: "b/1.png" },
    { type: "scroll", frames: ["b/2.png", "b/3.png"], seconds: 1 },
    { type: "spotlight", rect, src: "b/4.png", hold: 1, note: "A short note" },
    { type: "pull" },
  ],
};

test("every scene starts on a downbeat and lasts whole bars", () => {
  const tl = buildTimeline(cfg(), manifests);
  for (const s of tl.titles) {
    assert.ok(Math.abs((s.t0 / tl.bar) % 1) < 1e-6 || Math.abs((s.t0 / tl.bar) % 1) > 1 - 1e-6, `${s.id} starts at ${s.t0}`);
    assert.ok(Math.abs(((s.t1 - s.t0) / tl.bar) % 1) < 1e-3 || Math.abs(((s.t1 - s.t0) / tl.bar) % 1) > 1 - 1e-3);
  }
  assert.equal(tl.arrangement.length * tl.bar, tl.outro.t1);
});

test("nothing is scheduled to run backwards or past the end", () => {
  const tl = buildTimeline(cfg(), manifests);
  for (const list of [tl.shots, tl.camera]) {
    for (let i = 1; i < list.length; i++) assert.ok(list[i].t >= list[i - 1].t);
  }
  for (const s of tl.shots) assert.ok(s.t < tl.duration);
  for (const [i, s] of tl.titles.entries()) {
    const lastMove = tl.camera.filter((k) => k.t > s.t0 && k.t <= s.t1 && k.v.z !== 1).at(-1);
    if (lastMove) assert.ok(lastMove.t <= s.t1, `scene ${i} camera overruns`);
  }
});

test("a scene gets time to read its words", () => {
  const long = cfg({ scenes: [{ id: "a", title: "One two three four five six seven eight", body: "Nine ten eleven twelve thirteen fourteen fifteen sixteen" }, { id: "b", title: "Short" }] });
  const tl = buildTimeline(long, { a: [{ type: "cut", src: "a/1.png" }], b: [{ type: "cut", src: "b/1.png" }] });
  const first = tl.titles[0];
  assert.ok(first.openEnd - first.t0 >= 16 / 3.5, `${first.openEnd - first.t0}s for 16 words`);
});

test("the music is told where the clicks and scenes are", () => {
  const tl = buildTimeline(cfg(), manifests);
  assert.equal(tl.cues.click.length, 2);
  assert.equal(tl.cues.key.length, 2);
  assert.deepEqual(tl.cues.scene, [tl.titles[1].t0, tl.outro.t0]);
  assert.equal(tl.arrangement[0], "intro");
  assert.equal(tl.arrangement.at(-1), "outro");
});

test("the camera stays on the window", () => {
  const c = cfg();
  const tl = buildTimeline(c, manifests);
  const w = windowLayout(c);
  for (const { v } of tl.camera) {
    assert.ok(v.cx >= w.x - 40 && v.cx <= w.x + w.w + 40);
    assert.ok(v.z >= 1 && v.z <= c.film.focusZoom);
  }
});

test("long copy is called out", () => {
  const tl = buildTimeline(cfg({ scenes: [{ id: "a", title: "one two three four five six seven eight nine ten" }, { id: "b", title: "x" }] }), { a: [{ type: "cut", src: "a" }], b: [{ type: "cut", src: "b" }] });
  assert.match(tl.warnings[0], /ten|10 words/);
});

test("a scene with no capture is an error that names it", () => {
  assert.throws(() => buildTimeline(cfg(), { a: manifests.a }), /Scene "b" has not been captured/);
});

test("chapter files list every chapter", () => {
  const tl = buildTimeline(cfg(), manifests);
  const { webvtt, youtube, ffmeta } = chapterFiles(tl);
  assert.equal(youtube.trim().split("\n").length, tl.chapters.length);
  assert.ok(youtube.startsWith("0:00 Intro"));
  assert.ok(webvtt.startsWith("WEBVTT"));
  assert.equal(ffmeta.match(/\[CHAPTER\]/g).length, tl.chapters.length);
});
