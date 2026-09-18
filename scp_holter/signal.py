"""Section 6 - rhythm data metadata and sample access.

Body layout: AVM(2, nV per LSB) interval(2, us) diff_used(1) bimodal(1)
followed by one u16 byte-count per lead, then the samples.

Two things make a generic reader fail here:

*   the per-lead byte counts are u16 and OVERFLOW on a 24 h record - they read
    27656 where the true value is 21_589_000 (= 27656 mod 65536). The real
    length has to come from the section length, never from those fields;
*   samples are stored lead-by-lead (all of lead 0, then all of lead 1, ...),
    not interleaved, and with Section 2 absent there is neither Huffman nor
    difference coding, so the block is a plain int16 LE matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO

from .sections import HEADER_LEN, Section, u16

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np

META_FIXED_LEN = 6
SAMPLE_BYTES = 2


@dataclass(slots=True)
class SignalMeta:
    avm_nv: int                 # nanovolts per LSB, as declared by the device
    interval_us: int
    diff_encoded: int
    bimodal: int
    data_offset: int            # absolute byte offset of the sample matrix
    n_leads: int
    n_samples: int              # per lead, derived from the section length

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


def memmap(path: str, meta: SignalMeta) -> "np.memmap":
    """Zero-copy (n_leads, n_samples) int16 view of the sample matrix."""
    import numpy as np

    return np.memmap(path, dtype="<i2", mode="r", offset=meta.data_offset,
                     shape=(meta.n_leads, meta.n_samples))


def read_lead(path: str, meta: SignalMeta, lead: int, a: int, b: int) -> "np.ndarray":
    """Raw int16 samples [a, b) of one lead, read straight from the file.

    Unlike slicing the memmap this does not map the touched pages into the process
    (the OS may still cache them), so a sequential pass over a 24 h record leaves
    RSS where it was."""
    import numpy as np

    if not 0 <= lead < meta.n_leads:
        raise IndexError(f"lead {lead} out of range 0..{meta.n_leads - 1}")
    a = max(0, a); b = min(meta.n_samples, b)
    if b <= a:
        return np.empty(0, "<i2")
    off = meta.data_offset + (lead * meta.n_samples + a) * SAMPLE_BYTES
    return np.fromfile(path, dtype="<i2", count=b - a, offset=off)


def sample_window(meta: SignalMeta, start_s: float, dur_s: float | None) -> tuple[int, int]:
    """Clamp a seconds range to an inclusive-exclusive sample range."""
    a = max(0, min(meta.n_samples, int(round(start_s * meta.fs))))
    n = meta.n_samples - a if dur_s is None else int(round(dur_s * meta.fs))
    return a, max(a, min(meta.n_samples, a + n))
