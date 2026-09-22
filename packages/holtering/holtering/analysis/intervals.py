"""Интервалы QT по усреднённому синусовому комплексу — метод в docs/modules/analysis.md."""

import numpy as np
from msgspec import Struct

LEAD = 1  # II: зубец T выражен, а усреднение снимает шум
PRE_MS, POST_MS = 400.0, 560.0
BASE_MS = 48.0  # сегмент PQ перед комплексом — изолиния отсчёта
SLOPE_FRAC = 0.15  # тот же порог наклона, что и у ширины QRS (beats.qrs_duration_ms)
T_FROM_MS, T_TO_MS = 80.0, 420.0  # где искать вершину T после конца QRS
T_TAIL_MS = 200.0  # на этом участке ищется самый крутой спуск T
HOUR_MS = 3.6e6
PER_HOUR = 400  # больше усреднять нечего: шум падает как корень из числа комплексов
MIN_BEATS = 50
QT_RANGE = (250.0, 650.0)


class Intervals(Struct):
    """QT по часам: медиана и разброс, и сколько часов удалось измерить."""

    qt_ms: int | None
    qtc_ms: int | None
    qtc_min: int | None
    qtc_max: int | None
    hours: int


def _n(ms: float, fs: int) -> int:
    return max(1, round(ms * fs / 1000))


def sinus_beats(t_ms: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Комплексы, годные для усреднения: синусовый в синусовом окружении, ритм ровный."""
    rr = np.diff(t_ms)
    ok = np.zeros(len(t_ms), bool)
    if len(t_ms) < 3:
        return ok
    steady = (rr[:-1] > 500) & (rr[:-1] < 1500) & (rr[1:] > 500) & (rr[1:] < 1500)
    ok[1:-1] = (labels[1:-1] == "N") & (labels[:-2] == "N") & (labels[2:] == "N") & steady
    return ok


def template(mm: np.ndarray, fs: int, mv: float, centres: np.ndarray) -> np.ndarray | None:
    """Медианный комплекс: медиана, а не среднее, чтобы один артефакт не сдвинул форму."""
    pre, post = _n(PRE_MS, fs), _n(POST_MS, fs)
    rows = [
        np.asarray(mm[LEAD, i - pre : i + post + 1], np.float32)
        for i in centres
        if i >= pre and i + post + 1 <= mm.shape[1]
    ]
    if len(rows) < MIN_BEATS:
        return None
    w = np.median(np.stack(rows), 0) * mv
    return w - np.median(w[: _n(BASE_MS, fs)])


def _qrs_bounds(w: np.ndarray, r: int, fs: int) -> tuple[int, int]:
    smooth = max(1, _n(24.0, fs))
    d = np.convolve(np.abs(np.diff(w)), np.ones(smooth) / smooth, "same")
    half = _n(80.0, fs)
    thr = SLOPE_FRAC * float(d[max(0, r - half) : r + half].max())
    on = r
    while on > 1 and d[on - 1] > thr:
        on -= 1
    off = r
    while off < len(d) - 1 and d[off] > thr:
        off += 1
    return on, off


def measure_qt(w: np.ndarray, fs: int, rr_ms: float) -> tuple[float, float] | None:
    """QT от начала QRS до конца T по касательной к самому крутому спуску."""
    pre = _n(PRE_MS, fs)
    near = _n(56.0, fs)
    r = pre - near + int(np.argmax(np.abs(w[pre - near : pre + near + 1])))
    on, off = _qrs_bounds(w, r, fs)
    base = float(np.median(w[max(0, on - _n(BASE_MS, fs)) : max(1, on - 1)]))
    lo, hi = off + _n(T_FROM_MS, fs), min(len(w) - 1, off + _n(T_TO_MS, fs))
    if hi - lo < 5:
        return None
    t_peak = lo + int(np.argmax(np.abs(w[lo:hi] - base)))
    d = np.diff(w)
    tail = d[t_peak : min(len(d), t_peak + _n(T_TAIL_MS, fs))]
    if len(tail) < 3:
        return None
    steepest = t_peak + int(np.argmax(np.abs(tail)))
    slope = float(d[steepest])
    if slope == 0.0:
        return None
    end = steepest + (base - w[steepest]) / slope
    qt = (end - on) * 1000.0 / fs
    if not QT_RANGE[0] <= qt <= QT_RANGE[1] or rr_ms <= 0:
        return None
    return qt, qt / np.sqrt(rr_ms / 1000.0)


def measure(mm: np.ndarray, fs: int, mv: float, t_ms: np.ndarray, labels: np.ndarray) -> Intervals:
    ok = sinus_beats(t_ms, labels)
    rr = np.diff(t_ms)
    qt: list[float] = []
    qtc: list[float] = []
    for hour in range(int(t_ms[-1] // HOUR_MS) + 1):
        sel = np.where(ok & (t_ms >= hour * HOUR_MS) & (t_ms < (hour + 1) * HOUR_MS))[0]
        if len(sel) < MIN_BEATS:
            continue
        sel = sel[:: max(1, len(sel) // PER_HOUR)][:PER_HOUR]
        w = template(mm, fs, mv, (t_ms[sel] * fs / 1000).astype(int))
        if w is None:
            continue
        got = measure_qt(w, fs, float(np.median(rr[sel - 1])))
        if got:
            qt.append(got[0])
            qtc.append(got[1])
    if not qt:
        return Intervals(None, None, None, None, 0)
    return Intervals(
        qt_ms=round(float(np.median(qt))),
        qtc_ms=round(float(np.median(qtc))),
        qtc_min=round(float(min(qtc))),
        qtc_max=round(float(max(qtc))),
        hours=len(qt),
    )
