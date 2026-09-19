"""Шаблоны морфологии: группировка комплексов по форме QRS — docs/modules/analysis.md."""

from collections.abc import Callable

import numpy as np
from msgspec import Struct

ReadLead = Callable[[int, int, int], np.ndarray]

LEADS_T = [1, 10, 7]
GRID_HZ = 125
HALF = 12  # отсчётов сетки в каждую сторону -> 25 точек = 200 мс
CORR_MIN = 0.90
MAX_TEMPLATES = 48
CHUNK = 4096


class TemplateWave(Struct):
    fs: int
    half_ms: int
    leads: list[list[float]]


class Template(Struct):
    id: int
    count: int
    labels: dict[str, int]
    verdicts: dict[str, int]
    verdicts_by_label: dict[str, dict[str, int]]
    wave: TemplateWave
    first: int
    sample: list[int]


def grid_step(fs: int) -> int:
    return max(1, round(fs / GRID_HZ))


def beat_windows(
    read: ReadLead, n_samples: int, fs: int, mv: float, t_ms: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Окна комплексов в мВ, (n_beats, 3*(2*HALF+1)) float32; краевые комплексы — нули."""
    step = grid_step(fs)
    idx = np.round(t_ms * fs / 1000).astype(np.int64)
    # Чётная ширина берёт step+1 отсчёт с половинным весом по краям, чтобы центр окна
    # не сместился на полотсчёта.
    if step % 2:
        sub = np.arange(-(step // 2), step // 2 + 1)
        wts = np.full(step, 1.0 / step, np.float32)
    else:
        sub = np.arange(-(step // 2), step // 2 + 1)
        wts = np.full(step + 1, 1.0 / step, np.float32)
        wts[[0, -1]] = 0.5 / step
    lo, hi = HALF * step - sub[0], HALF * step + sub[-1] + 1
    valid = (idx >= lo) & (idx < n_samples - hi)
    offs = np.arange(-HALF, HALF + 1) * step
    gather = idx[valid][:, None, None] + offs[None, :, None] + sub[None, None, :]
    out = np.zeros((len(idx), len(LEADS_T), 2 * HALF + 1), np.float32)
    for li, ch in enumerate(LEADS_T):
        lead = read(ch, 0, n_samples)
        out[valid, li] = (lead[gather].astype(np.float32) @ wts) * mv
        del lead
    return out.reshape(len(idx), -1), valid


def _normalise(w: np.ndarray) -> np.ndarray:
    x = w.reshape(len(w), len(LEADS_T), -1)
    x = x - np.median(x, axis=2, keepdims=True)
    x = x.reshape(len(w), -1)
    nrm = np.linalg.norm(x, axis=1, keepdims=True) + 1e-6
    return x / nrm


def cluster(w: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Номер шаблона у каждого комплекса и единичные векторы шаблонов; краевые — -1."""
    x = _normalise(w)
    tm = np.empty((MAX_TEMPLATES, x.shape[1]), x.dtype)
    nt = 0
    assign = np.full(len(x), -1, np.int32)
    ids = np.where(valid)[0]
    for c0 in range(0, len(ids), CHUNK):
        sel = ids[c0 : c0 + CHUNK]
        if nt:
            corr = x[sel] @ tm[:nt].T
            best = corr.argmax(axis=1)
            ok = corr[np.arange(len(sel)), best] >= CORR_MIN
            assign[sel[ok]] = best[ok]
            rest = sel[~ok]
        else:
            rest = sel
        for pos, k in enumerate(rest):
            if nt >= MAX_TEMPLATES:
                # Набор заморожен: остаток раскладывается одним пакетным argmax.
                tail = rest[pos:]
                assign[tail] = (x[tail] @ tm[:nt].T).argmax(axis=1)
                break
            if nt:
                c = tm[:nt] @ x[k]
                j = int(c.argmax())
                if c[j] >= CORR_MIN:
                    assign[k] = j
                    continue
            tm[nt] = x[k]
            assign[k] = nt
            nt += 1
    tm = tm[:nt].copy()
    for _ in range(2):
        for j in range(nt):
            m = assign == j
            if m.any():
                v = x[m].mean(axis=0)
                tm[j] = v / (np.linalg.norm(v) + 1e-6)
        for c0 in range(0, len(ids), CHUNK):
            sel = ids[c0 : c0 + CHUNK]
            assign[sel] = (x[sel] @ tm.T).argmax(axis=1)
    counts = np.bincount(assign[assign >= 0], minlength=nt)
    order = [j for j in np.argsort(-counts) if counts[j] > 0]
    remap = {old: new for new, old in enumerate(order)}
    out = np.array([remap.get(a, -1) if a >= 0 else -1 for a in assign], np.int32)
    return out, tm[order]


def summarise(
    w: np.ndarray, assign: np.ndarray, labels: np.ndarray, verdicts: dict[int, str], fs: int
) -> list[Template]:
    n_t = int(assign.max()) + 1 if len(assign) else 0
    out = []
    for j in range(n_t):
        m = np.where(assign == j)[0]
        mean = w[m].reshape(len(m), len(LEADS_T), -1).mean(axis=0)
        mean = mean - np.median(mean, axis=1, keepdims=True)
        lab = {
            str(k): int(v) for k, v in zip(*np.unique(labels[m], return_counts=True), strict=True)
        }
        vd: dict[str, int] = {}
        by_label: dict[str, dict[str, int]] = {}
        for k in m:
            v = verdicts.get(int(k), "N")
            vd[v] = vd.get(v, 0) + 1
            label = str(labels[k])
            if label != "N":
                by_label.setdefault(label, {})[v] = by_label.setdefault(label, {}).get(v, 0) + 1
        wave = TemplateWave(
            fs=fs // grid_step(fs),
            half_ms=HALF * 1000 * grid_step(fs) // fs,
            leads=[np.round(row, 3).tolist() for row in mean],
        )
        out.append(
            Template(
                id=j,
                count=len(m),
                labels=lab,
                verdicts=vd,
                verdicts_by_label=by_label,
                wave=wave,
                first=int(m[0]),
                sample=[int(k) for k in m[:: max(1, len(m) // 40)][:40]],
            )
        )
    return out
