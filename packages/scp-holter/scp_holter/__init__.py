"""Reader for LabTech EC-12H / CardioSpy SCP-ECG Holter exports (*_raw_ECG.scp).

The file is standard SCP-ECG (ISO 11073-91064) framing carrying 24 h of 12-lead
data in a single Section 6. Verified on a 259 MB / 23.99 h export: 125 Hz,
1747 nV/LSB as declared, 12 x 10 794 500 int16 LE samples stored lead-by-lead
from byte 445, R peaks matching the companion Qrs.txt within 1-2 samples.

Where the vendor deviates from the standard - and why generic SCP readers fail
on these files - is documented next to the code that copes with it:

    scp_holter.sections  zeroed "SCPECG" reserved field, section version 10
    scp_holter.leads     0-based channel indices instead of SCP lead codes,
                         plus the montage/polarity evidence and what is still
                         unproven (chest order, absolute gain)
    scp_holter.signal    u16 per-lead byte counts that overflow mod 65536
    scp_holter.export.edf strict-ASCII EDF+ headers, asymmetric digital range

Typical use:

    from scp_holter import ScpHolter, to_edf
    rec = ScpHolter("data/raw.scp")
    sig = rec.read(start_s=10800, dur_s=10)      # (12, 1250) float32 mV
    to_edf(rec, "out/full.edf")                  # lossless EDF+C, 1 s records
"""

from .export import to_csv, to_edf, to_npy, to_svg
from .leads import CHEST_ASC, CHEST_DESC, CHEST_NOTE, LIMB6, LeadDefs
from .patient import parse_patient
from .record import ScpHolter
from .sections import Container, Section, read_container
from .signal import SignalMeta

__all__ = [
    "CHEST_ASC", "CHEST_DESC", "CHEST_NOTE", "LIMB6",
    "Container", "LeadDefs", "ScpHolter", "Section", "SignalMeta",
    "parse_patient", "read_container",
    "to_csv", "to_edf", "to_npy", "to_svg",
]
