"""ScpHolter - the record facade tying the section parsers together."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from . import leads as leads_mod
from . import signal as signal_mod
from .patient import full_name, parse_patient
from .sections import read_body, read_container

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np

HUFFMAN_SECTION = 2
PATIENT_SECTION = 1
LEADS_SECTION = 3
RHYTHM_SECTION = 6


class ScpHolter:
    """A LabTech EC-12H SCP-ECG Holter export.

    `invert=True` negates every sample on read and on export; see
    `scp_holter.leads` for why the stored sign is ambiguous for this device.
    """

    def __init__(self, path: str, invert: bool = False):
        self.path = path
        self.sign = -1 if invert else 1
        self.size = os.path.getsize(path)
        with open(path, "rb") as fh:
            self.container = read_container(fh)
            self.patient = (parse_patient(read_body(fh, self.container[PATIENT_SECTION]))
                            if PATIENT_SECTION in self.container else {})
            self.lead_defs = leads_mod.parse_leads(read_body(fh, self.container[LEADS_SECTION]))
            self.meta = signal_mod.parse_signal(
                fh, self.container[RHYTHM_SECTION], self.lead_defs.count,
                huffman=HUFFMAN_SECTION in self.container,
            )

    # ---- shorthands used all over the exporters ----------------------
    @property
    def leads(self) -> list[str]:
        return self.lead_defs.labels

    @leads.setter
    def leads(self, labels: list[str]) -> None:
        if len(labels) != self.lead_defs.count:
            raise ValueError(f"expected {self.lead_defs.count} labels, got {len(labels)}")
        self.lead_defs.labels = list(labels)

    @property
    def n_leads(self) -> int:
        return self.lead_defs.count

    @property
    def n_samples(self) -> int:
        return self.meta.n_samples

    @property
    def fs(self) -> float:
        return self.meta.fs

    @property
    def avm_nv(self) -> int:
        return self.meta.avm_nv

    @property
    def duration_s(self) -> float:
        return self.meta.duration_s

    @property
    def inverted(self) -> bool:
        return self.sign < 0

    def set_chest_labels(self, chest: list[str]) -> None:
        self.leads = leads_mod.relabel_chest(self.lead_defs.count, chest)

    # ---- data access -------------------------------------------------
    def memmap(self) -> "np.memmap":
        return signal_mod.memmap(self.path, self.meta)

    def read_lead(self, lead: int, a: int, b: int) -> "np.ndarray":
        """Raw int16 samples [a, b) of one lead via a plain file read (see signal.read_lead);
        the stored sign, not `invert` - callers scale with a signed mV/LSB."""
        return signal_mod.read_lead(self.path, self.meta, lead, a, b)

    def read(self, start_s: float = 0.0, dur_s: float | None = None, mv: bool = True):
        """Samples as (n_leads, n) - float32 mV by default, else raw int16."""
        import numpy as np

        a, b = signal_mod.sample_window(self.meta, start_s, dur_s)
        raw = self.memmap()[:, a:b]
        if not mv:
            return np.array(raw) * self.sign
        return raw.astype(np.float32) * (self.sign * self.meta.mv_per_lsb)

    # ---- reporting ---------------------------------------------------
    def describe(self) -> str:
        p, m = self.patient, self.meta
        return "\n".join([
            f"file            : {self.path}",
            f"size            : {self.size:,} bytes (header says {self.container.declared_size:,})",
            f"patient         : {full_name(p)}  id={p.get('patient_id')} sex={p.get('sex')} "
            f"age={p.get('age')} dob={p.get('dob')}",
            f"recorded        : {p.get('acq_date')} {p.get('acq_time')}",
            f"sections        : {sorted(self.container.sections)}",
            f"channels        : {self.n_leads} -> {', '.join(self.leads)}",
            f"chest labels    : ch6..ch11 {leads_mod.CHEST_NOTE} (--chest to relabel)",
            f"sample rate     : {m.fs:g} Hz (interval {m.interval_us} us)",
            f"resolution      : {m.avm_nv} nV/LSB  (+-{m.range_mv:.2f} mV range)",
            f"samples/lead    : {m.n_samples:,}",
            f"duration        : {m.duration_s:,.1f} s = {m.duration_s / 3600:.2f} h",
            f"layout          : int16 LE, lead-sequential, data starts at byte {m.data_offset}",
            f"polarity        : {'INVERTED (--invert)' if self.inverted else 'as stored'}",
        ])
