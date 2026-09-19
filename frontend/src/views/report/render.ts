import { api } from "../../api/client";
import type { EcgWindow, Overview, ReportData, ReportSaved, Summary } from "../../api/types";
import { clock, clockHM } from "../../lib/time";
import { verdictClass } from "../../lib/verdict";
import { el, svg } from "../../ui/dom";
import {
  COVER_SECTIONS,
  captionOf,
  KIND_RU,
  LANE,
  manualStrip,
  mergeSaved,
  PAGE_W,
  type ReportStrip,
  STRIP_W,
  STRIPS_PER_SHEET,
  stripGain,
  visibleStrips,
} from "./model";

/**
 * Печатный протокол, правимый на месте: на экране тот же лист A4, который уйдёт в печать.
 * Правки хранятся на сервере рядом с метками, поэтому принадлежат только этой записи.
 * Состав и порядок разделов — по национальным рекомендациям (РКО/РОХМИНЭ 2013).
 */
export interface ReportView {
  root: HTMLElement;
  open(): Promise<void>;
  /** Добавить фрагмент из текущего окна ленты (вкладка «Лента»). */
  addStrip(t0_s: number, dur_s: number, leads: string[]): Promise<void>;
}

/** При печати лист всегда A4, что бы ни было на экране: предупреждаем, где текст обрежется. */
const A4_PX = (297 * 96) / 25.4;

const editable = (
  tag: "div" | "span",
  cls: string,
  value: string,
  placeholder: string,
  onChange: (v: string) => void,
  onSave: () => void,
): HTMLElement => {
  const e: HTMLElement = tag === "div" ? el("div", `edit ${cls}`) : el("span", `edit ${cls}`);
  e.setAttribute("contenteditable", "plaintext-only");
  e.dataset.placeholder = placeholder;
  e.textContent = value;
  e.classList.toggle("empty", !value);
  e.addEventListener("input", () => {
    const v = e.textContent ?? "";
    e.classList.toggle("empty", !v.trim());
    onChange(v);
    onSave();
  });
  e.addEventListener("keydown", (ev: KeyboardEvent) => {
    if (ev.key === "Escape") e.blur();
    ev.stopPropagation();
  });
  return e;
};

const footer = (data: ReportData, pageNo: number, pages: number): HTMLElement => {
  const f = el("div", "doc-foot");
  f.append(
    el("span", "", `${data.header.patient.name}, ${data.header.start}`),
    el("span", "", `стр. ${pageNo} из ${pages}`),
  );
  return f;
};

const trendSvg = (ov: Overview, sum: Summary): SVGElement => {
  const W = PAGE_W,
    H = 58,
    L = 9,
    R = 2,
    T = 3,
    B = 8;
  const sv = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "doc-trend" });
  sv.style.width = `${W}mm`;
  sv.style.height = `${H}mm`;
  const hr = ov.minute_hr,
    n = hr.length,
    total = sum.record.duration_s;
  const x = (m: number) => L + ((m * 60) / total) * (W - L - R);
  const y0 = 30,
    y1 = 170,
    plotH = H - T - B - 6;
  const y = (v: number) => T + plotH - ((v - y0) / (y1 - y0)) * plotH;
  for (const [a, b] of ov.sleep)
    sv.append(svg("rect", { x: x(a), y: T, width: x(b) - x(a), height: plotH, class: "sleep" }));
  for (let v = y0 + 10; v < y1; v += 20) {
    sv.append(svg("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }));
    const t = svg("text", { x: L - 1, y: y(v) + 1, class: "lbl", "text-anchor": "end" });
    t.textContent = String(v);
    sv.append(t);
  }
  const hours = Math.floor(total / 3600);
  for (let hh = 0; hh <= hours; hh += 2) {
    sv.append(svg("line", { x1: x(hh * 60), x2: x(hh * 60), y1: T, y2: T + plotH, class: "grid" }));
    const t = svg("text", { x: x(hh * 60), y: T + plotH + 3.2, class: "lbl", "text-anchor": "middle" });
    t.textContent = clockHM(sum.record.start, hh * 3600);
    sv.append(t);
  }
  let d = "",
    pen = false;
  for (let m = 0; m < n; m++) {
    const v = hr[m];
    if (v === null) {
      pen = false;
      continue;
    }
    d += (pen ? "L" : "M") + x(m).toFixed(2) + " " + y(Math.max(y0, Math.min(y1, v))).toFixed(2);
    pen = true;
  }
  sv.append(svg("path", { d, class: "hr" }));
  // строки эктопии под графиком: штрих на каждую минуту, где она есть
  const rowV = T + plotH + 4.5,
    rowS = rowV + 2.2;
  ov.minute_v.forEach((c, m) => {
    if (c) sv.append(svg("rect", { x: x(m) - 0.15, y: rowV, width: 0.3, height: 1.8, class: "tv" }));
  });
  ov.minute_s.forEach((c, m) => {
    if (c) sv.append(svg("rect", { x: x(m) - 0.15, y: rowS, width: 0.3, height: 1.8, class: "ts" }));
  });
  const lv = svg("text", { x: L - 1, y: rowV + 1.6, class: "lbl", "text-anchor": "end" });
  lv.textContent = "ЖЭС";
  const ls = svg("text", { x: L - 1, y: rowS + 1.6, class: "lbl", "text-anchor": "end" });
  ls.textContent = "НЖЭС";
  sv.append(lv, ls);
  return sv;
};

const stripSvg = (win: EcgWindow, dur: number, calibrated: boolean): { svg: SVGElement; gain: number } => {
  const nL = win.leads.length,
    H = LANE * nL + 2;
  const sv = svg("svg", { viewBox: `0 0 ${STRIP_W} ${H}`, class: "doc-strip" });
  sv.style.width = `${STRIP_W}mm`;
  sv.style.height = `${H}mm`;
  // сетку рисуем линиями: SVG-паттерны видны на экране, но пропадают в PDF Chromium
  let minor = "",
    major = "";
  for (let x = 0; x <= STRIP_W; x++) {
    if (x % 5) minor += `M${x} 0V${H}`;
    else major += `M${x} 0V${H}`;
  }
  for (let y = 0; y <= H; y++) {
    if (y % 5) minor += `M0 ${y}H${STRIP_W}`;
    else major += `M0 ${y}H${STRIP_W}`;
  }
  sv.append(svg("path", { d: minor, class: "gmin" }), svg("path", { d: major, class: "gmaj" }));
  const mmPerS = STRIP_W / dur;
  // метка мВ — только при калиброванной шкале (--gain): по ошибочной метке будут мерить
  const gain = stripGain(win.data, calibrated);
  win.data.forEach((row, li) => {
    const base = 1 + LANE * li + LANE / 2;
    let d = "";
    for (let i = 0; i < row.length; i++) {
      const yy = base - row[i] * gain;
      d += (i ? "L" : "M") + ((i / win.fs) * mmPerS).toFixed(2) + " " + yy.toFixed(2);
    }
    sv.append(svg("path", { d, class: "trace" }));
    if (calibrated) sv.append(svg("path", { d: `M0.6 ${base} h1.2 v${-gain} h2 v${gain} h1.2`, class: "cal" }));
    const nm = svg("text", { x: calibrated ? 5.6 : 1, y: 1 + LANE * li + 2.6, class: "lead" });
    nm.textContent = win.leads[li];
    sv.append(nm);
  });
  for (const b of win.beats) {
    const cls = verdictClass(b.verdict);
    if (b.label !== "V" && b.label !== "S") continue;
    if (cls !== "likely" && cls !== "uncertain" && cls !== "manual") continue;
    const xx = (b.t_ms / 1000 - win.start) * mmPerS;
    const t = svg("text", { x: xx, y: 2.4, class: `bl ${b.label}`, "text-anchor": "middle" });
    t.textContent = b.label;
    sv.append(t);
  }
  return { svg: sv, gain };
};

export const createReport = (defaultLeads: string[], onJump: (sec: number, dur: number) => void): ReportView => {
  const root = el("div", "report");
  const doc = el("div", "report-doc");
  const sheets = el("div", "sheets");
  doc.append(sheets);
  const side = el("div", "report-side");
  root.append(doc, side);

  let sum: Summary, ov: Overview, data: ReportData;
  let saved: ReportSaved = mergeSaved();
  const leads = defaultLeads;
  let saveTimer: number | null = null;
  const status = el("span", "mono muted");

  // сохранение правок
  const scheduleSave = () => {
    status.textContent = "…";
    if (saveTimer) window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(async () => {
      await api.saveReport(saved);
      status.textContent = "сохранено";
    }, 500);
  };
  const include = (k: string) => saved.include[k] ?? true;

  const metaField = (k: string, placeholder: string) =>
    editable(
      "span",
      "meta",
      saved.meta[k] ?? "",
      placeholder,
      (v) => {
        if (v.trim()) saved.meta[k] = v;
        else delete saved.meta[k];
      },
      scheduleSave,
    );

  const section = (key: string): HTMLElement => {
    const box = el("div", "sec");
    const hh = el("div", "doc-h-row");
    hh.append(el("h3", "doc-h", data.titles[key]));
    const edited = key in saved.text;
    if (edited) {
      const undo = el("button", "btn tiny noprint", "вернуть автотекст");
      undo.addEventListener("click", () => {
        delete saved.text[key];
        scheduleSave();
        void render();
      });
      hh.append(undo);
    }
    box.append(hh);
    const text = saved.text[key] ?? data.generated[key];
    const ed = editable(
      "div",
      `p${edited ? " edited" : ""}`,
      text,
      key === "recommendations" ? "при необходимости" : "",
      (v) => {
        if (v === data.generated[key]) delete saved.text[key];
        else saved.text[key] = v;
      },
      scheduleSave,
    );
    box.append(ed);
    if (key === "recommendations" && !text) box.classList.add("optional");
    ed.addEventListener("input", () =>
      box.classList.toggle("optional", key === "recommendations" && !(ed.textContent ?? "").trim()),
    );
    return box;
  };

  const sheetCover = (): HTMLElement => {
    const s = el("section", "sheet");
    const head = el("div", "doc-head");
    const clinic = el("div", "doc-clinic");
    clinic.append(
      metaField("clinic", "Медицинская организация"),
      el("br"),
      metaField("dept", "Отделение функциональной диагностики"),
    );
    const title = el("div", "doc-title");
    title.innerHTML = `<b>Холтеровское мониторирование ЭКГ</b><br><span>Протокол исследования</span>`;
    head.append(clinic, title);
    s.append(head);

    const h = data.header,
      p = h.patient;
    const pt = el("table", "doc-kv");
    const kv = (k: string, v: string | HTMLElement) => {
      const tr = el("tr");
      const td = el("td");
      if (typeof v === "string") td.textContent = v;
      else {
        td.append(v);
        tr.classList.toggle("optional", v.classList.contains("empty"));
        v.addEventListener("input", () => tr.classList.toggle("optional", v.classList.contains("empty")));
      }
      tr.append(el("th", "", k), td);
      pt.append(tr);
    };
    kv("Пациент", `${p.name}, ${h.sex_ru}, ${h.age_ru}` + (p.dob ? ` (${p.dob.split("-").reverse().join(".")})` : ""));
    kv("Идентификатор", p.id);
    kv("Запись", `${h.start} — ${h.end}, ${h.duration}, комплексов ${h.beats}`);
    kv("Регистратор", `${h.device}; отведения ${h.leads.join(", ")}`);
    kv("Анализ", h.software);
    kv("Направление", metaField("referral", "диагноз, цель исследования"));
    kv("Терапия", metaField("medication", "препараты на момент записи"));
    s.append(pt);

    s.append(el("h3", "doc-h", "Итоговая таблица"));
    const st = el("table", "doc-sum");
    for (const r of data.summary) {
      const tr = el("tr");
      tr.append(el("th", "", r.k), el("td", "v", r.v), el("td", "n", r.n));
      st.append(tr);
    }
    s.append(st);

    for (const key of COVER_SECTIONS) s.append(section(key));
    const sig = el("div", "doc-sign");
    sig.append(
      el("span", "", "Врач: "),
      metaField("doctor", "фамилия, инициалы"),
      el("span", "sigline", ""),
      el("span", "", `Дата: ${new Date().toLocaleDateString("ru")}`),
    );
    s.append(sig);
    return s;
  };

  const sheetDetails = (pageNo: number, pages: number): HTMLElement => {
    const s = el("section", "sheet");
    s.append(el("h3", "doc-h", "Описание результатов"));
    for (const key of data.order) if (!COVER_SECTIONS.includes(key)) s.append(section(key));
    s.append(footer(data, pageNo, pages));
    return s;
  };

  // лист 2: тренды и почасовая таблица
  const sheetTrends = (pageNo: number, pages: number): HTMLElement => {
    const s = el("section", "sheet");
    s.append(
      el("h3", "doc-h", "Тренд ЧСС за сутки"),
      el(
        "div",
        "doc-cap",
        "уд/мин по минутам; серым выделен сон по ЧСС; под графиком минуты с желудочковыми и наджелудочковыми экстрасистолами (после проверки)",
      ),
    );
    s.append(trendSvg(ov, sum));
    s.append(el("h3", "doc-h", "Почасовые показатели"));
    const t = el("table", "doc-hourly");
    const thead = el("thead");
    const hr = el("tr");
    for (const c of [
      "Час",
      "Компл.",
      "ЧСС мин",
      "ЧСС ср",
      "ЧСС макс",
      "ЖЭС",
      "парн.",
      "групп.",
      "НЖЭС",
      "групп.",
      "Паузы",
      "Помеха",
    ])
      hr.append(el("th", "", c));
    thead.append(hr);
    t.append(thead);
    const tb = el("tbody");
    for (const r of data.hourly) {
      const tr = el("tr", r.sleep ? "sleep" : "");
      const cells = [
        r.partial ? `${r.hour} (${r.minutes} мин)` : r.hour,
        String(r.beats),
        r.hr_min ?? "—",
        r.hr_mean ?? "—",
        r.hr_max ?? "—",
        r.v || "·",
        r.pairs || "·",
        r.runs || "·",
        r.s || "·",
        r.s_runs || "·",
        r.pauses || "·",
        r.noise_pct ? `${String(r.noise_pct).replace(".", ",")}%` : "·",
      ];
      cells.forEach((c, i) => {
        tr.append(el("td", i === 0 ? "mono" : "", String(c)));
      });
      tb.append(tr);
    }
    t.append(tb);
    s.append(t);
    s.append(
      el(
        "div",
        "doc-cap",
        "часы по стенным часам; первая и последняя строки неполные; строки сна затенены; «·» означает ноль",
      ),
    );
    s.append(footer(data, pageNo, pages));
    return s;
  };

  // листы 3 и далее: фрагменты ЭКГ
  const stripBlock = (spec: ReportStrip, win: EcgWindow, idx: number): HTMLElement => {
    const box = el("div", "doc-stripbox");
    const cap = el("div", "doc-stripcap");
    const t0 = clock(sum.record.start, spec.t0_ms / 1000);
    const mmPerS = STRIP_W / spec.dur_s;
    cap.append(
      el("span", "mono", `${idx + 1}.`),
      el("span", "mono", t0),
      el("span", "kind", KIND_RU[spec.kind] ?? spec.kind),
    );
    cap.append(
      editable(
        "span",
        "cap",
        captionOf(spec, saved),
        "подпись",
        (v) => {
          if (spec.auto) {
            if (v === spec.caption) delete saved.captions[spec.id];
            else saved.captions[spec.id] = v;
          } else {
            const own = saved.strips.find((x) => x.id === spec.id);
            if (own) own.caption = v;
          }
        },
        scheduleSave,
      ),
    );
    const { svg: sv, gain } = stripSvg(win, spec.dur_s, sum.record.gain_verified);
    const speed = `${mmPerS % 1 ? mmPerS.toFixed(1) : mmPerS} мм/с`;
    cap.append(
      el(
        "span",
        "mono dim right",
        sum.record.gain_verified
          ? `${speed} · ${String(gain).replace(".", ",")} мм/мВ`
          : `${speed} · амплитуда не калибрована`,
      ),
    );
    const tools = el("span", "noprint tools");
    const go = el("button", "btn tiny", "на ленте");
    go.addEventListener("click", () => onJump(spec.t0_ms / 1000, spec.dur_s));
    const drop = el("button", "btn tiny", "убрать");
    drop.addEventListener("click", () => {
      if (spec.auto) saved.hidden.push(spec.id);
      else saved.strips = saved.strips.filter((x) => x.id !== spec.id);
      scheduleSave();
      void render();
    });
    tools.append(go, drop);
    cap.append(tools);
    box.append(cap, sv);
    return box;
  };

  // боковая панель
  const renderSide = (visible: ReportStrip[]) => {
    side.innerHTML = "";
    const acts = el("div", "report-acts");
    const printBtn = el("button", "btn primary", "Печать / PDF");
    printBtn.title = "в диалоге печати выберите принтер или «Сохранить как PDF»";
    printBtn.addEventListener("click", () => printDoc());
    const regen = el("button", "btn", "пересобрать текст");
    regen.title = "заменить все правки текста автотекстом по текущей разметке";
    regen.addEventListener("click", () => {
      saved.text = {};
      scheduleSave();
      void render();
    });
    acts.append(printBtn, regen);
    side.append(acts, status);

    side.append(el("h4", "", "Состав документа"));
    const opt = (k: string, label: string) => {
      const l = el("label", "chk");
      const c = el("input") as HTMLInputElement;
      c.type = "checkbox";
      c.checked = include(k);
      c.addEventListener("change", () => {
        saved.include[k] = c.checked;
        scheduleSave();
        void render();
      });
      l.append(c, el("span", "", label));
      side.append(l);
    };
    opt("trends", "тренд ЧСС и почасовая таблица");
    opt("strips", "фрагменты ЭКГ");

    side.append(el("h4", "", `Фрагменты ЭКГ · ${visible.length}`));
    const list = el("div", "report-strips");
    for (const s of visible) {
      const row = el("div", "rs-row");
      row.append(
        el("span", "mono", clockHM(sum.record.start, s.t0_ms / 1000)),
        el("span", "rs-cap", captionOf(s, saved)),
      );
      row.addEventListener("click", () => {
        const box = sheets.querySelector<HTMLElement>(`[data-strip="${s.id}"]`);
        box?.scrollIntoView({ block: "center" });
        box?.classList.add("flash");
        window.setTimeout(() => box?.classList.remove("flash"), 900);
      });
      list.append(row);
    }
    side.append(list);
    if (saved.hidden.length) {
      const restore = el("button", "btn tiny", `вернуть убранные (${saved.hidden.length})`);
      restore.addEventListener("click", () => {
        saved.hidden = [];
        scheduleSave();
        void render();
      });
      side.append(restore);
    }
    side.append(
      el(
        "div",
        "muted small",
        "На ленте кнопка «в заключение» (клавиша p) добавляет текущее окно с выбранными отведениями.",
      ),
    );
    side.append(
      el(
        "div",
        "muted small",
        sum.record.gain_verified
          ? "Текст правится прямо в документе; правки сохраняются с записью. Масштаб напряжения показан калибровочным импульсом 1 мВ на каждом фрагменте."
          : "Текст правится прямо в документе; правки сохраняются с записью. Масштаб напряжения не калиброван: на фрагментах нет импульса 1 мВ, пока не задан --gain по распечатке CardioSpy.",
      ),
    );
  };

  // отрисовка
  const render = async () => {
    const visible = visibleStrips(data.auto_strips, saved, include("strips"));
    const wins = await Promise.all(visible.map((s) => api.ecg(s.t0_ms / 1000, s.dur_s, s.leads ?? leads)));
    const nStripSheets = Math.ceil(visible.length / STRIPS_PER_SHEET);
    const pages = 2 + (include("trends") ? 1 : 0) + nStripSheets;
    sheets.innerHTML = "";
    const p1 = sheetCover();
    p1.append(footer(data, 1, pages));
    sheets.append(p1);
    sheets.append(sheetDetails(2, pages));
    let pageNo = 3;
    if (include("trends")) sheets.append(sheetTrends(pageNo++, pages));
    for (let i = 0; i < nStripSheets; i++) {
      const s = el("section", "sheet");
      s.append(el("h3", "doc-h", i === 0 ? "Фрагменты ЭКГ" : "Фрагменты ЭКГ (продолжение)"));
      if (i === 0)
        s.append(
          el(
            "div",
            "doc-cap",
            sum.record.gain_verified
              ? "25 мм/с если не указано иное; калибровочный импульс 1 мВ в начале каждого отведения; метки V и S над комплексами после проверки"
              : "25 мм/с если не указано иное; амплитуда подогнана под дорожку, масштаб напряжения не калиброван, по вертикали не измерять; метки V и S над комплексами после проверки",
          ),
        );
      visible.slice(i * STRIPS_PER_SHEET, (i + 1) * STRIPS_PER_SHEET).forEach((spec, j) => {
        const k = i * STRIPS_PER_SHEET + j;
        const box = stripBlock(spec, wins[k], k);
        box.dataset.strip = spec.id;
        s.append(box);
      });
      s.append(footer(data, pageNo++, pages));
      sheets.append(s);
    }
    renderSide(visible);
    fit();
    checkOverflow();
  };

  const checkOverflow = () => {
    for (const sh of sheets.querySelectorAll<HTMLElement>(".sheet")) {
      sh.querySelector(".over-mark")?.remove();
      const over = sh.offsetHeight > A4_PX + 1;
      sh.classList.toggle("over", over);
      if (over) {
        const m = el("div", "over-mark noprint", "граница листа A4: при печати текст ниже уйдёт на следующую страницу");
        sh.append(m);
      }
    }
  };
  sheets.addEventListener("input", () => window.setTimeout(checkOverflow, 50));

  const fit = () => {
    const avail = doc.clientWidth - 32;
    const sheetPx = 210 * (96 / 25.4);
    (sheets.style as CSSStyleDeclaration & { zoom: string }).zoom = String(Math.min(1, avail / sheetPx));
  };
  new ResizeObserver(fit).observe(doc);

  const printDoc = () => {
    const clone = sheets.cloneNode(true) as HTMLElement;
    clone.id = "print-root";
    clone.style.zoom = "1";
    for (const e of clone.querySelectorAll("[contenteditable]")) e.removeAttribute("contenteditable");
    document.body.append(clone);
    document.documentElement.style.setProperty(
      "--doc-foot",
      JSON.stringify(`${data.header.patient.name}, ${data.header.start}`),
    );
    const prev = document.title;
    document.title = `Холтер ${data.header.patient.name} ${data.header.start.slice(0, 10)}`;
    const done = () => {
      clone.remove();
      document.title = prev;
      window.removeEventListener("afterprint", done);
    };
    window.addEventListener("afterprint", done);
    window.print();
  };

  return {
    root,
    async open() {
      [sum, ov, data] = await Promise.all([api.summary(), api.overview(), api.report()]);
      saved = mergeSaved(data.saved);
      await render();
      status.textContent = Object.keys(saved.text).length
        ? `правок текста: ${Object.keys(saved.text).length}`
        : "автотекст";
    },
    async addStrip(t0_s, dur_s, stripLeads) {
      if (!data) {
        [sum, ov, data] = await Promise.all([api.summary(), api.overview(), api.report()]);
        saved = mergeSaved(data.saved);
      }
      const spec = manualStrip(t0_s, dur_s, stripLeads);
      if (!saved.strips.some((s) => s.id === spec.id)) saved.strips.push(spec);
      await api.saveReport(saved);
    },
  };
};
