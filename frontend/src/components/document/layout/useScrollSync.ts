"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/** The places both sides have, in order from the top of a pane: [key, element] (a slide, a segment, a row). */
export type Anchors = (pane: HTMLElement) => Iterable<readonly [string, Element]>;

type Pane = HTMLElement | null;

/** Two panes scrolled together: the original and its translation. The two can differ in length (a longer
 * translation, other page breaks), so they are matched at anchors both have, and in between the position is
 * interpolated: they move together smoothly instead of jumping from anchor to anchor.
 *
 * Only the pane the person is using (pointer over it, wheel, touch, keys) leads; the other one's scroll events
 * are ignored, so the two never echo each other. `hold()` lets both panes scroll on their own for a moment (to
 * show a segment on each side). `left` / `right`: ref callbacks for the two scrolling elements. */
export function useScrollSync(anchors: Anchors) {
  const [panes, setPanes] = useState<[Pane, Pane]>([null, null]);
  const left = useCallback((el: Pane) => setPanes((p) => (p[0] === el ? p : [el, p[1]])), []);
  const right = useCallback((el: Pane) => setPanes((p) => (p[1] === el ? p : [p[0], el])), []);
  const anchorsRef = useRef(anchors);
  useEffect(() => {
    anchorsRef.current = anchors;
  }, [anchors]);
  const held = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const [a, b] = panes;
    if (!a || !b) return;
    let lead: 0 | 1 = 0;
    let pairs: [number, number][] | null = null; // matching positions [in a, in b], both increasing
    let frame = 0;

    // Where each anchor is, from the top of its pane's content.
    const positions = (pane: HTMLElement) => {
      const top = pane.getBoundingClientRect().top - pane.scrollTop;
      const out = new Map<string, number>();
      for (const [key, el] of anchorsRef.current(pane)) if (!out.has(key)) out.set(key, el.getBoundingClientRect().top - top);
      return out;
    };
    const match = (): [number, number][] => {
      const pa = positions(a);
      const pb = positions(b);
      const out: [number, number][] = [[0, 0]];
      for (const [key, ya] of [...pa].sort((x, y) => x[1] - y[1])) {
        const yb = pb.get(key);
        const [la, lb] = out[out.length - 1];
        if (yb !== undefined && ya > la && yb > lb) out.push([ya, yb]); // out of order (a text box, a footnote): skipped
      }
      out.push([Math.max(a.scrollHeight, out[out.length - 1][0] + 1), Math.max(b.scrollHeight, out[out.length - 1][1] + 1)]);
      return out;
    };
    // A position in one pane → the same place in the other, between the two anchors around it.
    const map = (y: number, from: 0 | 1) => {
      pairs ??= match();
      const to = from === 0 ? 1 : 0;
      let i = 1;
      while (i < pairs.length - 1 && pairs[i][from] <= y) i++;
      const [p, q] = [pairs[i - 1], pairs[i]];
      const t = (y - p[from]) / (q[from] - p[from] || 1);
      return p[to] + Math.min(1, Math.max(0, t)) * (q[to] - p[to]);
    };
    const follow = () => {
      frame = 0;
      const [from, to] = lead === 0 ? [a, b] : [b, a];
      const atEnd = from.scrollTop >= from.scrollHeight - from.clientHeight - 1;
      to.scrollTop = atEnd ? to.scrollHeight : map(from.scrollTop, lead);
      const wide = from.scrollWidth - from.clientWidth;
      to.scrollLeft = wide > 0 ? (from.scrollLeft / wide) * (to.scrollWidth - to.clientWidth) : 0;
    };

    // Anchors move when either side renders, resizes or loads more (slides are mounted as they come into view).
    const stale = () => {
      pairs = null;
    };
    const resized = new ResizeObserver(stale);
    const changed = new MutationObserver(stale);
    for (const pane of [a, b]) {
      resized.observe(pane);
      for (const child of Array.from(pane.children)) resized.observe(child);
      changed.observe(pane, { childList: true, subtree: true });
    }

    const cleanups = [a, b].map((pane, i) => {
      const take = () => {
        lead = i as 0 | 1;
      };
      const scrolled = () => {
        if (lead !== i || held.current) return;
        if (!frame) frame = requestAnimationFrame(follow);
      };
      const events = ["pointerenter", "pointerdown", "wheel", "touchstart", "keydown", "focusin"] as const;
      for (const e of events) pane.addEventListener(e, take, { passive: true });
      pane.addEventListener("scroll", scrolled, { passive: true });
      return () => {
        for (const e of events) pane.removeEventListener(e, take);
        pane.removeEventListener("scroll", scrolled);
      };
    });
    return () => {
      cleanups.forEach((c) => c());
      resized.disconnect();
      changed.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [panes]);

  /** Let both panes scroll on their own for a moment (each shows the same segment), without following. */
  const hold = useCallback((ms = 900) => {
    if (held.current) clearTimeout(held.current);
    held.current = setTimeout(() => {
      held.current = null;
    }, ms);
  }, []);
  useEffect(
    () => () => {
      if (held.current) clearTimeout(held.current);
    },
    [],
  );

  // One object while the panes stay the same (effects can depend on it).
  return useMemo(() => ({ left, right, hold, panes }), [left, right, hold, panes]);
}
