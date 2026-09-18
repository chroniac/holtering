"""Signal-quality index per window, on the 8 INDEPENDENT channels only.

III/aVR/aVL/aVF are exact linear combinations of I and II for this device, so
they must not vote: a single bad limb electrode would otherwise produce six
"confirming" noisy channels. Independent set = I, II and the six chest channels.
"""

from __future__ import annotations

import numpy as np

INDEPENDENT = [0, 1, 6, 7, 8, 9, 10, 11]
WINDOW_S = 2                    # quality is scored per 2 s so shading hugs the artefact
SMOOTH = 13                     # ~100 ms moving average at 125 Hz
STEP_MV = 0.5                   # sample-to-sample jump that never happens in clean ECG
RAIL = 32000                    # ADC saturation
WANDER_SMOOTH = 50              # 0.4 s moving average: keeps baseline drift, drops QRS/T
WANDER_MIN_MV = 1.5             # absolute floor for "drift" (respiration stays well below)
WANDER_RATIO = 4.0              # ...and it must also be 4x the channel's typical drift


def hf_residual(x: np.ndarray) -> np.ndarray:
    """High-frequency residual after a short moving average, along the last axis."""
    k = np.ones(SMOOTH) / SMOOTH
    if x.ndim == 1:
        return x - np.convolve(x, k, mode="same")
    return x - np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), -1, x)


def baseline(x: np.ndarray) -> np.ndarray:
    """Slow component (0.4 s moving average) along the last axis."""
    k = np.ones(WANDER_SMOOTH) / WANDER_SMOOTH
    if x.ndim == 1:
        return np.convolve(x, k, mode="same")
    return np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), -1, x)


def window_metrics(mm: np.memmap, fs: int, mv_per_lsb: float, window_s: int = WINDOW_S):
    """Per window and per independent channel: HF RMS (mV), step fraction, rail hits,
    baseline wander (peak-to-peak of the slow component, mV)."""
    n_win = mm.shape[1] // (fs * window_s)
    n_ch = len(INDEPENDENT)
    hf = np.zeros((n_win, n_ch), np.float32)
    steps = np.zeros((n_win, n_ch), np.float32)
    rails = np.zeros((n_win, n_ch), np.float32)
    wander = np.zeros((n_win, n_ch), np.float32)
    per_chunk = 1800                                      # windows per chunk (1 h)
    for w0 in range(0, n_win, per_chunk):
        w1 = min(n_win, w0 + per_chunk)
        a, b = w0 * fs * window_s, w1 * fs * window_s
        raw = np.asarray(mm[INDEPENDENT, a:b])
        x = raw.astype(np.float32) * mv_per_lsb          # (8, samples)
        k = w1 - w0
        xs = x.reshape(n_ch, k, fs * window_s)
        res = hf_residual(x).reshape(n_ch, k, fs * window_s)
        hf[w0:w1] = res.std(axis=2).T
        steps[w0:w1] = (np.abs(np.diff(xs, axis=2)) > STEP_MV).mean(axis=2).T
        rails[w0:w1] = (np.abs(raw.reshape(n_ch, k, fs * window_s)) >= RAIL).mean(axis=2).T
        slow = baseline(x).reshape(n_ch, k, fs * window_s)
        wander[w0:w1] = (slow.max(axis=2) - slow.min(axis=2)).T
    return hf, steps, rails, wander


def noise_score(hf: np.ndarray, steps: np.ndarray, rails: np.ndarray, wander: np.ndarray):
    """Two scores per window, 0 = clean, 1 = unusable; baselines are per-channel medians.

    `sharp`  : HF noise, impulsive steps, rail hits. This is what breaks QRS detection and
               morphology, so it is the only score that may demote a beat verdict.
    `drift`  : baseline wander (slow swing > WANDER_MIN_MV and > WANDER_RATIO x the
               channel's usual drift; 3x the threshold on any single channel -> 0.5,
               4x -> 1.0, or >= half the channels over threshold). Re-checked at the
               2 s window on a 24 h record: worst-channel ratio p98 = 2.0, p99 = 2.7,
               so 3x sits past p99 and 1.3 % of windows score >= 0.5 (10 s windows gave
               3.9 %, because each flagged window then carried 10 s of clean signal).
               Drift corrupts ST and amplitude readings, not QRS shape: it
               shades the window and counts against record quality, never against a beat.
    Returns (combined, sharp, hf_base)."""
    base = np.median(hf, axis=0) + 1e-6
    ratio = hf / base                                      # 1 = typical, 3+ = bad
    ch_bad = ((ratio > 2.5) | (steps > 0.15) | (rails > 0)).astype(np.float32)
    soft = np.clip((np.median(ratio, axis=1) - 1.0) / 2.0, 0, 1)
    sharp = np.maximum(ch_bad.mean(axis=1), soft).astype(np.float32)
    wbase = np.median(wander, axis=0) + 1e-6
    wthr = np.maximum(WANDER_MIN_MV, WANDER_RATIO * wbase)
    drift_frac = (wander > wthr).mean(axis=1)
    drift_soft = np.clip(((wander / wthr).max(axis=1) - 2.0) / 2.0, 0, 1)
    drift = np.maximum(drift_frac, drift_soft).astype(np.float32)
    return np.maximum(sharp, drift), sharp, base


def gap_artifact(mm: np.memmap, fs: int, mv_per_lsb: float, t0_ms: int, t1_ms: int,
                 qrs_amp_mv: float, hf_base_mv: float) -> tuple[bool, str]:
    """Is an RR gap signal loss / impulsive artifact rather than a quiet isoelectric pause?

    A real pause is a flat, quiet line. Window-level SQI dilutes a 2-s burst inside a
    10-s window, so the gap itself is inspected on the independent channels: rail hits,
    single-sample jumps > 5 mV, range > 3x the local QRS amplitude, or HF residual
    > 2.5x the record baseline all mean the detector went blind, not the heart.
    """
    a = int(t0_ms * fs / 1000) + 8; b = int(t1_ms * fs / 1000) - 8
    if b - a < fs // 4:
        return False, "интервал короче 250 мс"
    raw = np.asarray(mm[INDEPENDENT, a:b])
    x = raw.astype(np.float32) * mv_per_lsb
    rails = float((np.abs(raw) >= RAIL).mean())
    max_step = float(np.abs(np.diff(x, axis=1)).max())
    rng = float((x.max(axis=1) - x.min(axis=1)).max())
    hf = float(hf_residual(x[INDEPENDENT.index(1)]).std())
    if rails > 0:
        return True, f"зашкал АЦП, {rails:.0%} отсчётов"
    if max_step > 5.0:
        return True, f"скачок {max_step:.1f} мВ за отсчёт"
    if rng > 3.0 * qrs_amp_mv:
        return True, f"размах {rng:.1f} мВ, ×{rng / qrs_amp_mv:.1f} к QRS"
    if hf > 2.5 * hf_base_mv:
        return True, f"шум ×{hf / hf_base_mv:.1f} от нормы записи"
    return False, f"изолиния: размах {rng:.2f} мВ, шум ×{hf / hf_base_mv:.1f}"


def local_noise(mm: np.memmap, fs: int, mv_per_lsb: float, i: int, half_s: float = 0.5, ch: int = 1) -> float:
    a = max(0, i - int(half_s * fs)); b = min(mm.shape[1], i + int(half_s * fs))
    x = np.asarray(mm[ch, a:b]).astype(np.float32) * mv_per_lsb
    return float(hf_residual(x).std())


def missed_beat(mm: np.memmap, fs: int, mv_per_lsb: float, t0_ms: int, t1_ms: int,
                qrs_amp_mv: float) -> tuple[bool, str]:
    """Is there a QRS-sized, QRS-shaped deflection in the middle 60 % of an RR gap?

    Looks at lead II and two chest channels; requires a sharp peak (>= 50 % of the
    typical QRS amplitude, rising within ~40 ms) on at least two of them at the same
    place. Slow humps (T waves, drift) fail the sharpness test."""
    a = int(t0_ms * fs / 1000); b = int(t1_ms * fs / 1000)
    lo = a + int((b - a) * 0.2); hi = a + int((b - a) * 0.8)
    if hi - lo < fs // 5:
        return False, ""
    hits = 0; where = None
    for ch in (1, 7, 8):
        x = np.asarray(mm[ch, lo:hi]).astype(np.float32) * mv_per_lsb
        x = x - np.median(x)
        d = np.abs(np.diff(x))
        peak = int(np.argmax(np.abs(x)))
        sharp = d[max(0, peak - 5):peak + 5].max() if len(d) else 0.0
        if abs(x[peak]) >= 0.5 * qrs_amp_mv and sharp >= 0.25 * qrs_amp_mv:
            hits += 1; where = lo + peak
    if hits >= 2 and where is not None:
        return True, f"комплекс без метки на {hits} отведениях, через {int(where * 1000 / fs) - t0_ms} мс после предыдущего"
    return False, ""
