"""ЧСС, вариабельность, паузы и эпизоды по проверенным меткам."""

from collections.abc import Callable

import numpy as np
from msgspec import Struct, field

from .beats import KEEP, VERDICT_RU, BeatAudit


class Episode(Struct):
    id: int
    kind: str  # pause | v-run | s-run | missed | noise
    t_ms: int
    dur_ms: int
    title: str
    verdict: str  # artifact | review | likely
    confidence: float
    reasons: list[str] = field(default_factory=list)
    beats: list[int] = field(default_factory=list)


class Hrv(Struct):
    sdnn: float
    rmssd: float
    pnn50: float
    mean_rr: int
    n: int


def plural(n: int, one: str, few: str, many: str) -> str:
    """Согласование числительных: 1 метка, 3 метки, 5 меток (11–14 — many)."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


MIN_RR_MS, MAX_RR_MS = 300, 2000  # физиологичный интервал: всё вне — не пара ударов подряд


def nn_intervals(t_ms: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rr = np.diff(t_ms)
    ok = (labels[:-1] == "N") & (labels[1:] == "N") & (rr > MIN_RR_MS) & (rr < MAX_RR_MS)
    return t_ms[:-1][ok], rr[ok]


HR_WINDOW_S = 15.0  # окно усреднения ЧСС; калибровка — docs/modules/analysis.md


def hr_extremes(t_ms: np.ndarray, window_s: float = HR_WINDOW_S) -> tuple[float, int, float, int]:
    """Крайние ЧСС по скользящему окну: мин, его середина (мс), макс, его середина."""
    t = t_ms.astype(np.float64)
    idx = np.arange(len(t))
    last = np.searchsorted(t, t + window_s * 1000.0, side="right") - 1
    inside = last - idx
    rr = np.diff(t)
    ok = np.concatenate([[0], np.cumsum(((rr > MIN_RR_MS) & (rr < MAX_RR_MS)).astype(np.int64))])
    span = t[np.clip(last, 0, len(t) - 1)] - t
    # Окно должно быть полным: на хвосте записи и у края артефактного провала оно
    # схлопывается до пары ударов, и двойной счёт в нём превращается в «максимум».
    good = (inside >= 2) & (span >= window_s * 1000.0 - MAX_RR_MS)
    good &= ok[np.clip(last, 0, len(rr))] - ok[idx] == inside
    if not good.any():
        return float("nan"), 0, float("nan"), 0
    hr = np.where(good, 60000.0 * inside / np.maximum(span, 1.0), np.nan)
    lo, hi = int(np.nanargmin(hr)), int(np.nanargmax(hr))
    return (
        float(hr[lo]),
        int(t[lo] + span[lo] / 2),
        float(hr[hi]),
        int(t[hi] + span[hi] / 2),
    )


def malik_filter(nn: np.ndarray) -> np.ndarray:
    keep = np.ones(len(nn), bool)
    prev = None
    for j, v in enumerate(nn):
        if prev is not None and abs(v - prev) / prev > 0.20:
            keep[j] = False
        else:
            prev = v
    return keep


def hrv(nn: np.ndarray) -> Hrv:
    nn = nn[malik_filter(nn)].astype(float)
    d = np.diff(nn)
    return Hrv(
        sdnn=round(float(nn.std()), 1),
        rmssd=round(float(np.sqrt(np.mean(d**2))), 1),
        pnn50=round(float((np.abs(d) > 50).mean() * 100), 1),
        mean_rr=round(float(nn.mean())),
        n=len(nn),
    )


def hr_per_minute(t_nn: np.ndarray, nn: np.ndarray, total_ms: int) -> list[float | None]:
    n_min = int(total_ms // 60000) + 1
    idx = (t_nn // 60000).astype(int)
    out: list[float | None] = [None] * n_min
    sums = np.bincount(idx, weights=nn, minlength=n_min)
    cnt = np.bincount(idx, minlength=n_min)
    for m in range(n_min):
        if cnt[m] >= 10:
            out[m] = round(float(60000 * cnt[m] / sums[m]), 1)
    return out


def estimate_sleep(
    hr_min: list[float | None], min_len: int = 45, merge_gap: int = 20
) -> list[list[int]]:
    """Сон по одной ЧСС, без дневника; критерий — docs/modules/analysis.md."""
    arr = np.array([np.nan if v is None else float(v) for v in hr_min])
    n = len(arr)
    med = np.full(n, np.nan)
    for i in range(n):
        w = arr[max(0, i - 7) : i + 8]
        w = w[~np.isnan(w)]
        if len(w) >= 5:
            med[i] = np.median(w)
    ok = ~np.isnan(med)
    if ok.sum() < 120:
        return []
    lo, mid = np.percentile(med[ok], 10), np.percentile(med[ok], 50)
    thr = lo + 0.5 * (mid - lo)
    below = ok & (med < thr)
    segs: list[list[int]] = []
    i = 0
    while i < n:
        if below[i]:
            j = i
            while j < n and below[j]:
                j += 1
            if segs and i - segs[-1][1] <= merge_gap:
                segs[-1][1] = j
            else:
                segs.append([i, j])
            i = j
        else:
            i += 1
    return [s for s in segs if s[1] - s[0] >= min_len]


def per_minute_counts(t_ms: np.ndarray, total_ms: int) -> list[int]:
    n_min = int(total_ms // 60000) + 1
    return np.bincount((t_ms // 60000).astype(int), minlength=n_min).astype(int).tolist()


def runs(indices: np.ndarray, min_len: int) -> list[np.ndarray]:
    if len(indices) == 0:
        return []
    return [
        g for g in np.split(indices, np.where(np.diff(indices) != 1)[0] + 1) if len(g) >= min_len
    ]


GapCheck = Callable[[int, int], tuple[bool, str]]
MissedCheck = Callable[[int, int], tuple[bool, str]]


def extract_episodes(
    t_ms: np.ndarray,
    labels: np.ndarray,
    audits: dict[int, BeatAudit],
    noise10: np.ndarray,
    sharp10: np.ndarray,
    window_s: int,
    gap_check: GapCheck,
    missed_check: MissedCheck | None = None,
) -> list[Episode]:
    """Паузы решает `noise10` (ВЧ + дрейф), строки «Помеха» — `sharp10` (только ВЧ)."""
    eps: list[Episode] = []
    rr = np.diff(t_ms)

    def noise_at(t0: int, t1: int) -> float:
        a = int(t0 / 1000 / window_s)
        b = max(a + 1, int(t1 / 1000 / window_s) + 1)
        return float(noise10[a:b].max()) if a < len(noise10) else 0.0

    for k in np.where(rr > 2000)[0]:
        t0, t1 = int(t_ms[k]), int(t_ms[k + 1])
        nz = noise_at(t0, t1)
        bad, why = gap_check(t0, t1)
        if bad or nz >= 0.5:
            reason = why if bad else f"помеха в окне {nz:.0%}"
            eps.append(
                Episode(
                    len(eps),
                    "pause",
                    t0,
                    t1 - t0,
                    f"«Пауза» {(t1 - t0) / 1000:.1f} с",
                    "artifact",
                    0.9,
                    [reason],
                    [int(k), int(k + 1)],
                )
            )
        else:
            eps.append(
                Episode(
                    len(eps),
                    "pause",
                    t0,
                    t1 - t0,
                    f"Пауза {(t1 - t0) / 1000:.1f} с",
                    "review",
                    0.6,
                    [why],
                    [int(k), int(k + 1)],
                )
            )

    v_idx = np.array([k for k, a in audits.items() if a.label == "V" and a.verdict in KEEP], int)
    v_idx.sort()
    for g in runs(v_idx, 2):
        rr_run = np.diff(t_ms[g])
        rate = 60000 / rr_run.mean()
        conf = float(np.mean([audits[int(k)].confidence for k in g]))
        kind = "пара" if len(g) == 2 else f"×{len(g)}"
        widths = ", ".join(f"{audits[int(k)].width_ms:.0f}" for k in g)
        eps.append(
            Episode(
                len(eps),
                "v-run",
                int(t_ms[g[0]]),
                int(t_ms[g[-1]] - t_ms[g[0]]),
                f"ЖЭС {kind}, {rate:.0f}/мин",
                "likely" if conf >= 0.7 else "review",
                round(conf, 2),
                [f"QRS {widths} мс"],
                [int(k) for k in g],
            )
        )
    # Серии прибора, не пережившие аудит, остаются в списке как артефакты: врач должен
    # видеть, что «ЖЭС ×3» разобрана, а не потеряна.
    dev_v = np.where(labels == "V")[0]
    for g in runs(dev_v, 3):
        if all(audits[int(k)].verdict not in KEEP for k in g):
            rr_run = np.diff(t_ms[g])
            rate = 60000 / rr_run.mean()
            why = sorted(
                {VERDICT_RU.get(audits[int(k)].verdict, audits[int(k)].verdict) for k in g}
            )
            rejected = plural(len(g), "метка отклонена", "метки отклонены", "меток отклонены")
            eps.append(
                Episode(
                    len(eps),
                    "v-run",
                    int(t_ms[g[0]]),
                    int(t_ms[g[-1]] - t_ms[g[0]]),
                    f"«ЖЭС ×{len(g)}, {rate:.0f}/мин»",
                    "artifact",
                    0.85,
                    [f"все {len(g)} {rejected}: {', '.join(why)}"],
                    [int(k) for k in g],
                )
            )

    dev_s = np.where(labels == "S")[0]
    for g in runs(dev_s, 3):
        rr_run = np.diff(t_ms[g])
        rate = 60000 / rr_run.mean()
        prev = [
            rr[j]
            for j in range(max(0, g[0] - 6), g[0] - 1)
            if labels[j] == "N" and labels[j + 1] == "N"
        ]
        prev_rate = 60000 / float(np.median(prev)) if prev else float("nan")
        kept = [int(k) for k in g if audits[int(k)].verdict in KEEP]
        if len(kept) < 3:
            bad = sorted(
                {
                    VERDICT_RU.get(audits[int(k)].verdict, audits[int(k)].verdict)
                    for k in g
                    if audits[int(k)].verdict not in KEEP
                }
            )
            eps.append(
                Episode(
                    len(eps),
                    "s-run",
                    int(t_ms[g[0]]),
                    int(t_ms[g[-1]] - t_ms[g[0]]),
                    f"«НЖЭС ×{len(g)}, {rate:.0f}/мин»",
                    "artifact",
                    0.8,
                    [f"подтверждено {len(kept)} из {len(g)}: {', '.join(bad)}"],
                    [int(k) for k in g],
                )
            )
        elif prev_rate == prev_rate and rate < 1.15 * prev_rate:
            eps.append(
                Episode(
                    len(eps),
                    "s-run",
                    int(t_ms[g[0]]),
                    int(t_ms[g[-1]] - t_ms[g[0]]),
                    f"«НЖТ ×{len(g)}, {rate:.0f}/мин»",
                    "artifact",
                    0.8,
                    [f"синус до эпизода {prev_rate:.0f}/мин, скачка частоты нет"],
                    [int(k) for k in g],
                )
            )
        else:
            eps.append(
                Episode(
                    len(eps),
                    "s-run",
                    int(t_ms[g[0]]),
                    int(t_ms[g[-1]] - t_ms[g[0]]),
                    f"НЖЭС ×{len(g)}, {rate:.0f}/мин",
                    "review",
                    0.6,
                    [f"синус до эпизода {prev_rate:.0f}/мин"],
                    [int(k) for k in g],
                )
            )

    if missed_check is not None and len(rr) > 16:
        # Медиана 8 RR до и 8 после каждого интервала одним проходом: поштучный np.median
        # на 100k комплексов стоил 0.85 с каждого пересчёта.
        from numpy.lib.stride_tricks import sliding_window_view

        windows = sliding_window_view(rr, 17)
        med = np.median(np.concatenate([windows[:, :8], windows[:, 9:]], axis=1), axis=1)
        ks = np.arange(8, len(rr) - 8)
        x = rr[ks]
        for k in ks[(x >= 900) & (x < 2000) & (x >= 1.6 * med) & (x <= 2.4 * med)]:
            k = int(k)
            if noise_at(int(t_ms[k]), int(t_ms[k + 1])) >= 0.35:
                continue
            hit, why = missed_check(int(t_ms[k]), int(t_ms[k + 1]))
            if hit:
                eps.append(
                    Episode(
                        len(eps),
                        "missed",
                        int(t_ms[k]),
                        int(rr[k]),
                        f"Пропущен комплекс? RR {int(rr[k])} мс",
                        "review",
                        0.6,
                        [why],
                        [int(k), int(k + 1)],
                    )
                )

    bad_windows = sharp10 >= 0.5
    for g in runs(np.where(bad_windows)[0], max(1, 30 // window_s)):
        t0 = int(g[0] * window_s * 1000)
        t1 = int((g[-1] + 1) * window_s * 1000)
        eps.append(
            Episode(
                len(eps), "noise", t0, t1 - t0, f"Помеха {(t1 - t0) / 1000:.0f} с", "artifact", 0.9
            )
        )
    eps.sort(key=lambda e: e.t_ms)
    for n, e in enumerate(eps):
        e.id = n
    return eps
