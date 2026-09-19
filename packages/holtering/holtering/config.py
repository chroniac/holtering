"""Runtime configuration: where the record lives and when it started."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_FNAME_DATE = re.compile(r"DATE(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})")


@dataclass(frozen=True)
class Config:
    scp: Path
    qrs: Path
    start: datetime          # wall-clock time of sample 0
    cache_dir: Path
    host: str = "127.0.0.1"
    port: int = 8790
    chest: tuple[str, ...] | None = None      # relabel channels 6.. (e.g. V1..V6) once the montage is confirmed
    invert: bool = False
    gain: float | None = None                 # amplitude factor measured against a CardioSpy printout; None = uncalibrated

    @property
    def cache_file(self) -> Path:
        st = self.scp.stat()
        g = f"-g{self.gain:g}" if self.gain is not None else ""
        inv = "-inv" if self.invert else ""
        return self.cache_dir / f"{self.scp.stem}-{st.st_size}-{int(st.st_mtime)}{g}{inv}.json"


def _guess_start(scp: Path) -> datetime | None:
    m = _FNAME_DATE.search(scp.name)
    if m:
        y, mo, d, h, mi, s = (int(x) for x in m.groups())
        return datetime(y, mo, d, h, mi, s)
    return None


def load(argv: list[str] | None = None) -> Config:
    import argparse

    ap = argparse.ArgumentParser(prog="holtering")
    ap.add_argument("--data", default=os.environ.get("HOLTERING_DATA", "data"),
                    help="directory with raw.scp + qrs.txt (or explicit --scp/--qrs)")
    ap.add_argument("--scp", default=os.environ.get("HOLTERING_SCP"))
    ap.add_argument("--qrs", default=os.environ.get("HOLTERING_QRS"))
    ap.add_argument("--start", default=os.environ.get("HOLTERING_START"),
                    help="wall-clock start 'YYYY-MM-DD HH:MM:SS'; default: from file name, else section 1")
    ap.add_argument("--chest", default=os.environ.get("HOLTERING_CHEST"),
                    help="comma list for channels 6.., e.g. V1,V2,V3,V4,V5,V6 (default: neutral ch6..ch11)")
    ap.add_argument("--invert", action="store_true", help="negate all samples (see scp_holter.leads)")
    ap.add_argument("--gain", type=float, default=os.environ.get("HOLTERING_GAIN"),
                    help="multiply the file's declared mV/LSB by this factor, measured against a CardioSpy printout; "
                         "until given, the voltage scale is treated as uncalibrated (no mV bar on printouts)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    a = ap.parse_args(argv)

    data = Path(a.data)
    scp = Path(a.scp) if a.scp else data / "raw.scp"
    qrs = Path(a.qrs) if a.qrs else data / "qrs.txt"
    if not scp.exists() or not qrs.exists():
        ap.error(f"need {scp} and {qrs}")

    if a.start:
        start = datetime.fromisoformat(a.start)
    else:
        start = _guess_start(scp)
        if start is None:
            from scp_holter import ScpHolter
            p = ScpHolter(str(scp)).patient
            start = datetime.fromisoformat(f"{p.get('acq_date', '1985-01-01')} {p.get('acq_time', '00:00:00')}")
    cfg = Config(scp=scp, qrs=qrs, start=start, cache_dir=ROOT / "cache", host=a.host, port=a.port,
                 chest=tuple(a.chest.split(",")) if a.chest else None, invert=a.invert,
                 gain=float(a.gain) if a.gain is not None else None)
    cfg.cache_dir.mkdir(exist_ok=True)
    return cfg
