"""Качество сигнала по окнам на восьми независимых каналах — docs/modules/analysis.md."""

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import numpy as np

INDEPENDENT = [0, 1, 6, 7, 8, 9, 10, 11]
WINDOW_S = 2  # окно 2 с: затенение обходит артефакт вплотную
SMOOTH_S = 0.104  # ~100 мс скользящего среднего (13 отсчётов на 125 Гц, где он настроен)
STEP_S = 0.008  # скачок меряется за 8 мс (один отсчёт на 125 Гц)...
STEP_MV = 0.5  # ...и 0.5 мВ в чистой ЭКГ не бывает
RAIL = 32000  # зашкал АЦП
WANDER_S = 0.4  # 0.4 с скользящего среднего: оставляет дрейф, убирает QRS/T
WANDER_MIN_MV = 1.5  # абсолютный пол «дрейфа» (дыхание держится заметно ниже)
WANDER_RATIO = 4.0  # ...и он же должен быть вчетверо больше обычного дрейфа канала

ReadLead = Callable[[int, int, int], np.ndarray]


def samples(seconds: float, fs: int, at_least: int = 1) -> int:
    """Длины окон заданы в секундах: на 500 Гц нужен тот же 100-мс сглаживатель, а не 13 отсчётов."""
    return max(at_least, round(seconds * fs))


def running_sum(x: np.ndarray, dtype: type = np.float64) -> np.ndarray:
    """c[i] = sum(x[:i]) по последней оси, длина n+1; int64 на сырых int16 точен."""
    n = x.shape[-1]
    c = np.zeros((*x.shape[:-1], n + 1), dtype)
    np.cumsum(x, axis=-1, dtype=dtype, out=c[..., 1:])
    return c


def box_from_sum(c: np.ndarray, k: int, scale: float = 1.0) -> np.ndarray:
    """Скользящее среднее ширины k из бегущей суммы, выравнивание как у np.convolve(mode="same")."""
    n = c.shape[-1] - 1
    hi, lo = (k - 1) // 2 + 1, k // 2  # out[i] = c[min(i+hi, n)] - c[max(i-lo, 0)]
    out = np.empty((*c.shape[:-1], n), np.float64)
    if n <= k:  # окно накрывает всё: обрезаются оба конца
        i = np.arange(n)
        out[...] = c[..., np.minimum(i + hi, n)] - c[..., np.maximum(i - lo, 0)]
    else:
        out[..., lo : n - hi + 1] = c[..., lo + hi : n + 1] - c[..., 0 : n - hi + 1 - lo]
        out[..., :lo] = c[..., hi : hi + lo] - c[..., :1]
        out[..., n - hi + 1 :] = c[..., n:] - c[..., n - hi + 1 - lo : n - lo]
    out *= scale / k
    return out


def box_same(x: np.ndarray, k: int) -> np.ndarray:
    """np.convolve(x, ones(k)/k, mode="same") за O(n) вместо O(n*k)."""
    return box_from_sum(running_sum(x), k)


def hf_residual(x: np.ndarray, fs: int) -> np.ndarray:
    """Высокочастотный остаток после ~100 мс скользящего среднего, по последней оси."""
    return x - box_same(x, samples(SMOOTH_S, fs))


def baseline(x: np.ndarray, fs: int) -> np.ndarray:
    """Медленная составляющая (0.4 с скользящего среднего) по последней оси."""
    return box_same(x, samples(WANDER_S, fs))


def window_metrics(
    read: ReadLead, n_samples: int, fs: int, mv_per_lsb: float, window_s: int = WINDOW_S
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """По окну и независимому каналу: ВЧ-СКО (мВ), доля скачков, зашкал, дрейф (мВ)."""
    win = fs * window_s
    n_win = n_samples // win
    n_ch = len(INDEPENDENT)
    hf = np.zeros((n_win, n_ch), np.float32)
    steps = np.zeros((n_win, n_ch), np.float32)
    rails = np.zeros((n_win, n_ch), np.float32)
    wander = np.zeros((n_win, n_ch), np.float32)
    # ~450k отсчётов на канал-кусок (1 ч на 125 Гц): временные массивы ~20 МБ на поток
    # при любой частоте дискретизации и длине записи.
    per_chunk = max(1, 450_000 // win)
    step_lsb = STEP_MV / abs(mv_per_lsb)
    k_hf, k_slow, lag = samples(SMOOTH_S, fs), samples(WANDER_S, fs), samples(STEP_S, fs)

    def one(a: int, b: int, w0: int, w1: int, ci: int) -> None:
        k = w1 - w0
        raw = read(INDEPENDENT[ci], a, b)
        rr = raw.reshape(k, win)
        c = running_sum(raw, np.int64)  # одна точная целочисленная сумма на оба средних
        x = raw * mv_per_lsb  # float64, без округления до float32
        res = (x - box_from_sum(c, k_hf, mv_per_lsb)).reshape(k, win)
        hf[w0:w1, ci] = res.std(axis=1)
        r32 = rr.astype(np.int32)
        steps[w0:w1, ci] = (np.abs(r32[:, lag:] - r32[:, :-lag]) > step_lsb).mean(axis=1)
        rails[w0:w1, ci] = ((rr >= RAIL) | (rr <= -RAIL)).mean(axis=1)
        slow = box_from_sum(c, k_slow, mv_per_lsb).reshape(k, win)
        wander[w0:w1, ci] = slow.max(axis=1) - slow.min(axis=1)

    # numpy отпускает GIL внутри cumsum и редукций, поэтому каналы считаются параллельно.
    with ThreadPoolExecutor(max_workers=min(n_ch, max(2, os.cpu_count() or 2))) as pool:
        for w0 in range(0, n_win, per_chunk):
            w1 = min(n_win, w0 + per_chunk)
            list(pool.map(partial(one, w0 * win, w1 * win, w0, w1), range(n_ch)))
    return hf, steps, rails, wander


def noise_score(
    hf: np.ndarray, steps: np.ndarray, rails: np.ndarray, wander: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Две оценки на окно, 0 — чисто, 1 — непригодно; пороги — docs/modules/analysis.md."""
    base = np.median(hf, axis=0) + 1e-6
    ratio = hf / base  # 1 — обычное, 3 и больше — плохо
    ch_bad = ((ratio > 2.5) | (steps > 0.15) | (rails > 0)).astype(np.float32)
    soft = np.clip((np.median(ratio, axis=1) - 1.0) / 2.0, 0, 1)
    sharp = np.maximum(ch_bad.mean(axis=1), soft).astype(np.float32)
    wbase = np.median(wander, axis=0) + 1e-6
    wthr = np.maximum(WANDER_MIN_MV, WANDER_RATIO * wbase)
    drift_frac = (wander > wthr).mean(axis=1)
    drift_soft = np.clip(((wander / wthr).max(axis=1) - 2.0) / 2.0, 0, 1)
    drift = np.maximum(drift_frac, drift_soft).astype(np.float32)
    return np.maximum(sharp, drift), sharp, base


def gap_artifact(
    mm: np.memmap,
    fs: int,
    mv_per_lsb: float,
    t0_ms: int,
    t1_ms: int,
    qrs_amp_mv: float,
    hf_base_mv: float,
) -> tuple[bool, str]:
    """Потеря сигнала внутри RR-интервала, а не тихая изолиния паузы?"""
    margin = samples(0.064, fs)  # держаться подальше от QRS с обеих сторон
    a = int(t0_ms * fs / 1000) + margin
    b = int(t1_ms * fs / 1000) - margin
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
        return True, f"скачок {max_step:.1f} мВ за {round(1000 * lag / fs)} мс"
    if rng > 3.0 * qrs_amp_mv:
        return True, f"размах {rng:.1f} мВ, ×{rng / qrs_amp_mv:.1f} к QRS"
    if hf > 2.5 * hf_base_mv:
        return True, f"шум ×{hf / hf_base_mv:.1f} от нормы записи"
    return False, f"изолиния: размах {rng:.2f} мВ, шум ×{hf / hf_base_mv:.1f}"


def local_noise(
    mm: np.memmap, fs: int, mv_per_lsb: float, i: int, half_s: float = 0.5, ch: int = 1
) -> float:
    a = max(0, i - int(half_s * fs))
    b = min(mm.shape[1], i + int(half_s * fs))
    x = np.asarray(mm[ch, a:b]).astype(np.float32) * mv_per_lsb
    return float(hf_residual(x, fs).std())


def missed_beat(
    mm: np.memmap, fs: int, mv_per_lsb: float, t0_ms: int, t1_ms: int, qrs_amp_mv: float
) -> tuple[bool, str]:
    """Есть ли в средних 60 % RR-интервала отклонение размером и формой с QRS?"""
    a = int(t0_ms * fs / 1000)
    b = int(t1_ms * fs / 1000)
    lo = a + int((b - a) * 0.2)
    hi = a + int((b - a) * 0.8)
    if hi - lo < fs // 5:
        return False, ""
    hits = 0
    where = None
    lag, reach = samples(STEP_S, fs), samples(0.04, fs)
    for ch in (1, 7, 8):
        x = np.asarray(mm[ch, lo:hi]).astype(np.float32) * mv_per_lsb
        x = x - np.median(x)
        d = np.abs(x[lag:] - x[:-lag])  # крутизна за 8 мс при любой частоте дискретизации
        peak = int(np.argmax(np.abs(x)))
        sharp = d[max(0, peak - reach) : peak + reach].max() if len(d) else 0.0
        if abs(x[peak]) >= 0.5 * qrs_amp_mv and sharp >= 0.25 * qrs_amp_mv:
            hits += 1
            where = lo + peak
    if hits >= 2 and where is not None:
        delay = int(where * 1000 / fs) - t0_ms
        return True, f"комплекс без метки на {hits} отведениях, через {delay} мс после предыдущего"
    return False, ""
