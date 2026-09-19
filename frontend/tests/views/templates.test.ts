import { describe, expect, test } from "bun:test";
import type { Template } from "../../src/api/types";
import { hoursNote, score } from "../../src/views/templates/model";

const tpl = (over: Partial<Template>): Template => ({
  id: 1,
  count: 100,
  labels: {},
  verdicts: {},
  verdicts_by_label: {},
  manual: {},
  hours: [],
  wave: { fs: 200, half_ms: 100, leads: [[0]] },
  first: 0,
  sample: [],
  ...over,
});

const byLabelV = (vV: Record<string, number>, nV: number) =>
  tpl({ labels: { V: nV }, verdicts_by_label: { V: vV }, verdicts: vV });

describe("score", () => {
  test("splits V families on the 0.2 and 0.8 confirmation boundaries", () => {
    expect(score(byLabelV({ likely: 2, narrow: 8 }, 10)).bucket).toBe("decide");
    expect(score(byLabelV({ likely: 8, narrow: 2 }, 10)).bucket).toBe("decide");
    expect(score(byLabelV({ likely: 9, narrow: 1 }, 10)).bucket).toBe("v");
    expect(score(byLabelV({ likely: 1, narrow: 9 }, 10)).bucket).toBe("n");
  });

  test("three uncertain verdicts put a family on the decide pile even when all V are kept", () => {
    expect(score(byLabelV({ likely: 7, uncertain: 3 }, 10)).bucket).toBe("decide");
    expect(score(byLabelV({ likely: 8, uncertain: 2 }, 10)).bucket).toBe("v");
  });

  test("fewer than three device V marks never reach the decide pile", () => {
    const sc = score(byLabelV({ likely: 1, narrow: 1 }, 2));
    expect(sc.bucket).toBe("n");
    expect(sc.dominant).toBe("N");
  });

  test("a doctor's label on the family wins over the audit", () => {
    const sc = score(tpl({ labels: { V: 10 }, verdicts_by_label: { V: { likely: 5, narrow: 5 } }, manual: { N: 10 } }));
    expect(sc.bucket).toBe("n");
    expect(sc.dominant).toBe("N");
  });

  test("S is about timing, so an S family is never up for a decision", () => {
    expect(score(tpl({ count: 100, labels: { S: 60 } })).bucket).toBe("s");
  });

  test("counts kept, uncertain and rejected verdicts of the whole family", () => {
    const sc = score(tpl({ verdicts: { likely: 4, uncertain: 2, manual: 1, narrow: 3, N: 90, "manual-N": 5 } }));
    expect([sc.kept, sc.uncertain, sc.rejected]).toEqual([7, 2, 3]);
  });
});

describe("hoursNote", () => {
  const hours = (at: Record<number, number>) => Array.from({ length: 24 }, (_, i) => at[i] ?? 0);

  test("counts hours by the patient's wall clock across midnight", () => {
    expect(hoursNote(hours({ 2: 10, 3: 10 }), "2024-01-01 22:00:00")).toBe("в основном ночью (100%)");
    expect(hoursNote(hours({ 0: 10, 1: 10 }), "2024-01-01 22:00:00")).toBe("в основном вечером (100%)");
  });

  test("names a part of the day only from 60% of the complexes", () => {
    expect(hoursNote(hours({ 0: 6, 12: 4 }), "2024-01-01 08:00:00")).toBe("в основном утром (60%)");
    expect(hoursNote(hours({ 0: 5, 12: 5 }), "2024-01-01 08:00:00")).toBe("в течение суток");
  });

  test("says nothing about a family without hourly counts", () => {
    expect(hoursNote(hours({}), "2024-01-01 08:00:00")).toBe("");
    expect(hoursNote([], "2024-01-01 08:00:00")).toBe("");
  });
});
