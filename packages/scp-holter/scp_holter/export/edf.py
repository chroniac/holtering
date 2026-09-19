"""Запись EDF+C: записи по 1 секунде, int16 без пересчёта, без потерь."""

import numpy as np

from scp_holter.leads import CHEST_NOTE, LIMB6
from scp_holter.record import ScpHolter

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
CHUNK_SECONDS = 600

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "і": "i", "ғ": "g", "қ": "q", "ң": "ng", "ө": "o", "ұ": "u", "ү": "u",
    "һ": "h", "ә": "a",
}  # fmt: skip


def field(value: object, width: int) -> bytes:
    """Одно поле заголовка EDF: строгий ASCII фиксированной ширины, добитый пробелами."""
    b = str(value).encode("ascii", "replace")[:width]
    return b + b" " * (width - len(b))


def translit(s: str | None) -> str:
    out: list[str] = []
    for ch in s or "":
        low = ch.lower()
        if low in _CYRILLIC:
            rep = _CYRILLIC[low]
            out.append(rep.capitalize() if ch.isupper() and rep else rep)
        elif ord(ch) < 128:
            out.append(ch)
    return "".join(out)


def edf_date(iso: object, fallback: str = "X") -> str:
    """ISO yyyy-mm-dd -> EDF+ dd-MMM-yyyy."""
    try:
        y, m, d = (int(x) for x in str(iso).split("-"))
        return f"{d:02d}-{MONTHS[m - 1]}-{y:04d}"
    except Exception:
        return fallback


def _patient_field(patient: dict[str, object]) -> str:
    name = translit(f"{patient.get('first_name', '')}_{patient.get('last_name', '')}")
    name = name.strip("_ ").replace(" ", "_")
    return (
        f"{patient.get('patient_id', 'X')} {patient.get('sex', 'X')} "
        f"{edf_date(patient.get('dob', ''))} {name or 'X'}"
    )


def _transducer(rec: ScpHolter, i: int) -> str:
    return "Holter limb" if i < len(LIMB6) else f"Holter chest; {CHEST_NOTE}"


def to_edf(
    rec: ScpHolter, out: str, start: float = 0.0, dur: float | None = None
) -> tuple[str, int]:
    fs = round(rec.fs)
    if abs(fs - rec.fs) > 1e-9:
        raise ValueError(f"non-integer sample rate: {rec.fs} Hz")

    a = round(start * fs)
    total = rec.n_samples - a if dur is None else round(dur * fs)
    total = max(0, min(total, rec.n_samples - a))
    nrec = total // fs
    nl = rec.n_leads

    p = rec.patient
    acq_date = str(p.get("acq_date") or "1985-01-01").split("-")
    acq_time = str(p.get("acq_time") or "00:00:00").split(":")
    # 1 LSB обязан равняться объявленному AVM, поэтому физический диапазон тоже асимметричен.
    phys_min = -32768 * rec.avm_nv / 1e6
    phys_max = 32767 * rec.avm_nv / 1e6

    signal_fields = (
        (lambda i: rec.leads[i], 16),
        (lambda i: _transducer(rec, i), 80),
        (lambda i: "mV", 8),
        (lambda i: f"{phys_min:.4f}", 8),
        (lambda i: f"{phys_max:.4f}", 8),
        (lambda i: -32768, 8),
        (lambda i: 32767, 8),
        (lambda i: "HP:0.05Hz", 80),
        (lambda i: fs, 8),
        (lambda i: "", 32),
    )

    with open(out, "wb") as fh:
        fh.write(field(0, 8))
        fh.write(field(_patient_field(p), 80))
        fh.write(
            field(
                f"Startdate {edf_date(p.get('acq_date', ''), '01-JAN-1985')} X X LabTech_EC-12H",
                80,
            )
        )
        fh.write(field(f"{int(acq_date[2]):02d}.{int(acq_date[1]):02d}.{acq_date[0][2:]}", 8))
        fh.write(field(f"{int(acq_time[0]):02d}.{int(acq_time[1]):02d}.{int(acq_time[2]):02d}", 8))
        fh.write(field(256 * (nl + 1), 8))
        fh.write(field("EDF+C", 44))
        fh.write(field(nrec, 8))
        fh.write(field(1, 8))
        fh.write(field(nl, 4))
        for render, width in signal_fields:
            for i in range(nl):
                fh.write(field(render(i), width))

        mm = rec.memmap()
        for r0 in range(0, nrec, CHUNK_SECONDS):
            k = min(CHUNK_SECONDS, nrec - r0)
            blk = np.asarray(mm[:, a + r0 * fs : a + (r0 + k) * fs])
            blk = blk.reshape(nl, k, fs).transpose(1, 0, 2)
            if rec.inverted:
                blk = np.clip(-blk.astype(np.int32), -32768, 32767)
            fh.write(np.ascontiguousarray(blk, dtype="<i2").tobytes())
    return out, nrec
