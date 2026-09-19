"""Секция 3: определения отведений и подписи каналов (монтаж — docs/modules/scp-holter.md)."""

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
    """Подписи по умолчанию: конечностные доказаны, грудные остаются ch6..ch11."""
    if ids != list(range(len(ids))):
        return [f"ch{i}" for i in ids]
    return [LIMB6[i] if i < len(LIMB6) else f"ch{i}" for i in ids]


def relabel_chest(count: int, chest: list[str]) -> list[str]:
    """Явный грудной монтаж, например --chest V1,V2,V3,V4,V5,V6."""
    want = count - len(LIMB6)
    if len(chest) != want:
        raise ValueError(f"expected {want} chest labels, got {len(chest)}")
    return LIMB6 + list(chest)


def parse_leads(body: bytes) -> LeadDefs:
    count, flags = body[0], body[1]
    ids: list[int] = []
    spans: list[tuple[int, int]] = []
    for i in range(count):
        o = 2 + i * LEAD_DEF_LEN
        spans.append((u32(body, o), u32(body, o + 4)))
        ids.append(body[o + 8])
    return LeadDefs(count=count, flags=flags, ids=ids, spans=spans, labels=default_labels(ids))
