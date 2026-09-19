export const clock = (startIso: string, offsetS: number): string => {
  const d = new Date(startIso.replace(" ", "T"));
  d.setMilliseconds(d.getMilliseconds() + offsetS * 1000);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
};

/** Часы и минуты без секунд: подписи осей и чипы, где секунда только мешает читать. */
export const clockHM = (startIso: string, offsetS: number): string => clock(startIso, offsetS).slice(0, 5);

export const hms = (s: number): string => {
  const h = Math.floor(s / 3600),
    m = Math.floor((s % 3600) / 60),
    sec = Math.floor(s % 60);
  return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
};

/** Время по часам пациента (HH:MM) в секунды от начала записи; после полуночи — следующие сутки. */
export const secOf = (start: Date, hhmm: string): number | null => {
  const [h, m] = hhmm.split(":").map(Number);
  if (Number.isNaN(h)) return null;
  const d = new Date(start);
  d.setHours(h, m, 0, 0);
  let sec = (d.getTime() - start.getTime()) / 1000;
  if (sec < 0) sec += 86400; // время после полуночи относится к следующим суткам
  return sec >= 0 ? sec : null;
};
