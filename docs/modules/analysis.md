# analysis — checking the Holter labelling

The `holtering.analysis` package takes what the device labelled (`qrs.txt`) and the raw
signal (`raw.scp`), and answers a single question: which labels can be trusted. It
re-labels nothing from scratch — it only checks and explains.

Modules:

| Module | Responsible for |
|---|---|
| `quality.py` | signal quality per window: noise, spikes, clipping, drift |
| `beats.py` | features and a verdict for every ectopic complex |
| `templates.py` | grouping complexes by QRS shape |
| `rhythm.py` | heart rate, variability, pauses, runs, episodes |
| `state.py` | record state: heavy pass, reviewer overrides, final summary |
| `protocol.py` | the paper protocol: text, tables, strips |

## Two passes

The heavy pass (`State._heavy`) reads the whole signal: quality metrics per window, an
audit of every ectopic label, shape clustering, per-minute heart rate and HRV. It does
not depend on the reviewer's overrides and is cached as JSON next to the record (the
name includes the file size and mtime, `gain`, `invert` and the number of the audit
rules, so substituting the record, the calibration or a threshold yields a new cache —
the verdicts live in that file).

The light pass (`State.recompute`) is recomputed on every override: merging device and
inserted complexes, applying manual labels and manual quality ranges, extracting
episodes, counters, criteria.

The reviewer's overrides live in a separate file
`<name>.<patient id>.<date>.overrides.json` next to the record: binding to the patient
and the acquisition date is needed so that a reused file name (the `raw.scp` of the
next patient) does not inherit someone else's labels, diary and conclusion.

## Signal quality (`quality.py`)

The score is computed only over the eight **independent** channels: I, II and the six
chest leads. III, aVR, aVL, aVF are exact linear combinations of I and II for this
device, and if they had a vote, a single detached limb electrode would produce six
"confirming" noisy channels.

The window is 2 s so that shading hugs the artefact closely. All lengths are given in
seconds and converted to samples using the record's sampling rate: a 100 ms smoother at
500 Hz stays 100 milliseconds long instead of turning into 26 ms.

Four quantities are computed per window and channel: the SD of the high-frequency
residual after a 100 ms moving average, the fraction of spikes larger than 0.5 mV over
8 ms, the fraction of samples in ADC clipping and the span of the slow component
(0.4 s moving average).

They yield two scores, 0 — clean, 1 — unusable:

- `sharp` — high-frequency noise, impulse spikes, clipping. This is exactly what breaks
  QRS detection and morphology, so only this score is allowed to downgrade a complex's
  verdict. A channel counts as bad when the ratio to its own median is above 2.5, the
  spike fraction is above 0.15, or there is any clipping; a soft score over the median
  of the ratios is taken separately.
- `drift` — baseline drift: a slow span larger than 1.5 mV **and** more than four times
  the channel's usual drift. A threefold excess over the threshold on a single channel
  gives 0.5, a fourfold one — 1.0; the same is given by an excess on half of the
  channels. On a 24-hour record with a 2 s window the p98 of the ratio on the worst
  channel equals 2.0 and p99 equals 2.7, so the "×3" threshold lies beyond p99 and
  1.3 % of windows fall under it (10 s windows gave 3.9 %, because every flagged window
  dragged 10 s of clean signal along with it). Drift spoils ST and amplitudes, not the
  QRS shape: it shades the window and spoils the record quality score, but it never
  downgrades a complex's verdict.

The window's final score is the maximum of the two. A pause counts as real by the final
score (`noise10`), while «Помеха» ("noise") rows in the episode list are driven only by
`sharp10`: drift is visible on the time scale, but it must not bury pauses and runs in
the review list.

`gap_artifact` answers the question of whether there was a signal loss inside a long RR
rather than a quiet baseline: the windowed score smears a two-second burst, so the
interval itself is inspected separately. Clipping, a spike larger than 5 mV, a span
larger than three QRS amplitudes or high-frequency noise above 2.5 baselines mean the
detector went blind, not that the heart stopped.

`missed_beat` looks in the middle 60 % of the interval for a deflection of QRS size and
shape: a peak of at least half the typical QRS amplitude with a rise over ~40 ms on at
least two leads. Slow humps (the T wave, drift) fail the steepness check.

## QRS width (`beats.py`)

`qrs_duration_ms` takes the span around the point of maximum slope where the smoothed
absolute derivative stays above 15 % of the maximum. The slope is measured over 8 ms
and smoothed over 24 ms regardless of the sampling rate, so a threshold calibrated at
125 Hz means the same thing at 500 Hz. A single one-sample dip inside a run is stepped
over.

## Complex verdicts (`beats.py`)

Every ectopic device label gets features and a verdict with reasons so that the
reviewer can see **why** a label was downgraded:

| Verdict | Meaning |
|---|---|
| `double-count` | the coupling interval is shorter than 300 ms — physiologically impossible |
| `on-wave` | amplitude below 50 % of the neighbouring N beats: the label is not on a QRS |
| `noisy` | local HF noise above 2.5 of the record's baseline level or above 25 % of the hour's QRS amplitude, or the window is in noise |
| `too-wide` | the measured QRS is wider than 240 ms — no complex lasts that long, the width was read off an artefact |
| `narrow` | a V label, but the QRS is no wider than the sinus one — this is not a ventricular complex |
| `sinus-shape` | a V label, but the complex is in a morphology family with more than 90 % sinus beats |
| `not-premature` | the complex is not premature relative to the preceding sinus rhythm — an extrasystole is premature by definition |
| `on-schedule` | the label arrived on the sinus schedule right after a rejected label: it is the ordinary sinus beat, its neighbour made it look premature |
| `uncertain` | a V label with a QRS width of 1.1–1.4 of the sinus one, or contradictory features |
| `likely` | passed every check |
| `manual`, `manual-N`, `manual-X` | the reviewer's decision: ectopy, normal, artefact |

The verdicts `likely`, `uncertain` and `manual` count towards ectopy (`KEEP`).

Amplitude is compared with the hourly median amplitude of sinus complexes, width — with
the median sinus width across the whole record: both calibrations live in the heavy
pass.

Prematurity is the coupling interval over the median of the preceding N→N intervals —
the last six, and, when a run of ectopic labels leaves no pair among them, the last
twenty. The reference must not disappear exactly where a run needs it: without the
fallback a whole run of mislabelled sinus beats keeps its `likely`.

The upper bound on width is 240 ms rather than the ~200 ms of the widest ventricular
complex, because at 125 Hz the estimator reads the same generated shape of `tests/synth.py`
as 160 ms on one beat and 208 ms on the next; a tighter ceiling would reject real ectopy.
The noise bound is relative to the signal, not only to the record: the width is measured
at a 15 % slope threshold, so local noise above a quarter of the hour's QRS amplitude
leaves nothing to measure, however noisy the record is on average.

`apply_schedule_evidence` covers the device's most productive error on the reference
record: a detection on an artefact, followed by the ordinary sinus beat, which the bogus
neighbour turns into a "premature" one — 44 of 264 S labels there. A label is `on-schedule`
when the preceding label was rejected by the audit and the interval from the last sinus
beat is within 10 % of a whole number of sinus cycles: the rhythm never noticed this beat,
so it is the beat the rhythm was due. Couplets survive it — a label whose preceding ectopic
label was kept is not tested.

## Morphology families (`templates.py`, `apply_family_evidence`)

Every complex is described by a ±96 ms window on three leads (II and two chest leads),
centred on the median and normalised. Partitioning is a greedy correlation match (0.90
attaches the complex to an existing template, otherwise a new one is opened, no more
than 48), followed by two reassignment passes to the nearest mean template.

The windows are taken on a 125 Hz grid whatever the record's sampling rate: every grid
point is the mean of `fs/125` raw samples around it (box decimation, so an impulse
artefact is averaged out instead of being carried into the shape by spectral aliasing).
A 500 Hz record is clustered in the same 75 dimensions and at the same cost, and the
correlation threshold keeps its meaning.

On the second pass the family revises the width-based verdict — it does not depend on
the width thresholds, so it is entitled to override it. Families of fewer than 10
complexes carry no statistical weight. If a family holds more than 90 % sinus beats, a
V label becomes `sinus-shape`; if it holds fewer than 20 % sinus beats, `uncertain` is
raised to `likely` and `narrow` — to `uncertain`. An S label in a family with more than
half of its members being PVCs is lowered to `uncertain`.

A PVC morphology is a family that has retained no fewer than three confirmed V beats.

## Heart rate: mean and extremes (`rhythm.hr_extremes`)

The mean is taken over the NN intervals after the Malik filter — the same intervals HRV
is computed on, so a single artefactual interval cannot move both numbers apart.

The minimum and the maximum are the extremes of a sliding 15-second window (every
interval inside it must lie in 300–2000 ms), and `min_at_s`/`max_at_s` are the middle of
the winning window. The window length is calibrated: on a real 24-hour record the
CardioSpy protocol reports 72 / 44 / 148 per minute, and the mean over the filtered NN
with a 15 s window gives 72 / 44 / 148 at 06:49:58 and 20:24:09 against the device's
06:50:01 and 20:24:11. Every width from 11 to 15 s rounds to the same pair; 15 s is the
widest of them — 16 s already reads the maximum as 147. Per-minute averages, which this
used to use, gave 48 and 141
on the same record — averaging over a minute compresses both tails, and the printed
number has to be comparable with the device's.

Noisy windows are not excluded from the extremes: the maximum of this record lives inside
the stair test, where the signal is barely readable, and it is a real finding — the noise
map shades the strip so that the reviewer can judge it.

## QT on the averaged complex (`intervals.py`)

The printed protocol of the recorder states PQ, QT and ST, so the note has to answer the
same three questions. One of them is answered with a measurement.

QT is measured on an hourly median complex of lead II, built from up to 400 sinus beats
that stand between sinus beats at a steady rate (RR 500–1500 ms on both sides) — the
median kills the noise that makes a single beat unmeasurable at 125 Hz, and it is a
median rather than a mean so that one artefact cannot bend the shape. The QRS bounds use
the same 15 % slope threshold as the width, the baseline is the PQ segment before the
complex, and the end of T is the intersection of the tangent at the steepest descent of
T with that baseline. QTc is Bazett over the hour's median RR. The protocol prints the
median across hours and the spread. On the reference record this gives QT 401 ms,
QTc 426 ms (spread 404–463) against the CardioSpy protocol's QTc 420 ms.

PQ is **not** measured, and the sampling rate is not the reason — 8 ms resolves a
130–160 ms interval perfectly well. The reason is amplitude: on the reference record the
baseline noise of lead II is 0.424 mV against a P wave of 0.1–0.25 mV, so P only exists
after averaging, and there it is soft-edged. The same template supports two equally
reasonable rules for the onset of P — a share of the P amplitude, or a share of its upstroke slope — and on the
reference record they disagree by up to 70 ms (160–200 ms against 104–184 ms), where the
device reads 130–160 ms. A number that depends on the choice of rule more than on the
patient is not worth printing, so the section says so and leaves P to the reviewer.

ST is not measured either, for a different reason: a shift is stated in millimetres, and
the millivolt scale of the export is not calibrated (`gain`, see
[modules/scp-holter](scp-holter.md)).

## Sleep from heart rate (`rhythm.estimate_sleep`)

Without a diary, sleep is estimated from the rate alone: a 15-minute rolling median
heart rate below the midpoint between the 10th percentile and the median of the record,
sustained for no less than 45 minutes; gaps of up to 20 minutes are merged. A record
with less than two hours of valid heart rate is not eligible for the estimate. In the
interface such stretches are marked «ориентировочно» ("approximate").

## The five reading criteria (`state._criteria`)

The set of "serious rhythm disorders" used to read 1000 Holter records in Fiorina et
al., JAHA 2022 (PMC9683671): a pause ≥ 2.5 s, VT of ≥ 4 complexes with RR < 500 ms,
AF/flutter/atrial tachycardia ≥ 30 s, a PVC fraction ≥ 10 %, Mobitz II or complete AV
block. The threshold for notifying the physician at a pause ≥ 4 s is taken from
ISHNE-HRS 2017, table 6.

Two criteria are not decided automatically and are marked `met: null`: AF is given as a
screen for RR irregularity (windows of 30 NN intervals where 70 % of adjacent intervals
differ by more than 12 %) — the diagnosis is made by the reviewer from the P waves; AV
conduction is not assessed at all without P labelling. VT triplets are shown separately
from the "≥ 4 complexes" criterion: the usual definition of non-sustained VT starts at
three, and the reviewer decides.

## The paper protocol (`protocol.py`)

Follows the final-protocol section of the Russian national guidelines on Holter
monitoring (2013): a summary table, trends, samples of normal and of every atypical
ECG, strips of the minimum and maximum heart rate and of the longest pause, ectopy
graded by density and circadian type, correlation of symptoms with the rhythm, the
reviewer's summary. The density grading (`density_class`) and the circadian type come
from there as well.

A strip is 7.2 s, which is 180 mm of an A4 sheet at 25 mm/s. The following are proposed
automatically: a sample of the dominant rhythm (the cleanest 7 s in the minute whose
heart rate is closest to the 24-hour average), the minimum and maximum heart rate, the
longest pause, up to eight ventricular and four supraventricular runs, one example per
PVC morphology (the most confident single complex, to show the shape rather than an
already shown pair) and every diary entry.

## Why the handlers compute synchronously

The application is single-user and local: one record per process, one reviewer in the
browser. The handlers are declared `async`, but the ECG windows, the recomputation and
the protocol are computed right inside them; blocking the event loop for tens to
hundreds of milliseconds is acceptable here and simpler than any thread pool.
