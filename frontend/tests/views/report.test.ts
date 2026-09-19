import { describe, expect, test } from "bun:test";
import type { ReportSaved, StripSpec } from "../../src/api/types";
import { mergeSaved, stripGain, visibleStrips } from "../../src/views/report/model";

describe("stripGain", () => {
  test("picks the largest calibrated step that keeps the trace inside the lane", () => {
    expect(stripGain([[0, 0.5]], true)).toBe(10);
    expect(stripGain([[0, 1]], true)).toBe(5);
    expect(stripGain([[0, 2]], true)).toBe(2.5);
    expect(stripGain([[0, -6.8]], true)).toBe(1);
  });

  test("falls back to the exact fit when even 0.5 mm/mV overflows the lane", () => {
    expect(stripGain([[0, 20]], true)).toBeCloseTo(0.34, 10);
  });

  test("without calibration fits the lane but never stretches past 10 mm/mV", () => {
    expect(stripGain([[0, 0.1]], false)).toBe(10);
    expect(stripGain([[0, 20]], false)).toBeCloseTo(0.34, 10);
  });

  test("treats a flat strip as 0.05 mV so the gain stays finite", () => {
    expect(stripGain([[0, 0]], true)).toBe(10);
  });
});

describe("visibleStrips", () => {
  const spec = (id: string, t0_ms: number): StripSpec => ({ id, kind: "pause", t0_ms, dur_s: 7.2, caption: "" });
  const saved = (over: Partial<ReportSaved>): ReportSaved => mergeSaved(over);

  test("merges the doctor's strips into the automatic ones in time order", () => {
    const got = visibleStrips(
      [spec("a", 3000), spec("b", 1000)],
      saved({ strips: [{ ...spec("m", 2000), kind: "sinus" }] }),
      true,
    );
    expect(got.map((s) => [s.id, s.kind, s.auto])).toEqual([
      ["b", "pause", true],
      ["m", "manual", false],
      ["a", "pause", true],
    ]);
  });

  test("drops automatic strips the doctor removed, but keeps their own", () => {
    const got = visibleStrips([spec("a", 1000)], saved({ hidden: ["a"], strips: [spec("m", 2000)] }), true);
    expect(got.map((s) => s.id)).toEqual(["m"]);
  });

  test("shows nothing when the section is switched off", () => {
    expect(visibleStrips([spec("a", 1000)], saved({}), false)).toEqual([]);
  });
});
