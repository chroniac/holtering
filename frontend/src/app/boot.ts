import { api } from "../api/client";
import { leadSets } from "../lib/leads";
import { zoomAround } from "../lib/nav";
import { el } from "../ui/dom";
import { tabs } from "../ui/tabs";
import { createBeatPanel } from "../views/beatpanel";
import { createDiary } from "../views/diary";
import { createDisclosure } from "../views/disclosure";
import { createEcgView } from "../views/ecg";
import { renderEpisodes } from "../views/episodes";
import { createMinimap, STRIP_MAX, STRIP_MIN } from "../views/minimap";
import { renderOverview } from "../views/overview";
import { createReport } from "../views/report";
import { createTemplates } from "../views/templates";
import { createActions, type Dom, type Views } from "./actions";
import { createKeyHandler } from "./keyboard";
import { createState, DURS, type MainTab, type SideTab } from "./state";
import { statsBlock } from "./stats";

export const boot = async () => {
  const app = document.getElementById("app")!;
  const [sum, ov, episodes] = await Promise.all([api.summary(), api.overview(), api.episodes()]);
  const sets = leadSets(sum.record.leads);
  const state = createState(sum, ov, episodes, [...sets.trio]);

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
    (t) => actions.setMain(t),
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
  rec.innerHTML = `<b>${sum.patient.name}</b> · ${sum.patient.sex} ${sum.patient.age} · ID ${sum.patient.id} · ${state.startIso.slice(0, 16)}`;
  const stats = statsBlock(sum);
  left.append(rec, stats);
  const ovView = renderOverview(
    sum,
    ov,
    episodes,
    (c, live) => actions.setContext(c, live),
    (ep) => actions.gotoEpisode(ep),
  );
  top.append(left, ovView.root);
  app.append(top);
  const applyTop = () => {
    top.hidden = !state.topOpen || state.mainTab === "templates";
    topBtn.classList.toggle("on", state.topOpen);
    localStorage.setItem("holtering.top", state.topOpen ? "1" : "0");
  };
  topBtn.addEventListener("click", () => {
    state.topOpen = !state.topOpen;
    applyTop();
    actions.redraw();
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
    const st = new Date(state.startIso.replace(" ", "T"));
    const d = new Date(st);
    d.setHours(hh, mm, ss || 0, 0);
    let sec = (d.getTime() - st.getTime()) / 1000;
    if (sec < 0) sec += 86400;
    if (sec <= state.total) actions.setStrip({ start: sec - state.strip.dur / 2, dur: state.strip.dur }, false);
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
    await rep.addStrip(state.strip.start, state.strip.dur, state.leads);
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
    b.addEventListener("click", () =>
      actions.setStrip({ start: state.strip.start + state.strip.dur / 2 - d / 2, dur: d }, false),
    );
    durBtns[d] = b;
    durSeg.append(b);
  }
  const gainSeg = el("div", "seg");
  const gainBtns: Record<string, HTMLElement> = {};
  for (const g of ["auto", "5", "10", "20"]) {
    const b = el("button", `btn${g === "auto" ? " on" : ""}`, g === "auto" ? "авто" : g);
    b.title = g === "auto" ? "усиление подбирается под самый высокий комплекс" : `${g} мм/мВ`;
    b.addEventListener("click", () => {
      state.gain = g === "auto" ? "auto" : Number(g);
      for (const [k, x] of Object.entries(gainBtns)) x.classList.toggle("on", k === g);
      actions.redraw();
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
    if (!state.leads.length) state.leads = [state.sum.record.leads[0]]; // набор, не совпавший ни с одним отведением, не должен обнулить ленту
    for (const [k, x] of Object.entries(leadBtns)) x.classList.toggle("on", state.leads.includes(k));
    void actions.load();
  };
  for (const [name, set] of PRESETS) {
    const b = el("button", "btn", name);
    b.title = set.join(", ");
    b.addEventListener("click", () => {
      state.leads = state.sum.record.leads.filter((x) => set.includes(x));
      syncLeads();
    });
    presetSeg.append(b);
  }
  for (const name of sum.record.leads) {
    const b = el("button", `btn${state.leads.includes(name) ? " on" : ""}`, name);
    b.addEventListener("click", () => {
      if (state.leads.includes(name)) {
        if (state.leads.length === 1) return;
        state.leads = state.leads.filter((x) => x !== name);
      } else state.leads = state.sum.record.leads.filter((x) => state.leads.includes(x) || x === name);
      syncLeads();
    });
    leadBtns[name] = b;
    leadBox.append(b);
  }
  const gLeads = group("Отведения", [leadBox], presetSeg);
  bar.append(gTime, gWin, gLeads);
  const ecg = createEcgView({
    onBeat: (b) => actions.selectBeat(b, true),
    onZoom: (at, f) => actions.setStrip(zoomAround(state.strip, at, f, STRIP_MIN, STRIP_MAX), false),
    onPan: (d, live) => actions.setStrip({ start: state.strip.start + d, dur: state.strip.dur }, live),
    onCursor: (sec) => actions.setCursor(sec),
    onRange: (t0, t1) => actions.setRange({ t0, t1 }),
  });
  const mini = createMinimap(state.startIso, state.total, (r, live) => actions.setStrip(r, live));
  stripPane.append(bar, ecg.root, mini.root);

  const fd = createDisclosure(state.startIso, state.total, sum.record.leads, (sec) => {
    actions.setMain("strip");
    actions.setStrip({ start: sec - state.strip.dur / 2, dur: state.strip.dur }, false);
  });
  fd.root.classList.add("pane");
  fd.root.hidden = true;
  const tpl = createTemplates(
    state.startIso,
    sum.record.leads,
    (idx) => {
      actions.setMain("strip");
      void actions.gotoBeat(idx);
    },
    () => actions.refreshAll(),
  );
  tpl.root.classList.add("pane");
  tpl.root.hidden = true;
  const rep = createReport(sets.trio, (sec, dur) => {
    actions.setMain("strip");
    actions.setStrip({ start: sec, dur }, false);
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
    (t) => actions.setSide(t),
  );
  const epView = renderEpisodes(sum, episodes, (ep) => actions.gotoEpisode(ep));
  const diary = createDiary(
    sum,
    (sec) => {
      actions.setMain("strip");
      actions.setStrip({ start: sec - state.strip.dur / 2, dur: state.strip.dur }, false);
    },
    () => {
      void actions.refreshEvents();
    },
  );
  diary.root.hidden = true;
  const beatPanel = createBeatPanel(
    {
      onLabel: (l) => void actions.label(l),
      onAdd: (l) => void actions.addBeat(l),
      onFamily: (t) => {
        actions.setMain("templates");
        void tpl.open(t);
      },
      onQuality: (v) => void actions.quality(v),
      onJump: (idx) => void actions.gotoBeat(idx),
      onStep: (dir) => actions.stepBeat(dir),
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
  const views: Views = { ov: ovView, ecg, mini, fd, tpl, rep, diary, beatPanel, eps: epView };
  const dom: Dom = { stats, stripPane, keys, timeIn, time, durBtns, mainTabs, sideTabs, applyTop, addToReport };
  const actions = createActions(state, views, dom);

  prev.addEventListener("click", () =>
    actions.setStrip({ start: state.strip.start - state.strip.dur, dur: state.strip.dur }, false),
  );
  next.addEventListener("click", () =>
    actions.setStrip({ start: state.strip.start + state.strip.dur, dur: state.strip.dur }, false),
  );
  prevEp.addEventListener("click", () => actions.stepEpisode(-1));
  nextEp.addEventListener("click", () => actions.stepEpisode(1));
  window.addEventListener("keydown", createKeyHandler(state, views, actions, dom));
  new ResizeObserver(() => actions.redraw()).observe(ecg.root);

  void actions.refreshEvents();
  const hash = new URLSearchParams(location.hash.slice(1));
  const first = episodes.find((e) => e.verdict !== "artifact") ?? episodes[0];
  if (hash.has("t")) actions.setStrip({ start: Number(hash.get("t")), dur: Number(hash.get("d") ?? 10) }, false);
  else if (first) actions.gotoEpisode(first);
  else void actions.load();
};
