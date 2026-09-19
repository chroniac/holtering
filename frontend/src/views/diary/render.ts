import { api } from "../../api/client";
import type { DiaryEvent, Summary } from "../../api/types";
import { clockHM, secOf } from "../../lib/time";
import { el } from "../../ui/dom";

export interface DiaryView {
  root: HTMLElement;
  reload(): Promise<DiaryEvent[]>;
  /** Подставить время (секунды от начала записи), например от курсора на ленте. */
  prefill(sec: number): void;
}

/**
 * Дневник симптомов: расшифровка начинается с него (ISHNE 2017 §4.1). Рядом с записью видно,
 * что делал ритм в ±2 минуты, поэтому связь «симптом — ритм» читается одной строкой.
 */
export const createDiary = (sum: Summary, onJump: (sec: number) => void, onChanged: () => void): DiaryView => {
  const root = el("div", "side-tab diary");
  const startIso = sum.record.start;
  const start = new Date(startIso.replace(" ", "T"));

  const form = el("form", "diary-form");
  const time = el("input", "inp mono") as HTMLInputElement;
  time.type = "text";
  time.placeholder = "чч:мм";
  time.pattern = "([01]?\\d|2[0-3]):[0-5]\\d";
  time.required = true;
  const text = el("input", "inp") as HTMLInputElement;
  text.placeholder = "симптом: сердцебиение, головокружение…";
  text.maxLength = 200;
  const add = el("button", "btn", "добавить");
  add.type = "submit";
  form.append(time, text, add);
  const hint = el(
    "div",
    "muted diary-hint",
    "время по часам пациента; запись с 10:50 идёт через полночь, дата выбирается сама",
  );
  const list = el("div", "eps");
  root.append(form, hint, list);

  const reload = async (): Promise<DiaryEvent[]> => {
    const evs = await api.events();
    list.innerHTML = "";
    if (!evs.length)
      list.append(
        el(
          "div",
          "bp-empty",
          "Записей дневника нет. Введите время симптома, и рядом появится, что делал ритм в эти минуты.",
        ),
      );
    for (const ev of evs) {
      const row = el("div", "ep-row diary-row");
      row.append(el("div", "t", clockHM(startIso, ev.t_ms / 1000)));
      const body = el("div");
      body.append(el("div", "title", ev.text || "симптом"));
      const parts: string[] = [];
      if (ev.hr !== null) parts.push(`ЧСС ${ev.hr} (${ev.hr_min}–${ev.hr_max})`);
      parts.push(ev.v ? `ЖЭС ${ev.v}` : "ЖЭС нет", ev.s ? `НЖЭС ${ev.s}` : "НЖЭС нет");
      if (ev.episodes.length) parts.push(`эпизодов: ${ev.episodes.length}`);
      if (ev.noise >= 0.5) parts.push("помеха");
      const why = el("div", "why mono", `±2 мин: ${parts.join(" · ")}`);
      body.append(why);
      const verdict = el(
        "div",
        "why diary-verdict",
        ev.episodes.length || ev.v || ev.s
          ? "есть с чем сопоставить"
          : ev.hr !== null && (ev.hr_max ?? 0) > 100
            ? "тахикардия без эктопии"
            : "ритм без особенностей",
      );
      body.append(verdict);
      row.append(body);
      const del = el("button", "ibtn diary-del", "×");
      del.title = "удалить";
      del.addEventListener("click", async (e) => {
        e.stopPropagation();
        await api.delEvent(ev.id);
        await reload();
        onChanged();
      });
      row.append(del);
      row.addEventListener("click", () => onJump(ev.t_ms / 1000));
      list.append(row);
    }
    return evs;
  };

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const sec = secOf(start, time.value);
    if (sec === null || sec > sum.record.duration_s) {
      hint.textContent = "это время не попадает в запись";
      return;
    }
    await api.addEvent(Math.round(sec * 1000), text.value);
    text.value = "";
    await reload();
    onChanged();
  });

  return {
    root,
    reload,
    prefill(sec) {
      time.value = clockHM(startIso, sec);
      text.focus();
    },
  };
};
