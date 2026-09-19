// Шрифты локальные: закрытый контур больницы не должен обращаться к fonts.googleapis.com
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import { api, type Beat, type EcgWindow, type Episode, type ManualLabel, type Summary } from "./api";
import { createBeatPanel } from "./beatpanel";
import { createDiary } from "./diary";
import { createDisclosure } from "./disclosure";
import { createEcgView } from "./ecg";
import { renderEpisodes } from "./episodes";
import { createMinimap, STRIP_MAX, STRIP_MIN } from "./minimap";
import { clampRange, type Range, zoomAround } from "./nav";
import { CTX_MAX, CTX_MIN, renderOverview } from "./overview";
import { createReport } from "./report";
import { createTemplates } from "./templates";
import { clock, el } from "./util";

/** Каналы 0-5 — от конечностей (тождества Эйнтховена в scp_holter.leads), дальше грудные. */
const LIMB_COUNT = 6;
function leadSets(all: string[]) {
  const limb = all.slice(0, LIMB_COUNT),
    chest = all.slice(LIMB_COUNT);
  // трио по умолчанию: II и два грудных канала, ближайших к позициям V2/V5
  const trio = [limb[1] ?? all[0], chest[4] ?? chest[chest.length - 1], chest[1] ?? chest[0]].filter(
    (x, i, arr) => x && arr.indexOf(x) === i,
  );
  return { limb, chest, trio, all };
}
const DURS = [5, 10, 20, 30, 60];
type MainTab = "strip" | "disclosure" | "templates" | "report";
type SideTab = "episodes" | "beat" | "diary";

/** Четыре карточки слева от обзора: крупное число с пометкой и строки «ключ — значение». */
function statsBlock(sum: Summary): HTMLElement {
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
  const segbar = (parts: [string, number][]) => {
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
  const t = (sec: number) => clock(r.start, sec).slice(0, 5);
  const nm = sum.morphologies.length;

  card("ЧСС, уд/мин", `${h.mean}`, `сон ${h.sleep ?? "—"} · день ${h.wake ?? "—"}`, [
    ["минимум", `${h.min} · ${t(h.min_at_s)}`],
    ["максимум", `${h.max} · ${t(h.max_at_s)}`],
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
}

function tabs<T extends string>(
  items: [T, string][],
  initial: T,
  onPick: (t: T) => void,
): { root: HTMLElement; set(t: T): void; label(t: T, s: string): void } {
  const root = el("div", "tabs");
  const btns: Record<string, HTMLElement> = {};
  for (const [id, label] of items) {
    const b = el("button", `tab${id === initial ? " on" : ""}`, label);
    b.addEventListener("click", () => onPick(id));
    btns[id] = b;
    root.append(b);
  }
  return {
    root,
    set(t) {
      for (const [k, b] of Object.entries(btns)) b.classList.toggle("on", k === t);
    },
    label(t, s) {
      btns[t].textContent = s;
    },
  };
}

async function boot() {
  const app = document.getElementById("app")!;
  let [sum, ov, episodes] = await Promise.all([api.summary(), api.overview(), api.episodes()]);
  const total = sum.record.duration_s;
  const startIso = sum.record.start;

  // состояние навигации: контекст (обзор → миникарта) и лента (миникарта → ЭКГ)
  let ctx: Range = { start: 0, dur: 600 };
  let strip: Range = { start: 0, dur: 10 };
  const sets = leadSets(sum.record.leads);
  let leads = [...sets.trio];
  let gain: number | "auto" = "auto";
  let activeEp: number | null = null;
  let activeBeat: Beat | null = null;
  let cursorSec: number | null = null;
  let range: { t0: number; t1: number } | null = null;
  let mainTab: MainTab = "strip",
    sideTab: SideTab = "episodes";

  // шапка: логотип | табы | легенда, свод, помощь
  const hdr = el("header", "hdr");
  const brand = el("div", "brand");
  brand.append(el("span", "logo", "holtering"));
  const mainTabs = tabs<MainTab>(
    [
      ["strip", "Лента"],
      ["disclosure", "Раскрытие"],
      ["templates", "Шаблоны"],
      ["report", "Заключение"],
    ],
    "strip",
    (t) => setMain(t),
  );
  const right = el("div", "hdr-right");
  const legend = el("div", "legend hdr-legend");
  legend.innerHTML = `<span><i class="sw likely"></i>вероятная</span><span><i class="sw uncertain"></i>спорная</span><span><i class="sw rejected"></i>отклонена</span><span><i class="sw manual"></i>ручная</span>`;
  const topBtn = el("button", "ibtn", "сводка");
  topBtn.title = "показать / скрыть сводку";
  const help = el("button", "ibtn", "?");
  help.title = "клавиши";
  right.append(legend, topBtn, help);
  hdr.append(brand, mainTabs.root, right);
  app.append(hdr);

  // верх: строка записи, карточки и обзор
  const top = el("div", "top");
  const left = el("div", "top-left");
  const rec = el("div", "recline mono");
  rec.innerHTML = `<b>${sum.patient.name}</b> · ${sum.patient.sex} ${sum.patient.age} · ID ${sum.patient.id} · ${startIso.slice(0, 16)}`;
  let stats = statsBlock(sum);
  left.append(rec, stats);
  const ovView = renderOverview(
    sum,
    ov,
    episodes,
    (c, live) => setContext(c, live),
    (ep) => gotoEpisode(ep),
  );
  top.append(left, ovView.root);
  app.append(top);
  let topOpen = localStorage.getItem("holtering.top") !== "0";
  const applyTop = () => {
    top.hidden = !topOpen || mainTab === "templates";
    topBtn.classList.toggle("on", topOpen);
    localStorage.setItem("holtering.top", topOpen ? "1" : "0");
  };
  topBtn.addEventListener("click", () => {
    topOpen = !topOpen;
    applyTop();
    redraw();
  });

  // основная область
  const main = el("div", "main");
  const area = el("div", "area");
  const stripPane = el("div", "pane strip");
  // панель: Время (где я, шаг) | Окно (сколько, какой масштаб) | Отведения (что)
  const bar = el("div", "ecg-bar");
  const group = (label: string, items: HTMLElement[], labelRowExtra?: HTMLElement) => {
    const g = el("div", "tb-group");
    const lr = el("div", "tb-labelrow");
    lr.append(el("div", "tb-label", label));
    if (labelRowExtra) lr.append(labelRowExtra);
    g.append(lr);
    const row = el("div", "tb-row");
    row.append(...items);
    g.append(row);
    return g;
  };
  // время: редактируемые часы (Enter — переход), длительность рядом, кнопки шага
  const timeIn = el("input", "tb-time mono") as HTMLInputElement;
  timeIn.title = "перейти ко времени: чч:мм[:сс], Enter";
  timeIn.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const [hh, mm, ss] = timeIn.value.split(":").map(Number);
    if (Number.isNaN(hh) || Number.isNaN(mm)) return;
    const st = new Date(startIso.replace(" ", "T"));
    const d = new Date(st);
    d.setHours(hh, mm, ss || 0, 0);
    let sec = (d.getTime() - st.getTime()) / 1000;
    if (sec < 0) sec += 86400;
    if (sec <= total) setStrip({ start: sec - strip.dur / 2, dur: strip.dur }, false);
    timeIn.blur();
  });
  timeIn.addEventListener("focus", () => timeIn.select());
  const time = el("span", "tb-dur mono");
  const prev = el("button", "btn", "‹"),
    next = el("button", "btn", "›");
  prev.title = "окно назад  ←";
  next.title = "окно вперёд  →";
  const stepSeg = el("div", "seg");
  stepSeg.append(prev, next);
  const prevEp = el("button", "btn", "‹ эпизод"),
    nextEp = el("button", "btn", "эпизод ›");
  prevEp.title = "предыдущий эпизод  [";
  nextEp.title = "следующий эпизод  ]";
  const epSeg = el("div", "seg");
  epSeg.append(prevEp, nextEp);
  const toRep = el("button", "btn tiny", "в заключение");
  toRep.title = "добавить это окно в фрагменты ЭКГ протокола  p";
  const addToReport = async () => {
    await rep.addStrip(strip.start, strip.dur, leads);
    toRep.textContent = "добавлено";
    toRep.classList.add("on");
    window.setTimeout(() => {
      toRep.textContent = "в заключение";
      toRep.classList.remove("on");
    }, 1200);
  };
  toRep.addEventListener("click", () => void addToReport());
  const gTime = group("Время", [timeIn, time, stepSeg, epSeg], toRep);

  // окно: длительность и усиление, каждое своим подписанным сегментом
  const durSeg = el("div", "seg");
  const durBtns: Record<number, HTMLElement> = {};
  for (const d of DURS) {
    const b = el("button", "btn", `${d}`);
    b.title = `${d} секунд в окне`;
    b.addEventListener("click", () => setStrip({ start: strip.start + strip.dur / 2 - d / 2, dur: d }, false));
    durBtns[d] = b;
    durSeg.append(b);
  }
  const gainSeg = el("div", "seg");
  const gainBtns: Record<string, HTMLElement> = {};
  for (const g of ["auto", "5", "10", "20"]) {
    const b = el("button", `btn${g === "auto" ? " on" : ""}`, g === "auto" ? "авто" : g);
    b.title = g === "auto" ? "усиление подбирается под самый высокий комплекс" : `${g} мм/мВ`;
    b.addEventListener("click", () => {
      gain = g === "auto" ? "auto" : Number(g);
      for (const [k, x] of Object.entries(gainBtns)) x.classList.toggle("on", k === g);
      redraw();
    });
    gainBtns[g] = b;
    gainSeg.append(b);
  }
  const gWin = group("Окно", [el("span", "tb-sub", "секунд"), durSeg, el("span", "tb-sub", "мм/мВ"), gainSeg]);

  // отведения: сначала наборы, затем отдельные переключатели
  const PRESETS: [string, string[]][] = [
    ["3", sets.trio],
    ["конечн.", sets.limb],
    ["грудные", sets.chest],
    ["все", sets.all],
  ];
  const presetSeg = el("div", "seg");
  const leadBox = el("div", "leads");
  const leadBtns: Record<string, HTMLElement> = {};
  const syncLeads = () => {
    if (!leads.length) leads = [sum.record.leads[0]]; // набор, не совпавший ни с одним отведением, не должен обнулить ленту
    for (const [k, x] of Object.entries(leadBtns)) x.classList.toggle("on", leads.includes(k));
    void load();
  };
  for (const [name, set] of PRESETS) {
    const b = el("button", "btn", name);
    b.title = set.join(", ");
    b.addEventListener("click", () => {
      leads = sum.record.leads.filter((x) => set.includes(x));
      syncLeads();
    });
    presetSeg.append(b);
  }
  for (const name of sum.record.leads) {
    const b = el("button", `btn${leads.includes(name) ? " on" : ""}`, name);
    b.addEventListener("click", () => {
      if (leads.includes(name)) {
        if (leads.length === 1) return;
        leads = leads.filter((x) => x !== name);
      } else leads = sum.record.leads.filter((x) => leads.includes(x) || x === name);
      syncLeads();
    });
    leadBtns[name] = b;
    leadBox.append(b);
  }
  const gLeads = group("Отведения", [leadBox], presetSeg);
  bar.append(gTime, gWin, gLeads);
  const ecg = createEcgView({
    onBeat: (b) => selectBeat(b, true),
    onZoom: (at, f) => setStrip(zoomAround(strip, at, f, STRIP_MIN, STRIP_MAX), false),
    onPan: (d, live) => setStrip({ start: strip.start + d, dur: strip.dur }, live),
    onCursor: (sec) => setCursor(sec),
    onRange: (t0, t1) => setRange({ t0, t1 }),
  });
  const mini = createMinimap(startIso, total, (r, live) => setStrip(r, live));
  stripPane.append(bar, ecg.root, mini.root);

  const fd = createDisclosure(startIso, total, sum.record.leads, (sec) => {
    setMain("strip");
    setStrip({ start: sec - strip.dur / 2, dur: strip.dur }, false);
  });
  fd.root.classList.add("pane");
  fd.root.hidden = true;
  const tpl = createTemplates(
    startIso,
    sum.record.leads,
    (idx) => {
      setMain("strip");
      void gotoBeat(idx);
    },
    () => refreshAll(),
  );
  tpl.root.classList.add("pane");
  tpl.root.hidden = true;
  const rep = createReport(sets.trio, (sec, dur) => {
    setMain("strip");
    setStrip({ start: sec, dur }, false);
  });
  rep.root.classList.add("pane");
  rep.root.hidden = true;
  area.append(stripPane, fd.root, tpl.root, rep.root);

  // боковая панель
  const side = el("aside", "side");
  const sideTabs = tabs<SideTab>(
    [
      ["episodes", `Эпизоды · ${episodes.length}`],
      ["diary", "Симптомы"],
      ["beat", "Комплекс"],
    ],
    "episodes",
    (t) => setSide(t),
  );
  let epView = renderEpisodes(sum, episodes, (ep) => gotoEpisode(ep));
  const diary = createDiary(
    sum,
    (sec) => {
      setMain("strip");
      setStrip({ start: sec - strip.dur / 2, dur: strip.dur }, false);
    },
    () => {
      void refreshEvents();
    },
  );
  diary.root.hidden = true;
  const beatPanel = createBeatPanel(
    {
      onLabel: (l) => void label(l),
      onAdd: (l) => void addBeat(l),
      onFamily: (t) => {
        setMain("templates");
        void tpl.open(t);
      },
      onQuality: (v) => void quality(v),
      onJump: (idx) => void gotoBeat(idx),
      onStep: (dir) => stepBeat(dir),
    },
    sets.trio,
  );
  beatPanel.root.hidden = true;
  side.append(sideTabs.root, epView.root, diary.root, beatPanel.root);
  main.append(area, side);
  app.append(main);

  const keys = el("div", "keys");
  keys.hidden = true;
  keys.innerHTML =
    `<b>Навигация</b> shift+колесо: влево/вправо · ctrl+колесо: масштаб · тянуть ленту: сдвиг · ← →: окно, с shift ×6 · − +: масштаб<br>` +
    `<b>Обход</b> [ ]: эпизоды · Tab: подозрительные комплексы · 1 2 3 4: вкладки · p: окно в заключение · Esc<br>` +
    `<b>Разметка</b> n v s x: метка · ⌫: снять / удалить · клик по ленте, затем a: добавить комплекс<br>` +
    `<b>Качество</b> shift+тянуть по ленте: диапазон · c: чисто · x: помеха · ⌫: сброс`;
  app.append(keys);
  help.addEventListener("click", () => {
    keys.hidden = !keys.hidden;
  });

  // поведение
  function setMain(t: MainTab) {
    mainTab = t;
    mainTabs.set(t);
    stripPane.hidden = t !== "strip";
    fd.root.hidden = t !== "disclosure";
    tpl.root.hidden = t !== "templates";
    rep.root.hidden = t !== "report";
    applyTop(); // на вкладке шаблонов суточная шкала не нужна — applyTop её скроет
    if (t === "report") void rep.open();
    if (t === "disclosure") void fd.show(strip.start, leads[0], strip);
    if (t === "templates") void tpl.open();
    if (t === "strip") redraw();
  }
  function setSide(t: SideTab) {
    sideTab = t;
    sideTabs.set(t);
    epView.root.hidden = t !== "episodes";
    beatPanel.root.hidden = t !== "beat";
    diary.root.hidden = t !== "diary";
    if (t === "diary" && cursorSec !== null) diary.prefill(cursorSec);
  }
  let eventTimes: number[] = [];
  async function refreshEvents() {
    const evs = await diary.reload();
    eventTimes = evs.map((e) => e.t_ms / 1000);
    ovView.setEvents(eventTimes);
    mini.setEvents(eventTimes);
    ecg.setEvents(eventTimes);
    sideTabs.label("diary", evs.length ? `Симптомы · ${evs.length}` : "Симптомы");
    redraw();
  }

  let last: EcgWindow | null = null;
  let reqId = 0,
    liveTimer: number | null = null;
  function paint() {
    if (document.activeElement !== timeIn) timeIn.value = clock(startIso, strip.start);
    time.textContent = `+${strip.dur % 1 ? strip.dur.toFixed(1) : strip.dur} с`;
    ovView.setContext(ctx, strip);
    for (const [k, x] of Object.entries(durBtns)) x.classList.toggle("on", Number(k) === strip.dur);
    void mini.set(ctx, strip);
  }
  async function load() {
    const id = ++reqId;
    paint();
    const win = await api.ecg(strip.start, strip.dur, leads);
    if (id !== reqId) return;
    last = win;
    history.replaceState(null, "", `#t=${strip.start.toFixed(1)}&d=${strip.dur}`);
    ecg.render(win, startIso, gain);
    ecg.setCursor(cursorSec);
    ecg.setRange(range);
    if (activeBeat) {
      const fresh = win.beats.find((b) => b.index === activeBeat!.index);
      if (fresh) selectBeat(fresh, false);
      else ecg.highlight(activeBeat.index);
    }
  }
  function redraw() {
    if (last && mainTab === "strip") {
      ecg.render(last, startIso, gain);
      ecg.setCursor(cursorSec);
      ecg.setRange(range);
      ecg.highlight(activeBeat?.index ?? null);
    }
  }
  /** Лента сдвинулась: держим её внутри контекста, контекст листается за ней. */
  function setStrip(r: Range, live: boolean) {
    strip = clampRange(
      { start: r.start, dur: Math.round(Math.max(STRIP_MIN, Math.min(STRIP_MAX, r.dur)) * 10) / 10 },
      total,
    );
    if (strip.start < ctx.start || strip.start + strip.dur > ctx.start + ctx.dur) {
      ctx = clampRange(
        { start: strip.start + strip.dur / 2 - ctx.dur / 2, dur: Math.max(ctx.dur, strip.dur * 3) },
        total,
      );
    }
    paint();
    if (liveTimer) window.clearTimeout(liveTimer);
    if (live) liveTimer = window.setTimeout(() => void load(), 120);
    else void load();
  }
  /** Контекст сменился на обзоре: лента переезжает в его центр, если выпала из него. */
  function setContext(c: Range, live: boolean) {
    ctx = clampRange({ start: c.start, dur: Math.max(CTX_MIN, Math.min(CTX_MAX, c.dur)) }, total);
    if (strip.start < ctx.start || strip.start + strip.dur > ctx.start + ctx.dur) {
      strip = clampRange({ start: ctx.start + ctx.dur / 2 - strip.dur / 2, dur: strip.dur }, total);
      if (liveTimer) window.clearTimeout(liveTimer);
      if (live) {
        paint();
        liveTimer = window.setTimeout(() => void load(), 150);
      } else void load();
    } else paint();
  }
  function gotoEpisode(ep: Episode) {
    setMain("strip");
    activeEp = ep.id;
    const epDur = ep.dur_ms / 1000;
    const dur = epDur + 4 > strip.dur ? Math.min(STRIP_MAX, DURS.find((d) => d >= epDur + 4) ?? epDur + 4) : strip.dur;
    activeBeat = null;
    setCursor(null);
    ovView.setActiveEpisode(ep.id);
    epView.setActive(ep.id);
    setStrip({ start: ep.t_ms / 1000 - (dur - epDur) / 2, dur }, false);
    window.setTimeout(() => {
      const b = last?.beats.find((x) => x.index === ep.beats[0]);
      if (b) selectBeat(b, false);
    }, 200);
  }
  async function gotoBeat(idx: number) {
    const b = await api.beat(idx);
    activeEp = null;
    ovView.setActiveEpisode(null);
    epView.setActive(null);
    activeBeat = b;
    setCursor(null);
    setStrip({ start: b.t_ms / 1000 - strip.dur / 2, dur: strip.dur }, false);
    setSide("beat");
  }
  function selectBeat(b: Beat, focusPanel: boolean) {
    activeBeat = b;
    cursorSec = null;
    ecg.setCursor(null);
    range = null;
    ecg.setRange(null);
    ecg.highlight(b.index);
    beatPanel.showBeat(b, startIso);
    if (focusPanel) setSide("beat");
  }
  function setRange(r: { t0: number; t1: number } | null) {
    range = r;
    ecg.setRange(r);
    if (r) {
      activeBeat = null;
      cursorSec = null;
      ecg.highlight(null);
      ecg.setCursor(null);
      setSide("beat");
    }
    beatPanel.showRange(r, startIso);
  }
  async function quality(v: "clean" | "noise" | null) {
    if (!range) return;
    await api.quality(Math.round(range.t0 * 1000), Math.round(range.t1 * 1000), v);
    await refreshAll();
  }
  function setCursor(sec: number | null) {
    cursorSec = sec;
    if (sec !== null && range) {
      range = null;
      ecg.setRange(null);
    }
    if (sec !== null) {
      activeBeat = null;
      ecg.highlight(null);
      beatPanel.showBeat(null, startIso);
      setSide("beat");
    }
    ecg.setCursor(sec);
    beatPanel.showCursor(sec, startIso);
  }
  async function label(l: ManualLabel | null) {
    if (!activeBeat) return;
    const wasAdded = activeBeat.added;
    const r = await api.annotate(activeBeat.index, l);
    activeBeat = wasAdded && l === null ? null : r;
    await refreshAll();
    if (!activeBeat) beatPanel.showBeat(null, startIso);
  }
  async function addBeat(l: ManualLabel) {
    if (cursorSec === null) return;
    try {
      const b = await api.addBeat(Math.round(cursorSec * 1000), l);
      cursorSec = null;
      ecg.setCursor(null);
      activeBeat = b;
      await refreshAll();
    } catch (e) {
      const msg = String(e).includes("400") ? "ближе 120 мс уже есть комплекс" : String(e);
      beatPanel.showError(msg);
    }
  }
  async function refreshAll() {
    [sum, ov, episodes] = await Promise.all([api.summary(), api.overview(), api.episodes()]);
    const ns = statsBlock(sum);
    stats.replaceWith(ns);
    stats = ns;
    ovView.update(ov, episodes);
    ovView.setContext(ctx, strip);
    ovView.setActiveEpisode(activeEp);
    sideTabs.label("episodes", `Эпизоды · ${episodes.length}`);
    const nv = renderEpisodes(sum, episodes, (ep) => gotoEpisode(ep));
    epView.root.replaceWith(nv.root);
    epView = nv;
    epView.root.hidden = sideTab !== "episodes";
    epView.setActive(activeEp);
    await Promise.all([mini.refresh(), fd.refresh(), load()]);
  }
  function stepEpisode(dir: 1 | -1) {
    if (!episodes.length) return;
    let i = activeEp === null ? -1 : episodes.findIndex((e) => e.id === activeEp);
    if (i === -1) {
      i =
        dir > 0
          ? episodes.findIndex((e) => e.t_ms / 1000 > strip.start + strip.dur)
          : episodes.map((e) => e.t_ms / 1000 < strip.start).lastIndexOf(true);
      if (i === -1) return;
    } else i = (i + dir + episodes.length) % episodes.length;
    gotoEpisode(episodes[i]);
  }
  function stepBeat(dir: 1 | -1) {
    if (!last) return;
    const marked = last.beats.filter((b) => b.verdict !== "N" && b.verdict !== "manual-N");
    if (!marked.length) return;
    const i = activeBeat ? marked.findIndex((b) => b.index === activeBeat!.index) : -1;
    selectBeat(marked[(i + dir + marked.length) % marked.length], true);
  }
  prev.addEventListener("click", () => setStrip({ start: strip.start - strip.dur, dur: strip.dur }, false));
  next.addEventListener("click", () => setStrip({ start: strip.start + strip.dur, dur: strip.dur }, false));
  prevEp.addEventListener("click", () => stepEpisode(-1));
  nextEp.addEventListener("click", () => stepEpisode(1));
  window.addEventListener("keydown", (e) => {
    const tag = (e.target as HTMLElement).tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || (e.target as HTMLElement).isContentEditable)
      return;
    const k = e.key.toLowerCase();
    if (e.key === "Escape") {
      activeBeat = null;
      ecg.highlight(null);
      setCursor(null);
      setRange(null);
      beatPanel.showBeat(null, startIso);
    } else if (k === "1") setMain("strip");
    else if (k === "2") setMain("disclosure");
    else if (k === "3") setMain("templates");
    else if (k === "4") setMain("report");
    else if (k === "?") keys.hidden = !keys.hidden;
    else if (mainTab !== "strip") return;
    else if (e.key === "ArrowLeft")
      setStrip({ start: strip.start - (e.shiftKey ? strip.dur * 6 : strip.dur), dur: strip.dur }, false);
    else if (e.key === "ArrowRight")
      setStrip({ start: strip.start + (e.shiftKey ? strip.dur * 6 : strip.dur), dur: strip.dur }, false);
    else if (e.key === "[") stepEpisode(-1);
    else if (e.key === "]") stepEpisode(1);
    else if (e.key === "Tab") stepBeat(e.shiftKey ? -1 : 1);
    else if (e.key === "-") setStrip(zoomAround(strip, strip.start + strip.dur / 2, 1.5, STRIP_MIN, STRIP_MAX), false);
    else if (e.key === "+" || e.key === "=")
      setStrip(zoomAround(strip, strip.start + strip.dur / 2, 1 / 1.5, STRIP_MIN, STRIP_MAX), false);
    else if (k === "a" && cursorSec !== null) void addBeat("N");
    else if (k === "p") void addToReport();
    else if (range && k === "c") void quality("clean");
    else if (range && k === "x") void quality("noise");
    else if (range && e.key === "Backspace") void quality(null);
    else if (k === "n" || k === "v" || k === "s" || k === "x") void label(k.toUpperCase() as ManualLabel);
    else if (e.key === "Backspace") void label(null);
    else return;
    e.preventDefault();
  });
  new ResizeObserver(() => redraw()).observe(ecg.root);

  void refreshEvents();
  const hash = new URLSearchParams(location.hash.slice(1));
  const first = episodes.find((e) => e.verdict !== "artifact") ?? episodes[0];
  if (hash.has("t")) setStrip({ start: Number(hash.get("t")), dur: Number(hash.get("d") ?? 10) }, false);
  else if (first) gotoEpisode(first);
  else void load();
}

boot().catch((e) => {
  document.getElementById("app")!.innerHTML = `<pre style="padding:20px;color:#c8102e">${String(e)}</pre>`;
});
