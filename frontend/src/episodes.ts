import type { Episode, Summary } from "./api";
import { dumbbell } from "./dumbbell";
import { clock, el } from "./util";

export interface EpisodesView {
  root: HTMLElement;
  setActive(id: number | null): void;
}

const VERDICT_LABEL: Record<string, string> = { artifact: "артефакт", review: "проверить", likely: "вероятно" };

export function renderEpisodes(sum: Summary, episodes: Episode[], onPick: (ep: Episode) => void): EpisodesView {
  const root = el("div", "side-tab");
  // the five findings a Holter read decides on, before the episode list
  const crit = el("div", "criteria");
  for (const c of sum.criteria) {
    const row = el("div", `crow ${c.met === true ? "met" : c.met === false ? "clear" : "na"}`);
    row.title = c.note;
    row.innerHTML = `<i class="cdot"></i><span class="ctitle">${c.title}</span><b class="cval mono">${c.value}</b>`;
    crit.append(row);
  }
  root.append(crit);
  const head = el("div", "side-head");
  const filters = el("div", "filters");
  const on: Record<string, boolean> = { artifact: true, review: true, likely: true };
  const chips: Record<string, HTMLElement> = {};
  for (const v of ["likely", "review", "artifact"]) {
    const c = el("button", `chip on ${v}`, VERDICT_LABEL[v]);
    c.addEventListener("click", () => {
      on[v] = !on[v];
      c.classList.toggle("on", on[v]); c.classList.toggle("off", !on[v]);
      list();
    });
    chips[v] = c; filters.append(c);
  }
  head.append(filters);
  root.append(head);

  const box = el("div", "eps");
  root.append(box);
  const rows: Record<number, HTMLElement> = {};

  function list() {
    box.innerHTML = "";
    for (const ep of episodes) {
      if (!on[ep.verdict]) continue;
      const row = el("div", "ep-row");
      row.append(el("div", "t", clock(sum.record.start, ep.t_ms / 1000).slice(0, 5)));
      const body = el("div");
      const title = el("div", "title", ep.title);
      const v = el("span", `v ${ep.verdict}`, VERDICT_LABEL[ep.verdict]);
      title.append(v);
      body.append(title);
      if (ep.reasons.length) body.append(el("div", "why", ep.reasons[0]));
      row.append(body);
      row.addEventListener("click", () => onPick(ep));
      box.append(row);
      rows[ep.id] = row;
    }
  }
  list();

  const foot = el("div", "side-foot");
  const c = sum.counts;
  const runsDev = episodes.filter((e) => e.kind === "v-run" && e.title.startsWith("«")).length + episodes.filter((e) => e.kind === "v-run" && !e.title.startsWith("«")).length;
  const runsKept = episodes.filter((e) => e.kind === "v-run" && e.verdict !== "artifact").length;
  const svtDev = episodes.filter((e) => e.kind === "s-run").length;
  const svtKept = episodes.filter((e) => e.kind === "s-run" && e.verdict !== "artifact").length;
  foot.append(dumbbell([
    { label: "ЖЭС", before: c.device.V, after: c.audited.V },
    { label: "НЖЭС", before: c.device.S, after: c.audited.S },
    { label: "залпы ЖЭС", before: runsDev, after: runsKept },
    { label: "НЖ-залпы", before: svtDev, after: svtKept },
    { label: "паузы", before: c.pauses_device, after: c.pauses_real, accent: c.pauses_real > 0 },
  ], ["прибор → аудит", `QRS синус ${sum.calibration.sinus_width_ms} мс`]));
  const actions = el("div", "side-actions");
  const meta = el("span", "mono muted", `аудит ${sum.computed_s} с · вручную ${c.manual + c.added + c.quality_spans}`);
  const exp = el("a", "btn", "экспорт"); (exp as HTMLAnchorElement).href = "/api/export"; (exp as HTMLAnchorElement).download = "holtering-export.json";
  exp.title = "исправленная разметка, эпизоды и сводка (JSON)";
  actions.append(meta, exp);
  foot.append(actions);
  root.append(foot);

  return {
    root,
    setActive(id) {
      for (const [k, r] of Object.entries(rows)) {
        const a = Number(k) === id;
        r.classList.toggle("active", a);
        if (a) r.scrollIntoView({ block: "nearest" });
      }
    },
  };
}
