"use client";

import { useSyncExternalStore } from "react";

/** Per-browser display preferences (theme, sidebar collapsed and its width). Stored in localStorage; the page works
 * without it. */

export type Theme = "system" | "light" | "dark";

/** The stored value; undefined when storage can't be used (then the in-page copy below decides). */
function read(key: string): string | null | undefined {
  try {
    return localStorage.getItem(key);
  } catch {
    return undefined;
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // storage unavailable (private window, blocked site data): the choice lasts until reload
  }
}

let memoryTheme: Theme | null = null; // when storage throws, keep the choice for this page
let memoryCollapsed: boolean | null = null;
let memoryWidth: number | null = null;

// The expanded sidebar's width (px): dragged by its edge, set before paint as --sidebar-w on <html>.
export const SIDEBAR_MIN = 208;
export const SIDEBAR_MAX = 420;
export const SIDEBAR_DEFAULT = 256;
export const clampSidebarWidth = (w: number) => Math.round(Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, w)));

export function getTheme(): Theme {
  const stored = read("theme");
  const t = stored === undefined ? memoryTheme : stored;
  return t === "light" || t === "dark" ? t : "system";
}

export function getSidebarCollapsed(): boolean {
  const stored = read("sidebarCollapsed");
  return stored === undefined ? (memoryCollapsed ?? false) : stored === "1";
}

export function getSidebarWidth(): number {
  const stored = read("sidebarWidth");
  const w = stored === undefined ? memoryWidth : stored === null ? null : parseInt(stored, 10);
  return w && Number.isFinite(w) ? clampSidebarWidth(w) : SIDEBAR_DEFAULT;
}

/** Only the CSS variable (while dragging: no storage, no re-render); setSidebarWidth when the drag ends. */
export function previewSidebarWidth(width: number) {
  const w = clampSidebarWidth(width);
  if (w === SIDEBAR_DEFAULT) document.documentElement.style.removeProperty("--sidebar-w");
  else document.documentElement.style.setProperty("--sidebar-w", `${w}px`);
}

/** Put the preferences on <html>: data-theme (absent = follow the OS), data-sidebar and --sidebar-w. */
export function applyPrefs() {
  const root = document.documentElement;
  const theme = getTheme();
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  if (getSidebarCollapsed()) root.setAttribute("data-sidebar", "collapsed");
  else root.removeAttribute("data-sidebar");
  previewSidebarWidth(getSidebarWidth());
}

function changed() {
  applyPrefs();
  window.dispatchEvent(new Event("prefs"));
}

export function setTheme(theme: Theme) {
  memoryTheme = theme;
  write("theme", theme === "system" ? null : theme);
  changed();
}

export function setSidebarCollapsed(collapsed: boolean) {
  memoryCollapsed = collapsed;
  write("sidebarCollapsed", collapsed ? "1" : null);
  changed();
}

/** The default width is stored as nothing (so a later default applies). */
export function setSidebarWidth(width: number) {
  const w = clampSidebarWidth(width);
  memoryWidth = w;
  write("sidebarWidth", w === SIDEBAR_DEFAULT ? null : String(w));
  changed();
}

function subscribe(onChange: () => void) {
  const onStorage = (e: StorageEvent) => {
    if (e.key === "theme" || e.key === "sidebarCollapsed" || e.key === "sidebarWidth" || e.key === null) {
      applyPrefs(); // another tab changed it
      onChange();
    }
  };
  window.addEventListener("prefs", onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener("prefs", onChange);
    window.removeEventListener("storage", onStorage);
  };
}

export const useTheme = () => useSyncExternalStore(subscribe, getTheme, () => "system" as Theme);
export const useSidebarCollapsed = () => useSyncExternalStore(subscribe, getSidebarCollapsed, () => false);
export const useSidebarWidth = () => useSyncExternalStore(subscribe, getSidebarWidth, () => SIDEBAR_DEFAULT);
