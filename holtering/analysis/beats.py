"""Per-beat audit of the device's V/S labels.

Every ectopic label gets features and a verdict with reasons, so a reviewer can
see WHY a label was demoted. Verdicts:

    double-count   coupling interval < 300 ms - physiologically impossible
    on-wave        amplitude < 50 % of the surrounding N complexes (label sits on a wave)
    noisy          local HF noise > 2.5x the record baseline
    narrow         V label but QRS not wider than sinus (not ventricular)
    sinus-shape    V label but the beat sits in a morphology family that is >90 % sinus
    not-premature  S label but the beat is not early vs the preceding sinus rate
    uncertain      V label with QRS 1.1-1.4x sinus width, or conflicting evidence
    likely         survives every test

Morphology-family evidence (see templates.py) is applied as a second pass by
`apply_family_evidence`: it is threshold-free with respect to QRS width, so it
overrides the width verdict whenever the family is decisive.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .quality import local_noise

VERDICT_RU = {
    "likely": "вероятная", "uncertain": "спорная", "double-count": "двойной счёт", "on-wave": "не на QRS",
    "noisy": "в помехе", "narrow": "узкий QRS", "not-premature": "не преждевременная",
    "sinus-shape": "синусовая морфология", "manual": "ручная", "manual-N": "ручная: N", "manual-X": "ручная: артефакт",
}

WIDTH_LEADS = [1, 7, 8]          # II + two strong chest channels
WIDTH_FRAC = 0.15                # slope threshold, calibrated on the median beat (80 ms)
WIDTH_GAP_S = 0.008              # bridged gap in the slope run (one sample at 125 Hz)
SLOPE_SMOOTH_S = 0.024           # |dx| smoother (3 samples at 125 Hz)
AMP_HALF_S, WIDTH_HALF_S, EDGE_S = 0.048, 0.16, 0.2


def _n(seconds: float, fs: int, at_least: int = 1) -> int:
    return max(at_least, int(round(seconds * fs)))


def qrs_duration_ms(x: np.ndarray, fs: int, frac: float = WIDTH_FRAC) -> float:
    """Span around the max-slope point where the smoothed |dx| stays above frac*max.
    Slope is taken over 8 ms and smoothed over 24 ms whatever the sample rate, so the
    threshold calibrated at 125 Hz means the same thing at 500 Hz."""
    gap, lag, sm = _n(WIDTH_GAP_S, fs), _n(0.008, fs), _n(SLOPE_SMOOTH_S, fs, 3)
    xf = x.astype(np.float64)
    d = np.abs(xf[lag:] - xf[:-lag])
    d = np.convolve(d, np.ones(sm) / sm, mode="same")
    pk = int(np.argmax(d)); thr = frac * d[pk]
    on = d > thr
    l = pk; miss = 0
    while l > 0:
        if on[l - 1]: l -= 1; miss = 0
        elif miss < gap: l -= 1; miss += 1
        else: break
    l += miss
    r = pk; miss = 0
    while r < len(on) - 1:
        if on[r + 1]: r += 1; miss = 0
        elif miss < gap: r += 1; miss += 1
        else: break
    r -= miss
    return (r - l + 1 + lag) * 1000.0 / fs


@dataclass
class BeatAudit:
    index: int
    t_ms: int
    label: str
    verdict: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    amp_ratio: float | None = None
    width_ms: float | None = None
    width_ratio: float | None = None
    noise_ratio: float | None = None
    rr_pre: int | None = None
    rr_post: int | None = None
    prematurity: float | None = None
    family: int | None = None
    family_n_frac: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class BeatAuditor:
    def __init__(self, mm: np.memmap, fs: int, mv_per_lsb: float, t_ms: np.ndarray, labels: np.ndarray,
                 noise_base_ii: float, noise10: np.ndarray, window_s: int):
        self.mm, self.fs, self.mv = mm, fs, mv_per_lsb
        self.t, self.lab = t_ms, labels
        self.n = mm.shape[1]
        self.noise_base = noise_base_ii
        self.noise10, self.window_s = noise10, window_s
        self.rr = np.diff(t_ms)
        self.amp_half, self.width_half, self.edge = _n(AMP_HALF_S, fs), _n(WIDTH_HALF_S, fs), _n(EDGE_S, fs)
        self.hour_amp = self._hourly_n_amplitude()
        self.n_width = self._sinus_width()

    # ---- calibration on N beats -----------------------------------------
    def _amp(self, i: int) -> float:
        s = np.asarray(self.mm[1, i - self.amp_half:i + self.amp_half + 1]).astype(np.float32) * self.mv
        return float(np.abs(s - np.median(s)).max())

    def _width(self, i: int) -> float:
        a, b = i - self.width_half, i + self.width_half + 1
        return float(np.median([qrs_duration_ms(np.asarray(self.mm[ch, a:b]), self.fs) for ch in WIDTH_LEADS]))

    def _sample_n(self, hour: int, per_hour: int, stride: int) -> list[int]:
        lo, hi = hour * 3.6e6, (hour + 1) * 3.6e6
        sel = np.where((self.lab == "N") & (self.t >= lo) & (self.t < hi))[0][::stride][:per_hour]
        return [int(self.t[k] * self.fs / 1000) for k in sel]

    def _hourly_n_amplitude(self) -> dict[int, float]:
        out = {}
        hours = int(self.t[-1] / 3.6e6) + 1
        for h in range(hours):
            idx = [i for i in self._sample_n(h, 150, 200) if self.amp_half + 1 <= i < self.n - self.amp_half - 1]
            out[h] = float(np.median([self._amp(i) for i in idx])) if idx else float("nan")
        return out

    def _sinus_width(self) -> float:
        hours = int(self.t[-1] / 3.6e6) + 1
        ws = []
        for h in range(hours):
            ws += [self._width(i) for i in self._sample_n(h, 40, 400) if self.width_half <= i < self.n - self.width_half - 1]
        return float(np.median(ws)) if ws else float("nan")

    # ---- audit ------------------------------------------------------------
    def audit(self, k: int) -> BeatAudit:
        t = int(self.t[k]); lab = str(self.lab[k])
        i = int(t * self.fs / 1000)
        h = min(int(t / 3.6e6), max(self.hour_amp))
        rr_pre = int(self.rr[k - 1]) if k > 0 else None
        rr_post = int(self.rr[k]) if k < len(self.rr) else None
        k = int(k)
        b = BeatAudit(index=k, t_ms=t, label=lab, verdict="likely", confidence=0.8,
                      rr_pre=rr_pre, rr_post=rr_post)
        if i < self.edge or i >= self.n - self.edge:
            b.verdict, b.confidence = "uncertain", 0.3
            b.reasons.append("edge of record")
            return b

        wi = min(len(self.noise10) - 1, int(t / 1000 / self.window_s))
        win_noise = float(self.noise10[wi])
        ref = self.hour_amp.get(h) or float("nan")
        b.amp_ratio = round(self._amp(i) / ref, 3) if ref == ref and ref > 0 else None
        b.noise_ratio = round(local_noise(self.mm, self.fs, self.mv, i) / self.noise_base, 2)
        b.width_ms = round(self._width(i), 1)
        b.width_ratio = round(b.width_ms / self.n_width, 2) if self.n_width == self.n_width else None

        # preceding sinus rate for prematurity
        prev = [self.rr[j] for j in range(max(0, k - 6), k - 1) if self.lab[j] == "N" and self.lab[j + 1] == "N"]
        if rr_pre is not None and prev:
            b.prematurity = round(rr_pre / float(np.median(prev)), 2)

        if rr_pre is not None and rr_pre < 300:
            b.verdict, b.confidence = "double-count", 0.95
            b.reasons.append(f"RR {rr_pre} мс: двойной счёт одного QRS")
        elif b.amp_ratio is not None and b.amp_ratio < 0.5:
            b.verdict, b.confidence = "on-wave", 0.9
            b.reasons.append(f"амплитуда {b.amp_ratio:.0%} от соседних N: метка не на QRS")
        elif b.noise_ratio > 2.5 or win_noise >= 0.5:
            b.verdict, b.confidence = "noisy", 0.5
            b.reasons.append(f"помеха в этом окне ({win_noise:.0%})" if win_noise >= 0.5
                             else ("сильный шум в этом месте" if b.noise_ratio >= 4 else "заметный шум в этом месте"))
        elif lab == "V":
            if b.width_ratio is not None and b.width_ratio >= 1.4:
                b.reasons.append(f"QRS {b.width_ms:.0f} мс при синусовом {self.n_width:.0f}")
                if b.noise_ratio > 1.5:
                    b.confidence = 0.6
                    b.reasons.append("умеренный шум в этом месте")
            elif b.width_ratio is not None and b.width_ratio < 1.1:
                b.verdict, b.confidence = "narrow", 0.7
                b.reasons.append(f"QRS {b.width_ms:.0f} мс, как синусовый ({self.n_width:.0f})")
            else:
                b.verdict, b.confidence = "uncertain", 0.5
                b.reasons.append(f"QRS {b.width_ms:.0f} мс при синусовом {self.n_width:.0f}: пограничная ширина")
        elif lab == "S":
            if b.prematurity is not None and b.prematurity > 0.9:
                b.verdict, b.confidence = "not-premature", 0.7
                b.reasons.append(f"не преждевременная: RR {b.rr_pre} мс, ритм до неё {b.rr_pre / b.prematurity:.0f}")
            else:
                b.reasons.append(f"преждевременная: RR {b.rr_pre} мс при ритме {b.rr_pre / b.prematurity:.0f}" if b.prematurity else "узкий QRS")
        return b

    def audit_all(self) -> list[BeatAudit]:
        return [self.audit(int(k)) for k in np.where(self.lab != "N")[0]]


FAMILY_MIN = 10          # smaller families carry no statistical weight
SINUS_FRAC = 0.90        # family this sinus-like cannot host a ventricular beat
DISTINCT_FRAC = 0.20     # family this un-sinus-like supports a ventricular beat


def apply_family_evidence(audits: list[BeatAudit], assign: np.ndarray, labels: np.ndarray) -> None:
    """Second audit pass using morphology families (in place)."""
    n_t = int(assign.max()) + 1 if len(assign) else 0
    size = np.bincount(assign[assign >= 0], minlength=n_t)
    n_cnt = np.bincount(assign[(assign >= 0) & (labels == "N")], minlength=n_t)
    v_cnt = np.bincount(assign[(assign >= 0) & (labels == "V")], minlength=n_t)
    for a in audits:
        f = int(assign[a.index])
        if f < 0:
            continue
        a.family = f
        n_frac = float(n_cnt[f] / size[f]); v_frac = float(v_cnt[f] / size[f])
        a.family_n_frac = round(n_frac, 3)
        if size[f] < FAMILY_MIN:
            continue
        fam_n = int(size[f])
        if a.label == "V" and a.verdict in ("likely", "uncertain", "narrow"):
            if n_frac > SINUS_FRAC:
                a.verdict, a.confidence = "sinus-shape", 0.85
                a.reasons.append(f"форма QRS как у синусовых: в её группе {fam_n} комплексов, {n_frac:.0%} из них N")
            elif n_frac < DISTINCT_FRAC:
                if a.verdict == "uncertain":
                    a.verdict, a.confidence = "likely", 0.8
                elif a.verdict == "narrow":
                    a.verdict, a.confidence = "uncertain", 0.5
                a.reasons.append(f"форма QRS отличается от синусовой: в её группе {v_frac:.0%} ЖЭС")
        elif a.label == "S" and a.verdict == "likely" and v_frac > 0.5:
            a.verdict, a.confidence = "uncertain", 0.5
            a.reasons.append(f"форма QRS желудочковая: в её группе {v_frac:.0%} ЖЭС")
