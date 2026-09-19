import { api } from "../../api/client";
import type { ManualLabel, Template } from "../../api/types";
import { clockHM } from "../../lib/time";
import { LABEL_RU } from "../../lib/verdict";
import { el, svg } from "../../ui/dom";
import {
  BUCKET_LABEL,
  type Bucket,
  bucketCounts,
  deviceLabels,
  hoursNote,
  inBucket,
  leadLabels,
  type Scored,
  score,
  verdictText,
} from "./model";

const CARD_W = 220,
  WAVE_H = 84;

export interface TemplatesView {
  root: HTMLElement;
  /** Перезагрузить сетку; с `focusId` прокрутить к семейству и подсветить его. */
  open(focusId?: number): Promise<void>;
}

// ui/segbar подписывает сегмент числом; в шаблонах врачу нужен и класс вердикта
const segbar = (parts: [string, number][]): HTMLElement => {
  const bar = el("div", "segbar");
  const tot = Math.max(
    1,
    parts.reduce((p, [, x]) => p + x, 0),
  );
  for (const [cls, x] of parts)
    if (x) {
      const sg = el("i", `seg ${cls}`);
      sg.style.flex = String(x / tot);
      sg.title = `${cls} ${x}`;
      bar.append(sg);
    }
  return bar;
};

const waveSvg = (t: Template, leadNames: string[]): SVGElement => {
  const sv = svg("svg", { viewBox: `0 0 ${CARD_W} ${WAVE_H}`, class: "tpl-wave" });
  const defs = svg("defs");
  defs.innerHTML = `<pattern id="tg${t.id}" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M8 0H0V8" fill="none" stroke="#f3dada" stroke-width="0.6"/></pattern>`;
  sv.append(defs, svg("rect", { width: CARD_W, height: WAVE_H, fill: `url(#tg${t.id})` }));
  const n = t.wave.leads[0].length,
    lane = WAVE_H / t.wave.leads.length;
  const amp = Math.max(0.3, ...t.wave.leads.map((r) => Math.max(...r.map(Math.abs))));
  t.wave.leads.forEach((row, li) => {
    const base = lane * li + lane / 2;
    let d = "";
    row.forEach((v, i) => {
      d += (i ? "L" : "M") + ((i / (n - 1)) * CARD_W).toFixed(1) + " " + (base - (v / amp) * lane * 0.44).toFixed(1);
    });
    sv.append(svg("path", { d, class: "tpl-trace" }));
    const nm = svg("text", { x: 3, y: lane * li + 9, class: "tpl-lead" });
    nm.textContent = leadNames[li] ?? "";
    sv.append(nm);
  });
  return sv;
};

const hoursSvg = (hrs: number[], startIso: string): SVGElement => {
  const hmax = Math.max(1, ...hrs);
  const sp = svg("svg", { viewBox: `0 0 ${CARD_W} 20`, class: "tpl-hours" });
  hrs.forEach((v, i) => {
    const hh = (v / hmax) * 14;
    sp.append(
      svg("rect", {
        x: (i / hrs.length) * CARD_W + 0.5,
        y: 15 - hh,
        width: CARD_W / hrs.length - 1,
        height: Math.max(hh, v ? 1 : 0),
        class: v ? "on" : "",
      }),
    );
  });
  const l0 = svg("text", { x: 1, y: 19.5, class: "tpl-hours-lbl" });
  l0.textContent = clockHM(startIso, 0);
  const l1 = svg("text", { x: CARD_W - 1, y: 19.5, class: "tpl-hours-lbl", "text-anchor": "end" });
  l1.textContent = clockHM(startIso, hrs.length * 3600);
  sp.append(l0, l1);
  return sp;
};

/**
 * Семейства комплексов по форме QRS. Вопрос врача здесь не «где комплекс», а «какие
 * семейства эктопические и где аудит разошёлся с прибором», поэтому спорные — первыми.
 */
export const createTemplates = (
  startIso: string,
  leadNames: string[],
  onJump: (beatIndex: number) => void,
  onChanged: () => Promise<void>,
): TemplatesView => {
  const LEAD_NAMES = leadLabels(leadNames);
  const root = el("div", "tpl");
  const head = el("div", "tpl-head");
  const title = el("h2", "", "Шаблоны");
  const filters = el("div", "tabs tpl-filters");
  const hint = el(
    "div",
    "muted",
    "N V S X: переразметить всё семейство · сброс: снять · клик по волне: открыть первый комплекс",
  );
  head.append(title, filters, hint);
  const grid = el("div", "tpl-grid");
  root.append(head, grid);
  const cards: Record<number, HTMLElement> = {};
  let bucket: Bucket | "all" = "decide";
  let scored: Scored[] = [];

  const card = (sc: Scored): HTMLElement => {
    const t = sc.t;
    const c = el("div", `tpl-card dom-${sc.dominant}${sc.bucket === "decide" ? " decide" : ""}`);
    const h = el("div", "tpl-card-head");
    h.append(el("span", "mono n", `${t.count.toLocaleString("ru")}`), el("span", "muted", "компл."));
    const badge = el(
      "span",
      `lbl ${sc.dominant}`,
      Object.keys(t.manual).length ? `${sc.dominant} · врач` : sc.dominant === "N" ? "N" : `${sc.dominant} · прибор`,
    );
    h.append(badge);
    c.append(h);

    const sv = waveSvg(t, LEAD_NAMES);
    sv.addEventListener("click", () => onJump(t.first));
    c.append(sv);

    // прибор против аудита: одна составная полоса и одна фраза
    const bar = segbar([
      ["likely", t.verdicts.likely ?? 0],
      ["uncertain", sc.uncertain],
      ["rejected", sc.rejected],
      ["n", t.verdicts.N ?? 0],
    ]);
    const meta = el("div", "tpl-meta");
    meta.innerHTML = `<div class="mono dim">прибор: ${deviceLabels(t.labels)}</div><div class="tpl-verdict">${verdictText(sc)}</div>`;
    c.append(bar, meta);

    // когда в течение суток
    const when = el("div", "tpl-when");
    when.append(hoursSvg(t.hours, startIso), el("span", "mono muted", hoursNote(t.hours, startIso)));
    c.append(when);

    const acts = el("div", "tpl-acts");
    for (const l of ["N", "V", "S", "X"] as ManualLabel[]) {
      const b = el("button", `btn tiny lbl-${l}${t.manual[l] ? " on" : ""}`, l);
      b.title = `всё семейство → ${LABEL_RU[l]}`;
      b.addEventListener("click", async () => {
        await api.annotateTemplate(t.id, l);
        await reload();
        await onChanged();
      });
      acts.append(b);
    }
    if (Object.keys(t.manual).length) {
      const reset = el("button", "btn tiny", "сброс");
      reset.addEventListener("click", async () => {
        await api.annotateTemplate(t.id, null);
        await reload();
        await onChanged();
      });
      acts.append(reset);
    }
    c.append(acts);
    cards[t.id] = c;
    return c;
  };

  const render = () => {
    grid.innerHTML = "";
    const show = inBucket(scored, bucket);
    for (const s of show) grid.append(card(s));
    if (!show.length)
      grid.append(
        el("div", "bp-empty", bucket === "decide" ? "Семейств, где аудит и прибор расходятся, нет." : "Пусто."),
      );
  };

  const renderFilters = () => {
    filters.innerHTML = "";
    const counts = bucketCounts(scored);
    const items: [Bucket | "all", string][] = [
      ["decide", BUCKET_LABEL.decide],
      ["v", BUCKET_LABEL.v],
      ["s", BUCKET_LABEL.s],
      ["n", BUCKET_LABEL.n],
      ["all", "все"],
    ];
    for (const [id, label] of items) {
      const n = id === "all" ? scored.length : counts[id];
      const b = el("button", `tab${id === bucket ? " on" : ""}`, `${label} · ${n}`);
      b.addEventListener("click", () => {
        bucket = id;
        renderFilters();
        render();
      });
      filters.append(b);
    }
  };

  const reload = async () => {
    const ts = await api.templates();
    scored = ts.map(score);
    title.textContent = `Шаблоны · ${ts.length} семейств`;
    if (bucket === "decide" && !scored.some((s) => s.bucket === "decide")) bucket = "v";
    renderFilters();
    render();
  };

  return {
    root,
    async open(focusId) {
      await reload();
      if (focusId !== undefined) {
        const s = scored.find((x) => x.t.id === focusId);
        if (s && bucket !== "all" && s.bucket !== bucket) {
          bucket = s.bucket;
          renderFilters();
          render();
        }
        const c = cards[focusId];
        if (c) {
          c.scrollIntoView({ block: "center" });
          c.classList.add("flash");
          window.setTimeout(() => c.classList.remove("flash"), 900);
        }
      }
    },
  };
};
