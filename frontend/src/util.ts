export const SVG_NS = "http://www.w3.org/2000/svg";

export function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

export function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number> = {}): SVGElementTagNameMap[K] {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  return e;
}

export function clock(startIso: string, offsetS: number): string {
  const d = new Date(startIso.replace(" ", "T"));
  d.setMilliseconds(d.getMilliseconds() + offsetS * 1000);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export function hms(s: number): string {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

export type VerdictClass = "N" | "likely" | "uncertain" | "rejected" | "manual";

export function verdictClass(v: string): VerdictClass {
  if (v === "N" || v === "manual-N") return "N";
  if (v === "likely") return "likely";
  if (v === "uncertain") return "uncertain";
  if (v === "manual") return "manual";
  return "rejected";
}

export const VERDICT_RU: Record<string, string> = {
  likely: "вероятная",
  uncertain: "спорная",
  "double-count": "двойной счёт",
  "on-wave": "метка не на QRS",
  noisy: "в помехе",
  narrow: "узкий QRS",
  "not-premature": "не преждевременная",
  "sinus-shape": "синусовая морфология",
  manual: "ручная",
  "manual-N": "ручная: N",
  "manual-X": "ручная: артефакт",
  N: "N",
};

export const LABEL_RU: Record<string, string> = { N: "N", V: "V, ЖЭС", S: "S, НЖЭС", X: "артефакт" };
