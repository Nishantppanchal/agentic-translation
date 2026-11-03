import { Easing } from "remotion";

export type Rect = { x: number; y: number; w: number; h: number };
export type View = { cx: number; cy: number; z: number };
export type Timeline = {
  fps: number;
  duration: number;
  bar: number;
  brand: {
    name?: string;
    logo?: string;
    logoRadius?: string;
    accent: string;
    theme: "light" | "dark";
    font?: string;
  };
  window: { x: number; y: number; w: number; h: number; s: number; chrome: string; chromeHeight: number; address?: string; appW: number; appH: number };
  shots: { t: number; src: string; fade: number }[];
  camera: { t: number; v: View }[];
  cursor: { t: number; move: number; x0: number; y0: number; x: number; y: number; straight?: boolean; fadeIn?: boolean; sceneEnd?: number }[];
  clicks: { t: number; x: number; y: number }[];
  spots: { t0: number; t1: number; rect: Rect }[];
  rings: { t0: number; t1: number; rect: Rect }[];
  notes: { t0: number; t1: number; text: string }[];
  keys: { t0: number; t1: number; label: string }[];
  titles: { id: string; t0: number; t1: number; eyebrow?: string; title: string; body?: string; openEnd: number }[];
  intro: { t0: number; t1: number; dive: number; headline: string; accent?: string; sub?: string };
  outro: { t0: number; t1: number; collapse: number; headline: string; accent?: string; sub?: string; cta?: string };
  audio: { music: string; sfx: string; musicGain: number };
};

export const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));
export const ease = {
  camera: Easing.bezier(0.62, 0.02, 0.2, 1), // slow to leave, slower to land
  rise: Easing.bezier(0.16, 1, 0.3, 1), // text and windows settling into place
  cursor: Easing.bezier(0.45, 0.05, 0.15, 1),
  soft: Easing.bezier(0.4, 0, 0.6, 1),
  in: Easing.bezier(0.55, 0, 0.9, 0.4),
};
/** 0 → 1 between a and b. */
export const ramp = (t: number, a: number, b: number, fn: (p: number) => number = ease.soft) => fn(clamp((t - a) / (b - a || 1e-6)));

export function cameraAt(tl: Timeline, t: number): View {
  const keys = tl.camera;
  const rest = { cx: 960, cy: 540, z: 1 };
  if (!keys.length || t <= keys[0].t) return keys[0]?.v ?? rest;
  for (let i = 1; i < keys.length; i++) {
    if (t <= keys[i].t) {
      const a = keys[i - 1];
      const b = keys[i];
      const p = ramp(t, a.t, b.t, ease.camera);
      // zoom eases geometrically, so a push feels the same speed all the way in
      return { cx: a.v.cx + (b.v.cx - a.v.cx) * p, cy: a.v.cy + (b.v.cy - a.v.cy) * p, z: a.v.z * (b.v.z / a.v.z) ** p };
    }
  }
  return keys[keys.length - 1].v;
}

/** The shot on screen at t, and the one it is fading in over. */
export function shotsAt(tl: Timeline, t: number) {
  const { shots } = tl;
  let lo = 0;
  let hi = shots.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (shots[mid].t <= t) lo = mid;
    else hi = mid - 1;
  }
  const top = shots[lo];
  const fading = top.fade > 0 && t >= top.t && t - top.t < top.fade && lo > 0;
  return { top, opacity: fading ? ease.soft((t - top.t) / top.fade) : 1, under: fading ? shots[lo - 1] : null };
}

/** Where the cursor is, how visible, and how far it is from a click. */
export function cursorAt(tl: Timeline, t: number) {
  const list = tl.cursor;
  let current = -1;
  for (let i = 0; i < list.length && list[i].t <= t; i++) current = i;
  if (current < 0) return null;
  const c = list[current];
  const end = c.t + c.move;
  const next = list[current + 1];
  const gone = Math.min(end + 2.4, c.sceneEnd ?? Infinity, next && next.t > end + 2.4 ? next.t : Infinity);
  if (t > gone + 0.3) return null;
  const p = ramp(t, c.t, end, c.straight ? ease.soft : ease.cursor);
  // real hands arc a little
  const dx = c.x - c.x0;
  const dy = c.y - c.y0;
  const bow = c.straight ? 0 : Math.sin(Math.PI * p) * 0.07;
  const opacity = Math.min(c.fadeIn ? ramp(t, c.t, c.t + 0.3) : 1, 1 - ramp(t, gone, gone + 0.3));
  return { x: c.x0 + dx * p - dy * bow, y: c.y0 + dy * p + dx * bow, opacity };
}
