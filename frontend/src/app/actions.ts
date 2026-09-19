import { api } from "../api/client";
import type { Beat, Episode, ManualLabel } from "../api/types";
import type { Range } from "../lib/nav";
import { clock } from "../lib/time";
import type { BeatPanel } from "../views/beatpanel";
import type { DiaryView } from "../views/diary";
import type { DisclosureView } from "../views/disclosure";
import type { EcgView } from "../views/ecg";
import { type EpisodesView, renderEpisodes } from "../views/episodes";
import type { MinimapView } from "../views/minimap";
import type { OverviewView } from "../views/overview";
import type { ReportView } from "../views/report";
import type { TemplatesView } from "../views/templates";
import {
  type AppState,
  contextInto,
  episodeDur,
  type MainTab,
  type SideTab,
  type Span,
  stepBeatTarget,
  stepEpisodeIndex,
  stripInto,
} from "./state";
import { statsBlock } from "./stats";

/** Созданные представления; `eps` пересоздаётся после каждой правки разметки. */
export interface Views {
  ov: OverviewView;
  ecg: EcgView;
  mini: MinimapView;
  fd: DisclosureView;
  tpl: TemplatesView;
  rep: ReportView;
  diary: DiaryView;
  beatPanel: BeatPanel;
  eps: EpisodesView;
}

/** Узлы оболочки, которые действия обновляют вместе с состоянием. */
export interface Dom {
  stats: HTMLElement;
  stripPane: HTMLElement;
  keys: HTMLElement;
  timeIn: HTMLInputElement;
  time: HTMLElement;
  durBtns: Record<number, HTMLElement>;
  mainTabs: { set(t: MainTab): void };
  sideTabs: { set(t: SideTab): void; label(t: SideTab, s: string): void };
  applyTop(): void;
  addToReport(): Promise<void>;
}

/** Все переходы расшифровки: меняют состояние и синхронизируют представления между собой. */
export interface Actions {
  redraw(): void;
  paint(): void;
  setSide(t: SideTab): void;
  setMain(t: MainTab): void;
  selectBeat(b: Beat, focusPanel: boolean): void;
  load(): Promise<void>;
  setStrip(r: Range, live: boolean): void;
  setContext(c: Range, live: boolean): void;
  setCursor(sec: number | null): void;
  setRange(r: Span | null): void;
  gotoEpisode(ep: Episode): void;
  gotoBeat(idx: number): Promise<void>;
  refreshAll(): Promise<void>;
  label(l: ManualLabel | null): Promise<void>;
  addBeat(l: ManualLabel): Promise<void>;
  quality(v: "clean" | "noise" | null): Promise<void>;
  refreshEvents(): Promise<void>;
  stepEpisode(dir: 1 | -1): void;
  stepBeat(dir: 1 | -1): void;
}

export const createActions = (state: AppState, views: Views, dom: Dom): Actions => {
  const redraw = () => {
    if (state.last && state.mainTab === "strip") {
      views.ecg.render(state.last, state.startIso, state.gain);
      views.ecg.setCursor(state.cursorSec);
      views.ecg.setRange(state.range);
      views.ecg.highlight(state.activeBeat?.index ?? null);
    }
  };

  const paint = () => {
    if (document.activeElement !== dom.timeIn) dom.timeIn.value = clock(state.startIso, state.strip.start);
    dom.time.textContent = `+${state.strip.dur % 1 ? state.strip.dur.toFixed(1) : state.strip.dur} с`;
    views.ov.setContext(state.ctx, state.strip);
    for (const [k, x] of Object.entries(dom.durBtns)) x.classList.toggle("on", Number(k) === state.strip.dur);
    void views.mini.set(state.ctx, state.strip);
  };

  const setSide = (t: SideTab) => {
    state.sideTab = t;
    dom.sideTabs.set(t);
    views.eps.root.hidden = t !== "episodes";
    views.beatPanel.root.hidden = t !== "beat";
    views.diary.root.hidden = t !== "diary";
    if (t === "diary" && state.cursorSec !== null) views.diary.prefill(state.cursorSec);
  };

  const setMain = (t: MainTab) => {
    state.mainTab = t;
    dom.mainTabs.set(t);
    dom.stripPane.hidden = t !== "strip";
    views.fd.root.hidden = t !== "disclosure";
    views.tpl.root.hidden = t !== "templates";
    views.rep.root.hidden = t !== "report";
    dom.applyTop(); // на вкладке шаблонов суточная шкала не нужна — applyTop её скроет
    if (t === "report") void views.rep.open();
    if (t === "disclosure") void views.fd.show(state.strip.start, state.leads[0], state.strip);
    if (t === "templates") void views.tpl.open();
    if (t === "strip") redraw();
  };

  const selectBeat = (b: Beat, focusPanel: boolean) => {
    state.activeBeat = b;
    state.cursorSec = null;
    views.ecg.setCursor(null);
    state.range = null;
    views.ecg.setRange(null);
    views.ecg.highlight(b.index);
    views.beatPanel.showBeat(b, state.startIso);
    if (focusPanel) setSide("beat");
  };

  const load = async () => {
    const id = ++state.reqId;
    paint();
    const win = await api.ecg(state.strip.start, state.strip.dur, state.leads);
    if (id !== state.reqId) return;
    state.last = win;
    history.replaceState(null, "", `#t=${state.strip.start.toFixed(1)}&d=${state.strip.dur}`);
    views.ecg.render(win, state.startIso, state.gain);
    views.ecg.setCursor(state.cursorSec);
    views.ecg.setRange(state.range);
    const cur = state.activeBeat;
    if (cur) {
      const fresh = win.beats.find((b) => b.index === cur.index);
      if (fresh) selectBeat(fresh, false);
      else views.ecg.highlight(cur.index);
    }
  };

  const setStrip = (r: Range, live: boolean) => {
    const next = stripInto(state.ctx, r, state.total);
    state.strip = next.strip;
    state.ctx = next.ctx;
    paint();
    if (state.liveTimer) window.clearTimeout(state.liveTimer);
    if (live) state.liveTimer = window.setTimeout(() => void load(), 120);
    else void load();
  };

  const setContext = (c: Range, live: boolean) => {
    const next = contextInto(state.strip, c, state.total);
    state.ctx = next.ctx;
    state.strip = next.strip;
    if (next.moved) {
      if (state.liveTimer) window.clearTimeout(state.liveTimer);
      if (live) {
        paint();
        state.liveTimer = window.setTimeout(() => void load(), 150);
      } else void load();
    } else paint();
  };

  const setCursor = (sec: number | null) => {
    state.cursorSec = sec;
    if (sec !== null && state.range) {
      state.range = null;
      views.ecg.setRange(null);
    }
    if (sec !== null) {
      state.activeBeat = null;
      views.ecg.highlight(null);
      views.beatPanel.showBeat(null, state.startIso);
      setSide("beat");
    }
    views.ecg.setCursor(sec);
    views.beatPanel.showCursor(sec, state.startIso);
  };

  const setRange = (r: Span | null) => {
    state.range = r;
    views.ecg.setRange(r);
    if (r) {
      state.activeBeat = null;
      state.cursorSec = null;
      views.ecg.highlight(null);
      views.ecg.setCursor(null);
      setSide("beat");
    }
    views.beatPanel.showRange(r, state.startIso);
  };

  const gotoEpisode = (ep: Episode) => {
    setMain("strip");
    state.activeEp = ep.id;
    const epDur = ep.dur_ms / 1000;
    const dur = episodeDur(epDur, state.strip.dur);
    state.activeBeat = null;
    setCursor(null);
    views.ov.setActiveEpisode(ep.id);
    views.eps.setActive(ep.id);
    setStrip({ start: ep.t_ms / 1000 - (dur - epDur) / 2, dur }, false);
    window.setTimeout(() => {
      const b = state.last?.beats.find((x) => x.index === ep.beats[0]);
      if (b) selectBeat(b, false);
    }, 200);
  };

  const gotoBeat = async (idx: number) => {
    const b = await api.beat(idx);
    state.activeEp = null;
    views.ov.setActiveEpisode(null);
    views.eps.setActive(null);
    state.activeBeat = b;
    setCursor(null);
    setStrip({ start: b.t_ms / 1000 - state.strip.dur / 2, dur: state.strip.dur }, false);
    setSide("beat");
  };

  const refreshAll = async () => {
    [state.sum, state.ov, state.episodes] = await Promise.all([api.summary(), api.overview(), api.episodes()]);
    const ns = statsBlock(state.sum);
    dom.stats.replaceWith(ns);
    dom.stats = ns;
    views.ov.update(state.ov, state.episodes);
    views.ov.setContext(state.ctx, state.strip);
    views.ov.setActiveEpisode(state.activeEp);
    dom.sideTabs.label("episodes", `Эпизоды · ${state.episodes.length}`);
    const nv = renderEpisodes(state.sum, state.episodes, (ep) => gotoEpisode(ep));
    views.eps.root.replaceWith(nv.root);
    views.eps = nv;
    views.eps.root.hidden = state.sideTab !== "episodes";
    views.eps.setActive(state.activeEp);
    await Promise.all([views.mini.refresh(), views.fd.refresh(), load()]);
  };

  const label = async (l: ManualLabel | null) => {
    if (!state.activeBeat) return;
    const wasAdded = state.activeBeat.added;
    const r = await api.annotate(state.activeBeat.index, l);
    state.activeBeat = wasAdded && l === null ? null : r;
    await refreshAll();
    if (!state.activeBeat) views.beatPanel.showBeat(null, state.startIso);
  };

  const addBeat = async (l: ManualLabel) => {
    if (state.cursorSec === null) return;
    try {
      const b = await api.addBeat(Math.round(state.cursorSec * 1000), l);
      state.cursorSec = null;
      views.ecg.setCursor(null);
      state.activeBeat = b;
      await refreshAll();
    } catch (e) {
      const msg = String(e).includes("400") ? "ближе 120 мс уже есть комплекс" : String(e);
      views.beatPanel.showError(msg);
    }
  };

  const quality = async (v: "clean" | "noise" | null) => {
    if (!state.range) return;
    await api.quality(Math.round(state.range.t0 * 1000), Math.round(state.range.t1 * 1000), v);
    await refreshAll();
  };

  const refreshEvents = async () => {
    const evs = await views.diary.reload();
    state.eventTimes = evs.map((e) => e.t_ms / 1000);
    views.ov.setEvents(state.eventTimes);
    views.mini.setEvents(state.eventTimes);
    views.ecg.setEvents(state.eventTimes);
    dom.sideTabs.label("diary", evs.length ? `Симптомы · ${evs.length}` : "Симптомы");
    redraw();
  };

  const stepEpisode = (dir: 1 | -1) => {
    const i = stepEpisodeIndex(state.episodes, state.activeEp, state.strip, dir);
    if (i !== null) gotoEpisode(state.episodes[i]);
  };

  const stepBeat = (dir: 1 | -1) => {
    if (!state.last) return;
    const b = stepBeatTarget(state.last.beats, state.activeBeat, dir);
    if (b) selectBeat(b, true);
  };

  return {
    redraw,
    paint,
    setSide,
    setMain,
    selectBeat,
    load,
    setStrip,
    setContext,
    setCursor,
    setRange,
    gotoEpisode,
    gotoBeat,
    refreshAll,
    label,
    addBeat,
    quality,
    refreshEvents,
    stepEpisode,
    stepBeat,
  };
};
