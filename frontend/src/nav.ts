/**
 * One navigation model for every time axis in the app (overview, minimap, strip),
 * following the Figma/Photoshop conventions the reviewer already knows:
 *
 *   shift + wheel (or trackpad deltaX)   pan left / right
 *   ctrl / ⌘ + wheel                     zoom around the cursor
 *   drag on empty space                  pan (hand)      -- strip, minimap
 *   drag inside a range box              move the range  -- overview, minimap
 *   drag a range edge                    resize it
 *   click                                centre the range there
 *
 * Plain wheel is deliberately ignored on the time axes so an accidental scroll
 * never jumps the reviewer somewhere else.
 */

export interface Range { start: number; dur: number }

export function wheelIntent(e: WheelEvent): { kind: "pan"; delta: number } | { kind: "zoom"; factor: number } | null {
  if (e.ctrlKey || e.metaKey) return { kind: "zoom", factor: e.deltaY > 0 ? 1.25 : 1 / 1.25 };
  if (e.shiftKey) return { kind: "pan", delta: e.deltaY || e.deltaX };
  if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return { kind: "pan", delta: e.deltaX };
  return null;
}

/** Zoom a range by `factor` keeping the time under the cursor (`at`) fixed. */
export function zoomAround(r: Range, at: number, factor: number, min: number, max: number): Range {
  const dur = Math.max(min, Math.min(max, r.dur * factor));
  const rel = (at - r.start) / r.dur;
  return { start: at - rel * dur, dur };
}

export function clampRange(r: Range, total: number): Range {
  const dur = Math.min(r.dur, total);
  return { start: Math.max(0, Math.min(total - dur, r.start)), dur };
}

export type DragMode = "none" | "new" | "move" | "left" | "right" | "hand";

/** Hit-test a range box drawn from px `a` to `b` with edge handles of `hw` px. */
export function hitRange(p: number, a: number, b: number, hw: number, outside: DragMode): DragMode {
  if (b - a < hw * 3) return p >= a - hw && p <= b + hw ? "move" : outside;
  if (Math.abs(p - a) <= hw) return "left";
  if (Math.abs(p - b) <= hw) return "right";
  return p > a && p < b ? "move" : outside;
}

export function cursorFor(mode: DragMode): string {
  return mode === "move" ? "grab" : mode === "left" || mode === "right" ? "ew-resize" : mode === "hand" ? "grab" : "crosshair";
}
