import { el } from "./dom";

/** Составная полоса долей: ширина сегмента пропорциональна его счёту, нули не рисуются. */
export const segbar = (parts: [string, number][]): HTMLElement => {
  const total = Math.max(
    1,
    parts.reduce((p, [, n]) => p + n, 0),
  );
  const bar = el("div", "segbar");
  for (const [cls, n] of parts) {
    if (n > 0) {
      const sg = el("i", `seg ${cls}`);
      sg.style.flex = String(n / total);
      sg.title = `${n}`;
      bar.append(sg);
    }
  }
  return bar;
};
