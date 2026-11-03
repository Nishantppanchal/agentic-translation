// The storyboard language. Each function describes one thing the viewer sees; capture.mjs performs it in the real app.
//
// A target is any Playwright selector string ("role=button[name='Save']", "text=Invoices", "#total") or a function
// (page) => locator, for anything a string can't express.

/** Open a URL (relative to app.url). */
export const goto = (url, opts = {}) => ({ do: "goto", url, ...opts });
/** The cursor glides to the target and clicks it, for real. {hold: seconds to look at the result, camera: false} */
export const click = (target, opts = {}) => ({ do: "click", target, ...opts });
/** The cursor glides to the target and rests there, so its hover state shows. */
export const hover = (target, opts = {}) => ({ do: "hover", target, ...opts });
/** Click a field and type into it, key by key. {cps: characters a second on screen, every: keys per screenshot} */
export const type = (target, text, opts = {}) => ({ do: "type", target, text, ...opts });
/** Press a key or a shortcut ("Enter", "Meta+K"). {show: true} draws it as a keycap on screen. */
export const press = (key, opts = {}) => ({ do: "press", key, ...opts });
/** Scroll smoothly. {by: pixels} or {to: target}, optionally {within: scrolling element}, {seconds}. */
export const scroll = (opts = {}) => ({ do: "scroll", ...opts });
/** Drag one element onto another. */
export const drag = (from, to, opts = {}) => ({ do: "drag", from, to, ...opts });
/** Wait off camera for something (a target, or milliseconds); the film cuts softly to the result. */
export const waitFor = (what, opts = {}) => ({ do: "wait", what, ...opts });
/** Show long work as a time-lapse: screenshots until `until` appears, played back in `seconds`. */
export const lapse = (opts = {}) => ({ do: "lapse", ...opts });
/** Push the camera in on a target. {hold: seconds, zoom: maximum zoom, ring: true, note: "a short line"} */
export const focus = (target, opts = {}) => ({ do: "focus", target, ...opts });
/** Dim everything but the target, Keynote style. {hold, note} */
export const spotlight = (target, opts = {}) => ({ do: "spotlight", target, ...opts });
/** Pull the camera back to the whole window. */
export const pull = (opts = {}) => ({ do: "pull", ...opts });
/** Rest on the current frame for this many seconds. */
export const hold = (seconds) => ({ do: "hold", seconds });
/** Escape hatch: run anything against the Playwright page, off camera; the film cuts softly to the result. */
export const run = (fn, opts = {}) => ({ do: "run", fn, ...opts });

export const dsl = { goto, click, hover, type, press, scroll, drag, waitFor, lapse, focus, spotlight, pull, hold, run };
