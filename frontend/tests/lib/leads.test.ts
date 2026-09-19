import { describe, expect, test } from "bun:test";
import { leadSets } from "../../src/lib/leads";

const TWELVE = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"];

describe("leadSets", () => {
  test("splits twelve leads into limb, chest and the II/V5/V2 trio", () => {
    const s = leadSets(TWELVE);
    expect(s.limb).toEqual(["I", "II", "III", "aVR", "aVL", "aVF"]);
    expect(s.chest).toEqual(["V1", "V2", "V3", "V4", "V5", "V6"]);
    expect(s.trio).toEqual(["II", "V5", "V2"]);
  });

  test("falls back without duplicates when there are fewer chest leads", () => {
    const s = leadSets(["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V5"]);
    expect(s.chest).toEqual(["V1", "V5"]);
    expect(s.trio).toEqual(["II", "V5"]);
  });
});
