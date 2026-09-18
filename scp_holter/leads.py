"""Section 3 - lead definitions, plus the montage evidence for this device.

Wire format: count(1) flags(1) then count x [start(4) end(4) lead_id(1)].

The vendor writes 0-based CHANNEL INDICES in `lead_id` (0..11), not SCP lead
codes - 0 is "unspecified" in the standard table, so the codes cannot be taken
at face value. What the channels actually are was established from the data:

Limb block, ch0..ch5 = I II III aVR aVL aVF -- PROVED.
    ch2 == ch1 - ch0            (III = II - I)      rmse 0.000000 mV
    ch3 == -(ch0 + ch1) / 2     (aVR)               rmse 0.000616 mV
    ch4 == ch0 - ch1 / 2        (aVL)               rmse 0.000616 mV
    ch5 == ch1 - ch0 / 2        (aVF)               rmse 0.000620 mV
    The reversed permutation (ch5=I, ch4=II, ...) misses by 0.78 mV, so the
    assignment is unique. Note the identities are linear and therefore hold for
    -x as well: they pin the ORDER, never the SIGN.

Chest block, ch6..ch11 = the six V leads -- ORDER UNVERIFIED, two readings fit:
    a) bytes as stored + descending order (ch6..ch11 = V6..V1): R/S then rises
       monotonically 0.10 -> 7.01 across V1->V6, and the P axis is normal sinus
       (P = +0.086 mV in II, -0.046 in aVR).
    b) sign-inverted + ascending order (ch6..ch11 = V1..V6): one flip makes the
       limb QRS axis, the T concordance and the V4 transition textbook (signed
       QRS areas -48 -69 -56 -3 +50 +62 mV*ms), at the cost of a negative P
       axis (low-atrial / ectopic).
    PR is 176-224 ms under both, so it does not arbitrate. The flip-invariant
    |P| gradient across the block is 0.014 0.048 0.086 0.077 0.069 0.058 mV;
    the near-null channel is ch6, which fits V1 (biphasic P cancels) and thus
    leans to (b). Defaults keep the bytes as stored and label the chest block
    neutrally; `--invert` / `--chest` switch to (b) once a CardioSpy printout of
    the same beat settles it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .sections import u32

LIMB6 = ["I", "II", "III", "aVR", "aVL", "aVF"]
CHEST_ASC = ["V1", "V2", "V3", "V4", "V5", "V6"]
CHEST_DESC = ["V6", "V5", "V4", "V3", "V2", "V1"]
CHEST_NOTE = "order unverified; with --invert ascending V1..V6 fits, else V6..V1"

LEAD_DEF_LEN = 9


@dataclass(slots=True)
class LeadDefs:
    count: int
    flags: int
    ids: list[int]
    spans: list[tuple[int, int]]
    labels: list[str]

    @property
    def reference_beat_subtracted(self) -> bool:
        return bool(self.flags & 1)

    @property
    def simultaneous(self) -> bool:
        return bool(self.flags >> 3)


def default_labels(ids: list[int]) -> list[str]:
    """Neutral labels: limb leads are proved, chest channels stay as ch6..ch11."""
    if ids != list(range(len(ids))):
        return [f"ch{i}" for i in ids]
    return [LIMB6[i] if i < len(LIMB6) else f"ch{i}" for i in ids]


def relabel_chest(count: int, chest: list[str]) -> list[str]:
    """Apply an explicit chest montage, e.g. --chest V1,V2,V3,V4,V5,V6."""
    want = count - len(LIMB6)
    if len(chest) != want:
        raise ValueError(f"expected {want} chest labels, got {len(chest)}")
    return LIMB6 + list(chest)


def parse_leads(body: bytes) -> LeadDefs:
    count, flags = body[0], body[1]
    ids, spans = [], []
    for i in range(count):
        o = 2 + i * LEAD_DEF_LEN
        spans.append((u32(body, o), u32(body, o + 4)))
        ids.append(body[o + 8])
    return LeadDefs(count=count, flags=flags, ids=ids, spans=spans,
                    labels=default_labels(ids))
