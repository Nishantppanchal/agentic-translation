import type {
  Answer,
  AppConfig,
  AppSettingsView,
  DocSettings,
  ExportFormat,
  ModelInfo,
  OfficeInfo,
  OfficeWriteReport,
  SheetGrid,
  StepChoice,
  StepId,
  Project,
  QaReport,
  ReplaceMatch,
  ReplaceOptions,
  Role,
  Segment,
  SessionDetail,
  SessionSummary,
  StatusCounts,
  StreamEvent,
  TaskKind,
  Term,
  TmMatch,
  TmUnit,
  Usage,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

const send = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  config: () => fetch(`${API_URL}/api/config`).then((r) => json<AppConfig>(r)),

  listSessions: () => fetch(`${API_URL}/api/sessions`).then((r) => json<SessionSummary[]>(r)),

  getSession: (id: string) => fetch(`${API_URL}/api/sessions/${id}`).then((r) => json<SessionDetail>(r)),

  deleteSession: (id: string) =>
    fetch(`${API_URL}/api/sessions/${id}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),

  /** `overrides`: this document's own models (only the steps that differ from the defaults) and dictionary. */
  createSession: (file: File, sourceLang: string, projectId?: string | null, overrides?: SettingsUpdate) => {
    const form = new FormData();
    form.append("file", file);
    form.append("source_lang", sourceLang);
    if (projectId) form.append("project_id", projectId);
    if (overrides?.models && Object.keys(overrides.models).length) form.append("models", JSON.stringify(overrides.models));
    if (overrides?.dictionary !== undefined) form.append("dictionary", String(overrides.dictionary));
    if (overrides?.second_reader !== undefined) form.append("second_reader", String(overrides.second_reader));
    return fetch(`${API_URL}/api/sessions`, { method: "POST", body: form }).then((r) => json<SessionSummary>(r));
  },

  models: () => fetch(`${API_URL}/api/models`).then((r) => json<ModelInfo[]>(r)),
  getSettings: () => fetch(`${API_URL}/api/settings`).then((r) => json<AppSettingsView>(r)),
  /** The defaults for new documents; a step set to null goes back to pipeline.yaml's model. */
  putSettings: (body: SettingsUpdate) => fetch(`${API_URL}/api/settings`, send("PUT", body)).then((r) => json<AppSettingsView>(r)),
  /** One document's models and dictionary, from its next run (409 while the agents work on it). */
  patchSessionSettings: (id: string, body: SettingsUpdate) =>
    fetch(`${API_URL}/api/sessions/${id}/settings`, send("PATCH", body)).then((r) => json<DocSettings>(r)),

  runTask: (id: string, kind: TaskKind, segmentIds: string[] = [], instruction = "", n = 1) =>
    fetch(`${API_URL}/api/sessions/${id}/tasks`, send("POST", { kind, segment_ids: segmentIds, instruction, n })).then((r) =>
      json<{ ok: boolean }>(r),
    ),

  addComment: (id: string, segmentId: string, text: string, role: Role) =>
    fetch(`${API_URL}/api/sessions/${id}/segments/${segmentId}/comments`, send("POST", { text, role })).then((r) =>
      json<{ segment: Segment }>(r),
    ),

  resolveComment: (id: string, segmentId: string, commentId: string, resolved: boolean) =>
    fetch(`${API_URL}/api/sessions/${id}/segments/${segmentId}/comments/${commentId}`, send("PATCH", { resolved })).then((r) =>
      json<{ segment: Segment | null }>(r),
    ),

  deleteComment: (id: string, segmentId: string, commentId: string) =>
    fetch(`${API_URL}/api/sessions/${id}/segments/${segmentId}/comments/${commentId}`, send("DELETE")).then((r) =>
      json<{ segment: Segment | null }>(r),
    ),

  sendMessage: (id: string, text: string) =>
    fetch(`${API_URL}/api/sessions/${id}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }).then((r) => json<{ ok: boolean }>(r)),

  answerQuestion: (id: string, questionId: string, answer: Answer | null) =>
    fetch(`${API_URL}/api/sessions/${id}/questions/${questionId}`, send("POST", answer ?? {})).then((r) => json<{ ok: boolean }>(r)),

  editSegment: (
    id: string,
    segmentId: string,
    body: { target?: string; confirm?: boolean; base_target?: string; role?: Role },
  ) =>
    fetch(`${API_URL}/api/sessions/${id}/segments/${segmentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => json<{ segment: Segment; human_dirty: string[]; counts: StatusCounts }>(r)),

  lockSegment: (id: string, segmentId: string, locked: boolean) =>
    fetch(`${API_URL}/api/sessions/${id}/segments/${segmentId}/lock`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ locked }),
    }).then((r) => json<{ segment: Segment }>(r)),

  confirmSegments: (id: string, ids: string[] | null, role: Role = "translator") =>
    fetch(`${API_URL}/api/sessions/${id}/segments/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, role }),
    }).then((r) => json<{ confirmed: string[]; counts: StatusCounts }>(r)),

  segmentTm: (id: string, segmentId: string) =>
    fetch(`${API_URL}/api/sessions/${id}/segments/${segmentId}/tm`).then((r) => json<{ matches: TmMatch[] }>(r)),

  qa: (id: string) => fetch(`${API_URL}/api/sessions/${id}/qa`).then((r) => json<QaReport>(r)),

  ignoreQa: (id: string, ids: string[], ignored = true) =>
    fetch(`${API_URL}/api/sessions/${id}/qa/ignore`, send("POST", { ids, ignored })).then((r) => json<{ ignored: number }>(r)),

  replacePreview: (id: string, opts: ReplaceOptions) =>
    fetch(`${API_URL}/api/sessions/${id}/replace/preview`, send("POST", opts)).then((r) =>
      json<{ matches: ReplaceMatch[]; locked: number }>(r),
    ),

  replaceApply: (id: string, opts: ReplaceOptions) =>
    fetch(`${API_URL}/api/sessions/${id}/replace`, send("POST", opts)).then((r) =>
      json<{ changed: string[]; version: number | null; locked: number }>(r),
    ),

  runLqa: (id: string) => fetch(`${API_URL}/api/sessions/${id}/lqa`, send("POST")).then((r) => json<{ ok: boolean; model: string }>(r)),

  saveVersion: (id: string) =>
    fetch(`${API_URL}/api/sessions/${id}/versions`, { method: "POST" }).then((r) => json<{ version: number | null }>(r)),

  usage: (id: string) => fetch(`${API_URL}/api/sessions/${id}/usage`).then((r) => json<Usage>(r)),

  /** `confirm`: Accept & confirm — the new translations are confirmed, and saved to the project's TM. */
  acceptProposal: (id: string, changes: string[] | null, choices: Record<string, number> | null = null, confirm = false) =>
    fetch(`${API_URL}/api/sessions/${id}/proposal/accept`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ changes, choices, confirm }),
    }).then((r) => json<{ version: number | null; applied: number; dropped: number }>(r)),

  rejectProposal: (id: string) =>
    fetch(`${API_URL}/api/sessions/${id}/proposal/reject`, { method: "POST" }).then((r) =>
      json<{ rejected: number }>(r),
    ),

  continueAfterSourceCheck: (id: string) =>
    fetch(`${API_URL}/api/sessions/${id}/source/continue`, { method: "POST" }).then((r) => json<{ ok: boolean }>(r)),

  decideSourceFix: (id: string, page: number, accept: boolean) =>
    fetch(`${API_URL}/api/sessions/${id}/source/fixes/${page}/${accept ? "accept" : "reject"}`, { method: "POST" }).then((r) =>
      json<{ ok: boolean }>(r),
    ),

  /** "This is text, not a picture": the page is read again with that picture's text in place, as a page fix. */
  figureAsText: (id: string, page: number, figure: number) =>
    fetch(`${API_URL}/api/sessions/${id}/source/figures/${page}/${figure}/text`, { method: "POST" }).then((r) =>
      json<{ status: "proposed" | "unchanged" }>(r),
    ),

  /** A Word / PowerPoint / Excel upload: the original, or translated (as of a version); `marks`: hidden _seg_ bookmarks. */
  officeFileUrl: (id: string, side: "source" | "target", version?: number, marks = false) =>
    `${API_URL}/api/sessions/${id}/office/file?side=${side}${version ? `&version=${version}` : ""}${marks ? "&marks=true" : ""}`,
  officeReport: (id: string, version?: number) =>
    fetch(`${API_URL}/api/sessions/${id}/office/report${version ? `?version=${version}` : ""}`).then((r) =>
      json<{ extract: OfficeInfo; write: OfficeWriteReport }>(r),
    ),
  officeSheets: (id: string) => fetch(`${API_URL}/api/sessions/${id}/office/sheets`).then((r) => json<SheetGrid>(r)),

  retry: (id: string) =>
    fetch(`${API_URL}/api/sessions/${id}/retry`, { method: "POST" }).then((r) => json<{ ok: boolean }>(r)),

  submitClarifications: (id: string, answers: Record<string, Answer | null>) =>
    fetch(`${API_URL}/api/sessions/${id}/clarifications`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers }),
    }).then((r) => json<{ ok: boolean }>(r)),

  getVersion: (id: string, version: number) =>
    fetch(`${API_URL}/api/sessions/${id}/versions/${version}`).then((r) =>
      json<{ version: number; segments: Record<string, string> }>(r),
    ),

  pageImageUrl: (id: string, page: number) => `${API_URL}/api/sessions/${id}/pages/${page}`,

  figureUrl: (id: string, name: string) => `${API_URL}/api/sessions/${id}/figures/${name}`,

  exportUrl: (id: string, version?: number, field: "target" | "source" = "target", format: ExportFormat["id"] = "md") =>
    `${API_URL}/api/sessions/${id}/export?format=${format}&field=${field}${version ? `&version=${version}` : ""}`,

  exportFormats: (id: string) =>
    fetch(`${API_URL}/api/sessions/${id}/export/formats`).then((r) => json<ExportFormat[]>(r)),
  /** The translation summary (the Assist model writes them from the document's decisions, queries and checks). */
  clientNotes: (id: string) =>
    fetch(`${API_URL}/api/sessions/${id}/assist/notes`, { method: "POST" }).then((r) =>
      json<{ text: string; version: number | null; at: number; stored: boolean }>(r),
    ),
};

/** A change to the model choices (null: back to the default) and/or the dictionary. */
export type SettingsUpdate = {
  models?: Partial<Record<StepId, StepChoice | null>>;
  dictionary?: boolean;
  second_reader?: boolean; // a second model reads scanned pages and pictures too
  assist?: boolean;
};

type ProjectFields = Partial<Pick<Project, "name" | "source_lang" | "instructions" | "auto_confirm_context" | "lqa_threshold">>;
type TermFields = Partial<Pick<Term, "source" | "target" | "note" | "forbidden" | "case_sensitive" | "status">>;

export const projectsApi = {
  list: () => fetch(`${API_URL}/api/projects`).then((r) => json<Project[]>(r)),
  get: (pid: string) => fetch(`${API_URL}/api/projects/${pid}`).then((r) => json<Project>(r)),
  create: (fields: ProjectFields) => fetch(`${API_URL}/api/projects`, send("POST", fields)).then((r) => json<Project>(r)),
  update: (pid: string, fields: ProjectFields) =>
    fetch(`${API_URL}/api/projects/${pid}`, send("PATCH", fields)).then((r) => json<Project>(r)),
  remove: (pid: string) => fetch(`${API_URL}/api/projects/${pid}`, send("DELETE")).then((r) => json<{ ok: boolean }>(r)),

  terms: (pid: string) => fetch(`${API_URL}/api/projects/${pid}/terms`).then((r) => json<Term[]>(r)),
  addTerm: (pid: string, fields: TermFields) =>
    fetch(`${API_URL}/api/projects/${pid}/terms`, send("POST", fields)).then((r) => json<Term>(r)),
  updateTerm: (pid: string, termId: number, fields: TermFields) =>
    fetch(`${API_URL}/api/projects/${pid}/terms/${termId}`, send("PATCH", fields)).then((r) => json<Term>(r)),
  deleteTerm: (pid: string, termId: number) =>
    fetch(`${API_URL}/api/projects/${pid}/terms/${termId}`, send("DELETE")).then((r) => json<{ ok: boolean }>(r)),

  tm: (pid: string, q = "") =>
    fetch(`${API_URL}/api/projects/${pid}/tm?q=${encodeURIComponent(q)}`).then((r) =>
      json<{ total: number; units: TmUnit[] }>(r),
    ),
  deleteUnit: (pid: string, unitId: number) =>
    fetch(`${API_URL}/api/projects/${pid}/tm/${unitId}`, send("DELETE")).then((r) => json<{ ok: boolean }>(r)),
};

/** The chat's AI assist: suggested next prompts, and completions of what's being typed (Tab). */
export const assistApi = {
  suggestions: (id: string, signal?: AbortSignal) =>
    fetch(`${API_URL}/api/sessions/${id}/assist/suggestions`, { ...send("POST", {}), signal }).then((r) =>
      json<{ suggestions: AssistSuggestion[]; cached?: boolean; disabled?: boolean; error?: string }>(r),
    ),
  complete: (id: string, text: string, signal?: AbortSignal) =>
    fetch(`${API_URL}/api/sessions/${id}/assist/complete`, { ...send("POST", { text }), signal }).then((r) =>
      json<{ completion: string }>(r),
    ),
};
export type AssistSuggestion = { label: string; prompt: string };

/**
 * Subscribe to a session's live run over SSE. Returns an abort function.
 * Uses fetch + ReadableStream (instead of EventSource) so we control reconnects.
 */
export function subscribe(id: string, onEvent: (e: StreamEvent) => void): () => void {
  const ctrl = new AbortController();
  (async () => {
    try {
      const res = await fetch(`${API_URL}/api/sessions/${id}/stream`, { signal: ctrl.signal });
      if (!res.body) return;
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += value;
        let idx: number;
        while ((idx = buf.search(/\r?\n\r?\n/)) !== -1) {
          const chunk = buf.slice(0, idx);
          buf = buf.slice(idx).replace(/^\r?\n\r?\n/, "");
          const data = chunk
            .split(/\r?\n/)
            .filter((l) => l.startsWith("data:"))
            .map((l) => l.slice(5).trimStart())
            .join("\n");
          if (data) {
            try {
              onEvent(JSON.parse(data) as StreamEvent);
            } catch {}
          }
        }
      }
    } catch (err) {
      if (!ctrl.signal.aborted) onEvent({ type: "error", message: String(err) });
    }
  })();
  return () => ctrl.abort();
}
