// Single frames from the film, for checking the look without rendering it all.
import fs from "node:fs";
import path from "node:path";
import { bundle } from "@remotion/bundler";
import { openBrowser, renderStill, selectComposition } from "@remotion/renderer";

/** The moments worth looking at: each headline, and each place the camera comes to rest. */
export function keyMoments(tl) {
  const times = [1.8 + (tl.intro.t1 - 1.8) * 0.5, tl.intro.t1 - 0.7];
  for (const s of tl.titles) times.push(s.t0 + 1.6);
  for (let i = 1; i < tl.camera.length; i++) {
    const a = tl.camera[i - 1];
    const b = tl.camera[i];
    if (a.v.z !== b.v.z && b.v.z > 1.01) times.push(b.t + 0.15);
  }
  times.push(tl.outro.t0 + 0.6, tl.outro.t1 - 1.2);
  return [...new Set(times.map((t) => Math.round(t * 10) / 10))].sort((a, b) => a - b);
}

export async function stills(tl, { entry, publicDir, outDir, at }) {
  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });
  const serveUrl = await bundle({ entryPoint: entry, publicDir });
  const browser = await openBrowser("chrome");
  try {
    const composition = await selectComposition({ serveUrl, id: "Film", puppeteerInstance: browser });
    const times = at ?? keyMoments(tl);
    for (const t of times) {
      const output = path.join(outDir, `t${t.toFixed(1).padStart(6, "0")}.png`);
      await renderStill({ composition, serveUrl, output, frame: Math.min(composition.durationInFrames - 1, Math.round(t * tl.fps)), puppeteerInstance: browser, overwrite: true });
    }
    console.log(`  ${times.length} stills in ${outDir}`);
  } finally {
    await browser.close({ silent: true });
  }
}
