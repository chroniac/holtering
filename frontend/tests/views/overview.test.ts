import { describe, expect, test } from "bun:test";
import { binSums, hrBounds, noiseRuns } from "../../src/views/overview/model";

describe("binSums", () => {
  test("sums the short tail bin of a record that is not a multiple of the bin", () => {
    expect(binSums([1, 1, 1, 1, 1, 2, 2], 3, 3)).toEqual([3, 4, 2]);
  });

  test("yields zero for bins past the end of a shorter series", () => {
    expect(binSums([5, 5], 3, 3)).toEqual([10, 0, 0]);
  });
});

describe("hrBounds", () => {
  test("rounds to decades with a margin and never drops below 30", () => {
    expect(hrBounds([55, 132])).toEqual({ lo: 40, hi: 150 });
    expect(hrBounds([31, 44])).toEqual({ lo: 30, hi: 60 });
  });

  test("ignores minutes without a heart rate", () => {
    expect(hrBounds([Number.NaN, 62, Number.NaN])).toEqual({ lo: 50, hi: 80 });
  });
});

describe("noiseRuns", () => {
  test("ends a run at the first clean window", () => {
    expect(noiseRuns([0, 0.9, 0.9, 0, 0])).toEqual([[1, 3]]);
  });

  test("closes a run that is still open at the end of the record", () => {
    expect(noiseRuns([0, 0.4, 0.4])).toEqual([[1, 3]]);
    expect(noiseRuns([0.4])).toEqual([[0, 1]]);
  });

  test("treats windows just below the threshold as clean", () => {
    expect(noiseRuns([0.34, 0.34])).toEqual([]);
  });
});
