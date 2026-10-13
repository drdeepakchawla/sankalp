"""Run the whole pipeline.

    python -m sankalp.build --k2024 Sankalp...csv --nhrp NHRP...csv --sncu "SNCU ...xlsx" --out output

Writes to --out (never commit this folder; it holds identifiable data):
  babies.parquet, sncu.parquet  - full tables incl. identifiers, for the local app
  dashboard_data.txt            - de-identified, gzip+base64 payload for the dashboard
  dashboard.html                - dashboard/index.html with the payload embedded
  summary.json                  - headline numbers, match rates and flag counts
  Sankalp_error_line_list_<date>.xlsx - every data-quality issue, one sheet per check (identifiable)
"""
import argparse
import json
import re
from pathlib import Path

import pandas as pd

from . import cohort2024, cohort2025, error_listing, export, link, outcomes, quality, sncu as sncu_mod

ROOT = Path(__file__).resolve().parent.parent
DATA_MARKER = "__SANKALP_DATA__"  # inside a JS string literal in dashboard/index.html


def _as_of(paths):
    """Export date from REDCap file names (…_DATA_LABELS_YYYY-MM-DD_…), else today."""
    dates = [m.group(1) for p in paths if (m := re.search(r"(\d{4}-\d{2}-\d{2})", Path(p).name))]
    return pd.Timestamp(max(dates)) if dates else pd.Timestamp.today().normalize()


def run(k2024, nhrp, sncu_path, as_of=None):
    as_of = pd.Timestamp(as_of) if as_of else _as_of([k2024, nhrp])
    babies = pd.concat([cohort2024.load(k2024), cohort2025.load(nhrp)], ignore_index=True)
    babies = outcomes.finalise(babies, as_of)
    s = sncu_mod.load(sncu_path)
    s = s.join(link.link(babies, s))

    babies["dup_group"] = quality.duplicate_groups(babies)
    babies["flags"] = quality.baby_flags(babies, as_of)
    quality.link_flags(babies["flags"], babies, s)
    s["flags"] = quality.sncu_flags(s, babies, cohort_start=babies["dob"].min())

    # Per-baby SNCU summary: first admission's reason, last admission's outcome.
    linked = s.dropna(subset=["baby_uid"]).sort_values("adm_date")
    g = linked.groupby("baby_uid")
    per = pd.DataFrame({
        "sncu_n": g.size(),
        "sncu_type": g["admission_type"].first(),
        "sncu_indication": g["indication"].first(),
        "sncu_outcome": g["outcome"].last(),
        "sncu_dx": g["final_dx"].last(),
        "sncu_cod": linked[linked["died"]].groupby("baby_uid")["cause_of_death"].last(),
    })
    babies = babies.merge(per, left_on="baby_uid", right_index=True, how="left")
    babies["sncu_n"] = babies["sncu_n"].fillna(0).astype(int)
    return babies, s, as_of


def summary(babies, s, as_of):
    out = {"as_of": as_of.date().isoformat(), "periods": {}}
    for p, d in babies.groupby("period"):
        out["periods"][p] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in outcomes.nmr(d).items()}
        out["periods"][p]["dob_range"] = [str(d["dob"].min().date()), str(d["dob"].max().date())]
    out["sncu"] = {"admissions": len(s), "linked": int(s["baby_uid"].notna().sum()),
                   "link_tiers": s["link_tier"].value_counts().sort_index().to_dict()}
    out["baby_flag_counts"] = babies["flags"].explode().value_counts().to_dict()
    out["sncu_flag_counts"] = s["flags"].explode().value_counts().to_dict()
    return out


def write(babies, s, as_of, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    keep = lambda df: df.drop(columns=[c for c in df.columns if df[c].map(type).eq(list).any()], errors="ignore")
    b = babies.copy()
    b["flags"] = b["flags"].map("; ".join)
    b["death_factors"] = b["death_factors"].map("; ".join)
    b.to_parquet(out_dir / "babies.parquet", index=False)
    s2 = s.copy()
    s2["flags"] = s2["flags"].map("; ".join)
    keep(s2).to_parquet(out_dir / "sncu.parquet", index=False)

    meta = {"as_of": as_of.date().isoformat(), "generated": pd.Timestamp.now().isoformat(timespec="minutes")}
    data = export.encode(export.payload(babies, s, meta))
    (out_dir / "dashboard_data.txt").write_text(data)
    template = ROOT / "dashboard" / "index.html"
    if template.exists():
        html = template.read_text()
        if DATA_MARKER not in html:
            raise ValueError(f"{template} has no {DATA_MARKER} placeholder")
        (out_dir / "dashboard.html").write_text(html.replace(DATA_MARKER, data, 1))
    error_listing.write(babies, s, out_dir / f"Sankalp_error_line_list_{as_of.date()}.xlsx", as_of)
    summ = summary(babies, s, as_of)
    (out_dir / "summary.json").write_text(json.dumps(summ, indent=2, default=str))
    return summ


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--k2024", required=True, help="SankalpKhargone_DATA_LABELS_*.csv (2024 cohort)")
    ap.add_argument("--nhrp", required=True, help="NHRPsankalpUpdated_DATA_LABELS_*.csv (2025-26 cohort)")
    ap.add_argument("--sncu", required=True, help="SNCU admission report .xlsx")
    ap.add_argument("--out", default="output", help="output folder (default: output)")
    ap.add_argument("--as-of", help="data export date YYYY-MM-DD (default: from file names)")
    a = ap.parse_args()
    babies, s, as_of = run(a.k2024, a.nhrp, a.sncu, a.as_of)
    summ = write(babies, s, as_of, Path(a.out))
    print(json.dumps({k: summ[k] for k in ("as_of", "periods", "sncu")}, indent=2, default=str))


if __name__ == "__main__":
    main()
