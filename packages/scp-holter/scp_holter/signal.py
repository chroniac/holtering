"""Секция 6: метаданные ритма и доступ к отсчётам (см. docs/modules/scp-holter.md)."""

from dataclasses import dataclass
from typing import BinaryIO

import numpy as np

from .sections import HEADER_LEN, Section, u16

META_FIXED_LEN = 6
SAMPLE_BYTES = 2


@dataclass(slots=True)
class SignalMeta:
    avm_nv: int
    interval_us: int
    diff_encoded: int
    bimodal: int
    data_offset: int
    n_leads: int
    n_samples: int

    @property
    def fs(self) -> float:
        return 1e6 / self.interval_us

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.fs

    @property
    def mv_per_lsb(self) -> float:
        return self.avm_nv / 1e6

    @property
    def range_mv(self) -> float:
        return 32768 * self.mv_per_lsb


def parse_signal(fh: BinaryIO, sec: Section, n_leads: int, huffman: bool) -> SignalMeta:
    fh.seek(sec.body_offset)
    meta = fh.read(META_FIXED_LEN + SAMPLE_BYTES * n_leads)
    diff, bimodal = meta[4], meta[5]
    if diff or huffman:
        raise NotImplementedError("difference- or Huffman-encoded section 6")

    # Счётчики байт на отведение — u16 и переполняются, длину даёт только сама секция.
    payload = sec.length - HEADER_LEN - len(meta)
    stride = SAMPLE_BYTES * n_leads
    if payload % stride:
        raise ValueError("section 6 payload is not divisible by the channel count")
    return SignalMeta(
        avm_nv=u16(meta, 0),
        interval_us=u16(meta, 2),
        diff_encoded=diff,
        bimodal=bimodal,
        data_offset=sec.body_offset + len(meta),
        n_leads=n_leads,
        n_samples=payload // stride,
    )


def memmap(path: str, meta: SignalMeta) -> np.memmap[tuple[int, int], np.dtype[np.int16]]:
    """Матрица отсчётов (n_leads, n_samples) int16 без копирования."""
    return np.memmap(
        path,
        dtype="<i2",
        mode="r",
        offset=meta.data_offset,
        shape=(meta.n_leads, meta.n_samples),
    )


def read_lead(path: str, meta: SignalMeta, lead: int, a: int, b: int) -> np.ndarray:
    """Сырые int16 отсчёты [a, b) одного отведения — чтением из файла, не через memmap."""
    if not 0 <= lead < meta.n_leads:
        raise IndexError(f"lead {lead} out of range 0..{meta.n_leads - 1}")
    a = max(0, a)
    b = min(meta.n_samples, b)
    if b <= a:
        return np.empty(0, "<i2")
    off = meta.data_offset + (lead * meta.n_samples + a) * SAMPLE_BYTES
    return np.fromfile(path, dtype="<i2", count=b - a, offset=off)


def sample_window(meta: SignalMeta, start_s: float, dur_s: float | None) -> tuple[int, int]:
    """Секундный диапазон → полуинтервал отсчётов [a, b), прижатый к границам записи."""
    a = max(0, min(meta.n_samples, round(start_s * meta.fs)))
    n = meta.n_samples - a if dur_s is None else round(dur_s * meta.fs)
    return a, max(a, min(meta.n_samples, a + n))
