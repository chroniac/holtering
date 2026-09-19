import { el, svg } from "./dom";

export interface DumbbellRow {
  label: string;
  before: number;
  after: number;
  accent?: boolean;
}

/**
 * «До → после» на одной оси: пустая точка — прибор, закрашенная — аудит, разница справа.
 * Строки, где аудит сдвинул счёт в другую сторону или не сдвинул вовсе, идут акцентом.
 */
export const dumbbell = (rows: DumbbellRow[], title: [string, string]): HTMLElement => {
  const box = el("div", "dumb");
  const head = el("div", "dumb-head mono");
  head.innerHTML = `<span>${title[0]}</span><span>${title[1]}</span>`;
  box.append(head);
  const W = 300,
    LBL = 70,
    VAL = 104,
    ROW = 22,
    PAD = 8;
  const plotW = W - LBL - VAL - PAD;
  const max = Math.max(1, ...rows.map((r) => Math.max(r.before, r.after)));
  const x = (v: number) => LBL + (v / max) * plotW;
  const sv = svg("svg", { viewBox: `0 0 ${W} ${rows.length * ROW + 4}`, class: "dumb-svg" });
  rows.forEach((r, i) => {
    const y = i * ROW + ROW / 2 + 2;
    const g = svg("g", { class: `drow${r.accent ? " accent" : ""}` });
    const t = svg("text", { x: 0, y: y + 3.5, class: "dlbl" });
    t.textContent = r.label;
    g.append(t);
    g.append(
      svg("line", {
        x1: x(Math.min(r.before, r.after)),
        x2: x(Math.max(r.before, r.after)),
        y1: y,
        y2: y,
        class: "dbar",
      }),
    );
    g.append(svg("circle", { cx: x(r.before), cy: y, r: 3.2, class: "dbefore" }));
    g.append(svg("circle", { cx: x(r.after), cy: y, r: 3.2, class: "dafter" }));
    const d = r.before > 0 ? Math.round((100 * (r.after - r.before)) / r.before) : 0;
    const v = svg("text", { x: W, y: y + 3.5, class: "dval", "text-anchor": "end" });
    v.textContent = `${r.before} → ${r.after}  ${d > 0 ? "+" : ""}${d}%`;
    g.append(v);
    sv.append(g);
  });
  box.append(sv);
  return box;
};
