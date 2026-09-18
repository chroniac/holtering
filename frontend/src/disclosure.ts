import { api, type BeatsWindow, type RawLead } from "./api";
import { clock, el } from "./util";

const ROW_S = 60, PAGE_ROWS = 30, ROW_H = 34, GUTTER = 52;
const CLS_COLOR = ["", "#c8102e", "#b7791f", "#9a8a89", "#6f5fa8"];

export interface DisclosureView {
  root: HTMLElement;
  show(atSec: number, lead: string, strip: { start: number; dur: number }): Promise<void>;
  refresh(): Promise<void>;
}

/**
 * Full disclosure — the classic Holter page: every minute of a 30-minute page is one
 * compressed row of one lead (min/max per pixel column), beats coloured by verdict
 * class in the gutter and as ticks, noise shaded. Click anywhere to open that spot
 * in the strip view. This is how a reviewer scans a day in minutes.
 */
export function createDisclosure(startIso: string, total: number, leads: string[],
                                 onOpen: (sec: number) => void): DisclosureView {
  const root = el("div", "fd");
  const bar = el("div", "fd-bar");
  const title = el("span", "mono fd-title");
  const prev = el("button", "btn", "‹ 30 мин"), next = el("button", "btn", "30 мин ›");
  const leadSel = el("select", "sel");
  for (const l of leads) { const o = el("option", "", l); o.value = l; leadSel.append(o); }
  const gainSel = el("select", "sel");
  for (const g of ["авто", "2", "4", "8"]) { const o = el("option", "", g === "авто" ? "авто" : `${g} мм/мВ`); o.value = g; gainSel.append(o); }
  bar.append(title, prev, next, leadSel, gainSel, el("span", "muted fd-hint", "строка 1 мин · клик открывает ленту"));
  const wrap = el("div", "fd-wrap");
  const cv = el("canvas", "fd-cv");
  const hover = el("div", "fd-hover mono"); hover.hidden = true;
  wrap.append(cv, hover);
  root.append(bar, wrap);
  const ctx = cv.getContext("2d")!;

  let pageStart = 0, lead = leads.includes("II") ? "II" : leads[0];
  let raw: RawLead | null = null, beats: BeatsWindow | null = null;
  let win: { start: number; dur: number } | null = null;
  leadSel.value = lead;

  function draw() {
    if (!raw || !beats) return;
    const dpr = window.devicePixelRatio || 1;
    const W = Math.max(600, wrap.clientWidth - 2), H = PAGE_ROWS * ROW_H;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    cv.style.width = `${W}px`; cv.style.height = `${H}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, W, H);
    const plotW = W - GUTTER, fs = raw.fs, mv = raw.mvPerLsb;
    const spp = (ROW_S * fs) / plotW;                        // samples per pixel
    // gain: mm/mV with 1 mm = ROW_H/ (auto: fit p99 amplitude into row)
    let ampMv: number;
    if (gainSel.value === "авто") {
      const s = raw.samples; let mx = 0;
      for (let i = 0; i < s.length; i += 7) { const v = Math.abs(s[i]); if (v > mx) mx = v; }
      ampMv = Math.max(0.5, (mx * mv) * 0.6);
    } else ampMv = (ROW_H / 2) / Number(gainSel.value) / 2.6;       // rough px->mm mapping
    const yScale = (ROW_H * 0.46) / ampMv;

    for (let r = 0; r < PAGE_ROWS; r++) {
      const y0 = r * ROW_H, base = y0 + ROW_H / 2;
      const rowStart = pageStart + r * ROW_S;
      if (rowStart >= total) break;
      // row background + noise
      ctx.fillStyle = r % 2 ? "#fff" : "#fffafa"; ctx.fillRect(0, y0, W, ROW_H);
      ctx.fillStyle = "rgba(200,16,46,0.08)";
      for (const nw of beats.noise_windows) {
        const a = Math.max(rowStart, nw.t0), b = Math.min(rowStart + ROW_S, nw.t1);
        if (b > a) ctx.fillRect(GUTTER + ((a - rowStart) / ROW_S) * plotW, y0, ((b - a) / ROW_S) * plotW, ROW_H);
      }
      ctx.strokeStyle = "#f0dcdc"; ctx.beginPath(); ctx.moveTo(0, y0 + 0.5); ctx.lineTo(W, y0 + 0.5); ctx.stroke();
      // time label
      ctx.fillStyle = "#5c4d4c"; ctx.font = "10px JetBrains Mono, monospace";
      ctx.fillText(clock(startIso, rowStart).slice(0, 5), 4, base + 4);
      // signal: baseline = row median (sampled), min/max per column
      const s0 = Math.round((rowStart - raw.start) * fs), s1 = Math.min(raw.samples.length, s0 + ROW_S * fs);
      if (s0 >= raw.samples.length) continue;
      const samp: number[] = [];
      for (let i = s0; i < s1; i += 25) samp.push(raw.samples[i]);
      samp.sort((a, b) => a - b); const med = samp[samp.length >> 1] ?? 0;
      ctx.strokeStyle = "#16100f"; ctx.lineWidth = 1; ctx.beginPath();
      for (let px = 0; px < plotW; px++) {
        const a = s0 + Math.floor(px * spp), b = Math.min(s1, s0 + Math.floor((px + 1) * spp));
        if (a >= b) break;
        let lo = Infinity, hi = -Infinity;
        for (let i = a; i < b; i++) { const v = raw.samples[i]; if (v < lo) lo = v; if (v > hi) hi = v; }
        const yl = base - Math.max(-ROW_H * 0.48, Math.min(ROW_H * 0.48, (hi - med) * mv * yScale));
        const yh = base - Math.max(-ROW_H * 0.48, Math.min(ROW_H * 0.48, (lo - med) * mv * yScale));
        ctx.moveTo(GUTTER + px + 0.5, yl); ctx.lineTo(GUTTER + px + 0.5, Math.max(yh, yl + 1));
      }
      ctx.stroke();
    }
    // beats: N as faint dots on the top rail, everything else as coloured dots
    for (let i = 0; i < beats.t_ms.length; i++) {
      const c = beats.cls[i];
      const t = beats.t_ms[i] / 1000 - pageStart;
      const r = Math.floor(t / ROW_S); if (r < 0 || r >= PAGE_ROWS) continue;
      const px = GUTTER + ((t - r * ROW_S) / ROW_S) * plotW;
      if (c === 0) { ctx.fillStyle = "#e6d3d5"; ctx.fillRect(px - 0.5, r * ROW_H + 3, 1, 3); continue; }
      ctx.fillStyle = CLS_COLOR[c];
      ctx.beginPath(); ctx.arc(px, r * ROW_H + 6, 2.6, 0, Math.PI * 2); ctx.fill();
    }
    // current strip window
    if (win) {
      const t0 = win.start - pageStart, t1 = t0 + win.dur;
      for (let r = 0; r < PAGE_ROWS; r++) {
        const a = Math.max(t0, r * ROW_S), b = Math.min(t1, (r + 1) * ROW_S);
        if (b <= a) continue;
        ctx.fillStyle = "rgba(200,16,46,0.12)";
        ctx.fillRect(GUTTER + ((a - r * ROW_S) / ROW_S) * plotW, r * ROW_H, ((b - a) / ROW_S) * plotW, ROW_H);
      }
    }
    const end = Math.min(total, pageStart + PAGE_ROWS * ROW_S);
    title.textContent = `${clock(startIso, pageStart).slice(0, 5)}–${clock(startIso, end).slice(0, 5)} · ${lead}`;
  }

  async function load() {
    const dur = Math.min(PAGE_ROWS * ROW_S, total - pageStart);
    [raw, beats] = await Promise.all([api.raw(pageStart, dur, lead), api.beats(pageStart, dur)]);
    draw();
  }

  prev.addEventListener("click", () => { pageStart = Math.max(0, pageStart - PAGE_ROWS * ROW_S); void load(); });
  next.addEventListener("click", () => { pageStart = Math.min(total - ROW_S, pageStart + PAGE_ROWS * ROW_S); void load(); });
  leadSel.addEventListener("change", () => { lead = leadSel.value; void load(); });
  gainSel.addEventListener("change", () => draw());
  cv.addEventListener("mousemove", (e) => {
    const r = cv.getBoundingClientRect();
    const row = Math.floor((e.clientY - r.top) / ROW_H);
    const frac = Math.max(0, Math.min(1, (e.clientX - r.left - GUTTER) / (r.width - GUTTER)));
    hover.hidden = false; hover.textContent = clock(startIso, pageStart + row * ROW_S + frac * ROW_S);
    hover.style.left = `${e.clientX - r.left + 14}px`; hover.style.top = `${e.clientY - r.top - 8}px`;
  });
  cv.addEventListener("mouseleave", () => { hover.hidden = true; });
  cv.addEventListener("click", (e) => {
    const r = cv.getBoundingClientRect();
    const row = Math.floor((e.clientY - r.top) / ROW_H);
    const frac = Math.max(0, (e.clientX - r.left - GUTTER) / (r.width - GUTTER));
    onOpen(pageStart + row * ROW_S + frac * ROW_S);
  });
  new ResizeObserver(() => draw()).observe(wrap);

  return {
    root,
    async show(atSec, l, strip) { lead = l; leadSel.value = l; win = strip; pageStart = Math.floor(atSec / (PAGE_ROWS * ROW_S)) * PAGE_ROWS * ROW_S; await load(); },
    async refresh() { if (raw) await load(); },
  };
}
