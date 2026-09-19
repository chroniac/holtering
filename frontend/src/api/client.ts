import type {
  Beat,
  BeatsWindow,
  DiaryEvent,
  EcgWindow,
  Episode,
  ManualLabel,
  Overview,
  QualitySpan,
  RawLead,
  ReportData,
  ReportSaved,
  Summary,
  Template,
} from "./types";

const get = async <T>(url: string): Promise<T> => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json() as Promise<T>;
};

const post = async <T>(url: string, body: unknown): Promise<T> => {
  const r = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json() as Promise<T>;
};

export const api = {
  summary: () => get<Summary>("/api/summary"),
  overview: () => get<Overview>("/api/overview"),
  episodes: () => get<Episode[]>("/api/episodes"),
  beat: (index: number) => get<Beat>(`/api/beat/${index}`),
  templates: () => get<Template[]>("/api/templates"),
  templateBeats: (id: number, offset = 0, limit = 200) =>
    get<{ total: number; beats: Beat[] }>(`/api/templates/${id}/beats?offset=${offset}&limit=${limit}`),
  beats: (start: number, dur: number) => get<BeatsWindow>(`/api/beats?start=${start.toFixed(2)}&dur=${dur.toFixed(1)}`),
  raw: async (start: number, dur: number, lead: string): Promise<RawLead> => {
    const r = await fetch(`/api/raw?start=${start.toFixed(2)}&dur=${dur.toFixed(1)}&lead=${encodeURIComponent(lead)}`);
    if (!r.ok) throw new Error(`raw: ${r.status}`);
    return {
      fs: Number(r.headers.get("x-fs")),
      start: Number(r.headers.get("x-start")),
      mvPerLsb: Number(r.headers.get("x-mv-per-lsb")),
      samples: new Int16Array(await r.arrayBuffer()),
    };
  },
  ecg: (start: number, dur: number, leads: string[]) =>
    get<EcgWindow>(
      `/api/ecg?start=${start.toFixed(3)}&dur=${dur.toFixed(2)}&leads=${encodeURIComponent(leads.join(","))}`,
    ),
  annotate: (index: number, label: ManualLabel | null) => post<Beat>(`/api/annotations/${index}`, { label }),
  addBeat: (t_ms: number, label: ManualLabel) => post<Beat>("/api/beats/add", { t_ms, label }),
  report: () => get<ReportData>("/api/report"),
  saveReport: (saved: ReportSaved) => post<{ ok: boolean }>("/api/report", saved),
  events: () => get<DiaryEvent[]>("/api/events"),
  addEvent: (t_ms: number, text: string) => post<DiaryEvent>("/api/events", { t_ms, text }),
  delEvent: async (id: number) => {
    const r = await fetch(`/api/events/${id}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`delete: ${r.status}`);
  },
  quality: (t0_ms: number, t1_ms: number, value: "clean" | "noise" | null) =>
    post<{ spans: QualitySpan[] }>("/api/quality", { t0_ms, t1_ms, value }),
  annotateTemplate: (id: number, label: ManualLabel | null) =>
    post<{ beats: number }>(`/api/templates/${id}/label`, { label }),
};
