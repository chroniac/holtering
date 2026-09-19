import type { Range } from "../../lib/nav";

export const H = 74,
  RR_TOP = 4,
  RR_H = 40,
  TICK_Y = 50,
  TICK_H = 14,
  AXIS_Y = 66;
export const HANDLE = 6;
export const STRIP_MIN = 2,
  STRIP_MAX = 120;

export interface MinimapView {
  root: HTMLElement;
  /** Показать `ctx` (догрузив комплексы при смене) и нарисовать в нём окно ленты. */
  set(ctx: Range, strip: Range): Promise<void>;
  refresh(): Promise<void>;
  setEvents(secs: number[]): void;
}

/** Тахограмма: R-R от 300 до 1600 мс занимает всю полосу, за краями — прижимается к ней. */
export const rrY = (rr: number): number => RR_TOP + RR_H - Math.max(0, Math.min(1, (rr - 300) / 1300)) * RR_H;

/** Шаг подписей оси, чтобы их оставалось около десятка на любом масштабе контекста. */
export const tickStep = (dur: number): number => (dur <= 180 ? 30 : dur <= 900 ? 60 : dur <= 3600 ? 300 : 900);

export const dotSize = (w: number, n: number): number => Math.max(1, Math.min(2.2, (w / Math.max(1, n)) * 1.2));

export const ctxLabel = (ctx: Range, strip: Range): string => {
  const ctxTxt =
    ctx.dur >= 3600 ? `${(ctx.dur / 3600).toFixed(ctx.dur % 3600 ? 1 : 0)} ч` : `${Math.round(ctx.dur / 60)} мин`;
  return `${ctxTxt} · окно ${strip.dur % 1 ? strip.dur.toFixed(1) : strip.dur} с · точки: R-R`;
};
