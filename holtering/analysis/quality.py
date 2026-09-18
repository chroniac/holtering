"""Signal-quality index per window, on the 8 INDEPENDENT channels only.

III/aVR/aVL/aVF are exact linear combinations of I and II for this device, so
they must not vote: a single bad limb electrode would otherwise produce six
"confirming" noisy channels. Independent set = I, II and the six chest channels.
"""

from __future__ import annotations

import numpy as np

INDEPENDENT = [0, 1, 6, 7, 8, 9, 10, 11]
WINDOW_S = 2                    # quality is scored per 2 s so shading hugs the artefact
SMOOTH_S = 0.104                # ~100 ms moving average (13 samples at 125 Hz, where it was tuned)
STEP_S = 0.008                  # jump measured over 8 ms (one sample at 125 Hz)...
STEP_MV = 0.5                   # ...of 0.5 mV never happens in clean ECG
RAIL = 32000                    # ADC saturation
WANDER_S = 0.4                  # 0.4 s moving average: keeps baseline drift, drops QRS/T
WANDER_MIN_MV = 1.5             # absolute floor for "drift" (respiration stays well below)
WANDER_RATIO = 4.0              # ...and it must also be 4x the channel's typical drift


def samples(seconds: float, fs: int, at_least: int = 1) -> int:
    """Window lengths are defined in seconds and derived per record: a 500 Hz recording
    must get the same 100 ms smoother, not 13 samples of 26 ms."""
    return max(at_least, int(round(seconds * fs)))


def running_sum(x: np.ndarray, dtype=np.float64) -> np.ndarray:
    """c[i] = sum(x[:i]) along the last axis, length n+1. int64 on raw int16 is exact."""
    n = x.shape[-1]
    c = np.zeros(x.shape[:-1] + (n + 1,), dtype)
    np.cumsum(x, axis=-1, dtype=dtype, out=c[..., 1:])
    return c


def box_from_sum(c: np.ndarray, k: int, scale: float = 1.0) -> np.ndarray:
    """Moving average of width k from a running sum, with exactly the alignment and
    zero-padded edges of np.convolve(x, ones(k)/k, mode="same"): O(n), one slice
    difference for the interior and two short ones for the edges. `scale` folds a
    unit conversion (mV per LSB) into the final multiply."""
    n = c.shape[-1] - 1
    hi, lo = (k - 1) // 2 + 1, k // 2                   # out[i] = c[min(i+hi, n)] - c[max(i-lo, 0)]
    out = np.empty(c.shape[:-1] + (n,), np.float64)
    if n <= k:                                          # window covers everything: clip both ends
        i = np.arange(n)
        out[...] = c[..., np.minimum(i + hi, n)] - c[..., np.maximum(i - lo, 0)]
    else:
        out[..., lo:n - hi + 1] = c[..., lo + hi:n + 1] - c[..., 0:n - hi + 1 - lo]
        out[..., :lo] = c[..., hi:hi + lo] - c[..., :1]
        out[..., n - hi + 1:] = c[..., n:] - c[..., n - hi + 1 - lo:n - lo]
    out *= scale / k
    return out


def box_same(x: np.ndarray, k: int) -> np.ndarray:
    """np.convolve(x, ones(k)/k, mode="same") in O(n) instead of O(n*k); float64
    accumulation keeps it within 1e-12 of the direct convolution."""
    return box_from_sum(running_sum(x), k)


def hf_residual(x: np.ndarray, fs: int) -> np.ndarray:
    """High-frequency residual after a ~100 ms moving average, along the last axis."""
    return x - box_same(x, samples(SMOOTH_S, fs))


def baseline(x: np.ndarray, fs: int) -> np.ndarray:
    """Slow component (0.4 s moving average) along the last axis."""
    return box_same(x, samples(WANDER_S, fs))


def window_metrics(read, n_samples: int, fs: int, mv_per_lsb: float, window_s: int = WINDOW_S):
    """Per window and per independent channel: HF RMS (mV), step fraction, rail hits,
    baseline wander (peak-to-peak of the slow component, mV).

    `read(ch, a, b)` returns raw int16 samples; it is called one channel and one hour at
    a time so the working set stays at a few tens of MB whatever the record length or
    sample rate (a memmap would pin every page it touched into RSS)."""
    from concurrent.futures import ThreadPoolExecutor

    win = fs * window_s
    n_win = n_samples // win
    n_ch = len(INDEPENDENT)
    hf = np.zeros((n_win, n_ch), np.float32)
    steps = np.zeros((n_win, n_ch), np.float32)
    rails = np.zeros((n_win, n_ch), np.float32)
    wander = np.zeros((n_win, n_ch), np.float32)
    per_chunk = max(1, 450_000 // win)                   # ~450k samples per channel-chunk (1 h at 125 Hz):
    step_lsb = STEP_MV / abs(mv_per_lsb)                  # temporaries stay ~20 MB per worker at any sample rate
    k_hf, k_slow, lag = samples(SMOOTH_S, fs), samples(WANDER_S, fs), samples(STEP_S, fs)

    def one(ci: int, ch: int, a: int, b: int, w0: int, w1: int) -> None:
        k = w1 - w0
        raw = read(ch, a, b)
        rr = raw.reshape(k, win)
        # one exact integer running sum feeds both moving averages
        c = running_sum(raw, np.int64)
        x = raw * mv_per_lsb                              # float64, no float32 rounding
        res = (x - box_from_sum(c, k_hf, mv_per_lsb)).reshape(k, win)
        hf[w0:w1, ci] = res.std(axis=1)
        r32 = rr.astype(np.int32)
        steps[w0:w1, ci] = (np.abs(r32[:, lag:] - r32[:, :-lag]) > step_lsb).mean(axis=1)
        rails[w0:w1, ci] = ((rr >= RAIL) | (rr <= -RAIL)).mean(axis=1)
        slow = box_from_sum(c, k_slow, mv_per_lsb).reshape(k, win)
        wander[w0:w1, ci] = slow.max(axis=1) - slow.min(axis=1)

    # numpy releases the GIL inside cumsum / reductions, so channels run in parallel;
    # each worker holds one channel-hour (~20 MB of temporaries)
    with ThreadPoolExecutor(max_workers=min(n_ch, max(2, (__import__("os").cpu_count() or 2)))) as pool:
        for w0 in range(0, n_win, per_chunk):
            w1 = min(n_win, w0 + per_chunk)
            a, b = w0 * win, w1 * win
            list(pool.map(lambda ci: one(ci, INDEPENDENT[ci], a, b, w0, w1), range(n_ch)))
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
    margin = samples(0.064, fs)                            # keep clear of the QRS on both sides
    a = int(t0_ms * fs / 1000) + margin; b = int(t1_ms * fs / 1000) - margin
    if b - a < fs // 4:
        return False, "интервал короче 250 мс"
    raw = np.asarray(mm[INDEPENDENT, a:b])
    x = raw.astype(np.float32) * mv_per_lsb
    rails = float(((raw >= RAIL) | (raw <= -RAIL)).mean())
    lag = samples(STEP_S, fs)
    max_step = float(np.abs(x[:, lag:] - x[:, :-lag]).max())
    rng = float((x.max(axis=1) - x.min(axis=1)).max())
    hf = float(hf_residual(x[INDEPENDENT.index(1)], fs).std())
    if rails > 0:
        return True, f"зашкал АЦП, {rails:.0%} отсчётов"
    if max_step > 5.0:
        return True, f"скачок {max_step:.1f} мВ за {int(round(1000 * lag / fs))} мс"
    if rng > 3.0 * qrs_amp_mv:
        return True, f"размах {rng:.1f} мВ, ×{rng / qrs_amp_mv:.1f} к QRS"
    if hf > 2.5 * hf_base_mv:
        return True, f"шум ×{hf / hf_base_mv:.1f} от нормы записи"
    return False, f"изолиния: размах {rng:.2f} мВ, шум ×{hf / hf_base_mv:.1f}"


def local_noise(mm: np.memmap, fs: int, mv_per_lsb: float, i: int, half_s: float = 0.5, ch: int = 1) -> float:
    a = max(0, i - int(half_s * fs)); b = min(mm.shape[1], i + int(half_s * fs))
    x = np.asarray(mm[ch, a:b]).astype(np.float32) * mv_per_lsb
    return float(hf_residual(x, fs).std())


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
    lag, reach = samples(STEP_S, fs), samples(0.04, fs)
    for ch in (1, 7, 8):
        x = np.asarray(mm[ch, lo:hi]).astype(np.float32) * mv_per_lsb
        x = x - np.median(x)
        d = np.abs(x[lag:] - x[:-lag])                      # slew over 8 ms, whatever the sample rate
        peak = int(np.argmax(np.abs(x)))
        sharp = d[max(0, peak - reach):peak + reach].max() if len(d) else 0.0
        if abs(x[peak]) >= 0.5 * qrs_amp_mv and sharp >= 0.25 * qrs_amp_mv:
            hits += 1; where = lo + peak
    if hits >= 2 and where is not None:
        return True, f"комплекс без метки на {hits} отведениях, через {int(where * 1000 / fs) - t0_ms} мс после предыдущего"
    return False, ""
