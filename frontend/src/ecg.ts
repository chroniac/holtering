import type { Beat, EcgWindow } from "./api";
import { wheelIntent } from "./nav";
import { VERDICT_RU, clock, el, svg, verdictClass } from "./util";

const MARK_H = 22, PAD_B = 14;
const GAIN_STEPS = [20, 10, 5, 2.5, 1.25];

export interface EcgView {
  root: HTMLElement;
  render(win: EcgWindow, startIso: string, gain: number | "auto"): void;
  highlight(beatIndex: number | null): void;
  /** Time cursor (seconds from record start) for inserting a beat; null hides it. */
  setCursor(sec: number | null): void;
  setRange(r: { t0: number; t1: number } | null): void;
  setEvents(secs: number[]): void;
}

export interface EcgHandlers {
  onBeat: (b: Beat) => void;
  onZoom: (atSec: number, factor: number) => void;
  onPan: (deltaSec: number, live: boolean) => void;
  onCursor: (sec: number) => void;
  /** shift+drag: a time span (seconds) to mark clean / noise. */
  onRange: (t0: number, t1: number) => void;
}

export function createEcgView(h: EcgHandlers): EcgView {
  const root = el("div", "ecg");
  const s = svg("svg");
  root.append(s);
  const tip = el("div", "tip");
  document.body.append(tip);
  let beatNodes: Record<number, SVGGElement> = {};
  let curStart = 0, curDur = 10, cursorSec: number | null = null, curIso = "";
  let cursorNode: SVGGElement | null = null, rangeNode: SVGRectElement | null = null;
  let range: { t0: number; t1: number } | null = null;
  let sel: { x0: number } | null = null;
  let events: number[] = [];

  const secAt = (clientX: number) => { const r = root.getBoundingClientRect(); return curStart + ((clientX - r.left) / r.width) * curDur; };
  root.addEventListener("wheel", (e) => {
    const w = wheelIntent(e);
    if (!w) return;
    e.preventDefault();
    if (w.kind === "zoom") h.onZoom(secAt(e.clientX), w.factor);
    else h.onPan(Math.sign(w.delta) * curDur * 0.25, false);
  }, { passive: false });
  // hand: drag the paper; a click without movement places the time cursor
  let hand: { x0: number; start0: number; moved: boolean } | null = null;
  root.addEventListener("mousedown", (e) => {
    if ((e.target as Element).closest(".beat")) return;
    if (e.shiftKey) { sel = { x0: e.clientX }; range = { t0: secAt(e.clientX), t1: secAt(e.clientX) }; drawRange(); e.preventDefault(); return; }
    hand = { x0: e.clientX, start0: curStart, moved: false };
    root.style.cursor = "grabbing";
  });
  window.addEventListener("mousemove", (e) => {
    if (sel) { const a = secAt(sel.x0), b = secAt(e.clientX); range = { t0: Math.min(a, b), t1: Math.max(a, b) }; drawRange(); return; }
    if (!hand) return;
    const dx = e.clientX - hand.x0;
    if (Math.abs(dx) > 3) hand.moved = true;
    if (hand.moved) { const r = root.getBoundingClientRect(); h.onPan(hand.start0 - (dx / r.width) * curDur - curStart, true); }
  });
  window.addEventListener("mouseup", (e) => {
    if (sel) { sel = null; if (range && range.t1 - range.t0 >= 0.1) h.onRange(range.t0, range.t1); else { range = null; drawRange(); } return; }
    if (!hand) return;
    const wasClick = hand.moved === false; hand = null; root.style.cursor = "";
    if (wasClick) h.onCursor(secAt(e.clientX)); else h.onPan(0, false);
  });

  function showTip(b: Beat, e: MouseEvent) {
    const vc = verdictClass(b.verdict);
    const what = b.label === "V" ? "ЖЭС" : b.label === "S" ? "НЖЭС" : b.label === "X" ? "артефакт" : "норма";
    const title = b.added ? `${what}, добавлен вручную` : b.manual ? `${what}, метка врача` : b.label === "N" ? "норма" : `${what} · ${VERDICT_RU[b.verdict] ?? b.verdict}`;
    tip.innerHTML = `<div class="t">${clock(curIso, b.t_ms / 1000)}${b.device_label ? ` · прибор ${b.device_label}` : ""}${b.rr_pre !== null ? ` · RR ${b.rr_pre} мс` : ""}</div>` +
      `<div class="v ${vc}">${title}</div>` +
      (b.reasons.length ? `<ul>${b.reasons.map((r) => `<li>${r}</li>`).join("")}</ul>` : "");
    tip.style.left = `${Math.min(window.innerWidth - 360, e.clientX + 14)}px`;
    tip.style.top = `${e.clientY + 14}px`;
    tip.classList.add("show");
  }

  return {
    root,
    render(win, startIso, gainOpt) {
      beatNodes = {};
      const n = win.leads.length;
      const dur = win.data[0].length / win.fs;
      curStart = win.start; curDur = dur; curIso = startIso;
      const W = Math.max(640, root.clientWidth || 900);
      const availH = Math.max(260, root.clientHeight || 620);
      const lane = Math.min(140, Math.max(40, Math.floor((availH - MARK_H - PAD_B) / Math.max(1, n))));
      const H = MARK_H + lane * n + PAD_B;
      const pxS = W / dur;                 // px per second
      const mm = pxS / 25;                 // px per mm at 25 mm/s
      s.setAttribute("viewBox", `0 0 ${W} ${H}`);
      s.setAttribute("preserveAspectRatio", "none");
      s.innerHTML = "";

      // gain: mm per mV
      let gain: number;
      if (gainOpt === "auto") {
        const ptp = Math.max(...win.data.map((row) => Math.max(...row) - Math.min(...row)), 0.2);
        gain = GAIN_STEPS.find((g) => ptp * g * mm <= lane * 0.92) ?? 1.25;
      } else gain = gainOpt;
      const pxMv = gain * mm;

      // grid
      const grid = svg("g");
      for (let xmm = 0; xmm * mm <= W; xmm++) {
        const major = xmm % 5 === 0;
        grid.append(svg("line", { x1: xmm * mm, x2: xmm * mm, y1: MARK_H, y2: H - PAD_B, stroke: major ? "var(--grid-major)" : "var(--grid-minor)", "stroke-width": major ? 0.9 : 0.5 }));
      }
      for (let ymm = 0; ymm * mm <= H - MARK_H - PAD_B; ymm++) {
        const major = ymm % 5 === 0;
        grid.append(svg("line", { x1: 0, x2: W, y1: MARK_H + ymm * mm, y2: MARK_H + ymm * mm, stroke: major ? "var(--grid-major)" : "var(--grid-minor)", "stroke-width": major ? 0.9 : 0.5 }));
      }
      s.append(grid);

      // noise windows (auto); adjacent windows merge into one label
      const merged: { a: number; b: number; score: number }[] = [];
      for (const nw of win.noise_windows) {
        const a = Math.max(0, (nw.t0 - win.start) * pxS), b = Math.min(W, (nw.t1 - win.start) * pxS);
        if (b <= a) continue;
        const last = merged[merged.length - 1];
        if (last && Math.abs(last.b - a) < 1) { last.b = b; last.score = Math.max(last.score, nw.score); } else merged.push({ a, b, score: nw.score });
      }
      for (const m of merged) {
        s.append(svg("rect", { class: "noise-win", x: m.a, y: MARK_H, width: m.b - m.a, height: H - MARK_H - PAD_B }));
        const t = svg("text", { class: "noise-win-lbl", x: m.a + 4, y: H - PAD_B - 4 });
        t.textContent = `помеха ${(m.score * 100).toFixed(0)}%`; s.append(t);
      }
      for (const q of win.quality_manual) {
        const a = Math.max(0, (q.t0_ms / 1000 - win.start) * pxS), b = Math.min(W, (q.t1_ms / 1000 - win.start) * pxS);
        if (b <= a) continue;
        s.append(svg("rect", { class: `qspan ${q.v}`, x: a, y: MARK_H, width: b - a, height: H - MARK_H - PAD_B }));
        const t = svg("text", { class: `qspan-lbl ${q.v}`, x: a + 4, y: MARK_H + 24 });
        t.textContent = q.v === "clean" ? "чисто · вручную" : "помеха · вручную"; s.append(t);
      }

      // traces
      win.data.forEach((row, li) => {
        const base = MARK_H + lane * li + lane / 2;
        let d = "";
        for (let i = 0; i < row.length; i++) {
          const x = (i / win.fs) * pxS, y = base - row[i] * pxMv;
          d += (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
        }
        const noisy = win.lead_noise[li] > 2.5, drifting = win.lead_drift[li] > win.drift_thr_mv;
        s.append(svg("path", { class: `trace${noisy || drifting ? " noisy" : ""}`, d }));
        const name = svg("text", { class: "lead-name", x: 6, y: MARK_H + lane * li + 13 });
        name.textContent = win.leads[li]; s.append(name);
        const nz = svg("text", { class: "lead-noise", x: 6, y: MARK_H + lane * li + 25 });
        nz.textContent = [noisy ? `шум ×${win.lead_noise[li].toFixed(1)}` : "", drifting ? `дрейф ${win.lead_drift[li].toFixed(1)} мВ` : ""].filter(Boolean).join(" · "); s.append(nz);
      });

      // beat markers
      for (const b of win.beats) {
        const x = ((b.t_ms / 1000) - win.start) * pxS;
        if (x < 0 || x > W) continue;
        const vc = verdictClass(b.verdict);
        const g = svg("g", { class: `beat ${vc}` });
        if (vc !== "N") {
          g.append(svg("rect", { class: "halo", x: x - 0.09 * pxS, y: MARK_H, width: 0.18 * pxS, height: H - MARK_H - PAD_B, rx: 3 }));
          g.append(svg("line", { x1: x, x2: x, y1: MARK_H - 2, y2: H - PAD_B }));
        } else {
          g.append(svg("line", { x1: x, x2: x, y1: MARK_H - 6, y2: MARK_H }));
        }
        const t = svg("text", { x, y: 13 });
        t.textContent = b.added ? `+${b.label}` : b.manual ? `${b.manual}·` : b.label; g.append(t);
        if (b.manual || b.added) g.classList.add("manual");
        g.addEventListener("mousemove", (e) => showTip(b, e));
        g.addEventListener("mouseleave", () => tip.classList.remove("show"));
        g.addEventListener("click", () => h.onBeat(b));
        s.append(g);
        beatNodes[b.index] = g;
      }

      // symptom diary marks
      for (const sec of events) {
        if (sec < win.start || sec > win.start + dur) continue;
        const ex = (sec - win.start) * pxS;
        s.append(svg("line", { class: "evline", x1: ex, x2: ex, y1: MARK_H, y2: H - PAD_B }));
        const t = svg("text", { class: "evlbl", x: ex + 4, y: MARK_H + 36 }); t.textContent = "симптом"; s.append(t);
      }
      // time cursor for inserting a beat
      cursorNode = svg("g", { class: "tcursor" });
      rangeNode = svg("rect", { class: "range", x: 0, y: MARK_H, width: 0, height: H - MARK_H - PAD_B });
      s.append(cursorNode, rangeNode);
      drawCursor(); drawRange();
      // scale bar: 1 s x 1 mV
      const sc = svg("g", { class: "scale" });
      const sx = W - pxS - 14, sy = H - PAD_B - 8;
      sc.append(svg("line", { x1: sx, x2: sx + pxS, y1: sy, y2: sy }));
      sc.append(svg("line", { x1: sx, x2: sx, y1: sy, y2: sy - pxMv }));
      const st = svg("text", { x: sx + 4, y: sy - 4 }); st.textContent = `1 с · 1 мВ · ${gain} мм/мВ`; sc.append(st);
      s.append(sc);

      // time labels every second
      const tl = svg("g", { class: "scale" });
      const step = dur <= 12 ? 1 : dur <= 40 ? 5 : 10;
      for (let sec = 0; sec <= dur; sec += step) {
        const t = svg("text", { x: sec * pxS + 3, y: H - 3, style: "fill:var(--ink-3)" });
        t.textContent = clock(startIso, win.start + sec); tl.append(t);
      }
      s.append(tl);
    },
    highlight(beatIndex) {
      for (const [k, g] of Object.entries(beatNodes)) g.classList.toggle("active", Number(k) === beatIndex);
    },
    setCursor(sec) { cursorSec = sec; drawCursor(); },
    setRange(r) { range = r; drawRange(); },
    setEvents(secs) { events = secs; },
  };

  function drawRange() {
    if (!rangeNode) return;
    if (!range) { rangeNode.setAttribute("width", "0"); return; }
    const W = Number(s.getAttribute("viewBox")!.split(" ")[2]);
    const a = Math.max(0, ((range.t0 - curStart) / curDur) * W), b = Math.min(W, ((range.t1 - curStart) / curDur) * W);
    rangeNode.setAttribute("x", String(a)); rangeNode.setAttribute("width", String(Math.max(0, b - a)));
  }

  function drawCursor() {
    if (!cursorNode) return;
    cursorNode.innerHTML = "";
    if (cursorSec === null || cursorSec < curStart || cursorSec > curStart + curDur) return;
    const W = Number(s.getAttribute("viewBox")!.split(" ")[2]), H = Number(s.getAttribute("viewBox")!.split(" ")[3]);
    const x = ((cursorSec - curStart) / curDur) * W;
    cursorNode.append(svg("line", { x1: x, x2: x, y1: MARK_H, y2: H - PAD_B }));
    const t = svg("text", { x: x + 4, y: MARK_H + 12 }); t.textContent = "добавить: a"; cursorNode.append(t);
  }
}
