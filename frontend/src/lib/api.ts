import type {
  Answer,
  AppConfig,
  ExportFormat,
  ImportReport,
  LayoutReport,
  OfficeLayout,
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
  XliffImportReport,
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

  createSession: (file: File, sourceLang: string, projectId?: string | null) => {
    const form = new FormData();
    form.append("file", file);
    form.append("source_lang", sourceLang);
    if (projectId) form.append("project_id", projectId);
    return fetch(`${API_URL}/api/sessions`, { method: "POST", body: form }).then((r) => json<SessionSummary>(r));
  },

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
      json<{ segment: Segment }>(r),
    ),

  deleteComment: (id: string, segmentId: string, commentId: string) =>
    fetch(`${API_URL}/api/sessions/${id}/segments/${segmentId}/comments/${commentId}`, send("DELETE")).then((r) =>
      json<{ segment: Segment }>(r),
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

  importXliff: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${API_URL}/api/sessions/${id}/import/xliff`, { method: "POST", body: form }).then((r) => json<XliffImportReport>(r));
  },

  runLqa: (id: string) => fetch(`${API_URL}/api/sessions/${id}/lqa`, send("POST")).then((r) => json<{ ok: boolean; model: string }>(r)),

  saveVersion: (id: string) =>
    fetch(`${API_URL}/api/sessions/${id}/versions`, { method: "POST" }).then((r) => json<{ version: number | null }>(r)),

  usage: (id: string) => fetch(`${API_URL}/api/sessions/${id}/usage`).then((r) => json<Usage>(r)),

  acceptProposal: (id: string, changes: string[] | null, choices: Record<string, number> | null = null) =>
    fetch(`${API_URL}/api/sessions/${id}/proposal/accept`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ changes, choices }),
    }).then((r) => json<{ version: number | null; applied: number; dropped: number }>(r)),

  rejectProposal: (id: string) =>
    fetch(`${API_URL}/api/sessions/${id}/proposal/reject`, { method: "POST" }).then((r) =>
      json<{ rejected: number }>(r),
    ),

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

  exportUrl: (id: string, version?: number, field: "target" | "source" = "target", format = "md") =>
    `${API_URL}/api/sessions/${id}/export?format=${format}&field=${field}${version ? `&version=${version}` : ""}`,

  exportFormats: (id: string) =>
    fetch(`${API_URL}/api/sessions/${id}/export/formats`).then((r) => json<ExportFormat[]>(r)),

  officeLayout: (id: string) => fetch(`${API_URL}/api/sessions/${id}/preview/office`).then((r) => json<OfficeLayout>(r)),

  previewReport: (id: string, version?: number) =>
    fetch(`${API_URL}/api/sessions/${id}/preview/report${version ? `?version=${version}` : ""}`).then((r) =>
      json<LayoutReport>(r),
    ),

  previewPageUrl: (id: string, page: number, version?: number) =>
    `${API_URL}/api/sessions/${id}/preview/pages/${page}${version ? `?version=${version}` : ""}`,
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

  importFile: (pid: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${API_URL}/api/projects/${pid}/import`, { method: "POST", body: form }).then((r) => json<ImportReport>(r));
  },
  exportUrl: (pid: string, format: "tmx" | "tbx" | "csv") => `${API_URL}/api/projects/${pid}/export?format=${format}`,
};

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
