import { describe, expect, test } from "bun:test";
import { autoGain, mergeNoise } from "../../src/views/ecg/model";

describe("autoGain", () => {
  test("picks the largest step that still fits the lane", () => {
    expect(autoGain([[0, 1]], 1, 100)).toBe(20);
    expect(autoGain([[-1, 3]], 1, 100)).toBe(20);
    expect(autoGain([[-2, 3]], 2, 100)).toBe(5);
  });

  test("falls back to the smallest step when nothing fits", () => {
    expect(autoGain([[-100, 100]], 1, 10)).toBe(1.25);
  });

  test("treats a flat lead as 0.2 mV so the gain does not blow up", () => {
    expect(autoGain([[0, 0.05]], 30, 100)).toBe(10);
  });
});

describe("mergeNoise", () => {
  test("merges touching windows and keeps the worst score", () => {
    const merged = mergeNoise(
      [
        { t0: 10, t1: 11, score: 0.4 },
        { t0: 11, t1: 12, score: 0.9 },
      ],
      10,
      100,
      1000,
    );
    expect(merged).toEqual([{ a: 0, b: 200, score: 0.9 }]);
  });

  test("clips to the window and drops what falls outside it", () => {
    expect(mergeNoise([{ t0: 5, t1: 10.5, score: 0.5 }], 10, 100, 1000)).toEqual([{ a: 0, b: 50, score: 0.5 }]);
    expect(mergeNoise([{ t0: 1, t1: 9, score: 0.5 }], 10, 100, 1000)).toEqual([]);
  });
});
