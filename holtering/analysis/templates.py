"""Morphology templates: group every beat by QRS shape, the way CardioSpy's
"Шаблоны" grid does, so a reviewer can relabel a whole family at once.

Each beat is a +-96 ms window on three leads (II + two chest channels),
median-centred and L2-normalised. Assignment is greedy correlation matching
(>= CORR_MIN joins an existing template, otherwise a new one is opened), then
one refinement pass reassigns everything to the nearest template mean.
"""

from __future__ import annotations

import numpy as np

LEADS_T = [1, 10, 7]
HALF = 12                    # samples each side -> 25 samples = 200 ms at 125 Hz
CORR_MIN = 0.90
MAX_TEMPLATES = 48
CHUNK = 4096


def beat_windows(mm: np.memmap, fs: int, mv: float, t_ms: np.ndarray):
    """(n_beats, 3*(2*HALF+1)) float32 raw windows in mV; invalid edge beats -> zeros."""
    idx = np.round(t_ms * fs / 1000).astype(np.int64)
    n = mm.shape[1]
    valid = (idx >= HALF) & (idx < n - HALF - 1)
    offs = np.arange(-HALF, HALF + 1)
    gather = idx[valid][:, None] + offs[None, :]
    out = np.zeros((len(idx), len(LEADS_T), 2 * HALF + 1), np.float32)
    for li, ch in enumerate(LEADS_T):
        lead = np.asarray(mm[ch])
        out[valid, li] = lead[gather].astype(np.float32) * mv
    return out.reshape(len(idx), -1), valid


def _normalise(w: np.ndarray) -> np.ndarray:
    x = w.reshape(len(w), len(LEADS_T), -1)
    x = x - np.median(x, axis=2, keepdims=True)
    x = x.reshape(len(w), -1)
    nrm = np.linalg.norm(x, axis=1, keepdims=True) + 1e-6
    return x / nrm


def cluster(w: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (template_id per beat, template unit vectors). Invalid beats get -1."""
    x = _normalise(w)
    T: list[np.ndarray] = []
    assign = np.full(len(x), -1, np.int32)
    ids = np.where(valid)[0]
    for c0 in range(0, len(ids), CHUNK):
        sel = ids[c0:c0 + CHUNK]
        xc = x[sel]
        if T:
            tm = np.stack(T)
            corr = xc @ tm.T
            best = corr.argmax(axis=1); ok = corr[np.arange(len(sel)), best] >= CORR_MIN
            assign[sel[ok]] = best[ok]
            rest = sel[~ok]
        else:
            rest = sel
        for k in rest:                                   # open new templates one by one
            if T:
                tm = np.stack(T); c = tm @ x[k]; j = int(c.argmax())
                if c[j] >= CORR_MIN or len(T) >= MAX_TEMPLATES:
                    assign[k] = j; continue
            T.append(x[k].copy()); assign[k] = len(T) - 1
    # refinement: template = mean of members, reassign
    tm = np.stack(T)
    for _ in range(2):
        for j in range(len(T)):
            m = assign == j
            if m.any():
                v = x[m].mean(axis=0); tm[j] = v / (np.linalg.norm(v) + 1e-6)
        for c0 in range(0, len(ids), CHUNK):
            sel = ids[c0:c0 + CHUNK]
            assign[sel] = (x[sel] @ tm.T).argmax(axis=1)
    # renumber by size, drop empties
    counts = np.bincount(assign[assign >= 0], minlength=len(T))
    order = [j for j in np.argsort(-counts) if counts[j] > 0]
    remap = {old: new for new, old in enumerate(order)}
    out = np.array([remap.get(a, -1) if a >= 0 else -1 for a in assign], np.int32)
    return out, tm[order]


def summarise(w: np.ndarray, assign: np.ndarray, labels: np.ndarray, verdicts: dict[int, str], fs: int) -> list[dict]:
    n_t = int(assign.max()) + 1 if len(assign) else 0
    out = []
    for j in range(n_t):
        m = np.where(assign == j)[0]
        mean = w[m].reshape(len(m), len(LEADS_T), -1).mean(axis=0)
        mean = mean - np.median(mean, axis=1, keepdims=True)
        lab = {k: int(v) for k, v in zip(*np.unique(labels[m], return_counts=True))}
        vd: dict[str, int] = {}
        by_label: dict[str, dict[str, int]] = {}
        for k in m:
            v = verdicts.get(int(k), "N")
            vd[v] = vd.get(v, 0) + 1
            l = str(labels[k])
            if l != "N":
                by_label.setdefault(l, {})[v] = by_label.setdefault(l, {}).get(v, 0) + 1
        out.append({"id": j, "count": int(len(m)), "labels": lab, "verdicts": vd, "verdicts_by_label": by_label,
                    "wave": {"fs": fs, "half_ms": HALF * 1000 // fs,
                             "leads": [np.round(row, 3).tolist() for row in mean]},
                    "first": int(m[0]), "sample": [int(k) for k in m[:: max(1, len(m) // 40)][:40]]})
    return out
