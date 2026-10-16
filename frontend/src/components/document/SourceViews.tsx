"use client";

import { cn } from "cn";
import { AlertTriangle, BookOpen, CheckCircle2, Database, Loader2, Pencil, Type } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { DocumentState, Segment } from "@/lib/types";
import { Markdown } from "./Markdown";
import { AltLine, FigureBlock, FLAG_LABEL, pairAltText, SegmentShell, type ShellActions } from "./SegmentShell";

const DECISION: Record<string, string> = {
  tm: "as in the TM",
  dictionary: "dictionary agrees",
  conflict: "dictionary disagrees",
  ai: "",
};

/** Page images next to their reading (OCR), with what the OCR check found — and, during the source check, "This is
 * text, not a picture" under each figure. */
export function SourceView({
  sessionId,
  segments,
  doc,
  highlight,
  actions,
  onFigureIsText,
}: {
  sessionId: string;
  segments: Segment[];
  doc: DocumentState;
  highlight: string | null;
  actions: ShellActions;
  onFigureIsText: (() => void) | null; // during the source check (and idle): offer "This is text, not a picture"
}) {
  const pages = [...new Set(segments.map((s) => s.page))];
  const reports = new Map(doc.ocr_report.map((r) => [r.page, r]));
  const { altOf, paired } = pairAltText(segments);
  const [figureBusy, setFigureBusy] = useState<string | null>(null);
  const [figureError, setFigureError] = useState<string | null>(null);
  const figureIsText = async (seg: Segment) => {
    const n = seg.figure ?? Number(/figure-p\d+-(\d+)\.png$/.exec(seg.image ?? "")?.[1] ?? 0);
    setFigureBusy(seg.id);
    setFigureError(null);
    try {
      await api.figureAsText(sessionId, seg.page, n);
      onFigureIsText?.();
    } catch (e) {
      setFigureError(`${seg.id}: ${String(e).replace(/^Error: /, "")}`);
    } finally {
      setFigureBusy(null);
    }
  };
  return (
    <div className="space-y-10">
      {pages.map((p) => {
        const r = reports.get(p);
        return (
          <div key={p}>
            <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
              <span className="rounded-full bg-muted px-2 py-0.5 font-medium">Page {p}</span>
              {r?.hard ? (
                <span className="flex items-center gap-1 font-medium text-del-fg" title="The two readings differ in too many places to settle: nothing was changed">
                  <AlertTriangle size={12} /> Hard to read — check the whole page
                </span>
              ) : (
                r &&
                (r.readers === 2 ? (
                  <span className={cn("flex items-center gap-1", r.ok ? "text-ins-fg" : "text-warn-fg")}>
                    {r.ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
                    {!r.disagreements
                      ? "Two readings agree"
                      : `Two readings differed in ${r.disagreements} place${r.disagreements === 1 ? "" : "s"}: the OCR check settled ${r.settled ?? 0}` +
                        (r.issues.length ? ` (${r.issues.length} changed)` : "")}
                  </span>
                ) : r.ok ? (
                  <span className="flex items-center gap-1 text-ins-fg">
                    <CheckCircle2 size={12} /> OCR verified
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-warn-fg">
                    <AlertTriangle size={12} /> OCR checker fixed {r.issues.length} issue{r.issues.length === 1 ? "" : "s"}
                  </span>
                ))
              )}
              {r?.enlarged && <span className="text-muted-foreground" title="The page image was small: the readers got it enlarged">· enlarged for reading</span>}
              {r?.used_text_layer && <span className="text-muted-foreground">· cross-checked with PDF text layer</span>}
              {!!r?.suggestions?.length && (
                <span className="flex items-center gap-1 text-warn-fg">
                  · {r.suggestions.length} possible misreading{r.suggestions.length === 1 ? "" : "s"} to check
                </span>
              )}
              {!!r?.figures && (
                <span className="text-muted-foreground">
                  · {r.figures} figure{r.figures === 1 ? "" : "s"}
                  {r.figure_source ? ` (${r.figure_source.replace("layout", "page layout").replace("pdf", "PDF")})` : ""}
                </span>
              )}
              {!!r?.figures_as_text?.length && (
                <span className="text-muted-foreground" title="The layout model took these regions for pictures; they were checked and read as text">
                  · {r.figures_as_text.length} region{r.figures_as_text.length === 1 ? "" : "s"} read as text, not as a picture
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-5">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={api.pageImageUrl(sessionId, p)}
                alt={`Page ${p}`}
                className="w-full rounded-lg border border-border bg-white shadow-xs"
                onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
              />
              <div>
                {segments
                  .filter((s) => s.page === p && !paired.has(s.id))
                  .map((s) => (
                    <SegmentShell key={s.id} seg={s} highlighted={highlight === s.id} actions={actions} rewrite={false}>
                      {s.kind === "figure" ? (
                        <>
                          <FigureBlock sessionId={sessionId} seg={s} legend={s.source} alt={altOf.get(s.id)} muted />
                          {onFigureIsText && (
                            <Button
                              variant="outline"
                              size="xs"
                              onClick={() => figureIsText(s)}
                              disabled={figureBusy !== null}
                              className="mb-2"
                              title="The layout model took printed text for a picture: read the page again with this text in its place (you accept or reject the result in the chat)"
                            >
                              {figureBusy === s.id ? <Loader2 className="animate-spin" /> : <Type />}
                              {figureBusy === s.id ? "Reading the page again…" : "This is text, not a picture"}
                            </Button>
                          )}
                          {figureError?.startsWith(`${s.id}:`) && <p className="mb-2 text-xs text-del-fg">{figureError.slice(s.id.length + 2)}</p>}
                        </>
                      ) : s.kind === "alt" ? (
                        <div className="py-1 text-xs text-muted-foreground">
                          <AltLine seg={s} side="source" />
                        </div>
                      ) : (
                        <Markdown text={s.source} />
                      )}
                    </SegmentShell>
                  ))}
              </div>
            </div>
            {r && !r.ok && r.issues.length > 0 && (
              <ul className="mt-2 list-disc pl-5 text-xs text-muted-foreground">
                {r.issues.map((i, k) => (
                  <li key={k}>Changed: {i}</li>
                ))}
              </ul>
            )}
            {!!r?.suggestions?.length && (
              <div className="mt-3 rounded-lg border border-warn-fg/30 bg-warn/40 px-3 py-2 text-xs">
                <div className="font-medium">
                  {r.hard
                    ? "Where the two readings differ — nothing was changed on this page, please check it against the image:"
                    : "Possible misreadings — not changed, please compare with the page image:"}
                </div>
                <ul className="mt-1 list-disc pl-5 text-foreground/80">
                  {r.suggestions.map((i, k) => (
                    <li key={k}>{i}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Section({ title, help, children }: { title: string; help?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-xs">
      <h3 className="text-sm font-semibold">{title}</h3>
      {help && <p className="mt-0.5 mb-2.5 text-xs text-muted-foreground">{help}</p>}
      {!help && <div className="mb-2" />}
      {children}
    </section>
  );
}

const table = "w-full text-left text-sm [&_td]:py-2 [&_td]:align-top [&_tr]:border-b [&_tr]:border-border [&_tr:last-child]:border-0";

/** The brief, the key terms (and how each was decided), the glossary, the terminology memory, and what the OCR
 * check and the review found. */
export function ChecksView({ doc, onDraft }: { doc: DocumentState; onDraft: (text: string) => void }) {
  const glossary = Object.entries(doc.glossary);
  const termbase = Object.entries(doc.termbase ?? {});
  const issues = doc.review_report.flatMap((r) => r.issues.map((i) => ({ ...i, round: r.round })));
  const ocrFixed = doc.ocr_report.filter((r) => !r.ok);
  const flagged = doc.segments.filter((s) => s.flags?.length);
  return (
    <div className="space-y-4 text-sm">
      {flagged.length > 0 && (
        <section className="rounded-xl border border-warn-fg/30 bg-warn/60 p-4">
          <h3 className="mb-1 font-semibold text-warn-fg">
            {flagged.length} segment{flagged.length === 1 ? "" : "s"} need{flagged.length === 1 ? "s" : ""} attention
          </h3>
          <p className="text-xs text-warn-fg">
            {flagged.map((s) => `${s.id} (${(s.flags ?? []).map((f) => FLAG_LABEL[f] ?? f).join(", ")})`).join(" · ")}
          </p>
        </section>
      )}
      <Section title="Document brief" help="Written after reading the whole document, before translating, and carried into every page (parties, abbreviations and defined terms, tone).">
        <p className="rounded-lg bg-muted px-3 py-2 text-sm whitespace-pre-line">{doc.brief || "Not written yet."}</p>
      </Section>
      {doc.tm_stats && (
        <Section title="Translation memory">
          <p className="text-sm">
            {doc.tm_stats.context + doc.tm_stats.exact} segment{doc.tm_stats.context + doc.tm_stats.exact === 1 ? "" : "s"} reused
            without a model call ({doc.tm_stats.context} in context · {doc.tm_stats.exact} exact · {doc.tm_stats.words} words) ·{" "}
            {doc.tm_stats.fuzzy} fuzzy match{doc.tm_stats.fuzzy === 1 ? "" : "es"} given to the translator to adapt
          </p>
        </Section>
      )}
      {(doc.terms ?? []).length > 0 && (
        <Section title="Project terms in this document" help="From the project termbase — given to every agent; underlined in the Segments tab.">
          <table className={table}>
            <tbody>
              {doc.terms.map((t) => (
                <tr key={t.id}>
                  <td className="pr-3 font-medium">{t.source}</td>
                  <td className="pr-3">{t.target || <span className="text-muted-foreground">—</span>}</td>
                  <td className="text-xs text-muted-foreground">
                    {t.note}
                    {t.forbidden.length > 0 && <span className="text-del-fg"> · never: {t.forbidden.join(", ")}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
      {(doc.key_terms?.length ?? 0) > 0 && (
        <Section
          title="Key terms"
          help={
            <>
              Fixed once for the whole document before translating, with what each one means and how it was decided: the translation memory and
              the dictionary are checked against the AI&apos;s choice (project termbase and your answers come first). Terms marked “asked” were
              decided by you (see the glossary below).
            </>
          }
        >
          <table className={table}>
            <tbody>
              {doc.key_terms.map((k) => (
                <tr key={k.term}>
                  <td className="pr-3 font-medium whitespace-nowrap">{k.term}</td>
                  <td className="pr-3 whitespace-nowrap">
                    {doc.glossary[k.term]?.target || k.target}
                    {k.asked ? (
                      <span className="ml-1.5 rounded-full bg-primary-soft px-1.5 text-[10px] font-medium text-primary uppercase">asked</span>
                    ) : (
                      k.decision &&
                      DECISION[k.decision] && (
                        <span
                          className={`ml-1.5 rounded-full px-1.5 text-[10px] ${k.decision === "conflict" ? "bg-warn text-warn-fg" : "bg-muted text-muted-foreground"}`}
                          title={k.note || undefined}
                        >
                          {DECISION[k.decision]}
                        </span>
                      )
                    )}
                  </td>
                  <td className="text-xs text-muted-foreground">
                    {k.meaning}
                    {k.dictionary?.map((d, i) => (
                      <span key={i} className="mt-0.5 flex items-start gap-1 text-foreground/80">
                        <BookOpen size={11} className="mt-0.5 shrink-0" />
                        <span>
                          <span className="font-medium">{d.translation}</span>
                          {d.domain && ` · ${d.domain}`} ·{" "}
                          {d.url ? (
                            <a href={d.url} target="_blank" rel="noreferrer" className="underline">
                              {d.source || "Dictionary"}
                            </a>
                          ) : (
                            d.source || "Dictionary"
                          )}
                        </span>
                      </span>
                    ))}
                    {k.tm?.map((t, i) => (
                      <span key={`tm-${i}`} className="mt-0.5 flex items-start gap-1 text-foreground/80" title={t.ref ? `From ${t.ref}` : undefined}>
                        <Database size={11} className="mt-0.5 shrink-0" />
                        <span>
                          {t.source} → <span className="font-medium">{t.target}</span>
                        </span>
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
      <Section title="Glossary">
        {glossary.length === 0 ? (
          <p className="text-muted-foreground">Empty. Terms are added when you answer questions or ask for terminology changes.</p>
        ) : (
          <table className={table}>
            <tbody>
              {glossary.map(([term, e]) => (
                <tr key={term}>
                  <td className="pr-3 font-medium">{term}</td>
                  <td className="pr-3">{e.target}</td>
                  <td className="text-xs text-muted-foreground">{e.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
      <Section
        title="Terminology memory"
        help="Term choices the translator made on earlier pages and reused on later ones. They are unverified — if one is wrong, change it and every page is updated."
      >
        {termbase.length === 0 ? (
          <p className="text-muted-foreground">None recorded.</p>
        ) : (
          <table className={table}>
            <tbody>
              {termbase.map(([term, target]) => (
                <tr key={term} className="group">
                  <td className="pr-3 font-medium">{term}</td>
                  <td>{target}</td>
                  <td className="text-right">
                    <Button
                      variant="ghost"
                      size="xs"
                      onClick={() => onDraft(`"${term}" is currently translated as "${target}". Change it everywhere to: `)}
                      className="text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                    >
                      <Pencil /> Change
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
      <Section title="OCR check">
        <p className="text-muted-foreground">
          {doc.ocr_report.length} page{doc.ocr_report.length === 1 ? "" : "s"} checked ·{" "}
          {ocrFixed.length === 0 ? "no corrections needed" : `${ocrFixed.length} page(s) corrected`}
          {(() => {
            const hard = doc.ocr_report.filter((r) => r.hard).map((r) => r.page);
            return hard.length ? ` · hard to read: page${hard.length === 1 ? "" : "s"} ${hard.join(", ")}` : "";
          })()}
          {(() => {
            const n = doc.ocr_report.reduce((sum, r) => sum + (r.suggestions?.length ?? 0), 0);
            return n ? ` · ${n} possible misreading${n === 1 ? "" : "s"} to check (Source tab)` : "";
          })()}
        </p>
      </Section>
      <Section title="Translation review">
        {issues.length === 0 ? (
          <p className="text-muted-foreground">No issues raised by the reviewer.</p>
        ) : (
          <ul className="divide-y divide-border">
            {issues.map((i, k) => (
              <li key={k} className="flex gap-2 py-1.5">
                <span
                  className={`mt-0.5 h-fit shrink-0 rounded-full px-1.5 text-[10px] font-medium uppercase ${
                    i.severity === "minor" ? "bg-warn text-warn-fg" : "bg-del text-del-fg"
                  }`}
                >
                  {i.severity}
                </span>
                <span className="font-mono text-xs text-muted-foreground">{i.segment_id}</span>
                <span className="text-xs">{i.note}</span>
                <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">round {i.round}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
