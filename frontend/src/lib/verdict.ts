export type VerdictClass = "N" | "likely" | "uncertain" | "rejected" | "manual";

export const verdictClass = (v: string): VerdictClass => {
  if (v === "N" || v === "manual-N") return "N";
  if (v === "likely") return "likely";
  if (v === "uncertain") return "uncertain";
  if (v === "manual") return "manual";
  return "rejected";
};

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

export const CLS_COLOR = ["#d9c4c7", "#c8102e", "#b7791f", "#9a8a89", "#6f5fa8"]; // N, likely, uncertain, rejected, manual
