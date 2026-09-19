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
name includes the file size and mtime, `gain` and `invert`, so substituting the record
or the calibration yields a new cache).

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
| `noisy` | local HF noise above 2.5 of the record's baseline level, or the window is in noise |
| `narrow` | a V label, but the QRS is no wider than the sinus one — this is not a ventricular complex |
| `sinus-shape` | a V label, but the complex is in a morphology family with more than 90 % sinus beats |
| `not-premature` | an S label, but the complex is not premature relative to the preceding sinus rhythm |
| `uncertain` | a V label with a QRS width of 1.1–1.4 of the sinus one, or contradictory features |
| `likely` | passed every check |
| `manual`, `manual-N`, `manual-X` | the reviewer's decision: ectopy, normal, artefact |

The verdicts `likely`, `uncertain` and `manual` count towards ectopy (`KEEP`).

Amplitude is compared with the hourly median amplitude of sinus complexes, width — with
the median sinus width across the whole record: both calibrations live in the heavy
pass.

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
