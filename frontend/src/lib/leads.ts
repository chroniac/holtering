/** Каналы 0-5 — от конечностей (тождества Эйнтховена в scp_holter.leads), дальше грудные. */
export const LIMB_COUNT = 6;

export interface LeadSets {
  limb: string[];
  chest: string[];
  trio: string[];
  all: string[];
}

export const leadSets = (all: string[]): LeadSets => {
  const limb = all.slice(0, LIMB_COUNT),
    chest = all.slice(LIMB_COUNT);
  // трио по умолчанию: II и два грудных канала, ближайших к позициям V2/V5
  const trio = [limb[1] ?? all[0], chest[4] ?? chest[chest.length - 1], chest[1] ?? chest[0]].filter(
    (x, i, arr) => x && arr.indexOf(x) === i,
  );
  return { limb, chest, trio, all };
};
