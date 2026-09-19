import { describe, expect, test } from "bun:test";
import type { Beat, EcgWindow } from "../../src/api/types";
import { beatShape, featRows, norm } from "../../src/views/beatpanel/model";

const beat = (over: Partial<Beat>): Beat => ({
  index: 0,
  t_ms: 0,
  label: "V",
  device_label: "V",
  manual: null,
  added: false,
  verdict: "likely",
  confidence: 1,
  reasons: [],
  width_ms: null,
  width_ratio: null,
  prematurity: null,
  amp_ratio: null,
  noise_ratio: null,
  family_n_frac: null,
  rr_pre: null,
  rr_post: null,
  template: 0,
  ...over,
});

const row = (b: Beat, key: string) => featRows(b).find(([k]) => k === key)?.[1];

describe("featRows", () => {
  test("shows a dash for every feature that was not computed", () => {
    expect(featRows(beat({})).map(([, v]) => v)).toEqual(["—", "—", "—", "—", "—", "—", "—", "—"]);
  });

  test("derives the sinus QRS width from the ratio, and only when the width is known", () => {
    expect(row(beat({ width_ms: 120, width_ratio: 1.5 }), "синусовый QRS")).toBe("80 мс");
    expect(row(beat({ width_ms: null, width_ratio: 1.5 }), "синусовый QRS")).toBe("—");
    expect(row(beat({ rr_pre: 900, prematurity: 0.9 }), "ритм до неё")).toBe("1000 мс");
    expect(row(beat({ rr_pre: null, prematurity: 0.9 }), "ритм до неё")).toBe("—");
  });

  test("names the noise level by its thresholds", () => {
    expect(row(beat({ noise_ratio: 1.49 }), "шум")).toBe("нет");
    expect(row(beat({ noise_ratio: 1.5 }), "шум")).toBe("умеренный");
    expect(row(beat({ noise_ratio: 2.5 }), "шум")).toBe("сильный");
  });

  test("calls a shape partially sinus at both ends of the band", () => {
    expect(row(beat({ family_n_frac: 0.9 }), "форма как N")).toBe("частично");
    expect(row(beat({ family_n_frac: 0.2 }), "форма как N")).toBe("частично");
    expect(row(beat({ family_n_frac: 0.91 }), "форма как N")).toBe("да");
    expect(row(beat({ family_n_frac: 0.19 }), "форма как N")).toBe("нет");
  });
});

describe("norm", () => {
  test("centres on the median and scales the peak to one", () => {
    expect(norm([1, 1, 1, 3])).toEqual([0, 0, 0, 1]);
    expect(norm([-4, 0, 0, 2])).toEqual([-1, 0, 0, 0.5]);
  });

  test("keeps a flat wave flat instead of amplifying rounding noise", () => {
    expect(norm([2, 2, 2])).toEqual([0, 0, 0]);
  });
});

describe("beatShape", () => {
  const win = (over: Partial<EcgWindow>): EcgWindow => ({
    start: 10,
    fs: 100,
    leads: ["II"],
    data: [Array.from({ length: 200 }, (_, i) => i)],
    lead_noise: [],
    lead_drift: [],
    drift_thr_mv: 0,
    beats: [],
    noise_windows: [],
    quality_manual: [],
    ...over,
  });

  test("takes ±96 ms of the first lead around the beat", () => {
    expect(beatShape(win({}), 10_500)).toEqual(Array.from({ length: 21 }, (_, i) => 40 + i));
  });

  test("clips at the start of the window instead of wrapping around", () => {
    expect(beatShape(win({}), 10_000)).toEqual(Array.from({ length: 11 }, (_, i) => i));
  });
});
