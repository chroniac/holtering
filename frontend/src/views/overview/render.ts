import type { Episode, Overview, Summary } from "../../api/types";
import { clampRange, cursorFor, type DragMode, hitRange, type Range, wheelIntent, zoomAround } from "../../lib/nav";
import { clock, clockHM } from "../../lib/time";
import { el, svg } from "../../ui/dom";
import {
  AX_H,
  BIN_MIN,
  binSums,
  CTX_MAX,
  CTX_MIN,
  DOT_ROWS,
  ECT_H,
  firstTickSec,
  HANDLE_W,
  HR_MIN,
  hourlySums,
  hrBounds,
  hrTicks,
  NOISE_H,
  nightMinutes,
  noiseRuns,
  type OverviewView,
  PAD_L,
  PAD_R,
  PAD_T,
} from "./model";

let H = 168,
  HR_H = 78; // пересчитывается от контейнера на каждой отрисовке

/**
 * Суточный обзор: выделение здесь — контекст (1 мин – 3 ч), который разворачивает миникарта.
 * Само окно ленты выделять нечем (10 с — это 0,2 px на суточной оси), оно показано волоском.
 */
export const renderOverview = (
  sum: Summary,
  ov0: Overview,
  episodes0: Episode[],
  onContext: (ctx: Range, live: boolean) => void,
  onEpisode: (ep: Episode) => void,
): OverviewView => {
  let ov = ov0,
    episodes = episodes0;
  const root = el("div", "ov card");
  const head = el("div", "card-head");
  const ttl = el("div", "card-titles");
  ttl.append(
    el("div", "card-title", "24 часа"),
    el(
      "div",
      "card-sub",
      `${clockHM(sum.record.start, 0)} → ${clockHM(sum.record.start, sum.record.duration_s)} · ЧСС, экстрасистолы, помехи, сон`,
    ),
  );
  head.append(el("div", "card-icon", "◔"), ttl);
  const legend = el("div", "legend");
  legend.innerHTML =
    `<span><i style="background:var(--ink)"></i>ЧСС/мин</span>` +
    `<span><i class="dot" style="background:var(--red)"></i>ЖЭС</span>` +
    `<span><i class="dot hollow"></i>только по прибору</span>` +
    `<span><i class="dot" style="background:#e8a0ab"></i>НЖЭС</span>` +
    `<span><i class="hatch"></i>помеха</span>` +
    `<span><i style="background:#ece6f7"></i>сон по ЧСС</span>`;
  head.append(legend);
  root.append(head);

  const total = sum.record.duration_s;
  const width = () => Math.max(500, root.clientWidth - 24);
  const height = () => Math.max(150, root.clientHeight - head.getBoundingClientRect().height - 8);
  const s = svg("svg", { viewBox: `0 0 ${width()} ${H}`, preserveAspectRatio: "none" });
  root.append(s);
  const tip = el("div", "tip small");
  document.body.append(tip);

  let box: SVGRectElement | null = null,
    hL: SVGRectElement | null = null,
    hR: SVGRectElement | null = null;
  let hair: SVGRectElement | null = null,
    brush: SVGRectElement | null = null;
  let epNodes: Record<number, SVGGElement> = {};
  let W = width();
  let ctx: Range = { start: 0, dur: 300 },
    strip: Range = { start: 0, dur: 10 };
  let events: number[] = [];
  let evLayer: SVGGElement | null = null;
  const x = (sec: number) => PAD_L + (sec / total) * (W - PAD_L - PAD_R);
  const sec = (px: number) => ((px - PAD_L) / (W - PAD_L - PAD_R)) * total;

  const drawEvents = () => {
    if (!evLayer) return;
    evLayer.innerHTML = "";
    for (const sec of events) {
      const px = x(sec);
      evLayer.append(svg("path", { class: "evmark", d: `M${px} ${PAD_T - 6} l4 6 l-4 6 l-4 -6 z` }));
      evLayer.append(
        svg("line", { class: "evline", x1: px, x2: px, y1: PAD_T, y2: PAD_T + HR_H + ECT_H + NOISE_H + 6 }),
      );
    }
  };

  const place = () => {
    if (!box || !hL || !hR || !hair) return;
    const a = x(ctx.start),
      b = x(ctx.start + ctx.dur);
    box.setAttribute("x", String(a));
    box.setAttribute("width", String(Math.max(2, b - a)));
    hL.setAttribute("x", String(a - HANDLE_W / 2));
    hR.setAttribute("x", String(b - HANDLE_W / 2));
    const wide = b - a >= HANDLE_W * 3;
    hL.style.display = hR.style.display = wide ? "" : "none";
    hair.setAttribute("x", String(x(strip.start + strip.dur / 2)));
  };

  const draw = () => {
    W = width();
    H = height();
    HR_H = Math.max(HR_MIN, H - PAD_T - ECT_H - NOISE_H - AX_H - 14); // панели ЧСС достаётся вся остальная высота
    s.setAttribute("viewBox", `0 0 ${W} ${H}`);
    s.style.height = `${H}px`;
    s.innerHTML = "";
    epNodes = {};
    const plotW = W - PAD_L - PAD_R;
    const start = new Date(sum.record.start.replace(" ", "T"));
    const bandH = HR_H + ECT_H + NOISE_H + 6;
    const defs = svg("defs");
    defs.innerHTML =
      `<pattern id="dotgrid" width="8" height="8" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="0.8" fill="#eed3d6"/></pattern>` +
      `<pattern id="hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2" height="5" fill="#c8102e" opacity="0.7"/></pattern>`;
    s.append(defs, svg("rect", { x: PAD_L, y: PAD_T, width: plotW, height: HR_H + ECT_H + 6, fill: "url(#dotgrid)" }));

    for (const m of nightMinutes(start, ov.minute_hr.length))
      s.append(
        svg("rect", {
          class: "night",
          x: x(m * 60),
          y: PAD_T,
          width: Math.max(1, plotW / (total / 60)),
          height: bandH,
        }),
      );
    for (const [a, b] of ov.sleep) {
      s.append(svg("rect", { class: "sleep", x: x(a * 60), y: PAD_T, width: x(b * 60) - x(a * 60), height: bandH }));
      const t = svg("text", { class: "sleep-lbl", x: x(a * 60) + 4, y: PAD_T + 11 });
      t.textContent = `сон ${clockHM(sum.record.start, a * 60)}–${clockHM(sum.record.start, b * 60)}`;
      s.append(t);
    }

    const hrs = ov.minute_hr.map((v) => v ?? NaN);
    const { lo, hi } = hrBounds(hrs);
    const y = (v: number) => PAD_T + HR_H - ((v - lo) / (hi - lo)) * HR_H;
    let d = "",
      area = "",
      open = false;
    hrs.forEach((v, m) => {
      if (Number.isNaN(v)) {
        if (open) area += "Z";
        open = false;
        return;
      }
      const px = x(m * 60 + 30).toFixed(1),
        py = y(v).toFixed(1);
      d += (open ? "L" : "M") + px + " " + py;
      area += open ? `L${px} ${py}` : `M${px} ${(PAD_T + HR_H).toFixed(1)}L${px} ${py}`;
      if (m === hrs.length - 1 || Number.isNaN(hrs[m + 1] ?? NaN)) area += `L${px} ${(PAD_T + HR_H).toFixed(1)}Z`;
      open = true;
    });
    s.append(svg("path", { class: "hr-area", d: area }), svg("path", { class: "hr-line", d }));
    // клинические пороги: пунктир с подписью
    for (const [v, txt] of [
      [100, "тахи >100"],
      [50, "бради <50"],
    ] as [number, string][]) {
      if (v <= lo || v >= hi) continue;
      s.append(svg("line", { class: "thr", x1: PAD_L, x2: W - PAD_R, y1: y(v), y2: y(v) }));
      const t = svg("text", { class: "thr-lbl", x: W - PAD_R - 2, y: y(v) - 3, "text-anchor": "end" });
      t.textContent = txt;
      s.append(t);
    }
    const ax = svg("g", { class: "axis" });
    for (const v of hrTicks(lo, hi)) {
      ax.append(svg("line", { x1: PAD_L, x2: W - PAD_R, y1: y(v), y2: y(v) }));
      const t = svg("text", { x: PAD_L - 4, y: y(v) + 3, "text-anchor": "end" });
      t.textContent = String(v);
      ax.append(t);
    }
    s.append(ax);

    // эктопия за 10 мин точками: точка = `unit` комплексов, аудит закрашен, прибор — контуром
    const nb = Math.ceil(ov.minute_v.length / BIN_MIN);
    const vDev = binSums(ov.minute_v_device, BIN_MIN, nb),
      vAud = binSums(ov.minute_v, BIN_MIN, nb),
      sAud = binSums(ov.minute_s, BIN_MIN, nb);
    const mx = Math.max(1, ...vDev, ...sAud);
    const unit = Math.max(1, Math.ceil(mx / DOT_ROWS));
    const y0 = PAD_T + HR_H + 6,
      bw = plotW / nb,
      dr = Math.min(2.2, bw * 0.22),
      dy = ECT_H / DOT_ROWS;
    for (let b = 0; b < nb; b++) {
      const bx = x(b * BIN_MIN * 60);
      const g = svg("g", { class: "bin" });
      g.append(svg("rect", { class: "bin-hit", x: bx, y: y0, width: Math.max(1, bw), height: ECT_H }));
      const nDev = Math.ceil(vDev[b] / unit),
        nAud = Math.ceil(vAud[b] / unit),
        nS = Math.ceil(sAud[b] / unit);
      const cxV = bx + bw * 0.33,
        cxS = bx + bw * 0.7;
      for (let i = 0; i < Math.min(DOT_ROWS, nDev); i++) {
        const cy = y0 + ECT_H - dy * (i + 0.5);
        g.append(svg("circle", { class: i < nAud ? "dot-v" : "dot-vdev", cx: cxV, cy, r: dr }));
      }
      for (let i = 0; i < Math.min(DOT_ROWS, nS); i++)
        g.append(svg("circle", { class: "dot-s", cx: cxS, cy: y0 + ECT_H - dy * (i + 0.5), r: dr * 0.8 }));
      g.addEventListener("mousemove", (e) => {
        tip.innerHTML =
          `<div class="t">${clockHM(sum.record.start, b * BIN_MIN * 60)}–${clockHM(sum.record.start, (b + 1) * BIN_MIN * 60)}</div>` +
          `<div class="v">ЖЭС ${vAud[b]} <span class="dim">прибор ${vDev[b]}</span> · НЖЭС ${sAud[b]}</div>`;
        tip.style.left = `${e.clientX + 12}px`;
        tip.style.top = `${e.clientY + 12}px`;
        tip.classList.add("show");
      });
      g.addEventListener("mouseleave", () => tip.classList.remove("show"));
      s.append(g);
    }
    const lbl = svg("text", { class: "row-lbl", x: PAD_L - 4, y: y0 + ECT_H - 2, "text-anchor": "end" });
    lbl.textContent = `● = ${unit}`;
    s.append(lbl);
    // час пика эктопии по аудиту: пунктирная рамка с подписью
    const hourly = hourlySums(ov.minute_v);
    const peakH = hourly.indexOf(Math.max(...hourly));
    if (hourly[peakH] > 0) {
      const bx0 = x(peakH * 3600),
        bx1 = x(Math.min(total, (peakH + 1) * 3600));
      s.append(svg("rect", { class: "peak-box", x: bx0, y: y0 - 2, width: bx1 - bx0, height: ECT_H + 4, rx: 2 }));
      const t = svg("text", { class: "peak-lbl", x: bx1 + 4, y: y0 + 9 });
      t.textContent = `пик ЖЭС · ${hourly[peakH]} за час`;
      s.append(t);
    }

    const yN = y0 + ECT_H + 4,
      w10 = ov.noise_window_s;
    for (const [r0, r1] of noiseRuns(ov.noise10)) {
      const a = x(r0 * w10),
        b = x(r1 * w10);
      s.append(
        svg("rect", {
          class: "noise",
          x: a,
          y: yN,
          width: Math.max(1.5, b - a),
          height: NOISE_H,
          fill: "url(#hatch)",
        }),
      );
    }
    const nl = svg("text", { class: "row-lbl", x: PAD_L - 4, y: yN + NOISE_H - 1, "text-anchor": "end" });
    nl.textContent = "шум";
    s.append(nl);

    const tax = svg("g", { class: "axis" });
    const yT = yN + NOISE_H + AX_H - 4;
    for (let t = firstTickSec(start); t < total; t += 7200) {
      tax.append(svg("line", { x1: x(t), x2: x(t), y1: PAD_T, y2: yN + NOISE_H + 2 }));
      const tt = svg("text", { x: x(t), y: yT, "text-anchor": "middle" });
      tt.textContent = clockHM(sum.record.start, t);
      tax.append(tt);
    }
    s.append(tax);

    evLayer = svg("g", { class: "events" });
    s.append(evLayer);
    drawEvents();
    box = svg("rect", { class: "ctx-box", x: PAD_L, y: PAD_T, width: 2, height: bandH + 4, rx: 2 });
    hL = svg("rect", { class: "handle", x: PAD_L, y: PAD_T + bandH / 2 - 10, width: HANDLE_W, height: 20, rx: 2 });
    hR = svg("rect", { class: "handle", x: PAD_L, y: PAD_T + bandH / 2 - 10, width: HANDLE_W, height: 20, rx: 2 });
    hair = svg("rect", { class: "hair", x: PAD_L, y: PAD_T, width: 1.5, height: bandH + 4 });
    brush = svg("rect", { class: "brush", x: 0, y: PAD_T, width: 0, height: bandH + 4 });
    s.append(box, hL, hR, hair, brush);

    for (const ep of episodes) {
      if (ep.kind === "noise") continue;
      const g = svg("g", { class: `ep ${ep.verdict}` });
      const cy = ep.kind === "pause" ? PAD_T + HR_H - 6 : y0 - 4;
      g.append(svg("circle", { cx: x(ep.t_ms / 1000), cy, r: 3.5 }));
      const title = svg("title");
      title.textContent = `${clock(sum.record.start, ep.t_ms / 1000)} ${ep.title}`;
      g.append(title);
      g.addEventListener("click", (e) => {
        e.stopPropagation();
        onEpisode(ep);
      });
      g.addEventListener("mousedown", (e) => e.stopPropagation());
      s.append(g);
      epNodes[ep.id] = g;
    }
    place();
  };

  // взаимодействия (см. lib/nav.ts)
  let drag: { mode: DragMode; px: number; r: Range } | null = null;
  const pxOf = (e: MouseEvent) => ((e.clientX - s.getBoundingClientRect().left) / s.getBoundingClientRect().width) * W;
  const hit = (p: number) => hitRange(p, x(ctx.start), x(ctx.start + ctx.dur), HANDLE_W, "new");
  s.addEventListener("mousemove", (e) => {
    if (!drag) s.style.cursor = cursorFor(hit(pxOf(e)));
  });
  s.addEventListener("mousedown", (e) => {
    const p = pxOf(e);
    drag = { mode: hit(p), px: p, r: { ...ctx } };
    if (drag.mode === "new") brush?.setAttribute("width", "0");
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    const p = pxOf(e),
      ds = sec(p) - sec(drag.px),
      r = drag.r;
    if (drag.mode === "new") {
      if (!brush) return;
      const a = Math.min(drag.px, p),
        b = Math.max(drag.px, p);
      brush.setAttribute("x", String(a));
      brush.setAttribute("width", String(b - a));
    } else if (drag.mode === "move") onContext(clampRange({ start: r.start + ds, dur: r.dur }, total), true);
    else if (drag.mode === "left") {
      const nd = Math.max(CTX_MIN, Math.min(CTX_MAX, r.dur - ds));
      onContext(clampRange({ start: r.start + r.dur - nd, dur: nd }, total), true);
    } else if (drag.mode === "right")
      onContext(clampRange({ start: r.start, dur: Math.max(CTX_MIN, Math.min(CTX_MAX, r.dur + ds)) }, total), true);
  });
  window.addEventListener("mouseup", (e) => {
    if (!drag) return;
    const p = pxOf(e),
      d = drag;
    drag = null;
    brush?.setAttribute("width", "0");
    if (d.mode !== "new") {
      onContext(ctx, false);
      return;
    }
    if (Math.abs(p - d.px) < 3) {
      onContext(clampRange({ start: sec(p) - ctx.dur / 2, dur: ctx.dur }, total), false);
      return;
    }
    const a = Math.max(0, sec(Math.min(d.px, p))),
      b = Math.min(total, sec(Math.max(d.px, p)));
    onContext(clampRange({ start: a, dur: Math.max(CTX_MIN, Math.min(CTX_MAX, b - a)) }, total), false);
  });
  s.addEventListener(
    "wheel",
    (e) => {
      const w = wheelIntent(e);
      if (!w) return;
      e.preventDefault();
      if (w.kind === "pan")
        onContext(clampRange({ start: ctx.start + Math.sign(w.delta) * ctx.dur * 0.25, dur: ctx.dur }, total), false);
      else onContext(clampRange(zoomAround(ctx, sec(pxOf(e)), w.factor, CTX_MIN, CTX_MAX), total), false);
    },
    { passive: false },
  );

  draw();
  new ResizeObserver(() => draw()).observe(root);

  return {
    root,
    setContext(c, st) {
      ctx = c;
      strip = st;
      place();
    },
    setActiveEpisode(id) {
      for (const [k, g] of Object.entries(epNodes)) g.classList.toggle("active", Number(k) === id);
    },
    update(o, eps) {
      ov = o;
      episodes = eps;
      draw();
    },
    setEvents(secs) {
      events = secs;
      drawEvents();
    },
  };
};
