"use client";

import { Loader2 } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

export const bookmarkId = (segId: string) => `_seg_${segId.replace(/\./g, "_")}`;
export const segOfBookmark = (id: string) => id.replace(/^_seg_/, "").replace(/_/g, ".");

export interface PaneHandle {
  /** Scroll to a segment and outline it for a moment. */
  locate: (segId: string) => void;
  /** The segment at the top of the visible area (for synced scrolling). */
  topSegment: () => string | null;
  scrollToSegment: (segId: string) => void;
}

/** A Word document rendered in the browser (docx-preview), pages scaled to the pane's width. Paragraphs carry
 * hidden `_seg_<id>` bookmarks from the server, so a segment can be found on the page. */
export const DocxPane = forwardRef<PaneHandle, { url: string; refreshKey: string; onScroll?: () => void; onPick?: (segId: string) => void }>(
  function DocxPane({ url, refreshKey, onScroll, onPick }, ref) {
    const scroller = useRef<HTMLDivElement>(null);
    const host = useRef<HTMLDivElement>(null);
    const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
    const [error, setError] = useState("");

    useEffect(() => {
      const ac = new AbortController();
      setStatus((s) => (s === "ready" ? s : "loading")); // keep the old render on screen while the new one loads
      (async () => {
        try {
          const res = await fetch(url, { signal: ac.signal, cache: "no-store" });
          if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
          const buf = await res.arrayBuffer();
          const { renderAsync } = await import("docx-preview");
          if (ac.signal.aborted) return;
          const staging = document.createElement("div"); // render off-screen, then swap: no flicker
          await renderAsync(buf, staging, staging, {
            className: "docx",
            inWrapper: true,
            breakPages: true,
            ignoreLastRenderedPageBreak: true,
            renderFootnotes: true,
            renderEndnotes: true,
            renderComments: false,
            renderChanges: false,
            experimental: true,
            useBase64URL: true,
          });
          if (ac.signal.aborted || !host.current) return;
          host.current.replaceChildren(...Array.from(staging.childNodes));
          fit();
          setStatus("ready");
        } catch (e) {
          if (ac.signal.aborted) return;
          setError(String(e).replace(/^Error: /, ""));
          setStatus("error");
        }
      })();
      return () => ac.abort();
    }, [url, refreshKey]);

    /** Pages are printed sizes: scale them to the pane. */
    const fit = () => {
      const wrapper = host.current?.querySelector<HTMLElement>(".docx-wrapper");
      const page = wrapper?.querySelector<HTMLElement>("section.docx");
      if (!wrapper || !page || !scroller.current) return;
      wrapper.style.zoom = "1";
      const scale = Math.min(1, (scroller.current.clientWidth - 8) / (page.offsetWidth + 32));
      wrapper.style.zoom = String(scale);
    };
    useEffect(() => {
      const el = scroller.current;
      if (!el) return;
      const observer = new ResizeObserver(() => fit());
      observer.observe(el);
      return () => observer.disconnect();
    }, []);

    const find = (segId: string) => host.current?.querySelector<HTMLElement>(`#${CSS.escape(bookmarkId(segId))}`) ?? null;

    useImperativeHandle(ref, () => ({
      locate: (segId) => {
        const mark = find(segId);
        const block = mark?.closest<HTMLElement>("p, li, td, h1, h2, h3, h4, h5, h6") ?? mark;
        if (!block) return;
        block.scrollIntoView({ behavior: "smooth", block: "center" });
        block.classList.add("office-located");
        setTimeout(() => block.classList.remove("office-located"), 2200);
      },
      topSegment: () => {
        const top = scroller.current?.getBoundingClientRect().top ?? 0;
        const marks = host.current?.querySelectorAll<HTMLElement>('span[id^="_seg_"]') ?? [];
        for (const m of Array.from(marks)) if (m.getBoundingClientRect().top >= top - 4) return segOfBookmark(m.id);
        return null;
      },
      scrollToSegment: (segId) => {
        const mark = find(segId);
        if (mark && scroller.current) {
          const delta = mark.getBoundingClientRect().top - scroller.current.getBoundingClientRect().top;
          scroller.current.scrollTop += delta;
        }
      },
    }));

    return (
      <div ref={scroller} onScroll={onScroll} className="scroll-thin relative h-full overflow-auto rounded-lg bg-muted">
        {status === "loading" && (
          <div className="absolute inset-x-0 top-6 flex justify-center text-xs text-muted-foreground">
            <Loader2 size={14} className="mr-1.5 animate-spin" /> Rendering…
          </div>
        )}
        {status === "error" && <p className="p-4 text-xs text-del-fg">Couldn&apos;t show the document: {error}</p>}
        <div
          ref={host}
          className="office-page"
          onClick={(e) => {
            const block = (e.target as HTMLElement).closest("p, li, td");
            const mark = block?.querySelector<HTMLElement>('span[id^="_seg_"]');
            if (mark && onPick) onPick(segOfBookmark(mark.id));
          }}
        />
      </div>
    );
  },
);
