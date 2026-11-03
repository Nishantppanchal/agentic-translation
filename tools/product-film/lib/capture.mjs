// Stage 1: drive the real app and save what each step looks like, with the position of everything the film points at.
//
// Nothing here is a screen recording. Each state is a 2× screenshot, so the film's motion can be perfectly smooth and
// the film's timing can change without touching the app again.
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const easeInOut = (p) => (p < 0.5 ? 4 * p * p * p : 1 - (-2 * p + 2) ** 3 / 2);

class Recorder {
  constructor(page, dir, sceneId, viewport) {
    Object.assign(this, { page, dir, sceneId, viewport, n: 0, events: [] });
  }

  async shot({ caret = false, animations = "disabled" } = {}) {
    const name = `${String(++this.n).padStart(4, "0")}.png`;
    await this.page.screenshot({ path: path.join(this.dir, name), animations, caret: caret ? "initial" : "hide" });
    return `${this.sceneId}/${name}`;
  }

  /** Wait until the page stops changing (fonts, data, transitions), up to a limit: spinners never settle. */
  async settle(limit = 3500) {
    const { page } = this;
    await page.waitForLoadState("networkidle", { timeout: Math.min(limit, 1500) }).catch(() => {});
    await page.evaluate(() => document.fonts?.ready).catch(() => {});
    const end = Date.now() + limit;
    let last = null;
    while (Date.now() < end) {
      const now = await page.screenshot({ type: "jpeg", quality: 40, scale: "css" });
      if (last && now.equals(last)) return true;
      last = now;
      await sleep(140);
    }
    return false;
  }

  locator(target) {
    return typeof target === "function" ? target(this.page) : this.page.locator(target).first();
  }

  /** The target on screen and measured. */
  async find(target, timeout = 15000) {
    const loc = this.locator(target);
    await loc.waitFor({ state: "visible", timeout });
    const was = await loc.boundingBox();
    await loc.scrollIntoViewIfNeeded({ timeout });
    await this.settle(1200);
    const now = await loc.boundingBox();
    // It had to scroll into view: show the new position before the cursor heads for it.
    if (was && now && Math.abs(was.y - now.y) + Math.abs(was.x - now.x) > 2) this.push({ type: "cut", src: await this.shot() });
    const box = await loc.boundingBox();
    if (!box) throw new Error("the target has no size on screen");
    return {
      loc,
      rect: { x: box.x, y: box.y, w: box.width, h: box.height },
      x: box.x + box.width / 2,
      y: box.y + box.height / 2,
    };
  }

  push(event) {
    this.events.push(event);
  }

  async goto(step, appUrl) {
    await this.page.goto(new URL(step.url, appUrl).href, { waitUntil: "domcontentloaded" });
    await this.settle();
    this.push({ type: "cut", src: await this.shot(), hold: step.hold });
  }

  async click(step) {
    const { rect, x, y } = await this.find(step.target);
    await this.page.mouse.move(x, y);
    await sleep(140);
    const before = await this.shot();
    await this.page.mouse.down();
    await this.page.mouse.up();
    await this.settle(step.settle);
    const after = await this.shot();
    this.push({ type: "click", rect, x, y, before, after, hold: step.hold, camera: step.camera, note: step.note });
  }

  async hover(step) {
    const { rect, x, y } = await this.find(step.target);
    await this.page.mouse.move(x, y);
    await this.settle(1200);
    this.push({ type: "hover", rect, x, y, src: await this.shot(), hold: step.hold, camera: step.camera, note: step.note });
  }

  async type(step) {
    const { rect, x, y } = await this.find(step.target);
    await this.page.mouse.move(x, y);
    await sleep(100);
    const before = await this.shot();
    await this.page.mouse.down();
    await this.page.mouse.up();
    await sleep(120);
    const every = step.every ?? 2;
    const frames = [await this.shot({ caret: true })];
    const chars = [...step.text];
    for (let i = 0; i < chars.length; i += every) {
      await this.page.keyboard.type(chars.slice(i, i + every).join(""));
      await sleep(30);
      frames.push(await this.shot({ caret: true }));
    }
    this.push({ type: "type", rect, x, y, before, frames, chars: chars.length, cps: step.cps, hold: step.hold, camera: step.camera, note: step.note });
  }

  async press(step) {
    await this.page.keyboard.press(step.key);
    await this.settle(step.settle);
    this.push({ type: "press", key: step.key, show: step.show, after: await this.shot(), hold: step.hold });
  }

  async scroll(step) {
    const seconds = step.seconds ?? 1.4;
    const count = Math.max(8, Math.round(seconds * 24));
    const within = step.within ? this.locator(step.within) : null;
    const read = () =>
      within
        ? within.evaluate((el) => el.scrollTop)
        : this.page.evaluate(() => window.scrollY);
    const write = (v) =>
      within
        ? within.evaluate((el, top) => {
            el.style.scrollBehavior = "auto";
            el.scrollTop = top;
          }, v)
        : this.page.evaluate((top) => window.scrollTo({ top, behavior: "instant" }), v);
    const from = await read();
    let to = from + (step.by ?? 0);
    if (step.to) {
      const offset = await this.locator(step.to).evaluate((el, hasContainer) => el.getBoundingClientRect().top + (hasContainer ? 0 : window.scrollY), !!within);
      if (within) {
        const top = await within.evaluate((el) => el.getBoundingClientRect().top);
        to = from + offset - top - (step.margin ?? 24);
      } else to = offset - (step.margin ?? 24);
    }
    const positions = Array.from({ length: count }, (_, i) => from + (to - from) * easeInOut((i + 1) / count));
    const frames = [];
    for (const p of positions) {
      await write(p);
      await sleep(16);
      frames.push(await this.shot());
    }
    const moved = Math.abs((await read()) - from);
    if (moved < 4) console.warn(`  Note: scene "${this.sceneId}": the scroll moved nothing. If the page scrolls inside a panel, name it with {within: "..."}.`);
    this.push({ type: "scroll", frames, seconds, hold: step.hold });
  }

  async drag(step) {
    const a = await this.find(step.from);
    const b = await this.find(step.to);
    await this.page.mouse.move(a.x, a.y);
    await sleep(100);
    const before = await this.shot();
    await this.page.mouse.down();
    const count = step.frames ?? 24;
    const frames = [];
    for (let i = 1; i <= count; i++) {
      const p = easeInOut(i / count);
      await this.page.mouse.move(a.x + (b.x - a.x) * p, a.y + (b.y - a.y) * p);
      await sleep(16);
      frames.push(await this.shot());
    }
    await this.page.mouse.up();
    await this.settle(step.settle);
    const after = await this.shot();
    this.push({ type: "drag", from: { x: a.x, y: a.y }, to: { x: b.x, y: b.y }, before, frames, after, seconds: step.seconds ?? 1.2, hold: step.hold });
  }

  async wait(step) {
    if (typeof step.what === "number") await sleep(step.what);
    else await this.locator(step.what).waitFor({ state: "visible", timeout: step.timeout ?? 120000 });
    await this.settle(step.settle);
    this.push({ type: "cut", src: await this.shot(), hold: step.hold });
  }

  async lapse(step) {
    const frames = [];
    const times = [];
    const every = step.every ?? 1000;
    const max = step.max ?? 240;
    const started = Date.now();
    const done = step.until ? this.locator(step.until) : null;
    for (let i = 0; i < max; i++) {
      frames.push(await this.shot({ animations: "allow" }));
      times.push((Date.now() - started) / 1000);
      if (done && (await done.isVisible().catch(() => false))) break;
      if (!done && step.forMs && Date.now() - started > step.forMs) break;
      await sleep(every);
    }
    await this.settle();
    frames.push(await this.shot());
    times.push((Date.now() - started) / 1000);
    this.push({ type: "lapse", frames, times, seconds: step.seconds, hold: step.hold, note: step.note });
  }

  async focus(step) {
    const { rect } = await this.find(step.target);
    this.push({ type: "focus", rect, src: await this.shot(), zoom: step.zoom, hold: step.hold, ring: step.ring, note: step.note });
  }

  async spotlight(step) {
    const { rect } = await this.find(step.target);
    this.push({ type: "spotlight", rect, src: await this.shot(), hold: step.hold, note: step.note });
  }

  async run(step) {
    await step.fn(this.page);
    await this.settle(step.settle);
    this.push({ type: "cut", src: await this.shot(), hold: step.hold });
  }
}

async function runScene(rec, scene, cfg) {
  if (scene.start) await rec.goto({ url: scene.start }, cfg.app.url);
  else {
    await rec.settle();
    rec.push({ type: "cut", src: await rec.shot() });
  }
  for (const [i, step] of (scene.steps ?? []).entries()) {
    try {
      switch (step.do) {
        case "goto":
          await rec.goto(step, cfg.app.url);
          break;
        case "pull":
          rec.push({ type: "pull", hold: step.hold });
          break;
        case "hold":
          rec.push({ type: "hold", seconds: step.seconds });
          break;
        default:
          await rec[step.do](step);
      }
    } catch (error) {
      const shotPath = path.join(rec.dir, `failed-step-${i + 1}.png`);
      await rec.page.screenshot({ path: shotPath }).catch(() => {});
      const what = step.target ?? step.what ?? step.key ?? "";
      throw new Error(`Scene "${scene.id}", step ${i + 1} (${step.do} ${typeof what === "function" ? "<locator>" : what}) failed: ${error.message.split("\n")[0]}\nWhat the page looked like: ${shotPath}`);
    }
  }
}

/** Capture every scene, or only the scenes in `only` (each of them needs its own `start`). */
export async function capture(cfg, { workDir, only }) {
  const shotsDir = path.join(workDir, "public");
  const { viewport } = cfg.app;
  const browser = await chromium.launch({ args: ["--hide-scrollbars", "--font-render-hinting=none", "--force-color-profile=srgb"] });
  try {
    const context = await browser.newContext({
      viewport,
      deviceScaleFactor: cfg.app.pixelRatio,
      colorScheme: cfg.app.colorScheme,
      locale: cfg.app.locale,
      timezoneId: cfg.app.timezone,
      storageState: cfg.app.storageState,
      reducedMotion: "no-preference",
    });
    if (cfg.app.css) {
      await context.addInitScript((css) => {
        const add = () => {
          const style = document.createElement("style");
          style.textContent = css;
          document.documentElement.appendChild(style);
        };
        if (document.documentElement) add();
        else document.addEventListener("DOMContentLoaded", add);
      }, cfg.app.css);
    }
    if (cfg.app.init) await cfg.app.init(context);
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));
    await page.goto(cfg.app.url, { waitUntil: "domcontentloaded", timeout: 60000 });
    if (cfg.app.setup) await cfg.app.setup(page);

    for (const scene of cfg.scenes) {
      if (only && !only.includes(scene.id)) continue;
      if (only && !scene.start) throw new Error(`Scene "${scene.id}" has no "start", so it can't be captured on its own.`);
      const dir = path.join(shotsDir, scene.id);
      fs.rmSync(dir, { recursive: true, force: true });
      fs.mkdirSync(dir, { recursive: true });
      const rec = new Recorder(page, dir, scene.id, viewport);
      const started = Date.now();
      await runScene(rec, scene, cfg);
      fs.writeFileSync(path.join(dir, "manifest.json"), JSON.stringify(rec.events, null, 1));
      console.log(`  ${scene.id}: ${rec.n} frames in ${((Date.now() - started) / 1000).toFixed(1)}s`);
    }
    if (pageErrors.length) console.warn(`  The app threw ${pageErrors.length} error(s) while capturing, the first: ${pageErrors[0]}`);
  } finally {
    await browser.close();
  }
}
