/** Motion presets (the `motion` library): subtle, quick, and switched off by the system's reduce-motion setting
 * (MotionConfig in components/shell/Providers.tsx). Spread one onto a motion element: <motion.div {...rise} />. */
import type { Transition } from "motion/react";

export const ease = [0.22, 1, 0.36, 1] as const; // a soft ease-out

/** Fade only: overlays, swapped content. */
export const fade = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.15, ease } satisfies Transition,
};

/** Fade and rise a few pixels: new chat messages, cards, list items. */
export const rise = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: 4 },
  transition: { duration: 0.22, ease } satisfies Transition,
};

/** Scale in from slightly smaller: popovers, menus, toolbars that appear at a point. */
export const pop = {
  initial: { opacity: 0, scale: 0.97 },
  animate: { opacity: 1, scale: 1 },
  exit: { opacity: 0, scale: 0.98 },
  transition: { duration: 0.16, ease } satisfies Transition,
};

/** For layout changes (a panel resizing, items reordering): `<motion.div layout transition={spring}>`. */
export const spring: Transition = { type: "spring", stiffness: 420, damping: 36, mass: 0.8 };

/** Stagger children of a list by this much (seconds). */
export const stagger = 0.03;
