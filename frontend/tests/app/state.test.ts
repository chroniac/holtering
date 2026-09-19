import { describe, expect, test } from "bun:test";
import type { Beat, Episode, Verdict } from "../../src/api/types";
import { contextInto, episodeDur, stepBeatTarget, stepEpisodeIndex, stripInto } from "../../src/app/state";

const episode = (id: number, tS: number): Episode => ({
  id,
  kind: "v-run",
  t_ms: tS * 1000,
  dur_ms: 1000,
  title: "залп",
  verdict: "review",
  confidence: 1,
  reasons: [],
  beats: [],
});

const beat = (index: number, verdict: Verdict): Beat => ({
  index,
  t_ms: index * 1000,
  label: "N",
  device_label: "N",
  manual: null,
  added: false,
  verdict,
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
});

describe("stripInto", () => {
  test("keeps the window inside the record when it is pushed past the end", () => {
    const { strip, ctx } = stripInto({ start: 540, dur: 60 }, { start: 598, dur: 10 }, 600);
    expect(strip).toEqual({ start: 590, dur: 10 });
    expect(ctx).toEqual({ start: 540, dur: 60 });
  });

  test("clamps the duration to the strip bounds and rounds it to a tenth", () => {
    expect(stripInto({ start: 0, dur: 600 }, { start: 0, dur: 0.5 }, 3600).strip.dur).toBe(2);
    expect(stripInto({ start: 0, dur: 600 }, { start: 0, dur: 900 }, 3600).strip.dur).toBe(120);
    expect(stripInto({ start: 0, dur: 600 }, { start: 0, dur: 7.77 }, 3600).strip.dur).toBe(7.8);
  });

  test("drags the context along and widens it to three windows when the strip leaves it", () => {
    const { strip, ctx } = stripInto({ start: 0, dur: 60 }, { start: 1000, dur: 120 }, 3600);
    expect(strip).toEqual({ start: 1000, dur: 120 });
    expect(ctx).toEqual({ start: 1030, dur: 360 });
  });

  test("leaves the context alone while the strip still fits in it", () => {
    const ctx0 = { start: 100, dur: 600 };
    expect(stripInto(ctx0, { start: 200, dur: 10 }, 3600).ctx).toBe(ctx0);
  });
});

describe("contextInto", () => {
  test("re-centres the strip only when it falls out of the new context", () => {
    const inside = contextInto({ start: 200, dur: 10 }, { start: 100, dur: 600 }, 3600);
    expect(inside.moved).toBe(false);
    expect(inside.strip).toEqual({ start: 200, dur: 10 });

    const outside = contextInto({ start: 20, dur: 10 }, { start: 1000, dur: 600 }, 3600);
    expect(outside.moved).toBe(true);
    expect(outside.strip).toEqual({ start: 1295, dur: 10 });
  });

  test("clamps the context duration and pins it inside the record", () => {
    expect(contextInto({ start: 0, dur: 10 }, { start: 0, dur: 10 }, 3600).ctx.dur).toBe(60);
    expect(contextInto({ start: 0, dur: 10 }, { start: 0, dur: 99999 }, 40000).ctx.dur).toBe(3 * 3600);
    expect(contextInto({ start: 0, dur: 10 }, { start: 3500, dur: 600 }, 3600).ctx).toEqual({ start: 3000, dur: 600 });
  });
});

describe("episodeDur", () => {
  test("keeps the current window when the episode already fits with a margin", () => {
    expect(episodeDur(3, 10)).toBe(10);
  });

  test("picks the next standard duration that holds the episode plus four seconds", () => {
    expect(episodeDur(8, 10)).toBe(20);
    expect(episodeDur(27, 10)).toBe(60);
  });

  test("never exceeds the strip maximum for an episode longer than every preset", () => {
    expect(episodeDur(300, 10)).toBe(120);
  });
});

describe("stepEpisodeIndex", () => {
  const eps = [episode(1, 10), episode(2, 100), episode(3, 200)];

  test("wraps around from the last episode to the first", () => {
    expect(stepEpisodeIndex(eps, 3, { start: 0, dur: 10 }, 1)).toBe(0);
    expect(stepEpisodeIndex(eps, 1, { start: 0, dur: 10 }, -1)).toBe(2);
  });

  test("without a selection takes the first episode past the window, or the last before it", () => {
    expect(stepEpisodeIndex(eps, null, { start: 50, dur: 10 }, 1)).toBe(1);
    expect(stepEpisodeIndex(eps, null, { start: 150, dur: 10 }, -1)).toBe(1);
  });

  test("returns null when there is nothing beyond the window in that direction", () => {
    expect(stepEpisodeIndex(eps, null, { start: 300, dur: 10 }, 1)).toBeNull();
    expect(stepEpisodeIndex(eps, null, { start: 0, dur: 10 }, -1)).toBeNull();
    expect(stepEpisodeIndex([], null, { start: 0, dur: 10 }, 1)).toBeNull();
  });
});

describe("stepBeatTarget", () => {
  const beats = [beat(0, "N"), beat(1, "likely"), beat(2, "manual-N"), beat(3, "uncertain")];

  test("skips sinus beats and wraps around the marked ones", () => {
    expect(stepBeatTarget(beats, null, 1)?.index).toBe(1);
    expect(stepBeatTarget(beats, beats[1], 1)?.index).toBe(3);
    expect(stepBeatTarget(beats, beats[3], 1)?.index).toBe(1);
    expect(stepBeatTarget(beats, beats[1], -1)?.index).toBe(3);
  });

  test("returns null when the window holds no marked beat", () => {
    expect(stepBeatTarget([beat(0, "N"), beat(1, "manual-N")], null, 1)).toBeNull();
  });
});
