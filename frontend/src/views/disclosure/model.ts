import { CLS_COLOR as PALETTE } from "../../lib/verdict";

export const ROW_S = 60,
  PAGE_ROWS = 30,
  ROW_H = 34,
  GUTTER = 52;
export const CLS_COLOR = ["", ...PALETTE.slice(1)]; // N рисуется штрихом, а не точкой

export interface DisclosureView {
  root: HTMLElement;
  show(atSec: number, lead: string, strip: { start: number; dur: number }): Promise<void>;
  refresh(): Promise<void>;
}

/** Авторежим: в высоту строки вписывается размах, взятый с запасом от пикового отсчёта. */
export const autoAmpMv = (samples: Int16Array, mvPerLsb: number): number => {
  let mx = 0;
  for (let i = 0; i < samples.length; i += 7) {
    const v = Math.abs(samples[i]);
    if (v > mx) mx = v;
  }
  return Math.max(0.5, mx * mvPerLsb * 0.6);
};

/** Базовая линия строки: медиана прореженных отсчётов, чтобы дрейф не уводил кривую. */
export const rowMedian = (samples: Int16Array, s0: number, s1: number): number => {
  const samp: number[] = [];
  for (let i = s0; i < s1; i += 25) samp.push(samples[i]);
  samp.sort((a, b) => a - b);
  return samp[samp.length >> 1] ?? 0;
};
