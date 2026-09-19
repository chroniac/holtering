import { describe, expect, test } from "bun:test";
import { clock, hms } from "../../src/lib/time";

describe("clock", () => {
  test("rolls over midnight and pads every field", () => {
    expect(clock("2026-09-17 23:59:30", 45)).toBe("00:00:15");
  });

  test("keeps the start time at offset zero", () => {
    expect(clock("2026-09-17 09:05:07", 0)).toBe("09:05:07");
  });
});

describe("hms", () => {
  test("carries the last second of an hour into the next hour", () => {
    expect(hms(3599)).toBe("0:59:59");
    expect(hms(3600)).toBe("1:00:00");
  });
});
