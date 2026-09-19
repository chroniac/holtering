/**
 * Одна модель навигации для всех временных осей (обзор, миникарта, лента) по привычным
 * из Figma/Photoshop жестам: shift+колесо — панорама, ctrl/⌘+колесо — зум у курсора,
 * перетаскивание — рука или диапазон, клик — центрирование. Простое колесо игнорируется:
 * случайный скролл не должен уводить врача с места.
 */

export interface Range {
  start: number;
  dur: number;
}

export const wheelIntent = (
  e: WheelEvent,
): { kind: "pan"; delta: number } | { kind: "zoom"; factor: number } | null => {
  if (e.ctrlKey || e.metaKey) return { kind: "zoom", factor: e.deltaY > 0 ? 1.25 : 1 / 1.25 };
  if (e.shiftKey) return { kind: "pan", delta: e.deltaY || e.deltaX };
  if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return { kind: "pan", delta: e.deltaX };
  return null;
};

/** Зум диапазона в `factor` раз с фиксацией времени под курсором (`at`). */
export const zoomAround = (r: Range, at: number, factor: number, min: number, max: number): Range => {
  const dur = Math.max(min, Math.min(max, r.dur * factor));
  const rel = (at - r.start) / r.dur;
  return { start: at - rel * dur, dur };
};

export const clampRange = (r: Range, total: number): Range => {
  const dur = Math.min(r.dur, total);
  return { start: Math.max(0, Math.min(total - dur, r.start)), dur };
};

export type DragMode = "none" | "new" | "move" | "left" | "right" | "hand";

/** Попадание в рамку диапазона от `a` до `b` px с ручками по краям шириной `hw` px. */
export const hitRange = (p: number, a: number, b: number, hw: number, outside: DragMode): DragMode => {
  if (b - a < hw * 3) return p >= a - hw && p <= b + hw ? "move" : outside;
  if (Math.abs(p - a) <= hw) return "left";
  if (Math.abs(p - b) <= hw) return "right";
  return p > a && p < b ? "move" : outside;
};

export const cursorFor = (mode: DragMode): string =>
  mode === "move" ? "grab" : mode === "left" || mode === "right" ? "ew-resize" : mode === "hand" ? "grab" : "crosshair";
