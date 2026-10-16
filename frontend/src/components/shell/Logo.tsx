import { useId } from "react";

/** The app's mark: a soft pastel-blue orb (white at the top, blue at the bottom). app/icon.svg is the same drawing.
 * `float`: it drifts slowly up and down over a shadow that shrinks as it rises (still under reduce-motion).
 * `size`: pixels, or "var" to take it from the CSS variable --orb on an ancestor — a transition on --orb (registered
 * in globals.css) then grows or shrinks the orb and its shadow smoothly, as the sidebar does when it folds. */
export function Logo({ size = 22, float = false, className = "" }: { size?: number | "var"; float?: boolean; className?: string }) {
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, ""); // a url(#…) reference can't hold React's id characters
  const px = (k: number, min = 0) => (size === "var" ? `max(${min}px, calc(var(--orb) * ${k}))` : `${Math.max(min, size * k)}px`);
  const box = size === "var" ? "var(--orb)" : `${size}px`;
  const orb = (
    <span
      className={`block shrink-0 ${float ? "motion-safe:animate-[orb-float_4.8s_ease-in-out_infinite]" : ""}`}
      // standing still: a soft shadow right under it, scaled with it
      style={{ width: box, height: box, filter: float ? undefined : `drop-shadow(0 ${px(0.07)} ${px(0.12)} rgba(60, 110, 170, 0.28))` }}
    >
      <svg width="100%" height="100%" viewBox="0 0 64 64" aria-hidden className="block">
        <defs>
          <linearGradient id={`${id}-body`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#FAFCFF" />
            <stop offset="0.36" stopColor="#E0EDFB" />
            <stop offset="0.66" stopColor="#A8CAF0" />
            <stop offset="1" stopColor="#6C9DD6" />
          </linearGradient>
          <radialGradient id={`${id}-rim`} cx="0.5" cy="0.5" r="0.5">
            <stop offset="0.78" stopColor="#2F5E94" stopOpacity="0" />
            <stop offset="1" stopColor="#2F5E94" stopOpacity="0.2" />
          </radialGradient>
          <radialGradient id={`${id}-shine`} cx="0.36" cy="0.26" r="0.5">
            <stop offset="0" stopColor="#FFFFFF" stopOpacity="0.9" />
            <stop offset="1" stopColor="#FFFFFF" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx="32" cy="32" r="30" fill={`url(#${id}-body)`} />
        <circle cx="32" cy="32" r="30" fill={`url(#${id}-rim)`} />
        <circle cx="32" cy="32" r="30" fill={`url(#${id}-shine)`} />
      </svg>
    </span>
  );
  if (!float) return <span className={`inline-block ${className}`}>{orb}</span>;
  return (
    <span className={`relative inline-flex flex-col items-center ${className}`} style={{ paddingBottom: px(0.24) }}>
      {orb}
      {/* its shadow on the "ground": smaller and fainter while the orb is up */}
      <span
        aria-hidden
        className="absolute bottom-0 rounded-[50%] bg-[rgb(60_110_170/0.35)] blur-[2px] motion-safe:animate-[orb-shadow_4.8s_ease-in-out_infinite] dark:bg-[rgb(0_0_0/0.6)]"
        style={{ width: px(0.62), height: px(0.12, 3) }}
      />
    </span>
  );
}
