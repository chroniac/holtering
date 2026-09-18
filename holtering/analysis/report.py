"""Analysis state: heavy pass computed once and cached, light pass (counts,
episodes, per-minute series) recomputed whenever a manual label changes."""

from __future__ import annotations

import json
import time
from datetime import timedelta

import numpy as np

from ..config import Config
from . import templates as tpl
from .beats import BeatAudit, BeatAuditor, apply_family_evidence
from .quality import INDEPENDENT, WINDOW_S, gap_artifact, missed_beat, noise_score, window_metrics
from .rhythm import KEEP, estimate_sleep, extract_episodes, hr_per_minute, hrv, nn_intervals, per_minute_counts

MANUAL_LABELS = {"N", "V", "S", "X"}      # X = artefact / not a beat
LABEL_CODE = {"N": 0, "V": 1, "S": 2, "X": 3}
CLASS_CODE = {"N": 0, "manual-N": 0, "likely": 1, "uncertain": 2, "manual": 4, "manual-X": 3}


def _json_default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    raise TypeError(f"not serializable: {type(o).__name__}")


def load_annotations(path) -> tuple[np.ndarray, np.ndarray]:
    rows = np.loadtxt(path, dtype=object, delimiter="\t", encoding="cp1251", ndmin=2)
    return rows[:, 0].astype(np.int64), rows[:, 1].astype(str)


class State:
    def __init__(self, cfg: Config):
        from scp_holter import ScpHolter

        self.cfg = cfg
        self.rec = ScpHolter(str(cfg.scp), invert=cfg.invert)
        if cfg.chest:
            self.rec.set_chest_labels(list(cfg.chest))
        self.mm = self.rec.memmap()
        self.fs = int(round(self.rec.fs))
        self.mv = self.rec.meta.mv_per_lsb * (cfg.gain if cfg.gain is not None else 1.0)
        self.dev_t, self.dev_labels = load_annotations(cfg.qrs)      # what the device found, immutable
        self.t_ms, self.labels = self.dev_t, self.dev_labels           # merged view, rebuilt in recompute()
        self.total_ms = int(self.dev_t[-1])
        # scoped to the patient and the recording date so a re-used file name (raw.scp of the
        # next patient) never inherits labels, diary entries or an edited conclusion
        pid = str(self.rec.patient.get("patient_id") or "na")
        self.overrides_file = cfg.cache_dir / f"{cfg.scp.stem}.{pid}.{cfg.start:%Y%m%d}.overrides.json"
        # keyed by time (ms) so that inserted beats never shift a key: relabels of device
        # beats live in "labels", reviewer-inserted beats in "added"
        self.relabels: dict[int, str] = {}
        self.added: dict[int, str] = {}
        self.quality: list[dict] = []          # [{t0_ms, t1_ms, v: "clean"|"noise"}], later entries win
        self.events: list[dict] = []           # symptom diary: [{id, t_ms, text}]
        self.report: dict = {}                 # reviewer's edits of the printed protocol (see protocol.py)
        if self.overrides_file.exists():
            raw = json.loads(self.overrides_file.read_text("utf-8"))
            self.relabels = {int(k): v for k, v in raw.get("labels", {}).items()}
            self.added = {int(k): v for k, v in raw.get("added", {}).items()}
            self.quality = list(raw.get("quality", []))
            self.events = list(raw.get("events", []))
            self.report = dict(raw.get("report", {}))

        base = json.loads(cfg.cache_file.read_text("utf-8")) if cfg.cache_file.exists() else None
        if base is None:
            base = self._heavy()
            cfg.cache_file.write_text(json.dumps(base, ensure_ascii=False, default=_json_default), "utf-8")
        self.base = base
        self.auto_noise = np.array(base["noise10"], np.float32)       # shading, record quality (auto)
        self.auto_sharp = np.array(base["sharp10"], np.float32)       # beat verdicts only (auto)
        self.noise10 = self.auto_noise; self.sharp10 = self.auto_sharp
        self.dev_template = np.array(base["beat_template"], np.int32)
        self.beat_template = self.dev_template
        self.auditor = BeatAuditor(self.mm, self.fs, self.mv, self.dev_t, self.dev_labels,
                                   base["calibration"]["noise_base_ii_mv"], self.sharp10, WINDOW_S)
        self.auditor.n_width = base["calibration"]["sinus_width_ms"]
        self.auto_audits: dict[int, BeatAudit] = {a["index"]: BeatAudit(**a) for a in base["audits"]}   # device index
        self.analysis: dict = {}
        self.recompute()

    # ---- heavy, cached ------------------------------------------------------
    def _heavy(self) -> dict:
        t0 = time.time()
        hf, steps, rails, wander = window_metrics(self.mm, self.fs, self.mv)
        noise10, sharp10, base = noise_score(hf, steps, rails, wander)
        wander_base = float(np.median(wander[:, INDEPENDENT.index(1)]))
        base_ii = float(base[INDEPENDENT.index(1)])
        auditor = BeatAuditor(self.mm, self.fs, self.mv, self.t_ms, self.labels, base_ii, sharp10, WINDOW_S)
        audits = auditor.audit_all()
        w, valid = tpl.beat_windows(self.mm, self.fs, self.mv, self.t_ms)
        assign, _ = tpl.cluster(w, valid)
        apply_family_evidence(audits, assign, self.labels)
        verdicts = {a.index: a.verdict for a in audits}
        templates = tpl.summarise(w, assign, self.labels, verdicts, self.fs)
        t_nn, nn = nn_intervals(self.t_ms, self.labels)
        hr_min = hr_per_minute(t_nn, nn, self.total_ms)
        return {
            "computed_s": round(time.time() - t0, 1),
            "noise10": [round(float(x), 2) for x in noise10],
            "sharp10": [round(float(x), 2) for x in sharp10],
            "calibration": {"sinus_width_ms": round(auditor.n_width, 1), "noise_base_ii_mv": round(base_ii, 3),
                            "wander_base_ii_mv": round(wander_base, 3),
                            "qrs_amp_mv": round(float(np.nanmedian(list(auditor.hour_amp.values()))), 2)},
            "audits": [a.to_dict() for a in audits],
            "beat_template": assign.tolist(),
            "templates": templates,
            "minute_hr": hr_min,
            "hrv": hrv(nn),
            "sleep": estimate_sleep(hr_min),
        }

    # ---- manual labels (all keyed by time) --------------------------------------
    def set_label(self, index: int, label: str | None) -> None:
        """Relabel the beat at merged index; None clears. On an inserted beat None deletes it."""
        t = int(self.t_ms[index])
        if self.origin[index] < 0:                      # reviewer-inserted beat
            if label is None:
                self.added.pop(t, None)
            else:
                self._check(label); self.added[t] = label
        elif label is None:
            self.relabels.pop(t, None)
        else:
            self._check(label); self.relabels[t] = label
        self._persist(); self.recompute()

    def add_beat(self, t_ms: int, label: str = "N") -> int:
        """Insert a beat the device missed; returns its merged index."""
        self._check(label)
        t_ms = int(t_ms)
        if len(self.t_ms) and int(np.abs(self.t_ms - t_ms).min()) < 120:
            raise ValueError("within 120 ms of an existing beat - relabel that one instead")
        self.added[t_ms] = label
        self._persist(); self.recompute()
        return int(np.searchsorted(self.t_ms, t_ms))

    def set_template_label(self, template_id: int, label: str | None) -> int:
        members = np.where(self.dev_template == template_id)[0]
        for k in members:
            t = int(self.dev_t[k])
            if label is None:
                self.relabels.pop(t, None)
            else:
                self._check(label); self.relabels[t] = label
        self._persist(); self.recompute()
        return int(len(members))

    @staticmethod
    def _check(label: str) -> None:
        if label not in MANUAL_LABELS:
            raise ValueError(f"label must be one of {sorted(MANUAL_LABELS)}")

    def set_quality(self, t0_ms: int, t1_ms: int, value: str | None) -> None:
        """Mark a span clean/noise by hand; None drops every manual span overlapping it."""
        t0_ms, t1_ms = int(min(t0_ms, t1_ms)), int(max(t0_ms, t1_ms))
        if value is None:
            self.quality = [q for q in self.quality if q["t1_ms"] <= t0_ms or q["t0_ms"] >= t1_ms]
        else:
            if value not in ("clean", "noise"):
                raise ValueError("value must be clean, noise or null")
            self.quality.append({"t0_ms": t0_ms, "t1_ms": t1_ms, "v": value})
        self._persist(); self.recompute()

    def _apply_quality(self) -> None:
        """Rebuild the effective quality arrays from the auto ones plus manual spans, and
        re-audit the device beats inside touched spans so 'в помехе' follows the override."""
        self.noise10 = self.auto_noise.copy(); self.sharp10 = self.auto_sharp.copy()
        self.auditor.noise10 = self.sharp10
        if not self.quality:
            return
        w = WINDOW_S * 1000
        touched: list[int] = []
        for q in self.quality:
            a, b = int(q["t0_ms"] // w), int(-(-q["t1_ms"] // w))
            val = 0.0 if q["v"] == "clean" else 1.0
            self.noise10[a:b] = val; self.sharp10[a:b] = val
            lo, hi = np.searchsorted(self.dev_t, q["t0_ms"]), np.searchsorted(self.dev_t, q["t1_ms"])
            touched += [int(k) for k in range(lo, hi) if self.dev_labels[k] != "N"]
        if touched:
            fresh = [self.auditor.audit(k) for k in sorted(set(touched))]
            apply_family_evidence(fresh, self.dev_template, self.dev_labels)
            for a_ in fresh:
                self.auto_audits[a_.index] = a_

    # ---- symptom diary ---------------------------------------------------------
    def add_event(self, t_ms: int, text: str) -> dict:
        eid = 1 + max((e["id"] for e in self.events), default=0)
        ev = {"id": eid, "t_ms": int(t_ms), "text": text.strip()[:200]}
        self.events.append(ev); self.events.sort(key=lambda e: e["t_ms"])
        self._persist()
        return self.event_context(ev)

    def remove_event(self, eid: int) -> None:
        self.events = [e for e in self.events if e["id"] != eid]
        self._persist()

    def event_context(self, ev: dict, half_s: int = 120) -> dict:
        """What the rhythm did around a diary entry: HR, ectopy, episodes within +-half_s."""
        t = ev["t_ms"]; lo, hi = t - half_s * 1000, t + half_s * 1000
        a, b = int(np.searchsorted(self.t_ms, lo)), int(np.searchsorted(self.t_ms, hi))
        rr = np.diff(self.t_ms[max(0, a - 1):b + 1]) if b > a else np.array([], np.int64)
        rr = rr[(rr > 300) & (rr < 2000)]
        hr = round(float(60000 / rr.mean())) if len(rr) else None
        hr_min = round(float(60000 / rr.max())) if len(rr) else None
        hr_max = round(float(60000 / rr.min())) if len(rr) else None
        v = s_ = 0
        for k in range(a, b):
            au = self._audits.get(k)
            if au and au.verdict in KEEP:
                if au.label == "V": v += 1
                elif au.label == "S": s_ += 1
        eps = [e.id for e in self._episodes if e.t_ms <= hi and e.t_ms + e.dur_ms >= lo and e.verdict != "artifact"]
        w = int(t / 1000 / WINDOW_S)
        return {**ev, "hr": hr, "hr_min": hr_min, "hr_max": hr_max, "v": v, "s": s_, "episodes": eps,
                "noise": float(self.noise10[w]) if 0 <= w < len(self.noise10) else 0.0}

    def events_with_context(self) -> list[dict]:
        return [self.event_context(e) for e in self.events]

    def _persist(self) -> None:
        self.overrides_file.write_text(json.dumps({
            "labels": {str(k): v for k, v in self.relabels.items()},
            "added": {str(k): v for k, v in self.added.items()},
            "quality": self.quality,
            "events": self.events,
            "report": self.report,
        }, ensure_ascii=False), "utf-8")

    def set_report(self, saved: dict) -> None:
        self.report = saved
        self._persist()

    def _merge(self) -> None:
        """Rebuild merged beat arrays: device beats + inserted ones, time-ordered."""
        if self.added:
            add_t = np.array(sorted(self.added), np.int64)
            t = np.concatenate([self.dev_t, add_t])
            origin = np.concatenate([np.arange(len(self.dev_t)), np.full(len(add_t), -1)])
            lab = np.concatenate([self.dev_labels, np.array([self.added[int(x)] for x in add_t], dtype=self.dev_labels.dtype)])
            order = np.argsort(t, kind="stable")
            self.t_ms, self.origin, self.labels = t[order], origin[order], lab[order]
        else:
            self.t_ms, self.origin, self.labels = self.dev_t, np.arange(len(self.dev_t)), self.dev_labels.copy()
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
            b = BeatAudit(**a.to_dict()); b.index = k
            out[k] = b
        for k in range(len(self.t_ms)):
            t = int(self.t_ms[k]); o = int(self.origin[k])
            lab = self.added.get(t) if o < 0 else self.relabels.get(t)
            if lab is None:
                continue
            a = out.get(k)
            if a is None:
                a = self.auditor.audit(o) if o >= 0 else BeatAudit(index=k, t_ms=t, label=lab, verdict="manual", confidence=1.0)
                a = BeatAudit(**a.to_dict()); a.index = k
            a.label = lab
            a.verdict = "manual" if lab in ("V", "S") else ("manual-N" if lab == "N" else "manual-X")
            a.confidence = 1.0
            a.reasons = [("добавлен вручную" if o < 0 else "ручная метка") + f": {lab}"]
            out[k] = a
        return out

    # ---- light, recomputed -----------------------------------------------------
    def recompute(self) -> None:
        cfg, base = self.cfg, self.base
        self._merge()
        self._apply_quality()
        audits = self.effective_audits()
        labels = self.labels
        cal = base["calibration"]
        episodes = extract_episodes(
            self.t_ms, labels, audits, self.noise10, self.sharp10, WINDOW_S,
            gap_check=lambda t0, t1: gap_artifact(self.mm, self.fs, self.mv, t0, t1, cal["qrs_amp_mv"], cal["noise_base_ii_mv"]),
            missed_check=lambda t0, t1: missed_beat(self.mm, self.fs, self.mv, t0, t1, cal["qrs_amp_mv"]),
        )
        hr_min = base["minute_hr"]
        hr_vals = np.array([v for v in hr_min if v is not None])
        t_nn, nn = nn_intervals(self.t_ms, labels)

        def clock_hour(ms: float) -> float:
            d = cfg.start + timedelta(milliseconds=ms)
            return d.hour + d.minute / 60
        night, day = [], []
        for m, v in enumerate(hr_min):
            if v is None:
                continue
            h = clock_hour(m * 60000 + 30000)
            (night if 0 <= h < 6 else day if 8 <= h < 22 else []).append(v)
        sleep = base["sleep"]
        in_sleep = np.zeros(len(hr_min), bool)
        for a, b in sleep:
            in_sleep[a:b] = True
        sl = [v for m, v in enumerate(hr_min) if v is not None and in_sleep[m]]
        wk = [v for m, v in enumerate(hr_min) if v is not None and not in_sleep[m]]

        kept = lambda lab: np.array([a.t_ms for a in audits.values() if a.label == lab and a.verdict in KEEP], np.int64)
        kept_v, kept_s = kept("V"), kept("S")
        likely_v = sum(1 for a in audits.values() if a.label == "V" and a.verdict in ("likely", "manual"))
        verdict_counts: dict[str, dict[str, int]] = {}
        for a in audits.values():
            verdict_counts.setdefault(a.label, {}).setdefault(a.verdict, 0)
            verdict_counts[a.label][a.verdict] += 1
        # clock-stamped extremes (1-min averages) and the five findings every Holter read decides on
        hr_arr = np.array([v if v is not None else np.nan for v in hr_min], float)
        i_min = int(np.nanargmin(hr_arr)); i_max = int(np.nanargmax(hr_arr))
        rr_all = np.diff(self.t_ms)
        real_pauses = [e for e in episodes if e.kind == "pause" and e.verdict != "artifact"]
        longest_pause = max((e.dur_ms for e in real_pauses), default=0)
        v_runs = [e for e in episodes if e.kind == "v-run" and e.verdict != "artifact"]
        fast = lambda e: 60000 * (len(e.beats) - 1) / max(1, e.dur_ms) > 100
        vt = [e for e in v_runs if len(e.beats) >= 4 and fast(e)]              # Fiorina 2022 reading criterion
        nsvt3 = [e for e in v_runs if len(e.beats) >= 3 and fast(e)]           # conventional NSVT: >= 3 beats > 100/min
        longest_run = max((len(e.beats) for e in v_runs), default=0)
        v_burden = 100 * len(kept_v) / len(self.t_ms)
        # PVC morphologies: distinct families that hold >= 3 kept V beats
        fam_counts: dict[int, int] = {}
        for a_ in audits.values():
            if a_.label == "V" and a_.verdict in KEEP and a_.family is not None and a_.family >= 0:
                fam_counts[a_.family] = fam_counts.get(a_.family, 0) + 1
        morph = sorted(((n, f) for f, n in fam_counts.items() if n >= 3), reverse=True)
        # irregularity screen for AF: 30-s windows where >= 70 % of successive NN differ by > 12 %
        irr_windows = 0
        if len(nn) > 30:
            d = np.abs(np.diff(nn)) / nn[:-1]
            wsz = 30
            for i0 in range(0, len(d) - wsz, wsz):
                if (d[i0:i0 + wsz] > 0.12).mean() >= 0.7:
                    irr_windows += 1
        # The five findings are the "major rhythm abnormality" set used to read 1000 Holters in
        # Fiorina et al., JAHA 2022 (PMC9683671): pause >= 2.5 s, VT >= 4 beats with an RR < 500 ms,
        # AF/flutter/AT >= 30 s, PVC burden >= 10 %, Mobitz II or 3rd-degree AV block.
        criteria = [
            {"key": "pause", "title": "Пауза ≥ 2.5 с", "value": f"{longest_pause / 1000:.1f} с" if longest_pause else "нет",
             "met": longest_pause >= 2500, "note": "порог 2.5 с: критерий чтения холтера в Fiorina 2022 (JAHA); ≥ 4 с: критерий уведомления врача, ISHNE-HRS 2017, табл. 6"},
            {"key": "vt", "title": "ЖТ > 100/мин",
             "value": (f"≥ 4 компл.: {len(vt)}" if vt else "≥ 4 компл.: нет") + (f" · триплетов: {len(nsvt3)}" if nsvt3 else ""),
             "met": bool(vt) or (None if nsvt3 else False),
             "note": "≥ 4 комплексов с RR < 500 мс: критерий чтения в Fiorina 2022; ≥ 3 комплексов: обычное определение неустойчивой ЖТ. Триплеты показаны отдельно, решает врач"},
            {"key": "pvc", "title": "ЖЭС ≥ 10 %", "value": f"{v_burden:.2f} %", "met": v_burden >= 10,
             "note": f"{len(morph)} {'морфология' if len(morph) == 1 else 'морфологии' if len(morph) < 5 else 'морфологий'}: " + ", ".join(f"{n}" for n, _ in morph[:4]) if morph else "морфологии не выделены"},
            {"key": "af", "title": "ФП ≥ 30 с", "value": f"{irr_windows} окон по 30 с с нерегулярным ритмом" if irr_windows else "нерегулярных окон нет",
             "met": None, "note": "автоматически не диагностируется: скрининг по нерегулярности RR, решает врач по P-волнам"},
            {"key": "avb", "title": "АВ-блокада II (Mobitz II) / III", "value": "не оценивается", "met": None,
             "note": "нужна разметка P-волн; смотреть паузы и брадикардию вручную"},
        ]
        p = self.rec.patient
        self.analysis = {
            "computed_s": base["computed_s"],
            "patient": {"name": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(), "id": p.get("patient_id"),
                        "sex": p.get("sex"), "age": p.get("age"), "dob": p.get("dob")},
            "record": {"start": cfg.start.isoformat(sep=" "), "duration_s": round(self.total_ms / 1000, 1), "fs": self.fs,
                       "leads": list(self.rec.leads), "beats": int(len(self.t_ms)), "avm_nv": self.rec.avm_nv,
                       "gain": cfg.gain, "gain_verified": cfg.gain is not None,
                       "clean_pct": round(float((self.noise10 < 0.5).mean() * 100), 2)},
            "hr": {"mean": round(float(60000 / nn.mean())), "min": round(float(hr_vals.min())), "max": round(float(hr_vals.max())),
                   "min_at_s": i_min * 60 + 30, "max_at_s": i_max * 60 + 30,
                   "night": round(float(np.mean(night))) if night else None, "day": round(float(np.mean(day))) if day else None,
                   "sleep": round(float(np.mean(sl))) if sl else None, "wake": round(float(np.mean(wk))) if wk else None,
                   "pct_over_100": round(float((60000 / nn > 100).mean() * 100), 2),
                   "pct_under_50": round(float((60000 / nn < 50).mean() * 100), 2)},
            "hrv": base["hrv"],
            "counts": {"device": {"N": int((self.dev_labels == "N").sum()), "V": int((self.dev_labels == "V").sum()), "S": int((self.dev_labels == "S").sum())},
                       # V is a range on purpose: QRS width at 125 Hz is +-1-2 samples, so the lower
                       # bound counts only confident wide beats, the upper adds borderline ones
                       "audited": {"V": int(len(kept_v)), "V_likely": int(likely_v), "S": int(len(kept_s))},
                       "manual": len(self.relabels), "added": len(self.added), "quality_spans": len(self.quality),
                       "verdicts": verdict_counts,
                       "pauses_device": int((np.diff(self.t_ms) > 2000).sum()),
                       "pauses_real": sum(1 for e in episodes if e.kind == "pause" and e.verdict != "artifact")},
            "calibration": cal,
            "overview": {"minute_hr": hr_min,
                         "minute_v": per_minute_counts(kept_v, self.total_ms) if len(kept_v) else [0] * len(hr_min),
                         "minute_s": per_minute_counts(kept_s, self.total_ms) if len(kept_s) else [0] * len(hr_min),
                         "minute_v_device": per_minute_counts(self.dev_t[self.dev_labels == "V"], self.total_ms),
                         "noise10": [round(float(x), 2) for x in self.noise10], "noise_window_s": WINDOW_S,
                         "quality_manual": self.quality, "sleep": sleep},
            "episodes": [e.to_dict() for e in episodes],
            "criteria": criteria,
            "morphologies": [{"family": f, "count": n} for n, f in morph],
        }
        self._audits = audits
        self._episodes = episodes
        # compact per-beat arrays for the context strip: label code + verdict class code
        self.code_label = np.zeros(len(self.t_ms), np.int8)          # 0 N, 1 V, 2 S, 3 X
        self.code_class = np.zeros(len(self.t_ms), np.int8)          # 0 N, 1 likely, 2 uncertain, 3 rejected, 4 manual
        for k, lab in enumerate(labels):
            self.code_label[k] = LABEL_CODE.get(lab, 0)
        for k, a in audits.items():
            self.code_class[k] = CLASS_CODE.get(a.verdict, 3)

    def beat_info(self, k: int) -> dict:
        au = self._audits.get(k)
        t = int(self.t_ms[k]); o = int(self.origin[k])
        return {"index": k, "t_ms": t, "label": au.label if au else str(self.labels[k]),
                "device_label": str(self.dev_labels[o]) if o >= 0 else None,
                "manual": self.added.get(t) if o < 0 else self.relabels.get(t), "added": o < 0,
                "verdict": au.verdict if au else "N", "confidence": au.confidence if au else 1.0,
                "reasons": au.reasons if au else [], "width_ms": au.width_ms if au else None,
                "width_ratio": au.width_ratio if au else None, "prematurity": au.prematurity if au else None,
                "amp_ratio": au.amp_ratio if au else None, "noise_ratio": au.noise_ratio if au else None,
                "family_n_frac": au.family_n_frac if au else None,
                "rr_pre": au.rr_pre if au else None, "rr_post": au.rr_post if au else None,
                "template": int(self.beat_template[k])}

    def templates(self) -> list[dict]:
        out = []
        n_h = int(self.total_ms // 3_600_000) + 1
        for t in self.base["templates"]:
            members = np.where(self.dev_template == t["id"])[0]
            manual: dict[str, int] = {}
            for k in members:
                v = self.relabels.get(int(self.dev_t[k]))
                if v:
                    manual[v] = manual.get(v, 0) + 1
            hours = np.bincount((self.dev_t[members] // 3_600_000).astype(int), minlength=n_h)[:n_h]
            out.append({**t, "manual": manual, "hours": hours.astype(int).tolist()})
        return out


def build(cfg: Config) -> State:
    return State(cfg)
