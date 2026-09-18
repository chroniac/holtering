import { api, type BeatsWindow } from "./api";
import { type DragMode, type Range, clampRange, cursorFor, hitRange, wheelIntent, zoomAround } from "./nav";
import { clock, el } from "./util";

const H = 74, RR_TOP = 4, RR_H = 40, TICK_Y = 50, TICK_H = 14, AXIS_Y = 66;
const HANDLE = 6;
export const STRIP_MIN = 2, STRIP_MAX = 120;
const CLS_COLOR = ["#d9c4c7", "#c8102e", "#b7791f", "#9a8a89", "#6f5fa8"];   // N, likely, uncertain, rejected, manual

export interface MinimapView {
  root: HTMLElement;
  /** Show `ctx` (fetching beats if it changed) and draw the strip window inside it. */
  set(ctx: Range, strip: Range): Promise<void>;
  refresh(): Promise<void>;
  setEvents(secs: number[]): void;
}

/**
 * Middle tier of the navigator: the context chosen on the 24 h overview, with the
 * R-R tachogram (double counts drop to ~250 ms, pauses jump up), beat ticks coloured
 * by verdict class, noise shading, and the strip window as a box with edge handles.
 * Same gestures as everywhere else (nav.ts).
 */
export function createMinimap(startIso: string, total: number,
                              onStrip: (r: Range, live: boolean) => void): MinimapView {
  const root = el("div", "mini");
  const cv = el("canvas", "mini-cv");
  const lbl = el("div", "mini-lbl");
  root.append(cv, lbl);
  const c2 = cv.getContext("2d")!;

  let ctx: Range = { start: 0, dur: 300 }, strip: Range = { start: 0, dur: 10 };
  let data: BeatsWindow | null = null, loaded: Range | null = null;
  let events: number[] = [];
  let W = 1000;
  const x = (sec: number) => ((sec - ctx.start) / ctx.dur) * W;
  const sec = (px: number) => ctx.start + (px / W) * ctx.dur;

  function draw() {
    const dpr = window.devicePixelRatio || 1;
    W = Math.max(400, root.clientWidth);
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    cv.style.width = `${W}px`; cv.style.height = `${H}px`;
    c2.setTransform(dpr, 0, 0, dpr, 0, 0);
    c2.clearRect(0, 0, W, H);
    if (!data) return;
    c2.fillStyle = "rgba(200,16,46,0.08)";
    for (const nw of data.noise_windows) {
      const a = Math.max(0, x(nw.t0)), b = Math.min(W, x(nw.t1));
      if (b > a) c2.fillRect(a, 0, b - a, AXIS_Y);
    }
    c2.strokeStyle = "#f0dcdc"; c2.lineWidth = 1; c2.font = "9px JetBrains Mono, monospace"; c2.fillStyle = "#9a8a89";
    const stepS = ctx.dur <= 180 ? 30 : ctx.dur <= 900 ? 60 : ctx.dur <= 3600 ? 300 : 900;
    for (let t = Math.ceil(ctx.start / stepS) * stepS; t < ctx.start + ctx.dur; t += stepS) {
      const px = Math.round(x(t)) + 0.5;
      c2.beginPath(); c2.moveTo(px, 0); c2.lineTo(px, AXIS_Y); c2.stroke();
      c2.fillText(clock(startIso, t).slice(0, stepS < 60 ? 8 : 5), px + 3, H - 2);
    }
    const rrY = (rr: number) => RR_TOP + RR_H - Math.max(0, Math.min(1, (rr - 300) / 1300)) * RR_H;
    c2.strokeStyle = "#f3c9c9"; c2.beginPath();
    for (const rr of [600, 1000]) { const y = Math.round(rrY(rr)) + 0.5; c2.moveTo(0, y); c2.lineTo(W, y); }
    c2.stroke();
    c2.fillStyle = "#9a8a89"; c2.fillText("1000", 2, rrY(1000) - 2); c2.fillText("600 мс", 2, rrY(600) - 2);
    const n = data.t_ms.length;
    const dot = Math.max(1, Math.min(2.2, (W / Math.max(1, n)) * 1.2));
    for (let i = 0; i < n; i++) {
      const px = x(data.t_ms[i] / 1000);
      if (px < 0 || px > W) continue;
      const c = data.cls[i];
      c2.fillStyle = c === 0 ? "#3a2f2f" : CLS_COLOR[c];
      c2.fillRect(px - dot / 2, rrY(data.rr_ms[i]) - dot / 2, dot, dot);
    }
    for (let i = 0; i < n; i++) {
      const c = data.cls[i];
      if (c === 0) continue;
      const px = Math.round(x(data.t_ms[i] / 1000)) + 0.5;
      if (px < 0 || px > W) continue;
      c2.strokeStyle = CLS_COLOR[c]; c2.lineWidth = c === 3 ? 1 : 1.5;
      c2.beginPath(); c2.moveTo(px, TICK_Y); c2.lineTo(px, TICK_Y + TICK_H); c2.stroke();
    }
    for (const sec of events) {
      const px = x(sec); if (px < 0 || px > W) continue;
      c2.fillStyle = "#6f5fa8"; c2.beginPath(); c2.moveTo(px, 0); c2.lineTo(px + 5, 6); c2.lineTo(px, 12); c2.lineTo(px - 5, 6); c2.closePath(); c2.fill();
      c2.strokeStyle = "#6f5fa8"; c2.setLineDash([3, 3]); c2.beginPath(); c2.moveTo(px + 0.5, 12); c2.lineTo(px + 0.5, AXIS_Y); c2.stroke(); c2.setLineDash([]);
    }
    const a = x(strip.start), b = Math.max(a + 3, x(strip.start + strip.dur));
    c2.fillStyle = "rgba(200,16,46,0.10)"; c2.fillRect(a, 0, b - a, AXIS_Y);
    c2.strokeStyle = "#c8102e"; c2.lineWidth = 1; c2.strokeRect(Math.round(a) + 0.5, 0.5, Math.round(b - a), AXIS_Y - 1);
    c2.fillStyle = "#c8102e";
    c2.fillRect(a - HANDLE / 2, AXIS_Y / 2 - 9, HANDLE, 18); c2.fillRect(b - HANDLE / 2, AXIS_Y / 2 - 9, HANDLE, 18);
    const ctxTxt = ctx.dur >= 3600 ? `${(ctx.dur / 3600).toFixed(ctx.dur % 3600 ? 1 : 0)} ч` : `${Math.round(ctx.dur / 60)} мин`;
    lbl.textContent = `${ctxTxt} · окно ${strip.dur % 1 ? strip.dur.toFixed(1) : strip.dur} с · точки: R-R`;
  }

  async function ensure() {
    if (loaded && loaded.start === ctx.start && loaded.dur === ctx.dur) return;
    loaded = { ...ctx };
    data = await api.beats(ctx.start, ctx.dur);
  }

  let drag: { mode: DragMode; px: number; r: Range } | null = null;
  const pxOf = (e: MouseEvent) => e.clientX - cv.getBoundingClientRect().left;
  const hit = (p: number) => hitRange(p, x(strip.start), x(strip.start + strip.dur), HANDLE, "new");
  cv.addEventListener("mousemove", (e) => { if (!drag) cv.style.cursor = cursorFor(hit(pxOf(e))); });
  cv.addEventListener("mousedown", (e) => {
    const p = pxOf(e), mode = hit(p);
    if (mode === "new") { onStrip(clampRange({ start: sec(p) - strip.dur / 2, dur: strip.dur }, total), false); return; }
    drag = { mode, px: p, r: { ...strip } }; cv.style.cursor = "grabbing";
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    const ds = ((pxOf(e) - drag.px) / W) * ctx.dur, r = drag.r;
    if (drag.mode === "move") onStrip(clampRange({ start: r.start + ds, dur: r.dur }, total), true);
    else if (drag.mode === "left") { const nd = Math.max(STRIP_MIN, Math.min(STRIP_MAX, r.dur - ds)); onStrip(clampRange({ start: r.start + r.dur - nd, dur: nd }, total), true); }
    else if (drag.mode === "right") onStrip(clampRange({ start: r.start, dur: Math.max(STRIP_MIN, Math.min(STRIP_MAX, r.dur + ds)) }, total), true);
  });
  window.addEventListener("mouseup", () => { if (drag) { drag = null; cv.style.cursor = ""; onStrip(strip, false); } });
  cv.addEventListener("wheel", (e) => {
    const w = wheelIntent(e);
    if (!w) return;
    e.preventDefault();
    if (w.kind === "pan") onStrip(clampRange({ start: strip.start + Math.sign(w.delta) * strip.dur * 0.5, dur: strip.dur }, total), false);
    else onStrip(clampRange(zoomAround(strip, sec(pxOf(e)), w.factor, STRIP_MIN, STRIP_MAX), total), false);
  }, { passive: false });
  new ResizeObserver(() => draw()).observe(root);

  return {
    root,
    async set(c, st) { ctx = c; strip = st; await ensure(); draw(); },
    async refresh() { loaded = null; await ensure(); draw(); },
    setEvents(secs) { events = secs; draw(); },
  };
}
