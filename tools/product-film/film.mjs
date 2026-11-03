#!/usr/bin/env node
// node film.mjs <storyboard.mjs> [capture|compile|score|stills|preview|draft|render|all] [--only=scene,scene] [--at=12.5,30]
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { capture } from "./lib/capture.mjs";
import { compile } from "./lib/compile.mjs";
import { dsl } from "./lib/dsl.mjs";
import { chapterFiles, writePlayer } from "./lib/player.mjs";
import { stills } from "./lib/stills.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PY = path.join(HERE, ".venv", "bin", "python");
const remotion = path.join(HERE, "node_modules", ".bin", "remotion");

const STAGES = ["capture", "compile", "score", "stills", "preview", "draft", "render", "all"];

function sh(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", cwd: HERE, ...opts });
  if (r.status !== 0) throw new Error(`${path.basename(cmd)} ${args[0] ?? ""} failed (exit ${r.status}).`);
}

function setup() {
  console.log("Browser for capturing the app…");
  sh("npx", ["playwright", "install", "--only-shell", "chromium"]);
  console.log("Python packages for the score…");
  sh("python3", ["-m", "venv", ".venv"]);
  sh(PY, ["-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", "requirements.txt"]);
  console.log("Ready. Try: npm run example");
}

/** The storyboard with every default filled in. */
export async function loadStoryboard(file) {
  const mod = await import(pathToFileURL(path.resolve(file)).href);
  const raw = typeof mod.default === "function" ? mod.default(dsl) : mod.default;
  const cfg = {
    ...raw,
    app: { viewport: { width: 1440, height: 810 }, pixelRatio: 2, colorScheme: "light", locale: "en-US", timezone: "UTC", ...raw.app },
    brand: { accent: "#0071e3", theme: "light", ...raw.brand },
    window: { chrome: "browser", ...raw.window },
    music: { bpm: 96, mood: "airy", gain: 1, ...raw.music },
    film: { fps: 60, scale: 1, autoCamera: true, autoZoom: 1.5, focusZoom: 2.0, typingSpeed: 24, maxTyping: 3.2, crf: 16, ...raw.film },
  };
  if (!cfg.app.url) throw new Error('The storyboard needs app.url, for example "http://localhost:3000".');
  if (!cfg.scenes?.length) throw new Error("The storyboard has no scenes.");
  if (!cfg.intro?.headline || !cfg.outro?.headline) throw new Error("The storyboard needs intro.headline and outro.headline.");
  const seen = new Set();
  for (const s of cfg.scenes) {
    if (!/^[a-z0-9-]+$/.test(s.id ?? "")) throw new Error(`Scene id "${s.id}": use lowercase letters, digits and hyphens.`);
    if (seen.has(s.id)) throw new Error(`Two scenes are called "${s.id}".`);
    if (!s.title) throw new Error(`Scene "${s.id}" has no title.`);
    seen.add(s.id);
  }
  return cfg;
}

/** Start the app if the storyboard says how, and wait for it. Returns a function that stops it. */
async function startApp(cfg, base) {
  const up = async () => {
    try {
      await fetch(cfg.app.url, { signal: AbortSignal.timeout(2000) });
      return true;
    } catch {
      return false;
    }
  };
  if (await up()) return () => {};
  if (!cfg.app.start) throw new Error(`Nothing answers at ${cfg.app.url}. Start your app, or add app.start: "npm run dev" to the storyboard.`);
  console.log(`  Starting the app: ${cfg.app.start}`);
  const child = spawn(cfg.app.start, { shell: true, cwd: path.resolve(base, cfg.app.cwd ?? "."), stdio: "ignore", detached: true });
  const stop = () => {
    try {
      process.kill(-child.pid);
    } catch {}
  };
  const deadline = Date.now() + (cfg.app.startTimeout ?? 120000);
  while (Date.now() < deadline) {
    if (await up()) return stop;
    await new Promise((r) => setTimeout(r, 500));
  }
  stop();
  throw new Error(`The app did not answer at ${cfg.app.url} in time.`);
}

function brandFiles(cfg, base, pub) {
  if (cfg.brand.logo) {
    const src = path.resolve(base, cfg.brand.logo);
    const name = `brand-logo${path.extname(src)}`;
    fs.copyFileSync(src, path.join(pub, name));
    cfg.brand.logo = name;
  }
  if (cfg.music.file) {
    const src = path.resolve(base, cfg.music.file);
    fs.copyFileSync(src, path.join(pub, `track${path.extname(src)}`));
  }
}

function score(work) {
  if (!fs.existsSync(PY)) throw new Error("Run `npm run setup` first: the score needs its Python packages.");
  sh(PY, [path.join(HERE, "score", "score.py"), path.join(work, "public", "timeline.json"), path.join(work, "public")]);
}

function render(cfg, work, out, { draft = false } = {}) {
  const args = ["render", "src/index.ts", "Film", out, `--public-dir=${path.join(work, "public")}`, "--codec=h264", "--color-space=bt709", "--pixel-format=yuv420p", "--audio-codec=aac", "--audio-bitrate=256k", "--image-format=jpeg", "--log=warn", "--timeout=180000"]; // one slow frame on a busy machine shouldn't end a long render
  if (cfg.film.concurrency) args.push(`--concurrency=${cfg.film.concurrency}`);
  if (draft) args.push("--crf=26", "--jpeg-quality=85", "--every-nth-frame=2", "--scale=0.5", "--x264-preset=veryfast");
  else args.push(`--crf=${cfg.film.crf}`, "--jpeg-quality=96", `--scale=${cfg.film.scale}`, "--x264-preset=medium");
  sh(remotion, args);
}

/** Remotion's bundled ffmpeg is trimmed and can't read chapter files; this one comes from the Python packages. */
function ffmpegPath() {
  const r = spawnSync(PY, ["-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"], { encoding: "utf8" });
  if (r.status !== 0) throw new Error("Run `npm run setup` first: adding chapters needs its Python packages.");
  return r.stdout.trim();
}

/** Chapters inside the file, the moov atom first so it starts playing at once, and the player page next to it. */
function finish(tl, work, out) {
  const { webvtt, youtube, ffmeta } = chapterFiles(tl);
  const stem = out.replace(/\.mp4$/, "");
  fs.writeFileSync(`${stem}.chapters.vtt`, webvtt);
  fs.writeFileSync(`${stem}.chapters.txt`, youtube);
  const metaFile = path.join(work, "chapters.ffmeta");
  fs.writeFileSync(metaFile, ffmeta);
  const temp = `${stem}.tmp.mp4`;
  sh(ffmpegPath(), ["-y", "-v", "error", "-i", out, "-i", metaFile, "-map", "0", "-map_metadata", "1", "-map_chapters", "1", "-c", "copy", "-movflags", "+faststart", temp]);
  fs.renameSync(temp, out);
  writePlayer(`${stem}.html`, tl, path.basename(out));
}

async function main() {
  const [first, second, ...rest] = process.argv.slice(2);
  if (first === "setup") return setup();
  if (!first || first === "--help") {
    console.log("node film.mjs setup\nnode film.mjs <storyboard.mjs> [capture|compile|score|stills|preview|draft|render|all] [--only=scene,scene] [--at=seconds,seconds]\nThe guide is in README.md.");
    return;
  }
  const stage = second ?? "all";
  if (!STAGES.includes(stage)) throw new Error(`Unknown stage "${stage}". Stages: ${STAGES.join(", ")}.`);
  const onlyArg = rest.find((a) => a.startsWith("--only="));
  const only = onlyArg ? onlyArg.slice(7).split(",") : undefined;
  const atArg = rest.find((a) => a.startsWith("--at="));
  const at = atArg ? atArg.slice(5).split(",").map(Number) : undefined;

  const file = path.resolve(first);
  const base = path.dirname(file);
  const name = path.basename(file).replace(/\.m?js$/, "").replace(/\.film$/, "");
  const cfg = await loadStoryboard(file);
  const work = path.join(base, ".film", name);
  const pub = path.join(work, "public");
  fs.mkdirSync(pub, { recursive: true });
  const outName = cfg.output ?? `${cfg.brand.name?.toLowerCase().replace(/[^a-z0-9]+/g, "-") || name}-film.mp4`;
  const out = path.resolve(base, outName);
  brandFiles(cfg, base, pub);

  const runCompile = () => (console.log("Compiling the timeline…"), compile(cfg, { workDir: work }));

  if (stage === "capture" || stage === "all") {
    console.log(`Capturing ${cfg.app.url}…`);
    const stop = await startApp(cfg, base);
    try {
      await capture(cfg, { workDir: work, only });
    } finally {
      stop();
    }
  }
  if (stage === "capture") return;
  const tl = runCompile();
  if (stage === "compile") return;

  // The score is written to the timeline, so it follows any change in timing.
  const scoreKeyFile = path.join(work, "score.key");
  const scoreKey = JSON.stringify([tl.arrangement, tl.bpm, tl.duration, tl.cues, tl.music]);
  const scoreIsCurrent = fs.existsSync(scoreKeyFile) && fs.readFileSync(scoreKeyFile, "utf8") === scoreKey;
  if (stage === "score" || !scoreIsCurrent) {
    console.log("Scoring…");
    score(work);
    fs.writeFileSync(scoreKeyFile, scoreKey);
  }
  if (stage === "score") return;

  if (stage === "stills") {
    await stills(tl, { entry: path.join(HERE, "src", "index.ts"), publicDir: pub, outDir: path.join(work, "stills"), at });
    return;
  }
  if (stage === "preview") {
    sh(remotion, ["studio", "src/index.ts", `--public-dir=${pub}`]);
    return;
  }
  if (stage === "draft") {
    const draftOut = out.replace(/\.mp4$/, ".draft.mp4");
    console.log("Rendering a quick draft…");
    render(cfg, work, draftOut, { draft: true });
    console.log(`Draft: ${draftOut}`);
    return;
  }
  console.log(`Rendering at ${cfg.film.fps} fps…`);
  render(cfg, work, out);
  finish(tl, work, out);
  const mb = fs.statSync(out).size / 1e6;
  console.log(`\nFilm:   ${out} (${mb.toFixed(0)} MB)\nPlayer: ${out.replace(/\.mp4$/, ".html")}\nChapters for video sites: ${out.replace(/\.mp4$/, ".chapters.txt")}`);
}

main().catch((error) => {
  console.error(`\n${error.message}`);
  process.exit(1);
});
