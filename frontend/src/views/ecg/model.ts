import type { Beat, EcgWindow, NoiseWindow } from "../../api/types";
import { clock } from "../../lib/time";
import { VERDICT_RU, verdictClass } from "../../lib/verdict";

export const MARK_H = 22,
  PAD_B = 14;
export const GAIN_STEPS = [20, 10, 5, 2.5, 1.25];

export interface EcgView {
  root: HTMLElement;
  render(win: EcgWindow, startIso: string, gain: number | "auto"): void;
  highlight(beatIndex: number | null): void;
  /** Курсор времени (секунды от начала записи) для вставки комплекса; null — скрыт. */
  setCursor(sec: number | null): void;
  setRange(r: { t0: number; t1: number } | null): void;
  setEvents(secs: number[]): void;
}

export interface EcgHandlers {
  onBeat: (b: Beat) => void;
  onZoom: (atSec: number, factor: number) => void;
  onPan: (deltaSec: number, live: boolean) => void;
  onCursor: (sec: number) => void;
  /** shift+перетаскивание: интервал (секунды) для отметки «чисто / помеха». */
  onRange: (t0: number, t1: number) => void;
}

/** Самое крупное усиление (мм/мВ), при котором размах сигнала ещё влезает в дорожку. */
export const autoGain = (data: number[][], mm: number, lane: number): number => {
  const ptp = Math.max(...data.map((row) => Math.max(...row) - Math.min(...row)), 0.2);
  return GAIN_STEPS.find((g) => ptp * g * mm <= lane * 0.92) ?? 1.25;
};

export interface NoiseBand {
  a: number;
  b: number;
  score: number;
}

/** Окна помех в пикселях; соседние сливаются в одно, чтобы не плодить подписи. */
export const mergeNoise = (windows: NoiseWindow[], start: number, pxS: number, W: number): NoiseBand[] => {
  const merged: NoiseBand[] = [];
  for (const nw of windows) {
    const a = Math.max(0, (nw.t0 - start) * pxS),
      b = Math.min(W, (nw.t1 - start) * pxS);
    if (b <= a) continue;
    const last = merged[merged.length - 1];
    if (last && Math.abs(last.b - a) < 1) {
      last.b = b;
      last.score = Math.max(last.score, nw.score);
    } else merged.push({ a, b, score: nw.score });
  }
  return merged;
};

export const beatTipHtml = (b: Beat, startIso: string): string => {
  const vc = verdictClass(b.verdict);
  const what = b.label === "V" ? "ЖЭС" : b.label === "S" ? "НЖЭС" : b.label === "X" ? "артефакт" : "норма";
  const title = b.added
    ? `${what}, добавлен вручную`
    : b.manual
      ? `${what}, метка врача`
      : b.label === "N"
        ? "норма"
        : `${what} · ${VERDICT_RU[b.verdict] ?? b.verdict}`;
  return (
    `<div class="t">${clock(startIso, b.t_ms / 1000)}${b.device_label ? ` · прибор ${b.device_label}` : ""}${b.rr_pre !== null ? ` · RR ${b.rr_pre} мс` : ""}</div>` +
    `<div class="v ${vc}">${title}</div>` +
    (b.reasons.length ? `<ul>${b.reasons.map((r) => `<li>${r}</li>`).join("")}</ul>` : "")
  );
};
