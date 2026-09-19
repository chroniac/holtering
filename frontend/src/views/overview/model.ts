import type { Episode, Overview } from "../../api/types";
import type { Range } from "../../lib/nav";

export const PAD_L = 34,
  PAD_R = 12,
  PAD_T = 8;
export const ECT_H = 30,
  NOISE_H = 8,
  AX_H = 18,
  HR_MIN = 60;
export const BIN_MIN = 10,
  HANDLE_W = 6;
export const CTX_MIN = 60,
  CTX_MAX = 3 * 3600;
export const DOT_ROWS = 6;
export const NOISE_THR = 0.35;

export interface OverviewView {
  root: HTMLElement;
  /** Нарисовать контекст (то, что показывает миникарта) и положение ленты внутри него. */
  setContext(ctx: Range, strip: Range): void;
  setActiveEpisode(id: number | null): void;
  update(ov: Overview, episodes: Episode[]): void;
  setEvents(secs: number[]): void;
}

/** Суммы по `bin` минут подряд; последняя корзина короче, если запись не кратна bin. */
export const binSums = (arr: number[], bin: number, nb: number): number[] =>
  Array.from({ length: nb }, (_, b) => arr.slice(b * bin, (b + 1) * bin).reduce((p, c) => p + c, 0));

export const hrBounds = (hrs: number[]): { lo: number; hi: number } => {
  const finite = hrs.filter((v) => !Number.isNaN(v));
  return {
    lo: Math.max(30, Math.floor(Math.min(...finite) / 10) * 10 - 10),
    hi: Math.ceil(Math.max(...finite) / 10) * 10 + 10,
  };
};

export const hrTicks = (lo: number, hi: number): number[] => [lo + 10, Math.round((lo + hi) / 20) * 10, hi - 10];

/** Номера минут, попавших в ночь (до 6 утра по локальному времени записи). */
export const nightMinutes = (start: Date, count: number): number[] => {
  const out: number[] = [];
  for (let m = 0; m < count; m++) if (new Date(start.getTime() + m * 60000).getHours() < 6) out.push(m);
  return out;
};

/** Отрезки помех как пары индексов десятисекундных окон [начало, конец). */
export const noiseRuns = (noise10: number[]): [number, number][] => {
  const out: [number, number][] = [];
  let run: number | null = null;
  noise10.forEach((v, i) => {
    const bad = v >= NOISE_THR;
    if (bad && run === null) run = i;
    if ((!bad || i === noise10.length - 1) && run !== null) {
      out.push([run, i + (bad ? 1 : 0)]);
      run = null;
    }
  });
  return out;
};

export const hourlySums = (minute: number[]): number[] =>
  Array.from({ length: Math.ceil(minute.length / 60) }, (_, hh) =>
    minute.slice(hh * 60, (hh + 1) * 60).reduce((p, c) => p + c, 0),
  );

/** Первая метка оси времени: ближайший чётный час от начала записи. */
export const firstTickSec = (start: Date): number =>
  (2 - (start.getHours() % 2)) * 3600 - start.getMinutes() * 60 - start.getSeconds();
