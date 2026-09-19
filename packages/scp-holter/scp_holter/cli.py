"""Command line front end: python -m scp_holter <cmd> FILE.scp [OUT] [options]."""

from __future__ import annotations

import argparse

from .export import to_csv, to_edf, to_npy, to_svg
from .record import ScpHolter

EPILOG = """\
examples:
  python -m scp_holter info data/raw.scp
  python -m scp_holter svg  data/raw.scp out/strip.svg --start 10800 --dur 10
  python -m scp_holter svg  data/raw.scp out/strip.svg --leads II,V2,V5 --gain 10
  python -m scp_holter edf  data/raw.scp out/full.edf
  python -m scp_holter edf  data/raw.scp out/flip.edf --invert --chest V1,V2,V3,V4,V5,V6
"""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="scp_holter",
        description="Read LabTech EC-12H / CardioSpy SCP-ECG Holter exports.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("cmd", choices=["info", "svg", "npy", "csv", "edf"])
    ap.add_argument("scp")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--start", type=float, default=0.0, help="seconds from record start")
    ap.add_argument("--dur", type=float, default=None, help="seconds (svg default 10)")
    ap.add_argument("--leads", default=None, help="comma list to plot, e.g. II,V2,V5")
    ap.add_argument("--gain", type=float, default=None, help="svg mm per mV (default: auto)")
    ap.add_argument("--invert", action="store_true",
                    help="negate all samples: makes the limb QRS/T and an ascending chest "
                         "order textbook-normal, at the cost of a negative P axis "
                         "(see scp_holter.leads)")
    ap.add_argument("--chest", default=None,
                    help="label channels 6..11 explicitly, e.g. V1,V2,V3,V4,V5,V6")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    rec = ScpHolter(args.scp, invert=args.invert)
    if args.chest:
        try:
            rec.set_chest_labels(args.chest.split(","))
        except ValueError as exc:
            ap.error(str(exc))

    if args.cmd == "info":
        print(rec.describe())
        return 0
    if not args.out:
        ap.error("output path required")

    if args.cmd == "svg":
        print(to_svg(rec, args.out, args.start, 10.0 if args.dur is None else args.dur,
                     args.leads.split(",") if args.leads else None, mm_mv=args.gain))
    elif args.cmd == "npy":
        print(to_npy(rec, args.out, args.start, args.dur))
    elif args.cmd == "csv":
        print(to_csv(rec, args.out, args.start, args.dur))
    else:
        path, nrec = to_edf(rec, args.out, args.start, args.dur)
        print(f"{path}  ({nrec} x 1 s records, {rec.n_leads} ch @ {rec.fs:g} Hz)")
    return 0
