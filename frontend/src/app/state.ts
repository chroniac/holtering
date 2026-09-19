import type { Beat, EcgWindow, Episode, Overview, Summary } from "../api/types";
import { clampRange, type Range } from "../lib/nav";
import { STRIP_MAX, STRIP_MIN } from "../views/minimap";
import { CTX_MAX, CTX_MIN } from "../views/overview";

export type MainTab = "strip" | "disclosure" | "templates" | "report";
export type SideTab = "episodes" | "beat" | "diary";

/** Выделенный по ленте диапазон времени (секунды от начала записи). */
export interface Span {
  t0: number;
  t1: number;
}

/** Длительности окна ленты на панели; из них же подбирается окно под эпизод. */
export const DURS = [5, 10, 20, 30, 60];

export interface AppState {
  readonly startIso: string;
  readonly total: number;
  ctx: Range;
  strip: Range;
  leads: string[];
  gain: number | "auto";
  activeEp: number | null;
  activeBeat: Beat | null;
  cursorSec: number | null;
  range: Span | null;
  mainTab: MainTab;
  sideTab: SideTab;
  topOpen: boolean;
  eventTimes: number[];
  sum: Summary;
  ov: Overview;
  episodes: Episode[];
  last: EcgWindow | null;
  /** Номер последнего запроса ленты: ответы более старых запросов отбрасываются. */
  reqId: number;
  liveTimer: number | null;
}

export const createState = (sum: Summary, ov: Overview, episodes: Episode[], leads: string[]): AppState => ({
  startIso: sum.record.start,
  total: sum.record.duration_s,
  ctx: { start: 0, dur: 600 },
  strip: { start: 0, dur: 10 },
  leads,
  gain: "auto",
  activeEp: null,
  activeBeat: null,
  cursorSec: null,
  range: null,
  mainTab: "strip",
  sideTab: "episodes",
  topOpen: localStorage.getItem("holtering.top") !== "0",
  eventTimes: [],
  sum,
  ov,
  episodes,
  last: null,
  reqId: 0,
  liveTimer: null,
});

const outside = (strip: Range, ctx: Range): boolean =>
  strip.start < ctx.start || strip.start + strip.dur > ctx.start + ctx.dur;

/** Лента сдвинулась: держим её внутри контекста, контекст листается за ней. */
export const stripInto = (ctx: Range, r: Range, total: number): { strip: Range; ctx: Range } => {
  const strip = clampRange(
    { start: r.start, dur: Math.round(Math.max(STRIP_MIN, Math.min(STRIP_MAX, r.dur)) * 10) / 10 },
    total,
  );
  if (outside(strip, ctx))
    return {
      strip,
      ctx: clampRange(
        { start: strip.start + strip.dur / 2 - ctx.dur / 2, dur: Math.max(ctx.dur, strip.dur * 3) },
        total,
      ),
    };
  return { strip, ctx };
};

/** Контекст сменился на обзоре: лента переезжает в его центр, если выпала из него. */
export const contextInto = (strip: Range, c: Range, total: number): { ctx: Range; strip: Range; moved: boolean } => {
  const ctx = clampRange({ start: c.start, dur: Math.max(CTX_MIN, Math.min(CTX_MAX, c.dur)) }, total);
  if (outside(strip, ctx))
    return {
      ctx,
      strip: clampRange({ start: ctx.start + ctx.dur / 2 - strip.dur / 2, dur: strip.dur }, total),
      moved: true,
    };
  return { ctx, strip, moved: false };
};

/** Окно под эпизод: ближайшая стандартная длительность с запасом 4 с, если текущего окна мало. */
export const episodeDur = (epDur: number, stripDur: number): number =>
  epDur + 4 > stripDur ? Math.min(STRIP_MAX, DURS.find((d) => d >= epDur + 4) ?? epDur + 4) : stripDur;

/** Следующий эпизод по кругу; без выбранного — первый за окном ленты (или последний перед ним). */
export const stepEpisodeIndex = (
  episodes: Episode[],
  activeEp: number | null,
  strip: Range,
  dir: 1 | -1,
): number | null => {
  if (!episodes.length) return null;
  let i = activeEp === null ? -1 : episodes.findIndex((e) => e.id === activeEp);
  if (i === -1) {
    i =
      dir > 0
        ? episodes.findIndex((e) => e.t_ms / 1000 > strip.start + strip.dur)
        : episodes.map((e) => e.t_ms / 1000 < strip.start).lastIndexOf(true);
    if (i === -1) return null;
  } else i = (i + dir + episodes.length) % episodes.length;
  return i;
};

/** Обход подозрительных комплексов окна: синусовые (N и ручной N) пропускаются. */
export const stepBeatTarget = (beats: Beat[], activeBeat: Beat | null, dir: 1 | -1): Beat | null => {
  const marked = beats.filter((b) => b.verdict !== "N" && b.verdict !== "manual-N");
  if (!marked.length) return null;
  const cur = activeBeat;
  const i = cur ? marked.findIndex((b) => b.index === cur.index) : -1;
  return marked[(i + dir + marked.length) % marked.length];
};
