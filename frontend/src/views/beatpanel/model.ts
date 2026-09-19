import type { Beat, EcgWindow, Template } from "../../api/types";

export const STRIP_DUR = 2.4; // секунд вокруг комплекса
export const SHAPE_MS = 96; // окно ± для наложения формы (как в templates.py)

const fmt = (v: number | null, f: (x: number) => string) => (v === null ? "—" : f(v));

/** Признаки комплекса строками «ключ — значение»; «—» там, где признак не считался. */
export const featRows = (b: Beat): [string, string][] => [
  ["QRS", fmt(b.width_ms, (x) => `${x.toFixed(0)} мс`)],
  ["синусовый QRS", fmt(b.width_ratio, (x) => (b.width_ms ? `${(b.width_ms / x).toFixed(0)} мс` : "—"))],
  ["RR до", fmt(b.rr_pre, (x) => `${x} мс`)],
  ["RR после", fmt(b.rr_post, (x) => `${x} мс`)],
  ["ритм до неё", fmt(b.prematurity, (x) => (b.rr_pre ? `${(b.rr_pre / x).toFixed(0)} мс` : "—"))],
  ["амплитуда", fmt(b.amp_ratio, (x) => `${(x * 100).toFixed(0)}% от N`)],
  ["шум", fmt(b.noise_ratio, (x) => (x < 1.5 ? "нет" : x < 2.5 ? "умеренный" : "сильный"))],
  ["форма как N", fmt(b.family_n_frac, (x) => (x > 0.9 ? "да" : x < 0.2 ? "нет" : "частично"))],
];

/** Формы накладываются друг на друга, поэтому каждую центрируем по медиане и делим на пик. */
export const norm = (w: number[]): number[] => {
  const med = [...w].sort((a, b) => a - b)[w.length >> 1];
  const c = w.map((v) => v - med);
  const m = Math.max(1e-6, ...c.map(Math.abs));
  return c.map((v) => v / m);
};

/** Отрезок первого отведения окна вокруг комплекса — то, что накладывается на форму семейства. */
export const beatShape = (win: EcgWindow, t_ms: number): number[] => {
  const ii = win.data[0];
  const c = Math.round((t_ms / 1000 - win.start) * win.fs),
    half = Math.round((SHAPE_MS / 1000) * win.fs);
  return ii.slice(Math.max(0, c - half), c + half + 1);
};

/** Отклонённые — всё, что не likely, не uncertain и не N. */
export const famParts = (t: Template): [string, number][] => [
  ["likely", t.verdicts.likely ?? 0],
  ["uncertain", t.verdicts.uncertain ?? 0],
  [
    "rejected",
    Object.entries(t.verdicts)
      .filter(([k]) => !["likely", "uncertain", "N"].includes(k))
      .reduce((p, [, n]) => p + n, 0),
  ],
  ["n", t.verdicts.N ?? 0],
];
