"use client";

import { Loader2 } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

export interface SlidesHandle {
  goTo: (index: number) => void;
  find: (index: number, text: string) => void;
}

type Viewer = {
  destroy: () => void;
  goToSlide: (i: number, o?: ScrollIntoViewOptions) => Promise<void>;
  searchText: (q: string, o?: { snippetRadius?: number }) => { slideIndex: number }[];
  highlightSearchResult: (m: { slideIndex: number }) => Promise<{ dispose: () => void } | null>;
};

/** A PowerPoint deck rendered in the browser (@aiden0z/pptx-renderer), slides in a scrolling list. */
export const PptxPane = forwardRef<SlidesHandle, { url: string; refreshKey: string; onSlide?: (index: number) => void }>(
  function PptxPane({ url, refreshKey, onSlide }, ref) {
    const scroller = useRef<HTMLDivElement>(null);
    const host = useRef<HTMLDivElement>(null);
    const viewer = useRef<Viewer | null>(null);
    const onSlideRef = useRef(onSlide);
    useEffect(() => {
      onSlideRef.current = onSlide;
    }, [onSlide]);
    const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
    const [error, setError] = useState("");

    useEffect(() => {
      const ac = new AbortController();
      let created: Viewer | null = null;
      (async () => {
        try {
          const res = await fetch(url, { signal: ac.signal, cache: "no-store" });
          if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
          const buf = await res.arrayBuffer();
          const { PptxViewer, RECOMMENDED_ZIP_LIMITS } = await import("@aiden0z/pptx-renderer");
          if (ac.signal.aborted || !host.current) return;
          host.current.replaceChildren();
          created = (await PptxViewer.open(buf, host.current, {
            renderMode: "list",
            fitMode: "contain",
            zipLimits: RECOMMENDED_ZIP_LIMITS,
            listOptions: { windowed: true },
            pdfjs: false,
            scrollContainer: scroller.current ?? undefined,
            onSlideChange: (i: number) => onSlideRef.current?.(i),
            signal: ac.signal,
          })) as unknown as Viewer;
          if (ac.signal.aborted) {
            created.destroy();
            return;
          }
          viewer.current = created;
          setStatus("ready");
        } catch (e) {
          if (ac.signal.aborted) return;
          setError(String(e).replace(/^Error: /, ""));
          setStatus("error");
        }
      })();
      return () => {
        ac.abort();
        created?.destroy();
        if (viewer.current === created) viewer.current = null;
      };
    }, [url, refreshKey]);

    useImperativeHandle(ref, () => ({
      goTo: (i) => void viewer.current?.goToSlide(i, { behavior: "instant" as ScrollBehavior, block: "start" }),
      find: async (i, text) => {
        const v = viewer.current;
        if (!v) return;
        await v.goToSlide(i, { behavior: "smooth", block: "center" });
        const hit = v.searchText(text.slice(0, 60), { snippetRadius: 0 }).find((m) => m.slideIndex === i);
        if (hit) {
          const mark = await v.highlightSearchResult(hit);
          setTimeout(() => mark?.dispose(), 2200);
        }
      },
    }));

    return (
      <div ref={scroller} className="scroll-thin relative h-full overflow-auto rounded-lg bg-muted p-2">
        {status === "loading" && (
          <div className="absolute inset-x-0 top-6 flex justify-center text-xs text-muted-foreground">
            <Loader2 size={14} className="mr-1.5 animate-spin" /> Rendering…
          </div>
        )}
        {status === "error" && <p className="p-4 text-xs text-del-fg">Couldn&apos;t show the slides: {error}</p>}
        <div ref={host} className="office-page" />
      </div>
    );
  },
);
