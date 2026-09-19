export interface Summary {
  patient: { name: string; id: string; sex: string; age: number; dob: string };
  record: {
    start: string;
    duration_s: number;
    fs: number;
    leads: string[];
    beats: number;
    avm_nv: number;
    gain: number | null;
    gain_verified: boolean;
    clean_pct: number;
  };
  hr: {
    mean: number;
    min: number;
    max: number;
    min_at_s: number;
    max_at_s: number;
    night: number | null;
    day: number | null;
    sleep: number | null;
    wake: number | null;
    pct_over_100: number;
    pct_under_50: number;
  };
  hrv: { sdnn: number; rmssd: number; pnn50: number; mean_rr: number; n: number };
  counts: {
    device: { N: number; V: number; S: number };
    audited: { V: number; V_likely: number; S: number };
    manual: number;
    added: number;
    quality_spans: number;
    verdicts: Record<string, Record<string, number>>;
    pauses_device: number;
    pauses_real: number;
  };
  calibration: { sinus_width_ms: number; noise_base_ii_mv: number; qrs_amp_mv: number };
  computed_s: number;
  criteria: Criterion[];
  morphologies: { family: number; count: number }[];
}

/** Одна из пяти находок расшифровки (ISHNE 2017); met: null — автоматически не оценивается. */
export interface Criterion {
  key: string;
  title: string;
  value: string;
  met: boolean | null;
  note: string;
}

export interface DiaryEvent {
  id: number;
  t_ms: number;
  text: string;
  hr: number | null;
  hr_min: number | null;
  hr_max: number | null;
  v: number;
  s: number;
  episodes: number[];
  noise: number;
}

export interface Overview {
  minute_hr: (number | null)[];
  minute_v: number[];
  minute_s: number[];
  minute_v_device: number[];
  noise10: number[];
  noise_window_s: number;
  quality_manual: QualitySpan[];
  sleep: [number, number][];
}

export type Verdict =
  | "N"
  | "likely"
  | "uncertain"
  | "double-count"
  | "on-wave"
  | "noisy"
  | "narrow"
  | "not-premature"
  | "sinus-shape"
  | "manual"
  | "manual-N"
  | "manual-X";

export type ManualLabel = "N" | "V" | "S" | "X";

export interface Beat {
  index: number;
  t_ms: number;
  label: string;
  device_label: string | null; // null у комплекса, добавленного врачом
  manual: ManualLabel | null;
  added: boolean;
  verdict: Verdict;
  confidence: number;
  reasons: string[];
  width_ms: number | null;
  width_ratio: number | null; // ширина QRS / ширина синусового QRS
  prematurity: number | null; // RR перед комплексом / предшествующий синусовый RR
  amp_ratio: number | null; // |QRS| / часовая синусовая амплитуда
  noise_ratio: number | null; // локальная ВЧ-помеха / базовый уровень записи
  family_n_frac: number | null; // доля метки N в морфологическом семействе комплекса
  rr_pre: number | null;
  rr_post: number | null;
  template: number;
}

export interface NoiseWindow {
  t0: number;
  t1: number;
  score: number;
}
export interface QualitySpan {
  t0_ms: number;
  t1_ms: number;
  v: "clean" | "noise";
}

export interface EcgWindow {
  start: number;
  fs: number;
  leads: string[];
  data: number[][];
  lead_noise: number[];
  lead_drift: number[];
  drift_thr_mv: number;
  beats: Beat[];
  noise_windows: NoiseWindow[];
  quality_manual: QualitySpan[];
}

/** Комплексы колонками для обзорных видов; cls: 0 N · 1 likely · 2 uncertain · 3 rejected · 4 manual, label: 0 N · 1 V · 2 S · 3 X. */
export interface BeatsWindow {
  start: number;
  dur: number;
  first_index: number;
  t_ms: number[];
  rr_ms: number[];
  label: number[];
  cls: number[];
  noise_windows: NoiseWindow[];
}

export interface RawLead {
  fs: number;
  start: number;
  mvPerLsb: number;
  samples: Int16Array;
}

export interface Episode {
  id: number;
  kind: "pause" | "v-run" | "s-run" | "noise" | "missed" | "qt";
  t_ms: number;
  dur_ms: number;
  title: string;
  verdict: "artifact" | "review" | "likely";
  confidence: number;
  reasons: string[];
  beats: number[];
}

export interface Template {
  id: number;
  count: number;
  labels: Record<string, number>;
  verdicts: Record<string, number>;
  verdicts_by_label: Record<string, Record<string, number>>; // {"V": {likely: n, narrow: n, ...}, "S": {...}}
  manual: Record<string, number>;
  hours: number[];
  wave: { fs: number; half_ms: number; leads: number[][] };
  first: number;
  sample: number[];
}

/** Фрагмент ЭКГ для печати: авто-фрагменты даёт сборщик протокола, врачебные несут свои отведения. */
export interface StripSpec {
  id: string;
  kind: string;
  t0_ms: number;
  dur_s: number;
  caption: string;
  beat?: number | null;
  leads?: string[];
}

export interface ReportSaved {
  text: Record<string, string>; // раздел -> правка врача (ключа нет — текст сгенерирован)
  meta: Record<string, string>; // клиника, отделение, врач, направление, терапия
  strips: StripSpec[]; // добавленные врачом
  captions: Record<string, string>; // id авто-фрагмента -> подпись врача
  hidden: string[]; // исключённые авто-фрагменты
  include: Record<string, boolean>; // тренды, фрагменты
}

export interface ReportData {
  generated: Record<string, string>;
  titles: Record<string, string>;
  order: string[];
  header: {
    patient: Summary["patient"];
    sex_ru: string;
    age_ru: string;
    start: string;
    end: string;
    duration: string;
    device: string;
    software: string;
    leads: string[];
    beats: string;
  };
  summary: { k: string; v: string; n: string }[];
  hourly: {
    hour: string;
    partial: boolean;
    minutes: number;
    beats: number;
    hr_min: number | null;
    hr_mean: number | null;
    hr_max: number | null;
    v: number;
    s: number;
    pairs: number;
    runs: number;
    s_runs: number;
    pauses: number;
    noise_pct: number;
    sleep: boolean;
  }[];
  auto_strips: StripSpec[];
  saved: Partial<ReportSaved>;
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json() as Promise<T>;
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json() as Promise<T>;
}

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
