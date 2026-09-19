"""Векторная ЭКГ-лента: клиническая сетка, по дорожке на отведение."""

import numpy as np

from scp_holter.record import ScpHolter

GRID = ((1.0, "#f3c9c9", 0.5), (5.0, "#e08c8c", 0.9))
GAIN_STEPS = (10.0, 5.0, 2.5, 2.0, 1.0)


def _auto_gain(sig: np.ndarray, pick: list[int], row_mm: float) -> float:
    """Крупнейшее усиление из ряда, при котором самое размашистое отведение ещё влезает."""
    ptp = max(float(sig[c].max() - sig[c].min()) for c in pick) or 1.0
    for gain in GAIN_STEPS:
        if ptp * gain <= row_mm:
            return gain
    return row_mm / ptp


def _grid(parts: list[str], w_mm: float, h_mm: float, px_mm: float) -> None:
    width, height = w_mm * px_mm, h_mm * px_mm
    for step, colour, stroke in GRID:
        x = 0.0
        while x <= w_mm + 1e-6:
            parts.append(
                f'<line x1="{x * px_mm:.1f}" y1="0" x2="{x * px_mm:.1f}" '
                f'y2="{height:.1f}" stroke="{colour}" stroke-width="{stroke}"/>'
            )
            x += step
        y = 0.0
        while y <= h_mm + 1e-6:
            parts.append(
                f'<line x1="0" y1="{y * px_mm:.1f}" x2="{width:.1f}" '
                f'y2="{y * px_mm:.1f}" stroke="{colour}" stroke-width="{stroke}"/>'
            )
            y += step


def to_svg(
    rec: ScpHolter,
    out: str,
    start: float = 0.0,
    dur: float = 10.0,
    leads: list[str] | None = None,
    mm_s: float = 25.0,
    mm_mv: float | None = None,
    px_mm: float = 3.2,
    row_mm: float = 16.0,
) -> str:
    sig = rec.read(start, dur)
    names = rec.leads
    pick = list(range(len(names))) if not leads else [names.index(x) for x in leads]
    n = sig.shape[1]
    if mm_mv is None:
        mm_mv = _auto_gain(sig, pick, row_mm)

    w_mm, h_mm = dur * mm_s, row_mm * len(pick)
    width, height = w_mm * px_mm, h_mm * px_mm
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.1f} {height:.1f}"><rect width="100%" height="100%" fill="#fff"/>'
    ]
    _grid(parts, w_mm, h_mm, px_mm)

    for row, ch in enumerate(pick):
        base_mm = row_mm * row + row_mm / 2
        s = sig[ch]
        coarse = s[::7]
        lane_zero = float(sorted(coarse)[len(coarse) // 2])
        pts = []
        for i in range(n):
            x = (i / rec.fs) * mm_s * px_mm
            y = (base_mm - (s[i] - lane_zero) * mm_mv) * px_mm
            pts.append(f"{x:.1f},{y:.1f}")
        parts.append(
            '<polyline fill="none" stroke="#111" stroke-width="1.2" points="'
            + " ".join(pts)
            + '"/>'
        )
        parts.append(
            f'<text x="4" y="{(base_mm - 4.2) * px_mm:.1f}" font-family="monospace" '
            f'font-size="{3.2 * px_mm:.1f}" fill="#06c">{names[ch]}</text>'
        )

    parts.append(
        f'<text x="{width - 250:.0f}" y="{height - 6:.0f}" font-family="monospace" '
        f'font-size="12" fill="#444">{start:.0f}-{start + dur:.0f} s | '
        f"{mm_s:g} mm/s {mm_mv:g} mm/mV | {rec.fs:g} Hz</text></svg>"
    )
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("".join(parts))
    return out
