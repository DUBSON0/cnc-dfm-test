"""Command-line DFM analysis: python cli.py part.step [--json out.json]"""

from __future__ import annotations

import argparse
import json
import sys

from dfm.analyzer import analyze_step_file

SEV_TAG = {"critical": "\033[91mCRIT\033[0m", "warning": "\033[93mWARN\033[0m",
           "info": "\033[94mINFO\033[0m"}


def main() -> int:
    ap = argparse.ArgumentParser(description="CNC milling manufacturability analysis")
    ap.add_argument("step_file")
    ap.add_argument("--json", help="write full report to this JSON file")
    args = ap.parse_args()

    result, _ = analyze_step_file(args.step_file)
    d = result.to_dict()

    print(f"\nManufacturability score: {d['score']}/100")
    print("-" * 56)
    for k, v in d["subscores"].items():
        bar = "#" * int(v / 5)
        print(f"  {k:<16} {v:5.1f}  {bar}")
    si = d["setup_info"]
    print(f"\nEstimated setups: {si['estimated_setups']} "
          f"({', '.join(si['setup_directions']) or 'single'})")

    recs = d.get("recommendations", [])
    if recs:
        print("\nMost critical design changes (ranked by score impact):")
        for rank, r in enumerate(recs[:5], 1):
            print(f"  {rank}. {r['action']}")
            print(f"     fixes +{r['solo_gain']} pts on its own; "
                  f"score after changes 1–{rank}: {r['score_after']}")
        if len(recs) > 5:
            print(f"  ... plus {len(recs) - 5} smaller changes "
                  f"(full detail in findings below)")

    print(f"\nFindings: {len(d['findings'])}\n")
    for f in d["findings"]:
        print(f"[{SEV_TAG[f['severity']]}] {f['title']}")
        print(f"   {f['detail']}")
        print(f"   fix: {f['suggestion']}\n")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(d, fh, indent=2)
        print(f"Full report written to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
