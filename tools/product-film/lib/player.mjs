// A page that plays the film with a chapter list, plus the chapter files for video sites and players.
import fs from "node:fs";

const clock = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const vtt = (t) => {
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${s.toFixed(3).padStart(6, "0")}`;
};
const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

export function chapterFiles(tl) {
  const list = tl.chapters;
  const webvtt = ["WEBVTT", ""];
  list.forEach((c, i) => webvtt.push(`${vtt(c.t)} --> ${vtt(list[i + 1]?.t ?? tl.duration)}`, c.title, ""));
  const youtube = list.map((c) => `${clock(c.t)} ${c.title}`).join("\n") + "\n";
  const ffmeta = [";FFMETADATA1"];
  list.forEach((c, i) => ffmeta.push("[CHAPTER]", "TIMEBASE=1/1000", `START=${Math.round(c.t * 1000)}`, `END=${Math.round((list[i + 1]?.t ?? tl.duration) * 1000)}`, `title=${c.title.replace(/([=;#\\])/g, "\\$1")}`));
  return { webvtt: webvtt.join("\n"), youtube, ffmeta: ffmeta.join("\n") + "\n" };
}

/** Self-contained: put it next to the video file and open it, or host the two together. */
export function writePlayer(file, tl, videoName) {
  const title = escapeHtml(tl.brand.name ?? "Product film");
  const items = tl.chapters
    .map((c, i) => `<li><button data-t="${c.t}" data-i="${i}"><time>${clock(c.t)}</time><span>${escapeHtml(c.title)}</span></button></li>`)
    .join("");
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<style>
  :root { color-scheme: light dark; --bg: #f5f5f7; --ink: #1d1d1f; --muted: #6e6e73; --on: rgba(0,0,0,.07); --accent: ${tl.brand.accent}; }
  @media (prefers-color-scheme: dark) { :root { --bg: #000; --ink: #f5f5f7; --muted: #a1a1a6; --on: rgba(255,255,255,.12); } }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.4 -apple-system, "Inter", "Helvetica Neue", sans-serif; }
  main { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 28px; max-width: 1480px; margin: auto; padding: 28px; align-items: start; }
  video { width: 100%; display: block; border-radius: 14px; background: #000; box-shadow: 0 30px 70px -30px rgba(0,0,0,.45); }
  ol { list-style: none; margin: 0; padding: 0; }
  button { all: unset; box-sizing: border-box; cursor: pointer; display: flex; gap: 12px; width: 100%; padding: 8px 12px; border-radius: 9px; color: var(--muted); }
  button:hover { color: var(--ink); }
  button:focus-visible { outline: 2px solid var(--accent); }
  button.on { background: var(--on); color: var(--ink); font-weight: 600; }
  time { font-variant-numeric: tabular-nums; opacity: .7; min-width: 34px; font-weight: 400; }
  small { display: block; color: var(--muted); padding: 14px 12px 0; }
  @media (max-width: 900px) { main { grid-template-columns: minmax(0, 1fr); padding: 16px; } }
</style>
</head>
<body>
<main>
  <video id="v" controls playsinline src="${encodeURI(videoName)}"></video>
  <nav aria-label="Chapters"><ol>${items}</ol><small>Click a chapter. ← → move between chapters, space plays.</small></nav>
</main>
<script>
  const v = document.getElementById("v");
  const buttons = [...document.querySelectorAll("button[data-t]")];
  const go = (i) => { const b = buttons[Math.max(0, Math.min(buttons.length - 1, i))]; v.currentTime = +b.dataset.t + 0.01; v.play(); };
  const current = () => { let c = 0; buttons.forEach((b, i) => { if (+b.dataset.t <= v.currentTime + 0.02) c = i; }); return c; };
  buttons.forEach((b, i) => b.addEventListener("click", () => go(i)));
  v.addEventListener("timeupdate", () => { const c = current(); buttons.forEach((b, i) => b.classList.toggle("on", i === c)); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") { e.preventDefault(); go(current() + 1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); go(current() - 1); }
    if (e.key === " " && e.target !== v) { e.preventDefault(); v.paused ? v.play() : v.pause(); }
  });
</script>
</body>
</html>
`;
  fs.writeFileSync(file, html);
}
