"use client";

import { useLayoutEffect } from "react";
import { applyPrefs } from "@/lib/prefs";

/** Re-applies the theme, the sidebar attribute and its width (--sidebar-w) after React's development remount clears
 * them from <html>. */
export function PrefsSync() {
  useLayoutEffect(applyPrefs, []);
  return null;
}
