import type { ReportSaved, StripSpec } from "../../api/types";

export const PAGE_W = 182; // печатная ширина, мм (A4 минус поля 14 мм)
export const STRIP_W = 180; // 7,2 с при 25 мм/с
export const LANE = 16; // мм на отведение
export const STRIPS_PER_SHEET = 4;

// листы 1-2: обложка со сводкой и заключением, затем подробное описание
export const COVER_SECTIONS = ["resume", "recommendations"];

export const KIND_RU: Record<string, string> = {
  sinus: "основной ритм",
  "hr-min": "мин. ЧСС",
  "hr-max": "макс. ЧСС",
  pause: "пауза",
  "v-run": "ЖЭС групповая",
  "s-run": "НЖЭС групповая",
  pvc: "ЖЭС",
  sve: "НЖЭС",
  symptom: "дневник",
  manual: "выбрано врачом",
};

/** Фрагмент листа: `auto` различает сборку протокола и добавленное врачом. */
export type ReportStrip = StripSpec & { auto: boolean };

/** Сервер отдаёт только изменённые части правок, остальное — пустые коллекции. */
export const mergeSaved = (saved?: Partial<ReportSaved>): ReportSaved => ({
  text: {},
  meta: {},
  strips: [],
  captions: {},
  hidden: [],
  include: {},
  ...saved,
});

export const visibleStrips = (auto: StripSpec[], saved: ReportSaved, include: boolean): ReportStrip[] => {
  if (!include) return [];
  const autos: ReportStrip[] = auto.filter((s) => !saved.hidden.includes(s.id)).map((s) => ({ ...s, auto: true }));
  const own: ReportStrip[] = saved.strips.map((s) => ({ ...s, kind: "manual", auto: false }));
  return [...autos, ...own].sort((a, b) => a.t0_ms - b.t0_ms);
};

/** Подпись фрагмента: правка врача поверх автоподписи, у своих фрагментов подпись одна. */
export const captionOf = (spec: ReportStrip, saved: ReportSaved): string =>
  spec.auto ? (saved.captions[spec.id] ?? spec.caption) : spec.caption;

/** id по времени начала: повторное добавление того же окна не плодит фрагменты. */
export const manualStrip = (t0_s: number, dur_s: number, leads: string[]): StripSpec => ({
  id: `m-${Math.round(t0_s * 1000)}`,
  kind: "manual",
  t0_ms: Math.round(t0_s * 1000),
  dur_s,
  caption: "",
  leads,
});

/**
 * Усиление: наибольшее из 10 / 5 / 2.5 мм/мВ, при котором отведения не вылезают из дорожки.
 * Без калибровки шкалы амплитуду подгоняем под дорожку, но не растягиваем сильнее 10 мм/мВ.
 */
export const stripGain = (data: number[][], calibrated: boolean): number => {
  const peak = Math.max(0.05, ...data.map((row) => Math.max(...row.map(Math.abs))));
  const fit = (LANE / 2 - 1.2) / peak;
  return calibrated ? ([10, 5, 2.5, 1, 0.5].find((g) => g <= fit) ?? fit) : Math.min(10, fit);
};
