import { api, type Beat, type ManualLabel, type Template } from "./api";
import { LABEL_RU, VERDICT_RU, clock, el, svg, verdictClass } from "./util";

let STRIP_LEADS: string[] = [];                    // the record's own trio, set in createBeatPanel
const STRIP_DUR = 2.4;                      // seconds shown around the beat
const SHAPE_MS = 96;                        // +- window for the shape overlay (matches templates.py)

export interface BeatPanel {
  root: HTMLElement;
  showBeat(b: Beat | null, startIso: string): void;
  showCursor(sec: number | null, startIso: string): void;
  showError(msg: string | null): void;
  showRange(r: { t0: number; t1: number } | null, startIso: string): void;
}

export interface BeatPanelHandlers {
  onLabel: (l: ManualLabel | null) => void;
  onAdd: (l: ManualLabel) => void;
  onFamily: (t: number) => void;
  onQuality: (v: "clean" | "noise" | null) => void;
  onJump: (index: number) => void;
  onStep: (dir: 1 | -1) => void;
}

/**
 * Sidebar tab for the selected beat. Answers "why this verdict" without leaving the
 * panel: the beat in a 2.4 s strip, its shape against the family mean and the sinus
 * mean, every audit feature, the family's make-up, and the actions.
 */
export function createBeatPanel(h: BeatPanelHandlers, stripLeads: string[]): BeatPanel {
  STRIP_LEADS = stripLeads;
  const root = el("div", "bp");
  const empty = el("div", "bp-empty");
  empty.innerHTML = `Выбрать комплекс: клик по метке или <kbd>Tab</kbd>.<br>Добавить пропущенный: клик по ленте.<br>Диапазон качества: <kbd>shift</kbd> + протянуть.`;

  // ---- add-beat box ----
  const addBox = el("div", "bp-box"); addBox.hidden = true;
  const addTitle = el("div", "bp-box-title mono");
  const addActs = el("div", "bp-acts");
  for (const l of ["N", "V", "S"] as ManualLabel[]) {
    const b = el("button", `btn lbl-${l}`, l); b.title = LABEL_RU[l];
    b.append(el("small", "", l === "N" ? "a" : ""));
    b.addEventListener("click", () => h.onAdd(l));
    addActs.append(b);
  }
  const addErr = el("div", "bp-err"); addErr.hidden = true;
  addBox.append(el("div", "bp-box-lbl", "Добавить комплекс"), addTitle, addActs, addErr);

  // ---- quality range box ----
  const rangeBox = el("div", "bp-box"); rangeBox.hidden = true;
  const rangeTitle = el("div", "bp-box-title mono");
  const rangeActs = el("div", "bp-acts");
  const qClean = el("button", "btn lbl-N", "чисто"); qClean.append(el("small", "", "c"));
  const qNoise = el("button", "btn lbl-X", "помеха"); qNoise.append(el("small", "", "x"));
  const qReset = el("button", "btn", "сброс"); qReset.append(el("small", "", "⌫"));
  qClean.addEventListener("click", () => h.onQuality("clean"));
  qNoise.addEventListener("click", () => h.onQuality("noise"));
  qReset.addEventListener("click", () => h.onQuality(null));
  rangeActs.append(qClean, qNoise, qReset);
  rangeBox.append(el("div", "bp-box-lbl", "Диапазон"), rangeTitle, rangeActs,
    el("div", "bp-note", "«чисто» снимает автоматическую помеху, «помеха» ставит её, «сброс» убирает ручные метки в диапазоне."));

  // ---- beat body ----
  const body = el("div", "bp-body"); body.hidden = true;
  const head = el("div", "bp-head");
  const big = el("div", "bp-big mono");
  const verdict = el("span", "bp-verdict");
  const sub = el("div", "bp-sub mono");
  const nav = el("div", "bp-nav");
  const prevB = el("button", "ibtn", "‹"); prevB.title = "предыдущий подозрительный  shift+Tab";
  const nextB = el("button", "ibtn", "›"); nextB.title = "следующий подозрительный  Tab";
  prevB.addEventListener("click", () => h.onStep(-1)); nextB.addEventListener("click", () => h.onStep(1));
  nav.append(prevB, nextB);
  head.append(big, sub, nav);

  const strip = svg("svg", { class: "bp-strip", viewBox: "0 0 320 150" });
  const shape = el("div", "bp-shape");
  const shapeSvg = svg("svg", { class: "bp-shape-svg", viewBox: "0 0 320 90" });
  const shapeLegend = el("div", "legend bp-legend");
  shapeLegend.innerHTML = `<span><i style="background:var(--ink)"></i>этот</span><span><i style="background:var(--red)"></i>семейство</span><span><i style="background:var(--ink-3)"></i>синус</span>`;
  shape.append(shapeSvg, shapeLegend);

  const reasons = el("ul", "bp-reasons");
  const feats = el("div", "bp-feats mono");
  const acts = el("div", "bp-acts");
  const labelBtns: Record<string, HTMLElement> = {};
  for (const l of ["N", "V", "S", "X"] as ManualLabel[]) {
    const b = el("button", `btn lbl-${l}`, l); b.title = LABEL_RU[l];
    b.append(el("small", "", l.toLowerCase()));
    b.addEventListener("click", () => h.onLabel(l));
    labelBtns[l] = b; acts.append(b);
  }
  const clear = el("button", "btn", "снять"); clear.append(el("small", "", "⌫"));
  clear.addEventListener("click", () => h.onLabel(null));
  acts.append(clear);

  const fam = el("div", "bp-fam");
  const famHead = el("div", "bp-fam-head");
  const famBtn = el("button", "btn ghost", "семейство");
  famHead.append(el("span", "bp-box-lbl", "Комплексы такой же формы"), famBtn);
  const famMeta = el("div", "lline mono");
  const famBar = el("div", "segbar");
  const famPeers = el("div", "bp-peers");
  fam.append(famHead, famMeta, famBar, famPeers);

  body.append(head, strip, shape, reasons, feats, acts, fam);
  root.append(empty, addBox, rangeBox, body);

  let cur: Beat | null = null, templates: Template[] | null = null, req = 0;
  famBtn.addEventListener("click", () => { if (cur) h.onFamily(cur.template); });

  async function loadTemplates() { if (!templates) templates = await api.templates(); return templates; }

  function drawStrip(sig: number[][], leads: string[], fs: number, start: number, marks: Beat[]) {
    strip.innerHTML = "";
    const W = 320, H = 150, lane = H / leads.length, pxS = W / STRIP_DUR;
    for (let xs = 0; xs <= STRIP_DUR; xs += 0.2) strip.append(svg("line", { x1: xs * pxS, x2: xs * pxS, y1: 0, y2: H, class: xs % 1 < 1e-6 ? "g-major" : "g-minor" }));
    for (let ym = 0; ym <= H; ym += lane / 4) strip.append(svg("line", { x1: 0, x2: W, y1: ym, y2: ym, class: "g-minor" }));
    const ptp = Math.max(0.3, ...sig.map((r) => Math.max(...r) - Math.min(...r)));
    const gain = (lane * 0.8) / ptp;
    sig.forEach((row, li) => {
      const base = lane * li + lane / 2;
      let d = "";
      row.forEach((v, i) => { d += (i ? "L" : "M") + ((i / fs) * pxS).toFixed(1) + " " + (base - v * gain).toFixed(1); });
      strip.append(svg("path", { d, class: "bp-trace" }));
      const t = svg("text", { x: 3, y: lane * li + 10, class: "bp-lead" }); t.textContent = leads[li]; strip.append(t);
    });
    for (const m of marks) {
      const x = (m.t_ms / 1000 - start) * pxS;
      const me = m.index === cur?.index;
      strip.append(svg("line", { x1: x, x2: x, y1: 0, y2: H, class: `bp-mark${me ? " me" : ""}` }));
      const t = svg("text", { x: x + 2, y: H - 3, class: `bp-mark-lbl${me ? " me" : ""}` }); t.textContent = m.label; strip.append(t);
    }
  }

  function drawShape(beatII: number[], famWave: number[] | null, sinusWave: number[] | null) {
    shapeSvg.innerHTML = "";
    const W = 320, H = 90;
    const norm = (w: number[]) => { const med = [...w].sort((a, b) => a - b)[w.length >> 1]; const c = w.map((v) => v - med); const m = Math.max(1e-6, ...c.map(Math.abs)); return c.map((v) => v / m); };
    const draw = (w: number[], cls: string) => {
      const n = w.length; let d = "";
      w.forEach((v, i) => { d += (i ? "L" : "M") + ((i / (n - 1)) * W).toFixed(1) + " " + (H / 2 - v * (H / 2) * 0.9).toFixed(1); });
      shapeSvg.append(svg("path", { d, class: `bp-shape-${cls}` }));
    };
    shapeSvg.append(svg("line", { x1: W / 2, x2: W / 2, y1: 0, y2: H, class: "g-major" }));
    if (sinusWave) draw(norm(sinusWave), "sinus");
    if (famWave) draw(norm(famWave), "fam");
    draw(norm(beatII), "me");
    const t = svg("text", { x: 4, y: H - 4, class: "bp-lead" }); t.textContent = `II · ±${SHAPE_MS} мс · нормировано`; shapeSvg.append(t);
  }

  async function fill(b: Beat, startIso: string) {
    const id = ++req;
    const t0 = b.t_ms / 1000 - STRIP_DUR / 2;
    const [win, ts] = await Promise.all([api.ecg(Math.max(0, t0), STRIP_DUR, STRIP_LEADS), loadTemplates()]);
    if (id !== req) return;
    drawStrip(win.data, win.leads, win.fs, win.start, win.beats);
    const ii = win.data[0];
    const c = Math.round((b.t_ms / 1000 - win.start) * win.fs), half = Math.round((SHAPE_MS / 1000) * win.fs);
    const beatII = ii.slice(Math.max(0, c - half), c + half + 1);
    const famT = ts.find((t) => t.id === b.template) ?? null;
    const sinusT = ts[0] ?? null;                      // largest family = sinus
    drawShape(beatII, famT ? famT.wave.leads[0] : null, sinusT ? sinusT.wave.leads[0] : null);
    if (famT) {
      const dev = Object.entries(famT.labels).sort((x, y) => y[1] - x[1]).map(([k, v]) => `${k} ${v}`).join(" · ");
      famMeta.innerHTML = `<span>${famT.count.toLocaleString("ru")} компл. с такой формой</span><span>прибор: ${dev}</span>`;
      famBar.innerHTML = "";
      const parts: [string, number][] = [["likely", famT.verdicts.likely ?? 0], ["uncertain", famT.verdicts.uncertain ?? 0],
        ["rejected", Object.entries(famT.verdicts).filter(([k]) => !["likely", "uncertain", "N"].includes(k)).reduce((p, [, n]) => p + n, 0)],
        ["n", famT.verdicts.N ?? 0]];
      const tot = Math.max(1, parts.reduce((p, [, n]) => p + n, 0));
      for (const [cls, n] of parts) if (n) { const sg = el("i", `seg ${cls}`); sg.style.flex = String(n / tot); sg.title = `${cls} ${n}`; famBar.append(sg); }
      famBtn.textContent = "все с такой формой";
      const peers = await api.templateBeats(famT.id, 0, 400);
      if (id !== req) return;
      famPeers.innerHTML = "";
      const marked = peers.beats.filter((p) => p.index !== b.index && p.device_label !== "N").slice(0, 8);
      for (const p of marked) {
        const chip = el("button", `chip peer ${verdictClass(p.verdict)}`, clock(startIso, p.t_ms / 1000).slice(0, 8));
        chip.title = `${p.label}: ${VERDICT_RU[p.verdict] ?? p.verdict}`;
        chip.addEventListener("click", () => h.onJump(p.index));
        famPeers.append(chip);
      }
      if (!marked.length) famPeers.append(el("span", "muted", "других меток V/S в семействе нет"));
    } else {
      famMeta.textContent = "семейство не определено"; famBar.innerHTML = ""; famPeers.innerHTML = ""; famBtn.textContent = "семейство";
    }
  }

  const fmt = (v: number | null, f: (x: number) => string) => (v === null ? "—" : f(v));
  return {
    root,
    showRange(r, startIso) {
      rangeBox.hidden = !r;
      if (!r) return;
      cur = null; body.hidden = true; addBox.hidden = true; empty.hidden = true;
      const ms = (x: number) => clock(startIso, x) + "." + String(Math.round((x % 1) * 10));
      rangeTitle.textContent = `${ms(r.t0)} – ${ms(r.t1)} · ${(r.t1 - r.t0).toFixed(1)} с`;
    },
    showBeat(b, startIso) {
      cur = b;
      body.hidden = !b; addBox.hidden = true; rangeBox.hidden = true; empty.hidden = !!b;
      if (!b) return;
      const vc = verdictClass(b.verdict);
      big.textContent = b.added ? `+${b.label}` : b.manual ? `${b.manual}` : b.label;
      big.className = `bp-big mono ${vc}`;
      verdict.textContent = b.added ? "добавлен вручную" : b.manual ? "ручная метка" : (VERDICT_RU[b.verdict] ?? b.verdict);
      verdict.className = `bp-verdict ${vc}`;
      big.append(verdict);
      sub.textContent = `${clock(startIso, b.t_ms / 1000)}${b.device_label ? ` · прибор ${b.device_label}` : ""}${b.manual && b.device_label ? ` → ${b.manual}` : ""}`;
      sub.title = `#${b.index}`;
      reasons.innerHTML = b.reasons.map((r) => `<li>${r}</li>`).join("");
      feats.innerHTML = [
        ["QRS", fmt(b.width_ms, (x) => `${x.toFixed(0)} мс`)],
        ["синусовый QRS", fmt(b.width_ratio, (x) => b.width_ms ? `${(b.width_ms / x).toFixed(0)} мс` : "—")],
        ["RR до", fmt(b.rr_pre, (x) => `${x} мс`)],
        ["RR после", fmt(b.rr_post, (x) => `${x} мс`)],
        ["ритм до неё", fmt(b.prematurity, (x) => b.rr_pre ? `${(b.rr_pre / x).toFixed(0)} мс` : "—")],
        ["амплитуда", fmt(b.amp_ratio, (x) => `${(x * 100).toFixed(0)}% от N`)],
        ["шум", fmt(b.noise_ratio, (x) => (x < 1.5 ? "нет" : x < 2.5 ? "умеренный" : "сильный"))],
        ["форма как N", fmt(b.family_n_frac, (x) => (x > 0.9 ? "да" : x < 0.2 ? "нет" : "частично"))],
      ].map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join("");
      for (const [k, btn] of Object.entries(labelBtns)) btn.classList.toggle("on", (b.manual ?? (b.added ? b.label : null)) === k);
      const undo = b.added ? "удалить" : b.manual ? "снять" : null;
      clear.hidden = !undo;
      if (undo) clear.firstChild!.textContent = undo;
      fam.hidden = b.template < 0;
      strip.innerHTML = ""; shapeSvg.innerHTML = ""; famPeers.innerHTML = "";
      void fill(b, startIso);
    },
    showError(msg) { addErr.hidden = !msg; addErr.textContent = msg ?? ""; },
    showCursor(sec, startIso) {
      if (cur) return;
      addErr.hidden = true; rangeBox.hidden = true;
      addBox.hidden = sec === null; empty.hidden = sec !== null;
      if (sec !== null) addTitle.textContent = clock(startIso, sec) + "." + String(Math.round((sec % 1) * 1000)).padStart(3, "0");
    },
  };
}
