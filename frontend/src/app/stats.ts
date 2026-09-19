import type { Summary } from "../api/types";
import { clockHM } from "../lib/time";
import { el } from "../ui/dom";
import { segbar } from "../ui/segbar";

/** Четыре карточки слева от обзора: крупное число с пометкой и строки «ключ — значение». */
export const statsBlock = (sum: Summary): HTMLElement => {
  const box = el("div", "cards");
  const c = sum.counts,
    h = sum.hr,
    r = sum.record;
  const card = (title: string, hero: string, note: string, rows: [string, string][], bar?: HTMLElement) => {
    const d = el("div", "card stat");
    d.append(el("div", "card-title", title));
    const hv = el("div", "hero mono");
    hv.textContent = hero;
    if (note) {
      const hn = el("span", "hero-note mono");
      hn.textContent = note;
      hv.append(hn);
    }
    d.append(hv);
    if (bar) d.append(bar);
    const kv = el("div", "kv");
    for (const [k, v] of rows) {
      const row = el("div", "kvr");
      row.innerHTML = `<span>${k}</span><b class="mono">${v}</b>`;
      kv.append(row);
    }
    d.append(kv);
    box.append(d);
  };
  const vv = c.verdicts.V ?? {},
    sv = c.verdicts.S ?? {};
  const rej = (o: Record<string, number>) =>
    Object.entries(o)
      .filter(([k]) => k !== "likely" && k !== "uncertain" && k !== "manual")
      .reduce((p, [, n]) => p + n, 0);
  const vL = c.audited.V_likely,
    vU = c.audited.V - vL,
    vR = rej(vv);
  const sL = c.audited.S,
    sR = rej(sv);
  const nm = sum.morphologies.length;

  card("ЧСС, уд/мин", `${h.mean}`, `сон ${h.sleep ?? "—"} · день ${h.wake ?? "—"}`, [
    ["минимум", `${h.min} · ${clockHM(r.start, h.min_at_s)}`],
    ["максимум", `${h.max} · ${clockHM(r.start, h.max_at_s)}`],
    ["SDNN / RMSSD", `${Math.round(sum.hrv.sdnn)} / ${Math.round(sum.hrv.rmssd)} мс`],
  ]);
  card(
    "ЖЭС",
    `${vL}–${c.audited.V}`,
    `${((100 * c.audited.V) / r.beats).toFixed(2)}%`,
    [
      ["прибор насчитал", `${c.device.V}`],
      ["вероятные · спорные", `${vL} · ${vU}`],
      ["отклонено", `${vR}`],
      ["морфологий", nm ? `${nm}` : "—"],
    ],
    segbar([
      ["likely", vL],
      ["uncertain", vU],
      ["rejected", vR],
    ]),
  );
  card(
    "НЖЭС",
    `${sL}`,
    `${((100 * sL) / r.beats).toFixed(2)}%`,
    [
      ["прибор насчитал", `${c.device.S}`],
      ["отклонено", `${sR}`],
    ],
    segbar([
      ["likely", sL],
      ["rejected", sR],
    ]),
  );
  card("Паузы > 2 с", `${c.pauses_real}`, "", [
    ["прибор насчитал", `${c.pauses_device}`],
    ["из них помеха", `${c.pauses_device - c.pauses_real}`],
    ["чистый сигнал", `${r.clean_pct}%`],
    ["правок врача", `${c.manual + c.added + c.quality_spans}`],
  ]);
  return box;
};
