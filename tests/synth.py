"""Синтетическая запись LabTech в формате, который читает `scp_holter`: 12 отведений, 125 Гц,
известные удары и известные ошибки прибора — чтобы тесты и смоук не зависели от реальных данных."""

from __future__ import annotations

import binascii
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

FS = 125
AVM_NV = 1747
N_LEADS = 12
SECTION_VERSION = 10
HEADER_LEN = 16
LIMB_AMP = {"I": 0.7, "II": 1.5}
CHEST_AMP = [0.5, 1.2, 2.0, 2.5, 2.0, 1.5]


@dataclass(frozen=True)
class Beat:
    t_ms: int
    kind: str  # N | V | S — что бьётся на самом деле; X — метки без удара (двойной счёт)
    label: str  # что написал прибор


@dataclass
class Synthetic:
    scp: Path
    qrs: Path
    seconds: int
    beats: list[Beat] = field(default_factory=list)
    pause_ms: tuple[int, int] | None = None
    noise_s: tuple[int, int] | None = None

    @property
    def fs(self) -> int:
        return FS

    @property
    def n_samples(self) -> int:
        return self.seconds * FS


def _gauss(t: np.ndarray, centre_s: float, sigma_s: float, amp: float) -> np.ndarray:
    return amp * np.exp(-0.5 * ((t - centre_s) / sigma_s) ** 2)


def _beat_shape(t: np.ndarray, centre_s: float, amp: float, kind: str) -> np.ndarray:
    """Форма одного удара в мВ на сетке `t` (с): P-QRS-T для N/S, широкий QRS без P для V."""
    if kind == "V":
        return _gauss(t, centre_s, 0.030, 1.6 * amp) - _gauss(t, centre_s + 0.30, 0.06, 0.5 * amp)
    p = _gauss(t, centre_s - 0.16, 0.025, 0.1) if kind == "N" else 0.0
    qrs = (
        _gauss(t, centre_s, 0.012, amp)
        - _gauss(t, centre_s - 0.03, 0.008, 0.15 * amp)
        - _gauss(t, centre_s + 0.03, 0.008, 0.25 * amp)
    )
    return p + qrs + _gauss(t, centre_s + 0.25, 0.05, 0.3)


def _rhythm(seconds: int, rng: np.random.Generator) -> tuple[list[Beat], tuple[int, int]]:
    """Синус 70/мин с лёгкой вариабельностью и вкраплениями: пара ЖЭС, три НЖЭС, ложная V,
    двойной счёт, пауза 2.5 с."""
    rr = 857
    beats: list[Beat] = []
    t = 600
    n = 0
    pause: tuple[int, int] | None = None
    ectopic_at = {
        80: "V-pair",
        150: "S",
        230: "S",
        300: "fakeV",
        360: "double",
        420: "S",
        480: "pause",
    }
    while t < seconds * 1000 - 1000:
        event = ectopic_at.get(n)
        beats.append(Beat(t, "N", "N"))
        n += 1
        step = int(rr * (1 + rng.normal(0, 0.02)))
        if event == "V-pair":
            t1 = t + int(0.6 * rr)
            t2 = t1 + int(0.55 * rr)
            beats += [Beat(t1, "V", "V"), Beat(t2, "V", "V")]
            t = t + 2 * step + int(0.4 * rr)
            continue
        if event == "S":
            t1 = t + int(0.65 * rr)
            beats.append(Beat(t1, "S", "S"))
            t = t1 + int(1.15 * rr)
            continue
        if event == "fakeV":
            beats[-1] = Beat(t, "N", "V")
        if event == "double":
            beats.append(Beat(t + 200, "X", "N"))
        if event == "pause":
            pause = (t, t + 2500)
            t += 2500
            continue
        t += step
    beats.sort(key=lambda b: b.t_ms)
    assert pause is not None
    return beats, pause


def _lead_signal(
    beats: list[Beat], seconds: int, amp: float, rng: np.random.Generator
) -> np.ndarray:
    n = seconds * FS
    t = np.arange(n) / FS
    x = 0.2 * np.sin(2 * np.pi * 0.15 * t) + rng.normal(0, 0.01, n)
    half = int(0.5 * FS)
    for b in beats:
        if b.kind == "X":
            continue
        i = round(b.t_ms * FS / 1000)
        a, z = max(0, i - half), min(n, i + half + 1)
        x[a:z] += _beat_shape(t[a:z], b.t_ms / 1000, amp, b.kind)
    return x


def _section(sid: int, body: bytes) -> bytes:
    head = struct.pack("<HHIBB6x", 0, sid, HEADER_LEN + len(body), SECTION_VERSION, SECTION_VERSION)
    crc = binascii.crc_hqx(head[2:] + body, 0xFFFF)
    return struct.pack("<H", crc) + head[2:] + body


@dataclass(frozen=True)
class PatientStub:
    last_name: str
    first_name: str
    patient_id: str
    age: int
    dob: tuple[int, int, int]
    sex: str
    acq_date: tuple[int, int, int]
    acq_time: tuple[int, int, int]


def _section1(patient: PatientStub) -> bytes:
    def tag(t: int, value: bytes) -> bytes:
        return struct.pack("<BH", t, len(value)) + value

    def text(s: str, width: int) -> bytes:
        return s.encode("cp1251").ljust(width, b"\x00")

    body = (
        tag(0, text(patient.last_name, 16))
        + tag(1, text(patient.first_name, 16))
        + tag(2, text(patient.patient_id, 8))
        + tag(4, bytes([patient.age]))
        + tag(5, struct.pack("<HBB", *patient.dob))
        + tag(8, bytes([1 if patient.sex == "M" else 2]))
        + tag(25, struct.pack("<HBB", *patient.acq_date))
        + tag(26, bytes(patient.acq_time))
        + tag(255, b"")
    )
    return _section(1, body)


def _section3(n_samples: int) -> bytes:
    body = bytes([N_LEADS, 0]) + b"".join(
        struct.pack("<IIB", 1, n_samples, ch) for ch in range(N_LEADS)
    )
    return _section(3, body)


def _section6(samples: np.ndarray) -> bytes:
    n_bytes = samples.shape[1] * 2
    # Байт-счётчики u16 переполняются на длинной записи ровно как у прибора: длина берётся из секции.
    meta = struct.pack("<HHBB", AVM_NV, 1_000_000 // FS, 0, 0) + b"".join(
        struct.pack("<H", n_bytes & 0xFFFF) for _ in range(N_LEADS)
    )
    return _section(6, meta + samples.astype("<i2").tobytes())


def _container(sections: dict[int, bytes]) -> bytes:
    """Преамбула + секция 0 с указателями (1-based) + секции по порядку."""
    n_entries = len(sections) + 1
    sec0_len = HEADER_LEN + 10 * n_entries
    offset = 6 + sec0_len
    pointers = [struct.pack("<HII", 0, sec0_len, 7)]
    for sid, blob in sections.items():
        pointers.append(struct.pack("<HII", sid, len(blob), offset + 1))
        offset += len(blob)
    sec0 = _section(0, b"".join(pointers))
    rest = sec0 + b"".join(sections.values())
    total = 6 + len(rest)
    body = struct.pack("<I", total) + rest
    return struct.pack("<H", binascii.crc_hqx(body, 0xFFFF)) + body


PATIENT = PatientStub(
    last_name="Тестов",
    first_name="Тест",
    patient_id="T-0001",
    age=54,
    dob=(1972, 3, 9),
    sex="M",
    acq_date=(2026, 9, 17),
    acq_time=(9, 30, 0),
)


def write_record(directory: Path, seconds: int = 600, seed: int = 1) -> Synthetic:
    """`raw.scp` + `qrs.txt` в `directory`; возвращает правду о записи для проверок."""
    rng = np.random.default_rng(seed)
    beats, pause = _rhythm(seconds, rng)
    lead_i = _lead_signal(beats, seconds, LIMB_AMP["I"], rng)
    lead_ii = _lead_signal(beats, seconds, LIMB_AMP["II"], rng)
    chest = [_lead_signal(beats, seconds, a, rng) for a in CHEST_AMP]
    # ЖЭС в двух грудных каналах — противоположной полярности, как у настоящей широкой ЖЭС.
    for ch in (1, 2):
        v_mask = np.zeros(seconds * FS, bool)
        for b in beats:
            if b.kind == "V":
                i = round(b.t_ms * FS / 1000)
                v_mask[max(0, i - 60) : i + 60] = True
        chest[ch][v_mask] *= -1
    noise_s = (seconds * 4 // 5, seconds * 4 // 5 + 40)
    mv = np.stack(
        [
            lead_i,
            lead_ii,
            lead_ii - lead_i,
            -(lead_i + lead_ii) / 2,
            lead_i - lead_ii / 2,
            lead_ii - lead_i / 2,
            *chest,
        ]
    )
    a, z = noise_s[0] * FS, noise_s[1] * FS
    mv[:, a:z] += rng.normal(0, 0.4, (N_LEADS, z - a))
    samples = np.clip(np.round(mv / (AVM_NV / 1e6)), -32768, 32767).astype(np.int16)

    scp = directory / "raw.scp"
    qrs = directory / "qrs.txt"
    scp.write_bytes(
        _container({1: _section1(PATIENT), 3: _section3(samples.shape[1]), 6: _section6(samples)})
    )
    qrs.write_text("".join(f"{b.t_ms}\t{b.label}\n" for b in beats), encoding="cp1251")
    return Synthetic(
        scp=scp, qrs=qrs, seconds=seconds, beats=beats, pause_ms=pause, noise_s=noise_s
    )


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    out.mkdir(parents=True, exist_ok=True)
    rec = write_record(out, seconds=int(sys.argv[2]) if len(sys.argv) > 2 else 600)
    sys.stdout.write(f"{rec.scp} {rec.scp.stat().st_size} B, {len(rec.beats)} beats\n")
