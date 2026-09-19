"""Бумажный протокол: всё, что нужно печатной форме, — docs/modules/analysis.md."""

import re
from datetime import timedelta
from typing import TYPE_CHECKING

import numpy as np
from msgspec import Struct

from .quality import WINDOW_S
from .rhythm import KEEP, Episode, plural
from .state import Patient

if TYPE_CHECKING:
    from .state import State

STRIP_S = 7.2  # 180 мм листа A4 при 25 мм/с
SECTIONS = [
    "rhythm",
    "ventricular",
    "supraventricular",
    "brady",
    "conduction",
    "symptoms",
    "quality",
    "resume",
    "recommendations",
]
SECTION_TITLES = {
    "rhythm": "Ритм и ЧСС",
    "ventricular": "Желудочковая эктопия",
    "supraventricular": "Наджелудочковая эктопия",
    "brady": "Брадиаритмии и паузы",
    "conduction": "Фибрилляция предсердий, проводимость",
    "symptoms": "Симптомы по дневнику",
    "quality": "Качество записи",
    "resume": "Заключение",
    "recommendations": "Рекомендации",
}


class SummaryRow(Struct):
    k: str
    v: str
    n: str


class HourlyRow(Struct):
    hour: str
    partial: bool
    minutes: int
    beats: int
    hr_min: int | None
    hr_mean: int | None
    hr_max: int | None
    v: int
    s: int
    pairs: int
    runs: int
    s_runs: int
    pauses: int
    noise_pct: float
    sleep: bool


class AutoStrip(Struct):
    id: str
    kind: str
    t0_ms: int
    dur_s: float
    caption: str
    beat: int | None


class ProtocolHeader(Struct):
    patient: Patient
    sex_ru: str
    age_ru: str
    start: str
    end: str
    duration: str
    device: str
    software: str
    leads: list[str]
    beats: str


def density_class(pct: float) -> str:
    """Градация частоты эктопии по доле от всех QRS, национальные рекомендации 2013."""
    if pct < 0.1:
        return "единичная"
    if pct < 1:
        return "редкая"
    if pct < 10:
        return "умеренно частая"
    if pct < 20:
        return "частая"
    return "очень частая"


def circadian_type(t_ms: np.ndarray, sleep_minutes: np.ndarray) -> str:
    """Ночной / дневной / смешанный по отношению частоты эктопии во сне и бодрствовании."""
    if not len(t_ms):
        return ""
    m = (t_ms // 60000).astype(int)
    m = m[m < len(sleep_minutes)]
    n_sleep = int(sleep_minutes[m].sum())
    n_wake = int(len(m) - n_sleep)
    d_sleep = max(1, int(sleep_minutes.sum()))
    d_wake = max(1, int(len(sleep_minutes) - d_sleep))
    r = (n_sleep / d_sleep) / max(1e-9, n_wake / d_wake)
    return "ночной" if r > 2 else "дневной" if r < 0.5 else "смешанный"


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


_DEC = re.compile(r"(?<=\d)\.(?=\d)")


def _ru_decimal(text: str) -> str:
    """1.32 -> 1,32 в тексте для истории болезни (время вида 06:44 не трогается)."""
    return _DEC.sub(",", text)


class Protocol:
    def __init__(self, st: State) -> None:
        self.st = st
        self.sm = st.analysis.summary
        self.ov = st.analysis.overview
        sleep = np.zeros(len(self.ov.minute_hr), bool)
        for a, b in self.ov.sleep:
            sleep[a:b] = True
        self.sleep = sleep
        kept = [a for a in st.audits.values() if a.verdict in KEEP]
        self.kept_v = np.array(sorted(a.t_ms for a in kept if a.label == "V"), np.int64)
        self.kept_s = np.array(sorted(a.t_ms for a in kept if a.label == "S"), np.int64)
        self.real = [e for e in st.episodes if e.verdict != "artifact"]

    def clk(self, ms: float) -> str:
        return (self.st.start + timedelta(milliseconds=ms)).strftime("%H:%M")

    def sections(self) -> dict[str, str]:
        st = self.st
        h, c, r = self.sm.hr, self.sm.counts, self.sm.record
        ci = round(h.day / h.night, 2) if h.day and h.night else None
        out: dict[str, str] = {}
        out["rhythm"] = (
            f"Основной ритм синусовый. ЧСС средняя за сутки {h.mean} уд/мин, минимальная {h.min} уд/мин ({self.clk(h.min_at_s * 1000)}), "
            f"максимальная {h.max} уд/мин ({self.clk(h.max_at_s * 1000)}). Средняя дневная {h.day if h.day is not None else '—'}, средняя ночная {h.night if h.night is not None else '—'} уд/мин"
            + (f"; циркадный индекс {ci:.2f} (норма 1,22–1,45)" if ci else "")
            + ". "
            f"Тахикардия свыше 100 уд/мин {h.pct_over_100:.1f}% времени, брадикардия ниже 50 уд/мин {h.pct_under_50:.1f}%. "
            f"Вариабельность ритма: SDNN {self.sm.hrv.sdnn:.0f} мс, RMSSD {self.sm.hrv.rmssd:.0f} мс, pNN50 {self.sm.hrv.pnn50:.1f}%."
        )
        v_likely, v_audited = c.audited.V_likely, c.audited.V
        runs = [e for e in self.real if e.kind == "v-run"]
        pairs = sum(1 for e in runs if len(e.beats) == 2)
        trip = [e for e in runs if len(e.beats) >= 3]
        morph = self.sm.morphologies
        pct = 100 * v_audited / r.beats
        vt = f"Желудочковая экстрасистолия {density_class(pct)}: {v_likely}–{v_audited} за сутки ({100 * v_likely / r.beats:.2f}–{pct:.2f}% комплексов), "
        vt += (
            "мономорфная"
            if len(morph) == 1
            else f"полиморфная, {len(morph)} {plural(len(morph), 'морфология', 'морфологии', 'морфологий')}"
            if morph
            else "морфологии не выделены"
        )
        ctype = circadian_type(self.kept_v, self.sleep)
        vt += f", циркадный тип {ctype}. " if ctype else ". "
        vt += f"Парных {pairs}. " if pairs else "Парных нет. "
        vt += (
            f"Групповых (3 и более): {len(trip)} ({', '.join(f'{self.clk(e.t_ms)} ×{len(e.beats)}' for e in trip)}). "
            if trip
            else "Групповых (3 и более) нет. "
        )
        rej = c.device.V - v_audited
        vt += f"Прибор насчитал {c.device.V}; {rej} {plural(rej, 'метка отклонена', 'метки отклонены', 'меток отклонены')} при проверке (двойной счёт, метки вне QRS, синусовая морфология, помехи)."
        out["ventricular"] = vt
        s_runs = [e for e in self.real if e.kind == "s-run"]
        s_audited = c.audited.S
        spct = 100 * s_audited / r.beats
        stt = f"Наджелудочковая экстрасистолия {density_class(spct)}: {s_audited} за сутки ({spct:.2f}% комплексов)"
        sct = circadian_type(self.kept_s, self.sleep)
        stt += f", циркадный тип {sct}. " if sct else ". "
        stt += (
            f"Групповых: {len(s_runs)} ({', '.join(f'{self.clk(e.t_ms)} {e.title}' for e in s_runs)}). "
            if s_runs
            else "Пароксизмов наджелудочковой тахикардии не зарегистрировано. "
        )
        stt += f"Прибор насчитал {c.device.S}."
        out["supraventricular"] = stt
        pauses = [e for e in self.real if e.kind == "pause"]
        bt = f"Минимальная ЧСС {h.min} уд/мин в {self.clk(h.min_at_s * 1000)}" + (
            " (сон). " if self.sleep[min(len(self.sleep) - 1, h.min_at_s // 60)] else ". "
        )
        if pauses:
            longest = max(pauses, key=lambda e: e.dur_ms)
            bt += f"{len(pauses)} {plural(len(pauses), 'пауза', 'паузы', 'пауз')} более 2 с, максимальная {longest.dur_ms / 1000:.1f} с ({self.clk(longest.t_ms)}). "
        else:
            bt += "Пауз более 2 с не зарегистрировано. "
        fake = c.pauses_device - len(pauses)
        if fake > 0:
            bt += f"{fake} {plural(fake, '«пауза» прибора', '«паузы» прибора', '«пауз» прибора')} при проверке — потеря сигнала (отклеенный электрод, помеха), не асистолия."
        out["brady"] = bt
        af = next((x for x in self.sm.criteria if x.key == "af"), None)
        out["conduction"] = (
            f"Фибрилляция предсердий: скрининг по нерегулярности RR — {af.value if af else '—'}; оценка по зубцам P за врачом. "
            "АВ-проводимость по автоматическим данным не оценивается: без разметки зубцов P блокады II–III степени исключаются только визуально."
        )
        evs = st.events_with_context()
        if evs:
            rows = []
            for e in evs:
                what = []
                if e.hr is not None:
                    what.append(f"ЧСС {e.hr} ({e.hr_min}–{e.hr_max}) уд/мин")
                what.append(f"ЖЭС {e.v}" if e.v else "ЖЭС нет")
                what.append(f"НЖЭС {e.s}" if e.s else "НЖЭС нет")
                if e.episodes:
                    what.append(
                        f"{len(e.episodes)} {plural(len(e.episodes), 'эпизод', 'эпизода', 'эпизодов')}"
                    )
                if e.noise >= 0.5:
                    what.append("помеха на записи")
                rows.append(
                    f"{self.clk(e.t_ms)} — {e.text or 'симптом'}: в пределах ±2 мин {', '.join(what)}."
                )
            out["symptoms"] = "\n".join(rows)
        else:
            out["symptoms"] = (
                "Дневник пациента не заполнен; сопоставление симптомов с ритмом не проводилось."
            )
        qt = f"Чистый сигнал {r.clean_pct}% времени записи. "
        n_manual = c.manual + c.added + c.quality_spans
        qt += (
            f"Правки врача: {c.manual} {plural(c.manual, 'комплекс переразмечен', 'комплекса переразмечено', 'комплексов переразмечено')}, "
            f"{c.added} добавлено, {c.quality_spans} {plural(c.quality_spans, 'диапазон', 'диапазона', 'диапазонов')} качества. "
            if n_manual
            else "Ручных правок разметки нет. "
        )
        if r.gain_verified:
            qt += f"Масштаб напряжения калиброван по распечатке CardioSpy (коэффициент {r.gain:g}). Интервал QT не оценивался: частота дискретизации 125 Гц."
        else:
            qt += "Масштаб напряжения экспорта не калиброван: амплитуды на фрагментах приведены без масштаба, сегмент ST, зубец T и вольтаж не оценивались. Интервал QT не оценивался: частота дискретизации 125 Гц."
        out["quality"] = qt
        res = f"Синусовый ритм со средней ЧСС {h.mean} уд/мин (мин. {h.min}, макс. {h.max})"
        res += f", циркадный индекс {ci:.2f}. " if ci else ". "
        res += f"{density_class(pct).capitalize()} "
        res += "мономорфная " if len(morph) == 1 else "полиморфная " if len(morph) > 1 else ""
        res += (
            f"желудочковая экстрасистолия ({v_audited} за сутки)"
            + (f", парная ({pairs})" if pairs else "")
            + (f", групповая ({len(trip)})" if trip else "")
            + ". "
        )
        res += (
            f"{density_class(spct).capitalize()} наджелудочковая экстрасистолия ({s_audited} за сутки)"
            + (f", групповая ({len(s_runs)})" if s_runs else "")
            + ". "
        )
        res += (
            "Пауз более 2 с нет. "
            if not pauses
            else f"Паузы до {max(e.dur_ms for e in pauses) / 1000:.1f} с. "
        )
        res += (
            "Фибрилляции предсердий по нерегулярности ритма не выявлено."
            if af and af.value.startswith("нерегулярных окон нет")
            else "Нерегулярный ритм требует оценки по зубцам P."
        )
        out["resume"] = res
        out["recommendations"] = ""
        return {k: _ru_decimal(v) for k, v in out.items()}

    def summary_rows(self) -> list[SummaryRow]:
        """Обязательная сводная таблица: длительность, разброс ЧСС, ВСР, паузы, эктопия."""
        h, c, r = self.sm.hr, self.sm.counts, self.sm.record
        dur = timedelta(seconds=int(r.duration_s))
        pauses = [e for e in self.real if e.kind == "pause"]
        runs = [e for e in self.real if e.kind == "v-run"]
        s_runs = [e for e in self.real if e.kind == "s-run"]
        v_audited, s_audited = c.audited.V, c.audited.S
        ci = f"{h.day / h.night:.2f}" if h.day and h.night else "—"
        pause_note = (
            f"максимальная {max(e.dur_ms for e in pauses) / 1000:.1f} с" if pauses else "нет"
        ) + (
            f"; {c.pauses_device - len(pauses)} у прибора — помехи"
            if c.pauses_device > len(pauses)
            else ""
        )
        rows = [
            SummaryRow(
                k="Длительность записи",
                v=f"{dur.seconds // 3600} ч {dur.seconds % 3600 // 60} мин",
                n=f"комплексов {_fmt_int(r.beats)}",
            ),
            SummaryRow(
                k="ЧСС средняя / мин / макс",
                v=f"{h.mean} / {h.min} / {h.max} уд/мин",
                n=f"мин. в {self.clk(h.min_at_s * 1000)}, макс. в {self.clk(h.max_at_s * 1000)}",
            ),
            SummaryRow(
                k="ЧСС днём / ночью",
                v=f"{h.day if h.day is not None else '—'} / {h.night if h.night is not None else '—'} уд/мин",
                n=f"циркадный индекс {ci}",
            ),
            SummaryRow(
                k="Вариабельность (SDNN / RMSSD)",
                v=f"{self.sm.hrv.sdnn:.0f} / {self.sm.hrv.rmssd:.0f} мс",
                n=f"pNN50 {self.sm.hrv.pnn50:.1f}%",
            ),
            SummaryRow(
                k="Желудочковые экстрасистолы",
                v=f"{v_audited}",
                n=f"{100 * v_audited / r.beats:.2f}%, {density_class(100 * v_audited / r.beats)}; парных {sum(1 for e in runs if len(e.beats) == 2)}, групповых {sum(1 for e in runs if len(e.beats) >= 3)}",
            ),
            SummaryRow(
                k="Наджелудочковые экстрасистолы",
                v=f"{s_audited}",
                n=f"{100 * s_audited / r.beats:.2f}%, {density_class(100 * s_audited / r.beats)}; групповых {len(s_runs)}",
            ),
            SummaryRow(k="Паузы более 2 с", v=f"{len(pauses)}", n=pause_note),
            SummaryRow(
                k="Чистый сигнал",
                v=f"{r.clean_pct}%",
                n="по независимым каналам, окна по 2 с",
            ),
        ]
        return [
            SummaryRow(k=_ru_decimal(row.k), v=_ru_decimal(row.v), n=_ru_decimal(row.n))
            for row in rows
        ]

    def hourly(self) -> list[HourlyRow]:
        """Строка на календарный час: так холтеровские таблицы читают против времён дневника."""
        st = self.st
        hr = self.ov.minute_hr
        noise = np.array(self.ov.noise10, float)
        start = st.start
        first_edge = (
            ((60 - start.minute) * 60 - start.second) * 1000
            if (start.minute or start.second)
            else 3_600_000
        )
        edges = [0]
        t = first_edge
        while t < st.total_ms:
            edges.append(t)
            t += 3_600_000
        edges.append(st.total_ms + 1)
        rows = []
        for i in range(len(edges) - 1):
            lo, hi = edges[i], edges[i + 1]
            if hi - lo < 60_000:
                continue
            a, b = int(np.searchsorted(st.t_ms, lo)), int(np.searchsorted(st.t_ms, hi))
            v = int(((self.kept_v >= lo) & (self.kept_v < hi)).sum())
            s_ = int(((self.kept_s >= lo) & (self.kept_s < hi)).sum())
            m0, m1 = int(lo // 60000), int(-(-hi // 60000))
            hm = [x for x in hr[m0:m1] if x is not None]
            eps = [e for e in self.real if lo <= e.t_ms < hi]
            runs = [e for e in eps if e.kind == "v-run"]
            wa, wb = int(lo // 1000 // WINDOW_S), int(hi // 1000 // WINDOW_S)
            nz = noise[wa:wb]
            rows.append(
                HourlyRow(
                    hour=self.clk(lo) if i == 0 else self.clk(lo)[:2] + ":00",
                    partial=(hi - lo) < 3_540_000,
                    minutes=round((hi - lo) / 60000),
                    beats=b - a,
                    hr_min=round(min(hm)) if hm else None,
                    hr_mean=round(float(np.mean(hm))) if hm else None,
                    hr_max=round(max(hm)) if hm else None,
                    v=v,
                    s=s_,
                    pairs=sum(1 for e in runs if len(e.beats) == 2),
                    runs=sum(1 for e in runs if len(e.beats) >= 3),
                    s_runs=sum(1 for e in eps if e.kind == "s-run"),
                    pauses=sum(1 for e in eps if e.kind == "pause"),
                    noise_pct=round(float((nz >= 0.5).mean() * 100), 1) if len(nz) else 0.0,
                    sleep=bool(self.sleep[m0:m1].mean() > 0.5) if len(self.sleep) > m0 else False,
                )
            )
        return rows

    def auto_strips(self) -> list[AutoStrip]:
        """Распечатки, которых требуют рекомендации 2013, — docs/modules/analysis.md."""
        st = self.st
        h = self.sm.hr
        out: list[AutoStrip] = []

        def add(
            kind: str,
            centre_ms: float,
            caption: str,
            key: str,
            dur_s: float = STRIP_S,
            beat: int | None = None,
        ) -> None:
            t0 = max(0.0, min(st.total_ms - dur_s * 1000, centre_ms - dur_s * 1000 / 2))
            out.append(
                AutoStrip(id=key, kind=kind, t0_ms=int(t0), dur_s=dur_s, caption=caption, beat=beat)
            )

        hr = self.ov.minute_hr
        noise = np.array(self.ov.noise10, float)
        # Основной ритм: самые чистые 7 с в минуте, чья ЧСС ближе всего к суточной средней.
        cand = sorted(
            (abs(v - h.mean), m, v) for m, v in enumerate(hr) if v is not None and not self.sleep[m]
        )[:30]
        best: tuple[int, float] | None = None
        for _, m, value in cand:
            wa = int(m * 60 // WINDOW_S)
            wb = wa + int(60 // WINDOW_S)
            seg = noise[wa:wb]
            if len(seg) and seg.max() < 0.15:
                best = (m, value)
                break
        if best is None and cand:
            best = (cand[0][1], cand[0][2])
        if best is not None:
            add(
                "sinus",
                best[0] * 60000 + 30000,
                f"Основной ритм: синусовый, ЧСС {round(best[1])} уд/мин",
                "sinus",
            )
        add(
            "hr-min",
            h.min_at_s * 1000,
            f"Минимальная ЧСС {h.min} уд/мин"
            + (" (сон)" if self.sleep[min(len(self.sleep) - 1, h.min_at_s // 60)] else ""),
            "hr-min",
        )
        add("hr-max", h.max_at_s * 1000, f"Максимальная ЧСС {h.max} уд/мин", "hr-max")
        pauses = [e for e in self.real if e.kind == "pause"]
        if pauses:
            e = max(pauses, key=lambda x: x.dur_ms)
            add(
                "pause",
                e.t_ms + e.dur_ms / 2,
                f"Максимальная пауза {e.dur_ms / 1000:.1f} с",
                f"pause-{e.id}",
                beat=e.beats[0] if e.beats else None,
            )
        for e in [x for x in self.real if x.kind == "v-run"][:8]:
            add(
                "v-run",
                e.t_ms + e.dur_ms / 2,
                e.title,
                f"ep-{e.id}",
                _strip_seconds(e),
                beat=e.beats[0] if e.beats else None,
            )
        for e in [x for x in self.real if x.kind == "s-run"][:4]:
            add(
                "s-run",
                e.t_ms + e.dur_ms / 2,
                e.title,
                f"ep-{e.id}",
                _strip_seconds(e),
                beat=e.beats[0] if e.beats else None,
            )
        # По одному примеру на морфологию ЖЭС: самый уверенный одиночный комплекс, чтобы
        # распечатка показывала форму, а не уже показанную выше пару.
        in_run = {k for e in self.real if e.kind in ("v-run", "s-run") for k in e.beats}
        for i, m in enumerate(self.sm.morphologies[:4]):
            members = [
                a
                for a in st.audits.values()
                if a.label == "V" and a.verdict in KEEP and a.family == m.family
            ]
            if not members:
                continue
            a = max(members, key=lambda x: _strip_rank(x, in_run))
            add(
                "pvc",
                a.t_ms,
                f"Желудочковая экстрасистола, морфология {i + 1} ({m.count} за сутки)",
                f"pvc-{m.family}",
                beat=a.index,
            )
        sv = [a for a in st.audits.values() if a.label == "S" and a.verdict in KEEP]
        if sv:
            a = max(sv, key=lambda x: _strip_rank(x, in_run))
            add("sve", a.t_ms, "Наджелудочковая экстрасистола", "sve", beat=a.index)
        for ev in st.events:
            add("symptom", ev.t_ms, f"Дневник: {ev.text or 'симптом'}", f"sym-{ev.id}")
        return out

    def header(self) -> ProtocolHeader:
        p, r = self.sm.patient, self.sm.record
        dur = timedelta(seconds=int(r.duration_s))
        end = self.st.start + dur
        return ProtocolHeader(
            patient=p,
            sex_ru="муж." if p.sex == "M" else "жен." if p.sex == "F" else (p.sex or ""),
            age_ru=f"{p.age} {plural(int(p.age or 0), 'год', 'года', 'лет')}"
            if p.age is not None
            else "",
            start=self.st.start.strftime("%d.%m.%Y %H:%M"),
            end=end.strftime("%d.%m.%Y %H:%M"),
            duration=f"{dur.seconds // 3600 + dur.days * 24} ч {dur.seconds % 3600 // 60} мин",
            device="LabTech EC-12H, 12 отведений, 125 Гц",
            software="CardioSpy (автоматический анализ); holtering (проверка разметки)",
            leads=r.leads,
            beats=_fmt_int(r.beats),
        )


def _strip_seconds(e: Episode) -> float:
    return STRIP_S if e.dur_ms / 1000 + 3 <= STRIP_S else float(np.ceil(e.dur_ms / 1000 + 3))


def _strip_rank(audit, in_run: set[int]) -> tuple[bool, bool, float, float]:
    return (
        audit.index not in in_run,
        audit.verdict == "manual",
        -(audit.noise_ratio or 0),
        audit.confidence,
    )
