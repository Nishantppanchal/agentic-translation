/**
 * Runs in <head> before the first paint (see app/layout.tsx), so the stored theme, the sidebar's collapsed state
 * and its width are on <html> before React hydrates — no flash, no jump. Keep the keys and the width range
 * (208–420) in step with lib/prefs.ts. No imports: the server layout inlines this string.
 */
export const PREFS_SCRIPT = `(function(){try{var d=document.documentElement,s=localStorage,t=s.getItem("theme");if(t==="light"||t==="dark")d.setAttribute("data-theme",t);if(s.getItem("sidebarCollapsed")==="1")d.setAttribute("data-sidebar","collapsed");var w=parseInt(s.getItem("sidebarWidth"),10);if(w>=208&&w<=420)d.style.setProperty("--sidebar-w",w+"px")}catch(e){}})()`;
