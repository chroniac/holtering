# scp-holter — reading the LabTech SCP-ECG export

## Purpose

The `scp_holter` package reads 24-hour Holter exports of the LabTech
EC-12H / CardioSpy recorder (`*_raw_ECG.scp`): it parses the SCP-ECG container
(ISO 11073-91064) and yields the patient record card, lead definitions, signal
metadata and the signal itself — either as a zero-copy `numpy.memmap` or as a
segment in mV. Export: EDF+C, SVG strip, `.npy`, `.csv`. The `holtering`
application uses the package as a library; there is no reverse dependency and
there never will be (`lint-imports` enforces it).

Verified on a real 259 MB / 23.99 h export: 125 Hz, 1747 nV/LSB as declared,
12 × 10 794 500 `int16 LE` samples laid out lead after lead starting at
byte 445, R peaks matching the accompanying `Qrs.txt` to within 1–2 samples.

Typical use:

```python
from scp_holter import ScpHolter, to_edf

rec = ScpHolter("data/raw.scp")
sig = rec.read(start_s=10800, dur_s=10)  # (12, 1250) float32, mV
to_edf(rec, "out/full.edf")  # lossless EDF+C, 1 s records
```

## File format

The preamble and the section headers are fixed-width, little-endian:

```
preamble  : CRC-CCITT(2) + record length(4)     length == file size
header    : CRC(2) ID(2) length(4) version(1) protocol(1) reserved(6)
section 0 : 10 bytes per entry — ID(2) length(4) index(4, 1-based offset)
```

| Section | What is in it | Who reads it |
|---|---|---|
| 0 | pointer table to the remaining sections | `sections.read_container` |
| 1 | patient record card and acquisition parameters, tag stream | `patient.parse_patient` |
| 2 | Huffman tables | presence only: `record` refuses to read such a file |
| 3 | lead definitions: count, flags, ranges, channel identifiers | `leads.parse_leads` |
| 6 | rhythm data: AVM, sampling interval, sample matrix | `signal.parse_signal` |

Section 1 is a stream of `tag(1) length(2) value(length)` entries, terminated
by tag 255. Text fields are cp1251 and null-padded: a Russian-locale firmware.

Section 6 starts with `AVM(2, nV/LSB) interval(2, µs) diff(1) bimodal(1)`, then
one `u16` byte counter per lead, then the samples. If `diff != 0` or section 2
is present, the package does not guess the encoding and fails with
`NotImplementedError`.

## Vendor deviations

They are the reason strict third-party parsers reject the file; hence the
package parses the container itself instead of taking an off-the-shelf reader.

- **The reserved header field is zeroed.** The standard requires the string
  `SCPECG` there.
- **The section version is 10.** Validators either expect 10 to mean "1.0" or
  reject everything except 20.
- **The per-lead byte counters in section 6 are `u16` and overflow.** On a
  24-hour record they hold 27656 while the true value is 21 589 000
  (= 27656 mod 65536). Only the length of the section itself gives the true
  length: `(section length − header − metadata) / (2 × channel count)` — that is
  the number of samples per lead. Never trust those fields.
- **`lead_id` in section 3 holds 0-based channel indices (0…11), not SCP lead
  codes.** Code 0 in the standard table means "unspecified", so they cannot be
  taken for codes — which channels these are was established from the data
  itself (below).
- **Samples are laid out lead by lead, not interleaved**: first the whole of
  lead 0, then the whole of lead 1 and so on. Without section 2 and without
  differential encoding the block is simply an `int16 LE` matrix, so it is
  mapped into memory as is (`signal.memmap`, shape `(n_leads, n_samples)`),
  without copying and without decompression. A segment of a single lead is a
  contiguous piece of the file and `signal.read_lead` reads it with a plain
  `np.fromfile`: unlike a memmap slice it does not map the touched pages into
  the process, so a sequential pass over a 24-hour record does not grow RSS.

## Montage and polarity

The limb leads, channels 0…5 = I II III aVR aVL aVF — **proved** by linear
identities on a real record:

| Identity | Meaning | rmse |
|---|---|---|
| `ch2 == ch1 - ch0` | III = II − I | 0.000000 mV |
| `ch3 == -(ch0 + ch1) / 2` | aVR | 0.000616 mV |
| `ch4 == ch0 - ch1 / 2` | aVL | 0.000616 mV |
| `ch5 == ch1 - ch0 / 2` | aVF | 0.000620 mV |

The reverse permutation (`ch5 = I`, `ch4 = II`, …) misses by 0.78 mV, so the
mapping is unique. But the identities are linear and hold for `−x` as well:
they pin down the **order**, not the **sign**.

The chest leads, channels 6…11 — **the order is not verified**, two hypotheses
fit the data:

- **(a) bytes as they lie, descending order** (`ch6…ch11 = V6…V1`): R/S grows
  monotonically 0.10 → 7.01 from V1 to V6, the P axis is normal sinus
  (P = +0.086 mV in II, −0.046 in aVR).
- **(b) sign inversion, ascending order** (`ch6…ch11 = V1…V6`): a single
  inversion makes the limb-lead QRS axis, the T concordance and the V4
  transition zone textbook (signed QRS areas −48 −69 −56 −3 +50 +62 mV·ms) — at
  the price of a negative P axis (low atrial / ectopic rhythm).

PR is 176–224 ms under both, so it does not settle the dispute. The
inversion-invariant |P| gradient across the block is
0.014 0.048 0.086 0.077 0.069 0.058 mV; the near-zero channel is `ch6`, which
fits V1 (a biphasic P cancels itself out) and leans towards (b).

By default the package leaves the bytes as they are and labels the chest block
neutrally (`ch6…ch11`); `--invert` and `--chest` switch to (b).

### What is not proved

- The order of the chest leads: the dispute will be settled by a CardioSpy
  printout of the same beat — until then neither hypothesis is chosen in code.
- The absolute sign of the signal: linear identities are insensitive to it.
- The absolute gain: 1747 nV/LSB is taken from the device declaration and is
  not confirmed by an independent calibration.

## Export

- **EDF+C** (`export/edf.py`) — 1-second records, `int16` without rescaling,
  lossless. The EDF header is strict fixed-width ASCII, so the cp1251 surname
  is transliterated and dates are written as `dd-MMM-yyyy`. The digital range
  is asymmetric (−32768…32767); mapping a symmetric physical range onto it
  would make 1 LSB stop being equal to the declared AVM — hence `phys_min` and
  `phys_max` are computed separately from the `±` limits. Written in chunks of
  600 records so that a 24-hour file is never assembled in memory as a whole.
- **SVG** (`export/svg.py`) — a clinical grid at 25 mm/s, 1 mm fine / 5 mm
  coarse cells, one track per lead; the gain is picked from the
  10/5/2.5/2/1 mm/mV series so that the widest-swinging of the selected leads
  still fits into its track.
- **`.npy` and `.csv`** (`export/arrays.py`) — a `float32` matrix in mV and a
  "time + one column per lead" table. Both honour the selected record polarity.

## CLI

The entry point is `scp-holter` (also `python -m scp_holter`):

```bash
scp-holter info data/raw.scp
scp-holter svg  data/raw.scp out/strip.svg --start 10800 --dur 10
scp-holter svg  data/raw.scp out/strip.svg --leads II,V2,V5 --gain 10
scp-holter edf  data/raw.scp out/full.edf
scp-holter edf  data/raw.scp out/flip.edf --invert --chest V1,V2,V3,V4,V5,V6
```

`info` prints the record card, the section inventory, the signal parameters and
the selected polarity. `--invert` flips the sign of all samples both on reading
and on export, `--chest` labels channels 6…11 explicitly.
