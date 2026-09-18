import { api, type ManualLabel, type Template } from "./api";
import { LABEL_RU, VERDICT_RU, clock, el, svg } from "./util";

const CARD_W = 220, WAVE_H = 84;
// templates.py builds its waves on channels [1, 10, 7]; label them with the record's names
const TEMPLATE_CHANNELS = [1, 10, 7];
type Bucket = "decide" | "v" | "s" | "n";
const BUCKET_LABEL: Record<Bucket, string> = { decide: "требуют решения", v: "ЖЭС", s: "НЖЭС", n: "норма" };

export interface TemplatesView {
  root: HTMLElement;
  /** (Re)load the grid; with `focusId` scroll that family into view and flash it. */
  open(focusId?: number): Promise<void>;
}

interface Scored { t: Template; bucket: Bucket; kept: number; rejected: number; uncertain: number; dominant: string; nV: number; keptV: number; rejV: number }

/**
 * Families of beats grouped by QRS shape. The reviewer's question here is not
 * "where does each beat sit" but "which families are ectopic, and which ones did
 * the audit and the device disagree on". So: families that need a decision first,
 * then ectopic families, then sinus; one card per family with the decision buttons.
 */
export function createTemplates(startIso: string, leadNames: string[], onJump: (beatIndex: number) => void, onChanged: () => Promise<void>): TemplatesView {
  const LEAD_NAMES = TEMPLATE_CHANNELS.map((c) => leadNames[c] ?? `ch${c}`);
  const root = el("div", "tpl");
  const head = el("div", "tpl-head");
  const title = el("h2", "", "Шаблоны");
  const filters = el("div", "tabs tpl-filters");
  const hint = el("div", "muted", "N V S X: переразметить всё семейство · сброс: снять · клик по волне: открыть первый комплекс");
  head.append(title, filters, hint);
  const grid = el("div", "tpl-grid");
  root.append(head, grid);
  const cards: Record<number, HTMLElement> = {};
  let bucket: Bucket | "all" = "decide";
  let scored: Scored[] = [];

  const KEPT = ["likely", "uncertain", "manual"];
  const sum = (o: Record<string, number> | undefined, keys?: string[], invert = false) =>
    Object.entries(o ?? {}).filter(([k]) => keys ? (invert ? !keys.includes(k) : keys.includes(k)) : true).reduce((p, [, n]) => p + n, 0);

  /** A family is a SHAPE. The only family-level question is "is this shape ventricular?",
   *  so buckets are driven by the device's V labels and what the audit made of them. S
   *  labels are about timing, not shape, and never put a family up for decision. */
  function score(t: Template): Scored {
    const dev = t.labels, vV = t.verdicts_by_label.V ?? {};
    const nV = dev.V ?? 0, keptV = sum(vV, KEPT), uncV = vV.uncertain ?? 0, rejV = sum(vV, [...KEPT, "N", "manual-N"], true);
    const kept = sum(t.verdicts, KEPT), uncertain = t.verdicts.uncertain ?? 0, rejected = sum(t.verdicts, [...KEPT, "N", "manual-N"], true);
    const manualDom = Object.entries(t.manual).sort((a, b) => b[1] - a[1])[0]?.[0];
    const sShare = (dev.S ?? 0) / Math.max(1, t.count), vShare = nV / Math.max(1, t.count);
    const dominant = manualDom ?? (vShare > 0.5 ? "V" : sShare > 0.5 ? "S" : "N");
    let b: Bucket;
    if (manualDom) b = manualDom === "V" ? "v" : manualDom === "S" ? "s" : "n";
    else if (nV >= 3 && (uncV >= 3 || (keptV / nV >= 0.2 && keptV / nV <= 0.8))) b = "decide";     // audit split on the V labels
    else if (nV >= 3 && keptV / nV > 0.8) b = "v";                                                  // audit agrees: ventricular shape
    else if (dominant === "V") b = "v";
    else if (dominant === "S") b = "s";
    else b = "n";
    return { t, bucket: b, kept, rejected, uncertain, dominant, nV, keptV, rejV };
  }

  function hoursNote(hours: number[]): string {
    const total = hours.reduce((p, c) => p + c, 0);
    if (!total) return "";
    const start = new Date(startIso.replace(" ", "T"));
    const bins = { "утром": 0, "днём": 0, "вечером": 0, "ночью": 0 } as Record<string, number>;
    hours.forEach((n, i) => {
      const h = (start.getHours() + i) % 24;
      const k = h < 6 ? "ночью" : h < 12 ? "утром" : h < 18 ? "днём" : "вечером";
      bins[k] += n;
    });
    const [best, n] = Object.entries(bins).sort((a, b) => b[1] - a[1])[0];
    return n / total >= 0.6 ? `в основном ${best} (${Math.round((100 * n) / total)}%)` : "в течение суток";
  }

  function card(sc: Scored): HTMLElement {
    const t = sc.t;
    const c = el("div", `tpl-card dom-${sc.dominant}${sc.bucket === "decide" ? " decide" : ""}`);
    const h = el("div", "tpl-card-head");
    h.append(el("span", "mono n", `${t.count.toLocaleString("ru")}`), el("span", "muted", "компл."));
    const badge = el("span", `lbl ${sc.dominant}`, Object.keys(t.manual).length ? `${sc.dominant} · врач` : sc.dominant === "N" ? "N" : `${sc.dominant} · прибор`);
    h.append(badge);
    c.append(h);

    const sv = svg("svg", { viewBox: `0 0 ${CARD_W} ${WAVE_H}`, class: "tpl-wave" });
    const defs = svg("defs");
    defs.innerHTML = `<pattern id="tg${t.id}" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M8 0H0V8" fill="none" stroke="#f3dada" stroke-width="0.6"/></pattern>`;
    sv.append(defs, svg("rect", { width: CARD_W, height: WAVE_H, fill: `url(#tg${t.id})` }));
    const n = t.wave.leads[0].length, lane = WAVE_H / t.wave.leads.length;
    const amp = Math.max(0.3, ...t.wave.leads.map((r) => Math.max(...r.map(Math.abs))));
    t.wave.leads.forEach((row, li) => {
      const base = lane * li + lane / 2;
      let d = "";
      row.forEach((v, i) => { d += (i ? "L" : "M") + ((i / (n - 1)) * CARD_W).toFixed(1) + " " + (base - (v / amp) * lane * 0.44).toFixed(1); });
      sv.append(svg("path", { d, class: "tpl-trace" }));
      const nm = svg("text", { x: 3, y: lane * li + 9, class: "tpl-lead" }); nm.textContent = LEAD_NAMES[li] ?? ""; sv.append(nm);
    });
    sv.addEventListener("click", () => onJump(t.first));
    c.append(sv);

    // device vs audit, as one stacked bar + one sentence
    const dev = Object.entries(t.labels).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${v}`).join(" · ");
    const bar = el("div", "segbar");
    const parts: [string, number][] = [["likely", t.verdicts.likely ?? 0], ["uncertain", sc.uncertain], ["rejected", sc.rejected], ["n", t.verdicts.N ?? 0]];
    const tot = Math.max(1, parts.reduce((p, [, x]) => p + x, 0));
    for (const [cls, x] of parts) if (x) { const sg = el("i", `seg ${cls}`); sg.style.flex = String(x / tot); sg.title = `${cls} ${x}`; bar.append(sg); }
    const meta = el("div", "tpl-meta");
    let verdictTxt = "";
    if (Object.keys(t.manual).length) verdictTxt = `врач: ${Object.entries(t.manual).map(([k, v]) => `${k} ${v}`).join(" · ")}`;
    else if (sc.nV === 0) verdictTxt = (t.labels.S ?? 0) ? `форма синусовая; ${t.labels.S} ранних (НЖЭС) по времени` : "синусовая форма";
    else if (sc.keptV === sc.nV) verdictTxt = `ЖЭС: аудит подтверждает все ${sc.nV}`;
    else if (sc.keptV === 0) verdictTxt = `не ЖЭС: все ${sc.nV} метки V отклонены (${topReason(t)})`;
    else verdictTxt = `ЖЭС? подтверждено ${sc.keptV} из ${sc.nV}, отклонено ${sc.rejV}`;
    meta.innerHTML = `<div class="mono dim">прибор: ${dev}</div><div class="tpl-verdict">${verdictTxt}</div>`;
    c.append(bar, meta);

    // when in the day
    const hrs = t.hours; const hmax = Math.max(1, ...hrs);
    const sp = svg("svg", { viewBox: `0 0 ${CARD_W} 20`, class: "tpl-hours" });
    hrs.forEach((v, i) => {
      const hh = (v / hmax) * 14;
      sp.append(svg("rect", { x: (i / hrs.length) * CARD_W + 0.5, y: 15 - hh, width: CARD_W / hrs.length - 1, height: Math.max(hh, v ? 1 : 0), class: v ? "on" : "" }));
    });
    const l0 = svg("text", { x: 1, y: 19.5, class: "tpl-hours-lbl" }); l0.textContent = clock(startIso, 0).slice(0, 5);
    const l1 = svg("text", { x: CARD_W - 1, y: 19.5, class: "tpl-hours-lbl", "text-anchor": "end" }); l1.textContent = clock(startIso, hrs.length * 3600).slice(0, 5);
    sp.append(l0, l1);
    const when = el("div", "tpl-when"); when.append(sp, el("span", "mono muted", hoursNote(hrs)));
    c.append(when);

    const acts = el("div", "tpl-acts");
    for (const l of ["N", "V", "S", "X"] as ManualLabel[]) {
      const b = el("button", `btn tiny lbl-${l}${t.manual[l] ? " on" : ""}`, l);
      b.title = `всё семейство → ${LABEL_RU[l]}`;
      b.addEventListener("click", async () => { await api.annotateTemplate(t.id, l); await reload(); await onChanged(); });
      acts.append(b);
    }
    if (Object.keys(t.manual).length) {
      const reset = el("button", "btn tiny", "сброс");
      reset.addEventListener("click", async () => { await api.annotateTemplate(t.id, null); await reload(); await onChanged(); });
      acts.append(reset);
    }
    c.append(acts);
    cards[t.id] = c;
    return c;
  }

  function topReason(t: Template): string {
    const r = Object.entries(t.verdicts_by_label.V ?? {}).filter(([k]) => ![...KEPT, "N", "manual-N"].includes(k)).sort((a, b) => b[1] - a[1])[0];
    return r ? (VERDICT_RU[r[0]] ?? r[0]) : "";
  }

  function render() {
    grid.innerHTML = "";
    const show = scored.filter((s) => bucket === "all" || s.bucket === bucket);
    const order: Bucket[] = ["decide", "v", "s", "n"];
    show.sort((a, b) => order.indexOf(a.bucket) - order.indexOf(b.bucket) || b.t.count - a.t.count);
    for (const s of show) grid.append(card(s));
    if (!show.length) grid.append(el("div", "bp-empty", bucket === "decide" ? "Семейств, где аудит и прибор расходятся, нет." : "Пусто."));
  }

  function renderFilters() {
    filters.innerHTML = "";
    const counts: Record<string, number> = { decide: 0, v: 0, s: 0, n: 0 };
    for (const s of scored) counts[s.bucket]++;
    const items: [Bucket | "all", string][] = [["decide", BUCKET_LABEL.decide], ["v", BUCKET_LABEL.v], ["s", BUCKET_LABEL.s], ["n", BUCKET_LABEL.n], ["all", "все"]];
    for (const [id, label] of items) {
      const n = id === "all" ? scored.length : counts[id];
      const b = el("button", `tab${id === bucket ? " on" : ""}`, `${label} · ${n}`);
      b.addEventListener("click", () => { bucket = id; renderFilters(); render(); });
      filters.append(b);
    }
  }

  async function reload() {
    const ts = await api.templates();
    scored = ts.map(score);
    title.textContent = `Шаблоны · ${ts.length} семейств`;
    if (bucket === "decide" && !scored.some((s) => s.bucket === "decide")) bucket = "v";
    renderFilters(); render();
  }

  return {
    root,
    async open(focusId) {
      await reload();
      if (focusId !== undefined) {
        const s = scored.find((x) => x.t.id === focusId);
        if (s && bucket !== "all" && s.bucket !== bucket) { bucket = s.bucket; renderFilters(); render(); }
        const c = cards[focusId];
        if (c) { c.scrollIntoView({ block: "center" }); c.classList.add("flash"); window.setTimeout(() => c.classList.remove("flash"), 900); }
      }
    },
  };
}
