"""Чтение SCP-ECG выгрузок LabTech EC-12H / CardioSpy (docs/modules/scp-holter.md)."""

from .export import to_csv, to_edf, to_npy, to_svg
from .leads import CHEST_ASC, CHEST_DESC, CHEST_NOTE, LIMB6, LeadDefs
from .patient import parse_patient
from .record import ScpHolter
from .sections import Container, Section, read_container
from .signal import SignalMeta

__all__ = [
    "CHEST_ASC",
    "CHEST_DESC",
    "CHEST_NOTE",
    "LIMB6",
    "Container",
    "LeadDefs",
    "ScpHolter",
    "Section",
    "SignalMeta",
    "parse_patient",
    "read_container",
    "to_csv",
    "to_edf",
    "to_npy",
    "to_svg",
]
