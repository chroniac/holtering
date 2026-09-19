import type { ManualLabel } from "../api/types";
import { zoomAround } from "../lib/nav";
import { STRIP_MAX, STRIP_MIN } from "../views/minimap";
import type { Actions, Dom, Views } from "./actions";
import type { AppState } from "./state";

/** Клавиатура расшифровки: вкладки, обход эпизодов и комплексов, разметка и качество. */
export const createKeyHandler =
  (state: AppState, views: Views, actions: Actions, dom: Dom) =>
  (e: KeyboardEvent): void => {
    const tag = (e.target as HTMLElement).tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || (e.target as HTMLElement).isContentEditable)
      return;
    const k = e.key.toLowerCase();
    if (e.key === "Escape") {
      state.activeBeat = null;
      views.ecg.highlight(null);
      actions.setCursor(null);
      actions.setRange(null);
      views.beatPanel.showBeat(null, state.startIso);
    } else if (k === "1") actions.setMain("strip");
    else if (k === "2") actions.setMain("disclosure");
    else if (k === "3") actions.setMain("templates");
    else if (k === "4") actions.setMain("report");
    else if (k === "?") dom.keys.hidden = !dom.keys.hidden;
    else if (state.mainTab !== "strip") return;
    else if (e.key === "ArrowLeft")
      actions.setStrip(
        { start: state.strip.start - (e.shiftKey ? state.strip.dur * 6 : state.strip.dur), dur: state.strip.dur },
        false,
      );
    else if (e.key === "ArrowRight")
      actions.setStrip(
        { start: state.strip.start + (e.shiftKey ? state.strip.dur * 6 : state.strip.dur), dur: state.strip.dur },
        false,
      );
    else if (e.key === "[") actions.stepEpisode(-1);
    else if (e.key === "]") actions.stepEpisode(1);
    else if (e.key === "Tab") actions.stepBeat(e.shiftKey ? -1 : 1);
    else if (e.key === "-")
      actions.setStrip(
        zoomAround(state.strip, state.strip.start + state.strip.dur / 2, 1.5, STRIP_MIN, STRIP_MAX),
        false,
      );
    else if (e.key === "+" || e.key === "=")
      actions.setStrip(
        zoomAround(state.strip, state.strip.start + state.strip.dur / 2, 1 / 1.5, STRIP_MIN, STRIP_MAX),
        false,
      );
    else if (k === "a" && state.cursorSec !== null) void actions.addBeat("N");
    else if (k === "p") void dom.addToReport();
    else if (state.range && k === "c") void actions.quality("clean");
    else if (state.range && k === "x") void actions.quality("noise");
    else if (state.range && e.key === "Backspace") void actions.quality(null);
    else if (k === "n" || k === "v" || k === "s" || k === "x") void actions.label(k.toUpperCase() as ManualLabel);
    else if (e.key === "Backspace") void actions.label(null);
    else return;
    e.preventDefault();
  };
