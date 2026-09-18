"""Numeric dumps: .npy (float32 mV matrix) and .csv (time column + one column
per lead). Both honour the record's polarity setting."""

from __future__ import annotations

from ..record import ScpHolter


def to_npy(rec: ScpHolter, out: str, start: float = 0.0, dur: float | None = None) -> str:
    import numpy as np

    np.save(out, rec.read(start, dur))
    return out


def to_csv(rec: ScpHolter, out: str, start: float = 0.0, dur: float | None = None) -> str:
    import numpy as np

    sig = rec.read(start, dur)
    t = (np.arange(sig.shape[1]) / rec.fs + start).astype(np.float32)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        fh.write("t_s," + ",".join(rec.leads) + "\n")
        for i in range(sig.shape[1]):
            fh.write(f"{t[i]:.4f}," + ",".join(f"{v:.4f}" for v in sig[:, i]) + "\n")
    return out
