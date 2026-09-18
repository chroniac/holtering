"""The paper protocol: everything the printed Holter report needs, built from the audited
State. Follows the final-protocol section of the Russian national Holter recommendations
(РКО/РОХМИНЭ 2013, Макаров): summary table, trends, samples of normal and every atypical
ECG, printouts of min/max HR and the longest pause, ectopy graded by density and
circadian type, symptom-rhythm correlation, physician's résumé."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import TYPE_CHECKING

import numpy as np

from .quality import WINDOW_S
from .rhythm import KEEP, plural

if TYPE_CHECKING:
    from .report import State

STRIP_S = 7.2                     # 180 mm of A4 at 25 mm/s
SECTIONS = ["rhythm", "ventricular", "supraventricular", "brady", "conduction", "symptoms", "quality", "resume", "recommendations"]
SECTION_TITLES = {
    "rhythm": "Ритм и ЧСС", "ventricular": "Желудочковая эктопия", "supraventricular": "Наджелудочковая эктопия",
    "brady": "Брадиаритмии и паузы", "conduction": "Фибрилляция предсердий, проводимость", "symptoms": "Симптомы по дневнику",
    "quality": "Качество записи", "resume": "Заключение", "recommendations": "Рекомендации",
}


def density_class(pct: float) -> str:
    """Ectopy frequency grade by share of all QRS, national recommendations 2013."""
    if pct < 0.1: return "единичная"
    if pct < 1: return "редкая"
    if pct < 10: return "умеренно частая"
    if pct < 20: return "частая"
    return "очень частая"


def circadian_type(t_ms: np.ndarray, sleep_minutes: np.ndarray) -> str:
    """Night / day / mixed by the ratio of ectopy rates during sleep and wake."""
    if not len(t_ms):
        return ""
    m = (t_ms // 60000).astype(int)
    m = m[m < len(sleep_minutes)]
    n_sleep = int(sleep_minutes[m].sum()); n_wake = int(len(m) - n_sleep)
    d_sleep = max(1, int(sleep_minutes.sum())); d_wake = max(1, int(len(sleep_minutes) - d_sleep))
    r = (n_sleep / d_sleep) / max(1e-9, n_wake / d_wake)
    return "ночной" if r > 2 else "дневной" if r < 0.5 else "смешанный"


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


_DEC = re.compile(r"(?<=\d)\.(?=\d)")


def _ru_decimal(text: str) -> str:
    """1.32 -> 1,32 in prose meant for the patient record (times like 06:44 are untouched)."""
    return _DEC.sub(",", text)


class Protocol:
    def __init__(self, st: "State"):
        self.st = st
        self.an = st.analysis
        self.clk = lambda ms: (st.cfg.start + timedelta(milliseconds=ms)).strftime("%H:%M")
        self.clks = lambda ms: (st.cfg.start + timedelta(milliseconds=ms)).strftime("%H:%M:%S")
        sleep = np.zeros(len(self.an["overview"]["minute_hr"]), bool)
        for a, b in self.an["overview"]["sleep"]:
            sleep[a:b] = True
        self.sleep = sleep
        self.kept_v = np.array(sorted(a.t_ms for a in st._audits.values() if a.label == "V" and a.verdict in KEEP), np.int64)
        self.kept_s = np.array(sorted(a.t_ms for a in st._audits.values() if a.label == "S" and a.verdict in KEEP), np.int64)
        self.real = [e for e in st._episodes if e.verdict != "artifact"]

    # ---- text --------------------------------------------------------------------
    def sections(self) -> dict[str, str]:
        st, an = self.st, self.an
        h, c, r = an["hr"], an["counts"], an["record"]
        ci = round(h["day"] / h["night"], 2) if h["day"] and h["night"] else None
        out: dict[str, str] = {}
        out["rhythm"] = (
            f"Основной ритм синусовый. ЧСС средняя за сутки {h['mean']} уд/мин, минимальная {h['min']} уд/мин ({self.clk(h['min_at_s'] * 1000)}), "
            f"максимальная {h['max']} уд/мин ({self.clk(h['max_at_s'] * 1000)}). Средняя дневная {h['day'] if h['day'] is not None else '—'}, средняя ночная {h['night'] if h['night'] is not None else '—'} уд/мин"
            + (f"; циркадный индекс {ci:.2f} (норма 1,22–1,45)" if ci else "") + ". "
            f"Тахикардия свыше 100 уд/мин {h['pct_over_100']:.1f}% времени, брадикардия ниже 50 уд/мин {h['pct_under_50']:.1f}%. "
            f"Вариабельность ритма: SDNN {an['hrv']['sdnn']:.0f} мс, RMSSD {an['hrv']['rmssd']:.0f} мс, pNN50 {an['hrv']['pnn50']:.1f}%."
        )
        # ventricular
        vL, vA = c["audited"]["V_likely"], c["audited"]["V"]
        runs = [e for e in self.real if e.kind == "v-run"]
        pairs = sum(1 for e in runs if len(e.beats) == 2); trip = [e for e in runs if len(e.beats) >= 3]
        morph = an["morphologies"]
        pct = 100 * vA / r["beats"]
        vt = f"Желудочковая экстрасистолия {density_class(pct)}: {vL}–{vA} за сутки ({100 * vL / r['beats']:.2f}–{pct:.2f}% комплексов), "
        vt += ("мономорфная" if len(morph) == 1 else f"полиморфная, {len(morph)} {plural(len(morph), 'морфология', 'морфологии', 'морфологий')}" if morph else "морфологии не выделены")
        ctype = circadian_type(self.kept_v, self.sleep)
        vt += f", циркадный тип {ctype}. " if ctype else ". "
        vt += (f"Парных {pairs}. " if pairs else "Парных нет. ")
        vt += (f"Групповых (3 и более): {len(trip)} ({', '.join(f'{self.clk(e.t_ms)} ×{len(e.beats)}' for e in trip)}). " if trip else "Групповых (3 и более) нет. ")
        rej = c["device"]["V"] - vA
        vt += f"Прибор насчитал {c['device']['V']}; {rej} {plural(rej, 'метка отклонена', 'метки отклонены', 'меток отклонены')} при проверке (двойной счёт, метки вне QRS, синусовая морфология, помехи)."
        out["ventricular"] = vt
        # supraventricular
        s_runs = [e for e in self.real if e.kind == "s-run"]
        sA = c["audited"]["S"]; spct = 100 * sA / r["beats"]
        stt = f"Наджелудочковая экстрасистолия {density_class(spct)}: {sA} за сутки ({spct:.2f}% комплексов)"
        sct = circadian_type(self.kept_s, self.sleep)
        stt += f", циркадный тип {sct}. " if sct else ". "
        stt += (f"Групповых: {len(s_runs)} ({', '.join(f'{self.clk(e.t_ms)} {e.title}' for e in s_runs)}). " if s_runs else "Пароксизмов наджелудочковой тахикардии не зарегистрировано. ")
        stt += f"Прибор насчитал {c['device']['S']}."
        out["supraventricular"] = stt
        # brady
        pauses = [e for e in self.real if e.kind == "pause"]
        bt = f"Минимальная ЧСС {h['min']} уд/мин в {self.clk(h['min_at_s'] * 1000)}" + (" (сон). " if self.sleep[min(len(self.sleep) - 1, h['min_at_s'] // 60)] else ". ")
        if pauses:
            longest = max(pauses, key=lambda e: e.dur_ms)
            bt += f"{len(pauses)} {plural(len(pauses), 'пауза', 'паузы', 'пауз')} более 2 с, максимальная {longest.dur_ms / 1000:.1f} с ({self.clk(longest.t_ms)}). "
        else:
            bt += "Пауз более 2 с не зарегистрировано. "
        fake = c["pauses_device"] - len(pauses)
        if fake > 0:
            bt += f"{fake} {plural(fake, '«пауза» прибора', '«паузы» прибора', '«пауз» прибора')} при проверке — потеря сигнала (отклеенный электрод, помеха), не асистолия."
        out["brady"] = bt
        af = next((x for x in an["criteria"] if x["key"] == "af"), None)
        out["conduction"] = (f"Фибрилляция предсердий: скрининг по нерегулярности RR — {af['value'] if af else '—'}; оценка по зубцам P за врачом. "
                             "АВ-проводимость по автоматическим данным не оценивается: без разметки зубцов P блокады II–III степени исключаются только визуально.")
        # symptoms
        evs = st.events_with_context()
        if evs:
            rows = []
            for e in evs:
                what = []
                if e["hr"] is not None: what.append(f"ЧСС {e['hr']} ({e['hr_min']}–{e['hr_max']}) уд/мин")
                what.append(f"ЖЭС {e['v']}" if e["v"] else "ЖЭС нет"); what.append(f"НЖЭС {e['s']}" if e["s"] else "НЖЭС нет")
                if e["episodes"]: what.append(f"{len(e['episodes'])} {plural(len(e['episodes']), 'эпизод', 'эпизода', 'эпизодов')}")
                if e["noise"] >= 0.5: what.append("помеха на записи")
                rows.append(f"{self.clk(e['t_ms'])} — {e['text'] or 'симптом'}: в пределах ±2 мин {', '.join(what)}.")
            out["symptoms"] = "\n".join(rows)
        else:
            out["symptoms"] = "Дневник пациента не заполнен; сопоставление симптомов с ритмом не проводилось."
        # quality
        qt = f"Чистый сигнал {r['clean_pct']}% времени записи. "
        n_manual = c["manual"] + c["added"] + c["quality_spans"]
        qt += (f"Правки врача: {c['manual']} {plural(c['manual'], 'комплекс переразмечен', 'комплекса переразмечено', 'комплексов переразмечено')}, "
               f"{c['added']} добавлено, {c['quality_spans']} {plural(c['quality_spans'], 'диапазон', 'диапазона', 'диапазонов')} качества. " if n_manual else "Ручных правок разметки нет. ")
        if r["gain_verified"]:
            qt += f"Масштаб напряжения калиброван по распечатке CardioSpy (коэффициент {r['gain']:g}). Интервал QT не оценивался: частота дискретизации 125 Гц."
        else:
            qt += "Масштаб напряжения экспорта не калиброван: амплитуды на фрагментах приведены без масштаба, сегмент ST, зубец T и вольтаж не оценивались. Интервал QT не оценивался: частота дискретизации 125 Гц."
        out["quality"] = qt
        # résumé: the physician's summary, generated as a starting point
        res = f"Синусовый ритм со средней ЧСС {h['mean']} уд/мин (мин. {h['min']}, макс. {h['max']})"
        res += f", циркадный индекс {ci:.2f}. " if ci else ". "
        res += f"{density_class(pct).capitalize()} "
        res += ("мономорфная " if len(morph) == 1 else "полиморфная " if len(morph) > 1 else "")
        res += f"желудочковая экстрасистолия ({vA} за сутки)" + (f", парная ({pairs})" if pairs else "") + (f", групповая ({len(trip)})" if trip else "") + ". "
        res += f"{density_class(spct).capitalize()} наджелудочковая экстрасистолия ({sA} за сутки)" + (f", групповая ({len(s_runs)})" if s_runs else "") + ". "
        res += ("Пауз более 2 с нет. " if not pauses else f"Паузы до {max(e.dur_ms for e in pauses) / 1000:.1f} с. ")
        res += "Фибрилляции предсердий по нерегулярности ритма не выявлено." if af and af["value"].startswith("нерегулярных окон нет") else "Нерегулярный ритм требует оценки по зубцам P."
        out["resume"] = res
        out["recommendations"] = ""
        return {k: _ru_decimal(v) for k, v in out.items()}

    # ---- tables ------------------------------------------------------------------
    def summary_rows(self) -> list[dict]:
        """The mandatory summary table: duration, HR spread, HRV, pauses, ectopy."""
        an = self.an; h, c, r = an["hr"], an["counts"], an["record"]
        dur = timedelta(seconds=int(r["duration_s"]))
        pauses = [e for e in self.real if e.kind == "pause"]
        runs = [e for e in self.real if e.kind == "v-run"]
        s_runs = [e for e in self.real if e.kind == "s-run"]
        vA = c["audited"]["V"]; sA = c["audited"]["S"]
        ci = f"{h['day'] / h['night']:.2f}" if h["day"] and h["night"] else "—"
        rows = [
            {"k": "Длительность записи", "v": f"{dur.seconds // 3600} ч {dur.seconds % 3600 // 60} мин", "n": f"комплексов {_fmt_int(r['beats'])}"},
            {"k": "ЧСС средняя / мин / макс", "v": f"{h['mean']} / {h['min']} / {h['max']} уд/мин", "n": f"мин. в {self.clk(h['min_at_s'] * 1000)}, макс. в {self.clk(h['max_at_s'] * 1000)}"},
            {"k": "ЧСС днём / ночью", "v": f"{h['day'] if h['day'] is not None else '—'} / {h['night'] if h['night'] is not None else '—'} уд/мин", "n": f"циркадный индекс {ci}"},
            {"k": "Вариабельность (SDNN / RMSSD)", "v": f"{an['hrv']['sdnn']:.0f} / {an['hrv']['rmssd']:.0f} мс", "n": f"pNN50 {an['hrv']['pnn50']:.1f}%"},
            {"k": "Желудочковые экстрасистолы", "v": f"{vA}", "n": f"{100 * vA / r['beats']:.2f}%, {density_class(100 * vA / r['beats'])}; парных {sum(1 for e in runs if len(e.beats) == 2)}, групповых {sum(1 for e in runs if len(e.beats) >= 3)}"},
            {"k": "Наджелудочковые экстрасистолы", "v": f"{sA}", "n": f"{100 * sA / r['beats']:.2f}%, {density_class(100 * sA / r['beats'])}; групповых {len(s_runs)}"},
            {"k": "Паузы более 2 с", "v": f"{len(pauses)}", "n": (f"максимальная {max(e.dur_ms for e in pauses) / 1000:.1f} с" if pauses else "нет") + (f"; {c['pauses_device'] - len(pauses)} у прибора — помехи" if c['pauses_device'] > len(pauses) else "")},
            {"k": "Чистый сигнал", "v": f"{r['clean_pct']}%", "n": "по независимым каналам, окна по 2 с"},
        ]
        return [{k: _ru_decimal(v) for k, v in row.items()} for row in rows]

    def hourly(self) -> list[dict]:
        """One row per wall-clock hour (10:00, 11:00, ...), the way Holter tables are read
        against diary times; the first and last rows are partial and labelled by their true start."""
        st, an = self.st, self.an
        hr = an["overview"]["minute_hr"]; noise = np.array(an["overview"]["noise10"], float)
        start = st.cfg.start
        first_edge = ((60 - start.minute) * 60 - start.second) * 1000 if (start.minute or start.second) else 3_600_000
        edges = [0]
        t = first_edge
        while t < st.total_ms:
            edges.append(t); t += 3_600_000
        edges.append(st.total_ms + 1)
        rows = []
        for i in range(len(edges) - 1):
            lo, hi = edges[i], edges[i + 1]
            if hi - lo < 60_000:
                continue
            a, b = int(np.searchsorted(st.t_ms, lo)), int(np.searchsorted(st.t_ms, hi))
            v = int(((self.kept_v >= lo) & (self.kept_v < hi)).sum()); s_ = int(((self.kept_s >= lo) & (self.kept_s < hi)).sum())
            m0, m1 = int(lo // 60000), int(-(-hi // 60000))
            hm = [x for x in hr[m0:m1] if x is not None]
            eps = [e for e in self.real if lo <= e.t_ms < hi]
            runs = [e for e in eps if e.kind == "v-run"]
            wa, wb = int(lo // 1000 // WINDOW_S), int(hi // 1000 // WINDOW_S)
            nz = noise[wa:wb]
            partial = (hi - lo) < 3_540_000
            rows.append({"hour": self.clk(lo) if i == 0 else self.clk(lo)[:2] + ":00", "partial": partial, "minutes": int(round((hi - lo) / 60000)),
                         "beats": b - a,
                         "hr_min": round(min(hm)) if hm else None, "hr_mean": round(float(np.mean(hm))) if hm else None, "hr_max": round(max(hm)) if hm else None,
                         "v": v, "s": s_, "pairs": sum(1 for e in runs if len(e.beats) == 2), "runs": sum(1 for e in runs if len(e.beats) >= 3),
                         "s_runs": sum(1 for e in eps if e.kind == "s-run"), "pauses": sum(1 for e in eps if e.kind == "pause"),
                         "noise_pct": round(float((nz >= 0.5).mean() * 100), 1) if len(nz) else 0.0,
                         "sleep": bool(self.sleep[m0:m1].mean() > 0.5) if len(self.sleep) > m0 else False})
        return rows

    # ---- strips ------------------------------------------------------------------
    def auto_strips(self) -> list[dict]:
        """The printouts the 2013 recommendations ask for: min and max HR, the longest pause,
        a sample of the base rhythm, one sample per PVC morphology, the runs, every diary entry."""
        st, an = self.st, self.an
        h = an["hr"]; out: list[dict] = []
        half = STRIP_S * 1000 / 2

        def add(kind: str, centre_ms: float, caption: str, key: str, dur_s: float = STRIP_S, beat: int | None = None):
            t0 = max(0.0, min(st.total_ms - dur_s * 1000, centre_ms - dur_s * 1000 / 2))
            out.append({"id": key, "kind": kind, "t0_ms": int(t0), "dur_s": dur_s, "caption": caption, "beat": beat})

        # base rhythm: the cleanest 7 s in the minute whose HR is closest to the daily mean
        hr = an["overview"]["minute_hr"]; noise = np.array(an["overview"]["noise10"], float)
        cand = sorted((abs(v - h["mean"]), m) for m, v in enumerate(hr) if v is not None and not self.sleep[m])[:30]
        best = None
        for _, m in cand:
            wa = int(m * 60 // WINDOW_S); wb = wa + int(60 // WINDOW_S)
            seg = noise[wa:wb]
            if len(seg) and seg.max() < 0.15:
                best = m; break
        if best is None and cand:
            best = cand[0][1]
        if best is not None:
            add("sinus", best * 60000 + 30000, f"Основной ритм: синусовый, ЧСС {round(hr[best])} уд/мин", "sinus")
        add("hr-min", h["min_at_s"] * 1000, f"Минимальная ЧСС {h['min']} уд/мин" + (" (сон)" if self.sleep[min(len(self.sleep) - 1, h['min_at_s'] // 60)] else ""), "hr-min")
        add("hr-max", h["max_at_s"] * 1000, f"Максимальная ЧСС {h['max']} уд/мин", "hr-max")
        pauses = [e for e in self.real if e.kind == "pause"]
        if pauses:
            e = max(pauses, key=lambda x: x.dur_ms)
            add("pause", e.t_ms + e.dur_ms / 2, f"Максимальная пауза {e.dur_ms / 1000:.1f} с", f"pause-{e.id}", beat=e.beats[0] if e.beats else None)
        for e in [x for x in self.real if x.kind == "v-run"][:8]:
            dur = STRIP_S if e.dur_ms / 1000 + 3 <= STRIP_S else float(np.ceil(e.dur_ms / 1000 + 3))
            add("v-run", e.t_ms + e.dur_ms / 2, e.title, f"ep-{e.id}", dur, beat=e.beats[0] if e.beats else None)
        for e in [x for x in self.real if x.kind == "s-run"][:4]:
            dur = STRIP_S if e.dur_ms / 1000 + 3 <= STRIP_S else float(np.ceil(e.dur_ms / 1000 + 3))
            add("s-run", e.t_ms + e.dur_ms / 2, e.title, f"ep-{e.id}", dur, beat=e.beats[0] if e.beats else None)
        # one example per PVC morphology (families with >= 3 kept V): the most confident
        # isolated member, so the printout shows the shape rather than a pair already shown above
        in_run = {k for e in self.real if e.kind in ("v-run", "s-run") for k in e.beats}
        for i, m in enumerate(an["morphologies"][:4]):
            fam = m["family"]
            members = [a for a in st._audits.values() if a.label == "V" and a.verdict in KEEP and a.family == fam]
            if not members:
                continue
            a = max(members, key=lambda x: (x.index not in in_run, x.verdict == "manual", -(x.noise_ratio or 0), x.confidence))
            add("pvc", a.t_ms, f"Желудочковая экстрасистола, морфология {i + 1} ({m['count']} за сутки)", f"pvc-{fam}", beat=a.index)
        # one supraventricular example
        sv = [a for a in st._audits.values() if a.label == "S" and a.verdict in KEEP]
        if sv:
            a = max(sv, key=lambda x: (x.index not in in_run, x.verdict == "manual", -(x.noise_ratio or 0), x.confidence))
            add("sve", a.t_ms, "Наджелудочковая экстрасистола", "sve", beat=a.index)
        for e in st.events:
            add("symptom", e["t_ms"], f"Дневник: {e['text'] or 'симптом'}", f"sym-{e['id']}")
        return out

    def header(self) -> dict:
        an = self.an; p, r = an["patient"], an["record"]
        dur = timedelta(seconds=int(r["duration_s"]))
        end = self.st.cfg.start + dur
        return {"patient": p, "sex_ru": "муж." if p["sex"] == "M" else "жен." if p["sex"] == "F" else (p["sex"] or ""),
                "age_ru": f"{p['age']} {plural(int(p['age'] or 0), 'год', 'года', 'лет')}" if p["age"] is not None else "",
                "start": self.st.cfg.start.strftime("%d.%m.%Y %H:%M"), "end": end.strftime("%d.%m.%Y %H:%M"),
                "duration": f"{dur.seconds // 3600 + dur.days * 24} ч {dur.seconds % 3600 // 60} мин",
                "device": "LabTech EC-12H, 12 отведений, 125 Гц", "software": "CardioSpy (автоматический анализ); holtering (проверка разметки)",
                "leads": r["leads"], "beats": _fmt_int(r["beats"])}
