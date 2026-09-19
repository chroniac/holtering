import type { Template } from "../../api/types";
import { VERDICT_RU } from "../../lib/verdict";

export type Bucket = "decide" | "v" | "s" | "n";

export const BUCKET_LABEL: Record<Bucket, string> = { decide: "требуют решения", v: "ЖЭС", s: "НЖЭС", n: "норма" };

// templates.py строит формы по каналам [1, 10, 7]; подписываем их именами отведений записи
const TEMPLATE_CHANNELS = [1, 10, 7];

const BUCKET_ORDER: Bucket[] = ["decide", "v", "s", "n"];

export interface Scored {
  t: Template;
  bucket: Bucket;
  kept: number;
  rejected: number;
  uncertain: number;
  dominant: string;
  nV: number;
  keptV: number;
  rejV: number;
}

export const KEPT = ["likely", "uncertain", "manual"];

export const leadLabels = (leadNames: string[]): string[] => TEMPLATE_CHANNELS.map((c) => leadNames[c] ?? `ch${c}`);

const sum = (o: Record<string, number> | undefined, keys?: string[], invert = false) =>
  Object.entries(o ?? {})
    .filter(([k]) => (keys ? (invert ? !keys.includes(k) : keys.includes(k)) : true))
    .reduce((p, [, n]) => p + n, 0);

/** Семейство — это форма, поэтому корзины ведут метки V; метки S про время, не про форму,
 *  и никогда не выносят семейство на решение. */
export const score = (t: Template): Scored => {
  const dev = t.labels,
    vV = t.verdicts_by_label.V ?? {};
  const nV = dev.V ?? 0,
    keptV = sum(vV, KEPT),
    uncV = vV.uncertain ?? 0,
    rejV = sum(vV, [...KEPT, "N", "manual-N"], true);
  const kept = sum(t.verdicts, KEPT),
    uncertain = t.verdicts.uncertain ?? 0,
    rejected = sum(t.verdicts, [...KEPT, "N", "manual-N"], true);
  const manualDom = Object.entries(t.manual).sort((a, b) => b[1] - a[1])[0]?.[0];
  const sShare = (dev.S ?? 0) / Math.max(1, t.count),
    vShare = nV / Math.max(1, t.count);
  const dominant = manualDom ?? (vShare > 0.5 ? "V" : sShare > 0.5 ? "S" : "N");
  let b: Bucket;
  if (manualDom) b = manualDom === "V" ? "v" : manualDom === "S" ? "s" : "n";
  else if (nV >= 3 && (uncV >= 3 || (keptV / nV >= 0.2 && keptV / nV <= 0.8)))
    b = "decide"; // аудит разошёлся с метками V
  else if (nV >= 3 && keptV / nV > 0.8)
    b = "v"; // аудит согласен: желудочковая форма
  else if (dominant === "V") b = "v";
  else if (dominant === "S") b = "s";
  else b = "n";
  return { t, bucket: b, kept, rejected, uncertain, dominant, nV, keptV, rejV };
};

export const hoursNote = (hours: number[], startIso: string): string => {
  const total = hours.reduce((p, c) => p + c, 0);
  if (!total) return "";
  const start = new Date(startIso.replace(" ", "T"));
  const bins = { утром: 0, днём: 0, вечером: 0, ночью: 0 } as Record<string, number>;
  hours.forEach((n, i) => {
    const h = (start.getHours() + i) % 24;
    const k = h < 6 ? "ночью" : h < 12 ? "утром" : h < 18 ? "днём" : "вечером";
    bins[k] += n;
  });
  const [best, n] = Object.entries(bins).sort((a, b) => b[1] - a[1])[0];
  return n / total >= 0.6 ? `в основном ${best} (${Math.round((100 * n) / total)}%)` : "в течение суток";
};

export const topReason = (t: Template): string => {
  const r = Object.entries(t.verdicts_by_label.V ?? {})
    .filter(([k]) => ![...KEPT, "N", "manual-N"].includes(k))
    .sort((a, b) => b[1] - a[1])[0];
  return r ? (VERDICT_RU[r[0]] ?? r[0]) : "";
};

/** Одна фраза «прибор против аудита» для карточки семейства. */
export const verdictText = (sc: Scored): string => {
  const t = sc.t;
  if (Object.keys(t.manual).length)
    return `врач: ${Object.entries(t.manual)
      .map(([k, v]) => `${k} ${v}`)
      .join(" · ")}`;
  if (sc.nV === 0)
    return (t.labels.S ?? 0) ? `форма синусовая; ${t.labels.S} ранних (НЖЭС) по времени` : "синусовая форма";
  if (sc.keptV === sc.nV) return `ЖЭС: аудит подтверждает все ${sc.nV}`;
  if (sc.keptV === 0) return `не ЖЭС: все ${sc.nV} метки V отклонены (${topReason(t)})`;
  return `ЖЭС? подтверждено ${sc.keptV} из ${sc.nV}, отклонено ${sc.rejV}`;
};

export const deviceLabels = (labels: Record<string, number>): string =>
  Object.entries(labels)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${k} ${v}`)
    .join(" · ");

/** Спорные первыми, внутри корзины — большие семейства. */
export const inBucket = (scored: Scored[], bucket: Bucket | "all"): Scored[] => {
  const show = scored.filter((s) => bucket === "all" || s.bucket === bucket);
  show.sort((a, b) => BUCKET_ORDER.indexOf(a.bucket) - BUCKET_ORDER.indexOf(b.bucket) || b.t.count - a.t.count);
  return show;
};

export const bucketCounts = (scored: Scored[]): Record<string, number> => {
  const counts: Record<string, number> = { decide: 0, v: 0, s: 0, n: 0 };
  for (const s of scored) counts[s.bucket]++;
  return counts;
};
