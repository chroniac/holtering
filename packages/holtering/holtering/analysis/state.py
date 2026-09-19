"""Состояние записи: тяжёлый проход считается один раз и кэшируется, лёгкий (счётчики,
эпизоды, поминутные ряды) пересчитывается на каждую ручную правку."""

import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import msgspec
import numpy as np
from msgspec import Struct, field

from holtering.settings import RecordSettings

from . import templates as tpl
from .beats import BeatAudit, BeatAuditor, apply_family_evidence
from .quality import (
    INDEPENDENT,
    WINDOW_S,
    gap_artifact,
    missed_beat,
    noise_score,
    window_metrics,
)
from .rhythm import (
    KEEP,
    Episode,
    Hrv,
    estimate_sleep,
    extract_episodes,
    hr_per_minute,
    hrv,
    nn_intervals,
    per_minute_counts,
)
from .templates import Template

MANUAL_LABELS = {"N", "V", "S", "X"}  # X — артефакт, не комплекс
LABEL_CODE = {"N": 0, "V": 1, "S": 2, "X": 3}
CLASS_CODE = {"N": 0, "manual-N": 0, "likely": 1, "uncertain": 2, "manual": 4, "manual-X": 3}

_FNAME_DATE = re.compile(r"DATE(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})")


def enc_hook(value: object) -> object:
    """numpy-скаляры: msgspec кодирует только точные типы Python."""
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"не сериализуется: {type(value).__name__}")


class NoiseWindow(Struct):
    t0: int
    t1: int
    score: float


class QualitySpan(Struct):
    t0_ms: int
    t1_ms: int
    v: str


class DiaryEvent(Struct):
    id: int
    t_ms: int
    text: str


class EventContext(Struct):
    id: int
    t_ms: int
    text: str
    hr: int | None
    hr_min: int | None
    hr_max: int | None
    v: int
    s: int
    episodes: list[int]
    noise: float


class Strip(Struct):
    id: str
    t0_ms: int
    dur_s: float
    caption: str = ""
    leads: list[str] | None = None


class ReportEdits(Struct):
    text: dict[str, str] = field(default_factory=dict)
    meta: dict[str, str] = field(default_factory=dict)
    strips: list[Strip] = field(default_factory=list)
    captions: dict[str, str] = field(default_factory=dict)
    hidden: list[str] = field(default_factory=list)
    include: dict[str, bool] = field(default_factory=dict)


class Overrides(Struct):
    """Файл правок: метки, вставленные комплексы, качество, дневник, правки протокола."""

    labels: dict[int, str] = field(default_factory=dict)
    added: dict[int, str] = field(default_factory=dict)
    quality: list[QualitySpan] = field(default_factory=list)
    events: list[DiaryEvent] = field(default_factory=list)
    report: ReportEdits | None = None


class Calibration(Struct):
    sinus_width_ms: float
    noise_base_ii_mv: float
    wander_base_ii_mv: float
    qrs_amp_mv: float


class HeavyPass(Struct):
    """Кэш тяжёлого прохода: всё, что не зависит от ручных правок."""

    computed_s: float
    noise10: list[float]
    sharp10: list[float]
    calibration: Calibration
    audits: list[BeatAudit]
    beat_template: list[int]
    templates: list[Template]
    minute_hr: list[float | None]
    hrv: Hrv
    sleep: list[list[int]]


class Patient(Struct):
    name: str
    id: str | None
    sex: str | None
    age: int | None
    dob: str | None


class Record(Struct):
    start: str
    duration_s: float
    fs: int
    leads: list[str]
    beats: int
    avm_nv: int
    gain: float | None
    gain_verified: bool
    clean_pct: float


class HeartRate(Struct):
    mean: int
    min: int
    max: int
    min_at_s: int
    max_at_s: int
    night: int | None
    day: int | None
    sleep: int | None
    wake: int | None
    pct_over_100: float
    pct_under_50: float


class DeviceCounts(Struct):
    N: int
    V: int
    S: int


class AuditedCounts(Struct):
    # Диапазон намеренный: ширина QRS на 125 Гц гуляет на 1–2 отсчёта, поэтому нижняя
    # граница считает только уверенно широкие комплексы, верхняя добавляет пограничные.
    V: int
    V_likely: int
    S: int


class Counts(Struct):
    device: DeviceCounts
    audited: AuditedCounts
    manual: int
    added: int
    quality_spans: int
    verdicts: dict[str, dict[str, int]]
    pauses_device: int
    pauses_real: int


class Criterion(Struct):
    key: str
    title: str
    value: str
    met: bool | None
    note: str


class Morphology(Struct):
    family: int
    count: int


class Overview(Struct):
    minute_hr: list[float | None]
    minute_v: list[int]
    minute_s: list[int]
    minute_v_device: list[int]
    noise10: list[float]
    noise_window_s: int
    quality_manual: list[QualitySpan]
    sleep: list[list[int]]


class Summary(Struct):
    computed_s: float
    patient: Patient
    record: Record
    hr: HeartRate
    hrv: Hrv
    counts: Counts
    calibration: Calibration
    criteria: list[Criterion]
    morphologies: list[Morphology]


class Analysis(Struct):
    summary: Summary
    overview: Overview
    episodes: list[Episode]


class BeatInfo(Struct):
    index: int
    t_ms: int
    label: str
    device_label: str | None
    manual: str | None
    added: bool
    verdict: str
    confidence: float
    reasons: list[str]
    width_ms: float | None
    width_ratio: float | None
    prematurity: float | None
    amp_ratio: float | None
    noise_ratio: float | None
    family_n_frac: float | None
    rr_pre: int | None
    rr_post: int | None
    template: int


class TemplateView(Template):
    manual: dict[str, int]
    hours: list[int]


def resolve_start(scp: Path, explicit: datetime | None, patient: dict[str, Any]) -> datetime:
    """Время съёма: явная настройка, затем штамп DATE… в имени файла, затем секция 1."""
    if explicit is not None:
        return explicit
    stamp = _FNAME_DATE.search(scp.name)
    if stamp:
        y, mo, d, h, mi, s = (int(x) for x in stamp.groups())
        return datetime(y, mo, d, h, mi, s)
    acq_date = patient.get("acq_date", "1985-01-01")
    acq_time = patient.get("acq_time", "00:00:00")
    return datetime.fromisoformat(f"{acq_date} {acq_time}")


def _as_str(value: object) -> str | None:
    return None if value is None else str(value)


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def load_annotations(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rows = np.loadtxt(path, dtype=object, delimiter="\t", encoding="cp1251", ndmin=2)
    return rows[:, 0].astype(np.int64), rows[:, 1].astype(str)


class State:
    def __init__(self, cfg: RecordSettings) -> None:
        from scp_holter import ScpHolter

        self.cfg = cfg
        self.rec = ScpHolter(str(cfg.scp), invert=cfg.invert)
        if cfg.chest:
            self.rec.set_chest_labels(list(cfg.chest))
        self.start = resolve_start(cfg.scp, cfg.start, self.rec.patient)
        self.mm = self.rec.memmap()  # произвольный доступ: окна ЭКГ и аудит комплексов
        self.fs = round(self.rec.fs)
        # Одна знаковая шкала на всех потребителей: invert живёт здесь (memmap — байты как
        # они лежат), gain — калибровка по распечатке CardioSpy.
        self.mv = (
            self.rec.sign * self.rec.meta.mv_per_lsb * (cfg.gain if cfg.gain is not None else 1.0)
        )
        self.dev_t, self.dev_labels = load_annotations(cfg.qrs)  # что нашёл прибор, неизменяемо
        self.t_ms, self.labels = self.dev_t, self.dev_labels  # слитая картина, см. _merge()
        self.total_ms = int(self.dev_t[-1])
        # Привязка к пациенту и дате съёма: переиспользованное имя файла (raw.scp следующего
        # пациента) не унаследует ни метки, ни дневник, ни заключение.
        pid = str(self.rec.patient.get("patient_id") or "na")
        # An explicit cache_dir may not exist yet; next to the record it always does.
        cfg.cache_root.mkdir(parents=True, exist_ok=True)
        self.overrides_file = (
            cfg.cache_root / f"{cfg.scp.stem}.{pid}.{self.start:%Y%m%d}.overrides.json"
        )
        # Ключ — время (мс), чтобы вставленный комплекс не сдвинул чужой ключ.
        saved = (
            msgspec.json.decode(self.overrides_file.read_bytes(), type=Overrides)
            if self.overrides_file.exists()
            else Overrides()
        )
        self.relabels = saved.labels
        self.added = saved.added
        self.quality = saved.quality  # поздние записи побеждают
        self.events = saved.events
        self.report = saved.report

        cache = cfg.cache_file
        if cache.exists():
            base = msgspec.json.decode(cache.read_bytes(), type=HeavyPass)
        else:
            base = self._heavy()
            cache.write_bytes(msgspec.json.encode(base, enc_hook=enc_hook))
        self.base = base
        self.auto_noise = np.array(base.noise10, np.float32)  # затенение, качество записи
        self.auto_sharp = np.array(base.sharp10, np.float32)  # только вердикты комплексов
        self.noise10 = self.auto_noise
        self.sharp10 = self.auto_sharp
        self.dev_template = np.array(base.beat_template, np.int32)
        self.beat_template = self.dev_template
        self.auditor = BeatAuditor(
            self.mm,
            self.fs,
            self.mv,
            self.dev_t,
            self.dev_labels,
            base.calibration.noise_base_ii_mv,
            self.sharp10,
            WINDOW_S,
        )
        self.auditor.n_width = base.calibration.sinus_width_ms
        self.auto_audits: dict[int, BeatAudit] = {a.index: a for a in base.audits}
        self.audits: dict[int, BeatAudit] = {}
        self.episodes: list[Episode] = []
        self.recompute()

    @property
    def total_s(self) -> float:
        return self.mm.shape[1] / self.fs

    def _heavy(self) -> HeavyPass:
        t0 = time.time()
        n = self.mm.shape[1]
        hf, steps, rails, wander = window_metrics(self.rec.read_lead, n, self.fs, self.mv)
        noise10, sharp10, base = noise_score(hf, steps, rails, wander)
        wander_base = float(np.median(wander[:, INDEPENDENT.index(1)]))
        base_ii = float(base[INDEPENDENT.index(1)])
        auditor = BeatAuditor(
            self.mm, self.fs, self.mv, self.t_ms, self.labels, base_ii, sharp10, WINDOW_S
        )
        audits = auditor.audit_all()
        w, valid = tpl.beat_windows(self.rec.read_lead, n, self.fs, self.mv, self.t_ms)
        assign, _ = tpl.cluster(w, valid)
        apply_family_evidence(audits, assign, self.labels)
        verdicts = {a.index: a.verdict for a in audits}
        templates = tpl.summarise(w, assign, self.labels, verdicts, self.fs)
        t_nn, nn = nn_intervals(self.t_ms, self.labels)
        hr_min = hr_per_minute(t_nn, nn, self.total_ms)
        return HeavyPass(
            computed_s=round(time.time() - t0, 1),
            noise10=[round(float(x), 2) for x in noise10],
            sharp10=[round(float(x), 2) for x in sharp10],
            calibration=Calibration(
                sinus_width_ms=round(auditor.n_width, 1),
                noise_base_ii_mv=round(base_ii, 3),
                wander_base_ii_mv=round(wander_base, 3),
                qrs_amp_mv=round(float(np.nanmedian(list(auditor.hour_amp.values()))), 2),
            ),
            audits=audits,
            beat_template=assign.tolist(),
            templates=templates,
            minute_hr=hr_min,
            hrv=hrv(nn),
            sleep=estimate_sleep(hr_min),
        )

    def set_label(self, index: int, label: str | None) -> None:
        """Переразметить комплекс по слитому индексу; None снимает, у вставленного — удаляет."""
        t = int(self.t_ms[index])
        if self.origin[index] < 0:
            if label is None:
                self.added.pop(t, None)
            else:
                self._check(label)
                self.added[t] = label
        elif label is None:
            self.relabels.pop(t, None)
        else:
            self._check(label)
            self.relabels[t] = label
        self._persist()
        self.recompute()

    def add_beat(self, t_ms: int, label: str = "N") -> int:
        """Вставить комплекс, который прибор пропустил; возвращает слитый индекс."""
        self._check(label)
        t_ms = int(t_ms)
        if len(self.t_ms) and int(np.abs(self.t_ms - t_ms).min()) < 120:
            raise ValueError("within 120 ms of an existing beat - relabel that one instead")
        self.added[t_ms] = label
        self._persist()
        self.recompute()
        return int(np.searchsorted(self.t_ms, t_ms))

    def set_template_label(self, template_id: int, label: str | None) -> int:
        members = np.where(self.dev_template == template_id)[0]
        for k in members:
            t = int(self.dev_t[k])
            if label is None:
                self.relabels.pop(t, None)
            else:
                self._check(label)
                self.relabels[t] = label
        self._persist()
        self.recompute()
        return len(members)

    @staticmethod
    def _check(label: str) -> None:
        if label not in MANUAL_LABELS:
            raise ValueError(f"label must be one of {sorted(MANUAL_LABELS)}")

    def set_quality(self, t0_ms: int, t1_ms: int, value: str | None) -> None:
        """Пометить диапазон чистым или шумным вручную; None снимает все пересекающие его."""
        t0_ms, t1_ms = int(min(t0_ms, t1_ms)), int(max(t0_ms, t1_ms))
        if value is None:
            self.quality = [q for q in self.quality if q.t1_ms <= t0_ms or q.t0_ms >= t1_ms]
        else:
            if value not in ("clean", "noise"):
                raise ValueError("value must be clean, noise or null")
            self.quality.append(QualitySpan(t0_ms, t1_ms, value))
        self._persist()
        self.recompute()

    def _apply_quality(self) -> None:
        """Пересобрать качество из автоматического и ручного и переаудировать задетые комплексы."""
        self.noise10 = self.auto_noise.copy()
        self.sharp10 = self.auto_sharp.copy()
        self.auditor.noise10 = self.sharp10
        if not self.quality:
            return
        w = WINDOW_S * 1000
        touched: list[int] = []
        for q in self.quality:
            a, b = int(q.t0_ms // w), int(-(-q.t1_ms // w))
            val = 0.0 if q.v == "clean" else 1.0
            self.noise10[a:b] = val
            self.sharp10[a:b] = val
            lo, hi = np.searchsorted(self.dev_t, q.t0_ms), np.searchsorted(self.dev_t, q.t1_ms)
            touched += [int(k) for k in range(lo, hi) if self.dev_labels[k] != "N"]
        if touched:
            fresh = [self.auditor.audit(k) for k in sorted(set(touched))]
            apply_family_evidence(fresh, self.dev_template, self.dev_labels)
            for audit in fresh:
                self.auto_audits[audit.index] = audit

    def add_event(self, t_ms: int, text: str) -> EventContext:
        eid = 1 + max((e.id for e in self.events), default=0)
        ev = DiaryEvent(eid, int(t_ms), text.strip()[:200])
        self.events.append(ev)
        self.events.sort(key=lambda e: e.t_ms)
        self._persist()
        return self.event_context(ev)

    def remove_event(self, eid: int) -> None:
        self.events = [e for e in self.events if e.id != eid]
        self._persist()

    def event_context(self, ev: DiaryEvent, half_s: int = 120) -> EventContext:
        """Что делал ритм вокруг записи дневника: ЧСС, эктопия, эпизоды в ±half_s."""
        t = ev.t_ms
        lo, hi = t - half_s * 1000, t + half_s * 1000
        a, b = int(np.searchsorted(self.t_ms, lo)), int(np.searchsorted(self.t_ms, hi))
        rr = np.diff(self.t_ms[max(0, a - 1) : b + 1]) if b > a else np.array([], np.int64)
        rr = rr[(rr > 300) & (rr < 2000)]
        hr = round(float(60000 / rr.mean())) if len(rr) else None
        hr_min = round(float(60000 / rr.max())) if len(rr) else None
        hr_max = round(float(60000 / rr.min())) if len(rr) else None
        v = s_ = 0
        for k in range(a, b):
            au = self.audits.get(k)
            if au and au.verdict in KEEP:
                if au.label == "V":
                    v += 1
                elif au.label == "S":
                    s_ += 1
        eps = [
            e.id
            for e in self.episodes
            if e.t_ms <= hi and e.t_ms + e.dur_ms >= lo and e.verdict != "artifact"
        ]
        w = int(t / 1000 / WINDOW_S)
        return EventContext(
            id=ev.id,
            t_ms=ev.t_ms,
            text=ev.text,
            hr=hr,
            hr_min=hr_min,
            hr_max=hr_max,
            v=v,
            s=s_,
            episodes=eps,
            noise=float(self.noise10[w]) if 0 <= w < len(self.noise10) else 0.0,
        )

    def events_with_context(self) -> list[EventContext]:
        return [self.event_context(e) for e in self.events]

    def _persist(self) -> None:
        overrides = Overrides(
            labels=self.relabels,
            added=self.added,
            quality=self.quality,
            events=self.events,
            report=self.report,
        )
        self.overrides_file.write_bytes(msgspec.json.encode(overrides, enc_hook=enc_hook))

    def set_report(self, saved: ReportEdits) -> None:
        self.report = saved
        self._persist()

    @property
    def saved_report(self) -> dict[str, Any]:
        """Пустой объект, а не null: фронт отличает «правок не было» от сохранённого протокола."""
        return {} if self.report is None else msgspec.to_builtins(self.report)

    def _merge(self) -> None:
        """Пересобрать слитые массивы комплексов: приборные плюс вставленные, по времени."""
        if self.added:
            add_t = np.array(sorted(self.added), np.int64)
            t = np.concatenate([self.dev_t, add_t])
            origin = np.concatenate([np.arange(len(self.dev_t)), np.full(len(add_t), -1)])
            lab = np.concatenate(
                [
                    self.dev_labels,
                    np.array([self.added[int(x)] for x in add_t], dtype=self.dev_labels.dtype),
                ]
            )
            order = np.argsort(t, kind="stable")
            self.t_ms, self.origin, self.labels = t[order], origin[order], lab[order]
        else:
            self.t_ms = self.dev_t
            self.origin = np.arange(len(self.dev_t))
            self.labels = self.dev_labels.copy()
        for t, v in self.relabels.items():
            k = int(np.searchsorted(self.t_ms, t))
            if k < len(self.t_ms) and self.t_ms[k] == t:
                self.labels[k] = v
        self.dev_to_merged = np.full(len(self.dev_t), -1, np.int64)
        m = self.origin >= 0
        self.dev_to_merged[self.origin[m]] = np.where(m)[0]
        self.beat_template = np.full(len(self.t_ms), -1, np.int32)
        self.beat_template[m] = self.dev_template[self.origin[m]]

    def effective_audits(self) -> dict[int, BeatAudit]:
        out: dict[int, BeatAudit] = {}
        for dk, a in self.auto_audits.items():
            k = int(self.dev_to_merged[dk])
            out[k] = msgspec.structs.replace(a, index=k)
        for k in range(len(self.t_ms)):
            t = int(self.t_ms[k])
            o = int(self.origin[k])
            lab = self.added.get(t) if o < 0 else self.relabels.get(t)
            if lab is None:
                continue
            a = out.get(k)
            if a is None:
                a = (
                    self.auditor.audit(o)
                    if o >= 0
                    else BeatAudit(index=k, t_ms=t, label=lab, verdict="manual", confidence=1.0)
                )
                a = msgspec.structs.replace(a, index=k)
            a.label = lab
            a.verdict = (
                "manual" if lab in ("V", "S") else ("manual-N" if lab == "N" else "manual-X")
            )
            a.confidence = 1.0
            a.reasons = [("добавлен вручную" if o < 0 else "ручная метка") + f": {lab}"]
            out[k] = a
        return out

    def recompute(self) -> None:
        base = self.base
        self._merge()
        self._apply_quality()
        audits = self.effective_audits()
        labels = self.labels
        cal = base.calibration
        episodes = extract_episodes(
            self.t_ms,
            labels,
            audits,
            self.noise10,
            self.sharp10,
            WINDOW_S,
            gap_check=lambda t0, t1: gap_artifact(
                self.mm, self.fs, self.mv, t0, t1, cal.qrs_amp_mv, cal.noise_base_ii_mv
            ),
            missed_check=lambda t0, t1: missed_beat(
                self.mm, self.fs, self.mv, t0, t1, cal.qrs_amp_mv
            ),
        )
        hr_min = base.minute_hr
        hr_vals = np.array([v for v in hr_min if v is not None])
        _, nn = nn_intervals(self.t_ms, labels)

        def clock_hour(ms: float) -> float:
            d = self.start + timedelta(milliseconds=ms)
            return d.hour + d.minute / 60

        night, day = [], []
        for m, v in enumerate(hr_min):
            if v is None:
                continue
            h = clock_hour(m * 60000 + 30000)
            (night if 0 <= h < 6 else day if 8 <= h < 22 else []).append(v)
        sleep = base.sleep
        in_sleep = np.zeros(len(hr_min), bool)
        for a, b in sleep:
            in_sleep[a:b] = True
        sl = [v for m, v in enumerate(hr_min) if v is not None and in_sleep[m]]
        wk = [v for m, v in enumerate(hr_min) if v is not None and not in_sleep[m]]

        def kept(lab: str) -> np.ndarray:
            times = [a.t_ms for a in audits.values() if a.label == lab and a.verdict in KEEP]
            return np.array(times, np.int64)

        kept_v, kept_s = kept("V"), kept("S")
        likely_v = sum(
            1 for a in audits.values() if a.label == "V" and a.verdict in ("likely", "manual")
        )
        verdict_counts: dict[str, dict[str, int]] = {}
        for a in audits.values():
            verdict_counts.setdefault(a.label, {}).setdefault(a.verdict, 0)
            verdict_counts[a.label][a.verdict] += 1
        hr_arr = np.array([v if v is not None else np.nan for v in hr_min], float)
        i_min = int(np.nanargmin(hr_arr))
        i_max = int(np.nanargmax(hr_arr))
        real_pauses = [e for e in episodes if e.kind == "pause" and e.verdict != "artifact"]
        longest_pause = max((e.dur_ms for e in real_pauses), default=0)
        v_runs = [e for e in episodes if e.kind == "v-run" and e.verdict != "artifact"]

        def fast(e: Episode) -> bool:
            return 60000 * (len(e.beats) - 1) / max(1, e.dur_ms) > 100

        vt = [e for e in v_runs if len(e.beats) >= 4 and fast(e)]
        nsvt3 = [e for e in v_runs if len(e.beats) >= 3 and fast(e)]
        v_burden = 100 * len(kept_v) / len(self.t_ms)
        # Морфологии ЖЭС: семейства, удержавшие не меньше трёх подтверждённых V.
        fam_counts: dict[int, int] = {}
        for a in audits.values():
            if a.label == "V" and a.verdict in KEEP and a.family is not None and a.family >= 0:
                fam_counts[a.family] = fam_counts.get(a.family, 0) + 1
        morph = sorted(((n, f) for f, n in fam_counts.items() if n >= 3), reverse=True)
        # Скрининг ФП: окна по 30 NN, где 70 % соседних интервалов различаются больше чем на 12 %.
        irr_windows = 0
        if len(nn) > 30:
            d = np.abs(np.diff(nn)) / nn[:-1]
            wsz = 30
            for i0 in range(0, len(d) - wsz, wsz):
                if (d[i0 : i0 + wsz] > 0.12).mean() >= 0.7:
                    irr_windows += 1
        p = self.rec.patient
        self.analysis = Analysis(
            summary=Summary(
                computed_s=base.computed_s,
                patient=Patient(
                    name=f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                    id=_as_str(p.get("patient_id")),
                    sex=_as_str(p.get("sex")),
                    age=_as_int(p.get("age")),
                    dob=_as_str(p.get("dob")),
                ),
                record=Record(
                    start=self.start.isoformat(sep=" "),
                    duration_s=round(self.total_ms / 1000, 1),
                    fs=self.fs,
                    leads=list(self.rec.leads),
                    beats=len(self.t_ms),
                    avm_nv=self.rec.avm_nv,
                    gain=self.cfg.gain,
                    gain_verified=self.cfg.gain is not None,
                    clean_pct=round(float((self.noise10 < 0.5).mean() * 100), 2),
                ),
                hr=HeartRate(
                    mean=round(float(60000 / nn.mean())),
                    min=round(float(hr_vals.min())),
                    max=round(float(hr_vals.max())),
                    min_at_s=i_min * 60 + 30,
                    max_at_s=i_max * 60 + 30,
                    night=round(float(np.mean(night))) if night else None,
                    day=round(float(np.mean(day))) if day else None,
                    sleep=round(float(np.mean(sl))) if sl else None,
                    wake=round(float(np.mean(wk))) if wk else None,
                    pct_over_100=round(float((60000 / nn > 100).mean() * 100), 2),
                    pct_under_50=round(float((60000 / nn < 50).mean() * 100), 2),
                ),
                hrv=base.hrv,
                counts=Counts(
                    device=DeviceCounts(
                        N=int((self.dev_labels == "N").sum()),
                        V=int((self.dev_labels == "V").sum()),
                        S=int((self.dev_labels == "S").sum()),
                    ),
                    audited=AuditedCounts(V=len(kept_v), V_likely=int(likely_v), S=len(kept_s)),
                    manual=len(self.relabels),
                    added=len(self.added),
                    quality_spans=len(self.quality),
                    verdicts=verdict_counts,
                    pauses_device=int((np.diff(self.t_ms) > 2000).sum()),
                    pauses_real=len(real_pauses),
                ),
                calibration=cal,
                criteria=_criteria(longest_pause, vt, nsvt3, v_burden, morph, irr_windows),
                morphologies=[Morphology(family=f, count=n) for n, f in morph],
            ),
            overview=Overview(
                minute_hr=hr_min,
                minute_v=per_minute_counts(kept_v, self.total_ms)
                if len(kept_v)
                else [0] * len(hr_min),
                minute_s=per_minute_counts(kept_s, self.total_ms)
                if len(kept_s)
                else [0] * len(hr_min),
                minute_v_device=per_minute_counts(
                    self.dev_t[self.dev_labels == "V"], self.total_ms
                ),
                noise10=[round(float(x), 2) for x in self.noise10],
                noise_window_s=WINDOW_S,
                quality_manual=self.quality,
                sleep=sleep,
            ),
            episodes=episodes,
        )
        self.audits = audits
        self.episodes = episodes
        # Компактные массивы на полосу контекста: код метки и код класса вердикта.
        self.code_label = np.zeros(len(self.t_ms), np.int8)
        self.code_class = np.zeros(len(self.t_ms), np.int8)
        for k, lab in enumerate(labels):
            self.code_label[k] = LABEL_CODE.get(lab, 0)
        for k, a in audits.items():
            self.code_class[k] = CLASS_CODE.get(a.verdict, 3)

    def beat_info(self, k: int) -> BeatInfo:
        au = self.audits.get(k)
        t = int(self.t_ms[k])
        o = int(self.origin[k])
        return BeatInfo(
            index=k,
            t_ms=t,
            label=au.label if au else str(self.labels[k]),
            device_label=str(self.dev_labels[o]) if o >= 0 else None,
            manual=self.added.get(t) if o < 0 else self.relabels.get(t),
            added=o < 0,
            verdict=au.verdict if au else "N",
            confidence=au.confidence if au else 1.0,
            reasons=au.reasons if au else [],
            width_ms=au.width_ms if au else None,
            width_ratio=au.width_ratio if au else None,
            prematurity=au.prematurity if au else None,
            amp_ratio=au.amp_ratio if au else None,
            noise_ratio=au.noise_ratio if au else None,
            family_n_frac=au.family_n_frac if au else None,
            rr_pre=au.rr_pre if au else None,
            rr_post=au.rr_post if au else None,
            template=int(self.beat_template[k]),
        )

    def beats_in(self, start: float, dur: float) -> list[BeatInfo]:
        lo = int(np.searchsorted(self.t_ms, start * 1000))
        hi = int(np.searchsorted(self.t_ms, (start + dur) * 1000))
        return [self.beat_info(k) for k in range(lo, hi)]

    def noise_windows(self, start: float, dur: float, thr: float = 0.35) -> list[NoiseWindow]:
        w = self.analysis.overview.noise_window_s
        n10 = self.analysis.overview.noise10
        wa, wb = int(start // w), int((start + dur) // w) + 1
        return [
            NoiseWindow(t0=i * w, t1=(i + 1) * w, score=n10[i])
            for i in range(max(0, wa), min(wb, len(n10)))
            if n10[i] >= thr
        ]

    def templates(self) -> list[TemplateView]:
        out = []
        n_h = int(self.total_ms // 3_600_000) + 1
        for t in self.base.templates:
            members = np.where(self.dev_template == t.id)[0]
            manual: dict[str, int] = {}
            for k in members:
                v = self.relabels.get(int(self.dev_t[k]))
                if v:
                    manual[v] = manual.get(v, 0) + 1
            hours = np.bincount((self.dev_t[members] // 3_600_000).astype(int), minlength=n_h)[:n_h]
            out.append(
                TemplateView(
                    id=t.id,
                    count=t.count,
                    labels=t.labels,
                    verdicts=t.verdicts,
                    verdicts_by_label=t.verdicts_by_label,
                    wave=t.wave,
                    first=t.first,
                    sample=t.sample,
                    manual=manual,
                    hours=hours.astype(int).tolist(),
                )
            )
        return out


def _criteria(
    longest_pause: int,
    vt: list[Episode],
    nsvt3: list[Episode],
    v_burden: float,
    morph: list[tuple[int, int]],
    irr_windows: int,
) -> list[Criterion]:
    """Пять находок, по которым читают холтер (Fiorina 2022) — docs/modules/analysis.md."""
    morph_word = (
        "морфология" if len(morph) == 1 else "морфологии" if len(morph) < 5 else "морфологий"
    )
    return [
        Criterion(
            key="pause",
            title="Пауза ≥ 2.5 с",
            value=f"{longest_pause / 1000:.1f} с" if longest_pause else "нет",
            met=longest_pause >= 2500,
            note="порог 2.5 с: критерий чтения холтера в Fiorina 2022 (JAHA); ≥ 4 с: критерий уведомления врача, ISHNE-HRS 2017, табл. 6",
        ),
        Criterion(
            key="vt",
            title="ЖТ > 100/мин",
            value=(f"≥ 4 компл.: {len(vt)}" if vt else "≥ 4 компл.: нет")
            + (f" · триплетов: {len(nsvt3)}" if nsvt3 else ""),
            met=bool(vt) or (None if nsvt3 else False),
            note="≥ 4 комплексов с RR < 500 мс: критерий чтения в Fiorina 2022; ≥ 3 комплексов: обычное определение неустойчивой ЖТ. Триплеты показаны отдельно, решает врач",
        ),
        Criterion(
            key="pvc",
            title="ЖЭС ≥ 10 %",
            value=f"{v_burden:.2f} %",
            met=v_burden >= 10,
            note=f"{len(morph)} {morph_word}: " + ", ".join(f"{n}" for n, _ in morph[:4])
            if morph
            else "морфологии не выделены",
        ),
        Criterion(
            key="af",
            title="ФП ≥ 30 с",
            value=f"{irr_windows} окон по 30 с с нерегулярным ритмом"
            if irr_windows
            else "нерегулярных окон нет",
            met=None,
            note="автоматически не диагностируется: скрининг по нерегулярности RR, решает врач по P-волнам",
        ),
        Criterion(
            key="avb",
            title="АВ-блокада II (Mobitz II) / III",
            value="не оценивается",
            met=None,
            note="нужна разметка P-волн; смотреть паузы и брадикардию вручную",
        ),
    ]


def build(cfg: RecordSettings) -> State:
    return State(cfg)
