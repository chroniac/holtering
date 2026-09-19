import { describe, expect, test } from "bun:test";
import { clampRange, hitRange, zoomAround } from "../../src/lib/nav";

describe("zoomAround", () => {
  test("keeps the time under the cursor at the same relative position", () => {
    const r = zoomAround({ start: 100, dur: 60 }, 130, 0.5, 2, 120);
    expect(r).toEqual({ start: 115, dur: 30 });
    expect((130 - r.start) / r.dur).toBeCloseTo(0.5, 10);
  });

  test("clamps the duration to min and max while keeping the cursor fixed", () => {
    const zoomedIn = zoomAround({ start: 0, dur: 10 }, 4, 0.01, 2, 120);
    expect(zoomedIn.dur).toBe(2);
    expect(zoomedIn.start).toBeCloseTo(4 - 0.4 * 2, 10);
    expect(zoomAround({ start: 0, dur: 100 }, 50, 10, 2, 120).dur).toBe(120);
  });
});

describe("clampRange", () => {
  test("pins the window to the start and to the end of the record", () => {
    expect(clampRange({ start: -30, dur: 60 }, 600)).toEqual({ start: 0, dur: 60 });
    expect(clampRange({ start: 900, dur: 60 }, 600)).toEqual({ start: 540, dur: 60 });
  });

  test("shrinks a window longer than the record and puts it at zero", () => {
    expect(clampRange({ start: 42, dur: 900 }, 600)).toEqual({ start: 0, dur: 600 });
  });
});

describe("hitRange", () => {
  test("prefers the handles over move at the edges of a wide box", () => {
    expect(hitRange(100, 100, 300, 6, "new")).toBe("left");
    expect(hitRange(295, 100, 300, 6, "new")).toBe("right");
    expect(hitRange(200, 100, 300, 6, "new")).toBe("move");
    expect(hitRange(50, 100, 300, 6, "new")).toBe("new");
  });

  test("collapses to move when the box is narrower than three handle widths", () => {
    expect(hitRange(100, 100, 115, 6, "new")).toBe("move");
    expect(hitRange(120, 100, 115, 6, "new")).toBe("move");
    expect(hitRange(122, 100, 115, 6, "new")).toBe("new");
  });
});
