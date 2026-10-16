"use client";

import { CheckCircle2, Database, FileText, User } from "lucide-react";
import { motion } from "motion/react";
import { cn } from "cn";
import { useEffect, useMemo, useRef, useState } from "react";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import type { AppSettingsView, ModelChoices, ModelInfo, PipelineFlowSpec, StepChoice, StepId } from "@/lib/types";
import { defaultEffort, EFFORT_LABEL, EffortToggle, effectiveEffort, ModelSelect } from "./ModelChoices";
import { ModelLogo } from "./ModelLogo";

// The diagram is laid out by hand: every box at its (row, col) from the flow spec, the row names in a column on the
// left, and each arrow one of three shapes — straight along a row, down through the gap between two rows, or a loop
// under a row back to an earlier box (Review → Refinement). No arrow passes behind a box.
const W = 168; // a box's width
const H = 58; // and height
const GAP_X = 52; // between columns (room for an arrow's label)
const GAP_Y = 48; // between rows (an arrow going down turns in the middle of it)
const NAMES = 112; // the column of row names
const LOOP = 20; // how far a loop runs under its row

type Point = { x: number; y: number };
type Box = { id: string; row: number; col: number };

const left = (b: Box) => NAMES + b.col * (W + GAP_X);
const top = (b: Box) => b.row * (H + GAP_Y);
const middle = (b: Box) => ({ x: left(b) + W / 2, y: top(b) + H / 2 });

/** The arrow from one box to another, as an orthogonal polyline, and where its label goes. */
function route(s: Box, t: Box): { points: Point[]; at: Point; above: boolean } {
  if (s.row === t.row && t.col > s.col) {
    const y = middle(s).y;
    const a = { x: left(s) + W, y };
    const b = { x: left(t), y };
    return { points: [a, b], at: { x: (a.x + b.x) / 2, y }, above: true };
  }
  if (s.row === t.row) {
    // back along the row: under the boxes
    const y = top(s) + H + LOOP;
    const points = [
      { x: middle(s).x, y: top(s) + H },
      { x: middle(s).x, y },
      { x: middle(t).x, y },
      { x: middle(t).x, y: top(t) + H },
    ];
    return { points, at: { x: (middle(s).x + middle(t).x) / 2, y }, above: false };
  }
  if (t.row < s.row && t.col === s.col) {
    // up into the step right above (the second reading feeding the check): straight, into its bottom
    const a = { x: middle(s).x, y: top(s) };
    const b = { x: middle(t).x, y: top(t) + H };
    return { points: [a, b], at: { x: a.x, y: (a.y + b.y) / 2 }, above: false };
  }
  // down to a later row: turn in the gap above it
  const y = top(t) - GAP_Y / 2;
  const points = [
    { x: middle(s).x, y: top(s) + H },
    { x: middle(s).x, y },
    { x: middle(t).x, y },
    { x: middle(t).x, y: top(t) },
  ];
  return { points, at: { x: (middle(s).x + middle(t).x) / 2, y }, above: false };
}

/** An orthogonal polyline with softly rounded corners. */
function roundedPath(points: Point[], radius = 7): string {
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const [a, b, c] = [points[i - 1], points[i], points[i + 1]];
    const r = Math.min(radius, Math.hypot(b.x - a.x, b.y - a.y) / 2, Math.hypot(c.x - b.x, c.y - b.y) / 2);
    const toward = (p: Point, q: Point) => {
      const l = Math.hypot(q.x - p.x, q.y - p.y) || 1;
      return { x: p.x + ((q.x - p.x) / l) * r, y: p.y + ((q.y - p.y) / l) * r };
    };
    const p1 = toward(b, a);
    const p2 = toward(b, c);
    d += ` L ${p1.x} ${p1.y} Q ${b.x} ${b.y} ${p2.x} ${p2.y}`;
  }
  const last = points[points.length - 1];
  return `${d} L ${last.x} ${last.y}`;
}

type StepData = {
  step: StepId;
  label: string;
  model: ModelInfo | undefined;
  level: string | null;
  isDefault: boolean;
  lit: boolean;
  dim: boolean;
  changed: boolean;
  pulse: number | null;
  open: boolean;
  setOpen: (open: boolean) => void;
  editor: React.ReactNode;
};

/** A step that runs on a model: its name, the model's logo and name, and the reasoning level. Click to change it. */
function StepCard({ data, className, style }: { data: StepData; className?: string; style?: React.CSSProperties }) {
  return (
    <Popover open={data.open} onOpenChange={data.setOpen}>
      <PopoverAnchor asChild>
        <motion.button
          type="button"
          key={data.pulse ?? 0}
          initial={data.pulse ? { scale: 0.96 } : false}
          animate={{ scale: 1 }}
          transition={{ type: "spring", stiffness: 500, damping: 18 }}
          onClick={() => data.setOpen(!data.open)}
          style={{ height: H, ...style }}
          className={cn(
            "relative flex flex-col justify-center rounded-lg border bg-card px-2.5 text-left shadow-xs transition-[opacity,box-shadow,border-color,background-color] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
            data.lit ? "border-primary/60 bg-primary-soft shadow-sm" : "border-border hover:border-primary/40",
            data.dim && "opacity-35",
            data.changed && "ring-2 ring-primary/35",
            data.open && "border-primary",
            className,
          )}
          aria-label={`${data.label}: ${data.model?.label ?? "no model"}${data.level ? `, ${data.level}` : ""}. Change`}
        >
          {data.changed && <span className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-primary" aria-hidden />}
          <span className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">{data.label}</span>
          <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs font-medium">
            <ModelLogo model={data.model} size={13} />
            <span className="truncate">{data.model?.label ?? "—"}</span>
          </span>
          {data.level && (
            <span className="text-[10px] text-muted-foreground">
              {data.level}
              {data.isDefault && " · default"}
            </span>
          )}
        </motion.button>
      </PopoverAnchor>
      <PopoverContent side="bottom" align="start" className="w-80 space-y-3">
        <div className="text-sm font-medium">{data.label}</div>
        {data.editor}
      </PopoverContent>
    </Popover>
  );
}

const ICONS: Record<string, typeof Database> = { memory: Database, office: FileText, ready: CheckCircle2 };

/** A turn of yours (the source check, questions), or what feeds the pipeline (the TM, a file read directly). */
function OtherBox({ id, kind, label, dim, style }: { id: string; kind: "you" | "context"; label: string; dim: boolean; style: React.CSSProperties }) {
  const Icon = kind === "you" ? User : (ICONS[id] ?? FileText);
  return (
    <div
      style={style}
      className={cn(
        "absolute flex items-center gap-2 px-2.5 text-[11px] leading-snug text-muted-foreground transition-opacity",
        kind === "you" ? "rounded-full border border-dashed border-primary/40" : "rounded-lg bg-muted",
        dim && "opacity-35",
      )}
    >
      <Icon size={14} className={cn("shrink-0", kind === "you" && "text-primary")} />
      <span className="line-clamp-3">{label}</span>
    </div>
  );
}

/** Scale a fixed-size drawing down to its container's width (never up). */
function useFit(width: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => setScale(Math.min(1, el.clientWidth / width));
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [width]);
  return { ref, scale };
}

/** The pipeline as it runs, each step on its model: hover a group row to light up the steps it changes, click a step
 * to change just that one. The steps that run on request (no arrows between them) are listed under it. */
export function PipelineFlow({
  spec,
  choices,
  models,
  settings,
  highlight,
  changed,
  pulse,
  onChange,
}: {
  spec: PipelineFlowSpec;
  choices: ModelChoices;
  models: ModelInfo[];
  settings: AppSettingsView;
  highlight: StepId[] | null;
  changed: Set<StepId>;
  pulse: { steps: StepId[]; at: number } | null;
  onChange: (step: StepId, choice: StepChoice) => void;
}) {
  const [open, setOpen] = useState<StepId | null>(null);
  const byId = useMemo(() => new Map(models.map((m) => [m.id, m])), [models]);
  const vision = useMemo(() => new Set(settings.steps.filter((s) => s.vision).map((s) => s.step)), [settings.steps]);
  const lit = highlight ? new Set(highlight) : null;

  // The connected part (boxes with arrows) is drawn; its rows are renumbered without the gaps of the others.
  const linked = useMemo(() => new Set(spec.edges.flatMap(([a, b]) => [a, b])), [spec.edges]);
  const drawn = spec.nodes.filter((n) => linked.has(n.id));
  const rows = [...new Set(drawn.map((n) => n.row))].sort((a, b) => a - b);
  const boxes = new Map(drawn.map((n) => [n.id, { id: n.id, row: rows.indexOf(n.row), col: n.col }]));
  const cols = Math.max(0, ...drawn.map((n) => n.col)) + 1;
  const loopsUnderLast = spec.edges.some(([a, b]) => {
    const s = boxes.get(a);
    const t = boxes.get(b);
    return s && t && s.row === t.row && t.col < s.col && s.row === rows.length - 1;
  });
  const width = NAMES + cols * W + (cols - 1) * GAP_X;
  const height = rows.length * H + (rows.length - 1) * GAP_Y + (loopsUnderLast ? LOOP + 14 : 0);
  const { ref, scale } = useFit(width);

  const stepData = (step: StepId, label: string): StepData => {
    const choice = choices[step];
    const model = choice ? byId.get(choice.model) : undefined;
    const level = choice ? effectiveEffort(settings, models, step, choice) : null;
    const editor = choice && (
      <div className="space-y-2">
        <ModelSelect
          value={choice.model}
          models={models}
          visionOnly={vision.has(step)}
          onChange={(m) => onChange(step, { model: m, effort: byId.get(m)?.thinking && model?.thinking ? choice.effort : null })}
          label={`${label} model`}
          className="w-full"
        />
        <EffortToggle
          value={choice.effort}
          model={model}
          fallback={defaultEffort(settings, models, step, choice.model)}
          onChange={(effort) => onChange(step, { ...choice, effort })}
          label={`${label} reasoning level`}
          compact
        />
      </div>
    );
    return {
      step,
      label,
      model,
      level: level ? EFFORT_LABEL[level.effort] : null,
      isDefault: !!level?.isDefault,
      lit: !!lit?.has(step),
      dim: !!lit && !lit.has(step),
      changed: changed.has(step),
      pulse: pulse?.steps.includes(step) ? pulse.at : null,
      open: open === step,
      setOpen: (o: boolean) => setOpen(o ? step : null),
      editor: editor ?? null,
    };
  };

  const stepOf = new Map(spec.nodes.map((n) => [n.id, n.step]));
  const arrows = spec.edges.flatMap(([a, b, label], i) => {
    const s = boxes.get(a);
    const t = boxes.get(b);
    if (!s || !t) return [];
    const active = !!lit && [stepOf.get(a), stepOf.get(b)].some((x) => x && lit.has(x));
    return [{ key: `${a}-${b}-${i}`, active, label, ...route(s, t) }];
  });

  // The steps run on request, by the row they belong to (no arrows: a grid).
  const sections = spec.rows
    .map((title, row) => ({ title, steps: spec.nodes.filter((n) => n.row === row && !linked.has(n.id) && n.step) }))
    .filter((s) => s.steps.length);

  return (
    <div className="space-y-4 rounded-xl border border-border bg-background/60 p-3" aria-label="The pipeline: each step and the model it uses">
      <div ref={ref} style={{ height: height * scale }}>
        <div className="relative origin-top-left" style={{ width, height, transform: `scale(${scale})` }}>
          {rows.map((row, i) => (
            <div
              key={row}
              className="absolute flex items-center pr-4 text-[10px] leading-tight font-semibold tracking-wider text-muted-foreground/80 uppercase"
              style={{ left: 0, top: i * (H + GAP_Y), width: NAMES, height: H }}
            >
              {spec.rows[row]}
            </div>
          ))}
          <svg className="pointer-events-none absolute inset-0 overflow-visible" width={width} height={height} aria-hidden>
            <defs>
              {(["idle", "active"] as const).map((k) => (
                <marker key={k} id={`arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill={k === "active" ? "var(--primary)" : "var(--muted-foreground)"} fillOpacity={k === "active" ? 0.9 : 0.55} />
                </marker>
              ))}
            </defs>
            {arrows.map((a) => (
              <path
                key={a.key}
                d={roundedPath(a.points)}
                fill="none"
                stroke={a.active ? "var(--primary)" : "var(--muted-foreground)"}
                strokeOpacity={a.active ? 0.85 : 0.4}
                strokeWidth={1.25}
                strokeDasharray={a.active ? "5 4" : undefined}
                className={a.active ? "motion-safe:animate-[flow-dash_0.8s_linear_infinite]" : undefined}
                markerEnd={`url(#arrow-${a.active ? "active" : "idle"})`}
              />
            ))}
          </svg>
          {arrows
            .filter((a) => a.label)
            .map((a) => (
              <span
                key={`${a.key}-label`}
                className="pointer-events-none absolute rounded bg-card px-1 text-[9px] whitespace-nowrap text-muted-foreground"
                style={{ left: a.at.x, top: a.at.y, transform: a.above ? "translate(-50%, -125%)" : "translate(-50%, -50%)" }}
              >
                {a.label}
              </span>
            ))}
          {drawn.map((n) => {
            const b = boxes.get(n.id)!;
            const style = { left: left(b), top: top(b), width: W, height: H };
            return n.kind === "step" && n.step ? (
              <StepCard key={n.id} data={stepData(n.step, n.label)} className="absolute" style={style} />
            ) : (
              <OtherBox key={n.id} id={n.id} kind={n.kind as "you" | "context"} label={n.label} dim={!!lit} style={style} />
            );
          })}
        </div>
      </div>
      {sections.map((s) => (
        <div key={s.title}>
          <div className="mb-1.5 text-[10px] font-semibold tracking-wider text-muted-foreground/80 uppercase">{s.title}</div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-3">
            {s.steps.map((n) => (
              <StepCard key={n.id} data={stepData(n.step!, n.label)} className="w-full" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
