"""Section 1 - patient / acquisition tags.

Tag stream: tag(1) length(2, LE) value(length); tag 255 terminates. Text fields
are cp1251, NUL-padded (the device is a Russian-locale build).
"""

from __future__ import annotations

from .sections import u16

TAGS = {
    0: "last_name", 1: "first_name", 2: "patient_id", 4: "age", 5: "dob",
    6: "height", 7: "weight", 8: "sex", 14: "acq_device", 25: "acq_date",
    26: "acq_time", 30: "free_text",
}

TEXT_TAGS = frozenset({0, 1, 2, 30})
_SEX = {1: "M", 2: "F"}


def _iso_date(val: bytes) -> str:
    return f"{u16(val, 0):04d}-{val[2]:02d}-{val[3]:02d}"


def parse_patient(body: bytes) -> dict[str, object]:
    """Decode the Section 1 tag stream into a flat dict."""
    out: dict[str, object] = {}
    o = 0
    while o + 3 <= len(body):
        tag, length = body[o], u16(body, o + 1)
        if tag == 255:
            break
        val = body[o + 3:o + 3 + length]
        name = TAGS.get(tag, f"tag{tag}")
        if tag in TEXT_TAGS:
            out[name] = val.decode("cp1251", "replace").rstrip("\x00").strip()
        elif tag == 4 and length >= 1:
            out[name] = val[0]
        elif tag in (5, 25) and length >= 4:
            out[name] = _iso_date(val)
        elif tag == 8 and length >= 1:
            out[name] = _SEX.get(val[0], "?")
        elif tag == 26 and length >= 3:
            out[name] = f"{val[0]:02d}:{val[1]:02d}:{val[2]:02d}"
        o += 3 + length
    return out


def full_name(patient: dict[str, object]) -> str:
    parts = (patient.get("first_name"), patient.get("last_name"))
    return " ".join(str(x) for x in parts if x)
