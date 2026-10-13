"""Sankalp local app: identifiable records for checking and correcting data.

Run on a computer that holds the REDCap exports (never on a shared server):

    streamlit run app/streamlit_app.py

It reads either a processed output folder (from `python -m sankalp.build`) or the raw
exports directly. Nothing leaves the computer.
"""
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sankalp import build, outcomes, quality  # noqa: E402
from sankalp.link import _norm, name_sim  # noqa: E402

st.set_page_config(page_title="Sankalp records (local)", layout="wide")
CHECKS = {**quality.BABY_CHECKS, **quality.SNCU_CHECKS}
ID_COLS = ["period", "record_id", "baby_no", "mother_name", "father_name", "phone1", "phone2", "village",
           "res_block", "dob", "birth_place_type", "birth_facility", "outcome", "dod", "fu_date", "flags"]
SNCU_COLS = ["admission_id", "adm_date", "dob", "mother_name", "father_name", "phone", "village", "res_block",
             "sex", "bw_g", "admission_type", "outcome", "discharge_date", "cause_of_death", "flags"]


def _as_lists(s: pd.Series) -> pd.Series:
    return s.fillna("").map(lambda v: [x for x in v.split("; ") if x] if isinstance(v, str) else list(v))


@st.cache_data(show_spinner="Reading processed files…")
def load_output(folder: str, stamp: float):
    b = pd.read_parquet(Path(folder) / "babies.parquet")
    s = pd.read_parquet(Path(folder) / "sncu.parquet")
    return b, s


@st.cache_data(show_spinner="Processing the exports (about 30 seconds)…")
def load_raw(k2024: str, nhrp: str, sncu: str, as_of: str, stamp: tuple):
    b, s, _ = build.run(k2024, nhrp, sncu, as_of or None)
    for df in (b, s):
        df["flags"] = df["flags"].map("; ".join)
    b["death_factors"] = b["death_factors"].map("; ".join)
    return b, s


def pick_data():
    st.sidebar.header("Data")
    mode = st.sidebar.radio("Read from", ["Processed output folder", "Raw REDCap / SNCU exports"], key="mode")
    if mode.startswith("Processed"):
        folder = st.sidebar.text_input("Folder", os.environ.get("SANKALP_OUTPUT", str(ROOT / "output")), key="folder")
        f = Path(folder) / "babies.parquet"
        if not f.exists():
            st.info(f"No babies.parquet in {folder}. Run `python -m sankalp.build …` first, or switch to raw exports.")
            st.stop()
        return load_output(folder, f.stat().st_mtime)
    k = st.sidebar.text_input("2024 cohort CSV", key="k2024")
    n = st.sidebar.text_input("2025-26 NHRP CSV", key="nhrp")
    x = st.sidebar.text_input("SNCU admission report (.xlsx)", key="sncu")
    as_of = st.sidebar.text_input("Export date (YYYY-MM-DD, optional)", key="asof")
    paths = [Path(p) for p in (k, n, x)]
    if not all(p.is_file() for p in paths):
        st.info("Enter the full paths of the three files in the sidebar.")
        st.stop()
    return load_raw(k, n, x, as_of, tuple(p.stat().st_mtime for p in paths))


def flag_labels(codes):
    return ", ".join(CHECKS[c][1] for c in codes if c in CHECKS)


def download(df: pd.DataFrame, name: str, key: str):
    st.download_button(f"Download {len(df):,} rows as CSV", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=name, mime="text/csv", key=key)


babies, sncu = pick_data()
babies = babies.copy()
sncu = sncu.copy()
babies["flag_list"] = _as_lists(babies["flags"])
sncu["flag_list"] = _as_lists(sncu["flags"])
for c in ("live_born", "stillborn", "outcome_known", "nnd", "early_nnd"):
    babies[c] = babies[c].astype(bool)

st.title("Sankalp records (local)")
st.caption("Identifiable data. Keep this on the project computer; share only the published dashboard.")
tab_sum, tab_find, tab_work, tab_dup, tab_sncu = st.tabs(["Summary", "Find a record", "Worklists", "Duplicates", "SNCU matching"])

with tab_sum:
    cols = st.columns(2)
    for col, (period, d) in zip(cols, babies.groupby("period")):
        r = outcomes.nmr(d)
        with col:
            st.subheader(f"{period} cohort")
            a, b_, c = st.columns(3)
            a.metric("NMR per 1,000", f"{r['nmr']:.1f}")
            b_.metric("Neonatal deaths", f"{r['deaths']:,}")
            c.metric("Outcome known", f"{100 * r['coverage']:.1f}%")
            st.caption(f"{r['live_births']:,} live births · {r['stillbirths']:,} stillbirths · SBR {r['sbr']:.1f}")
    rows = [dict(period=p, block=blk, **outcomes.nmr(d)) for (p, blk), d in babies.groupby(["period", "res_block"])]
    t = pd.DataFrame(rows)[["period", "block", "live_births", "known", "deaths", "nmr", "stillbirths", "sbr", "coverage"]]
    st.dataframe(t.round(2), hide_index=True, width="stretch")

with tab_find:
    q = st.text_input("Record ID, SNCU admission ID, phone number or a parent's name", key="q").strip()
    if q:
        ql = q.lower()
        has = lambda s: s.astype("string").str.lower().str.contains(ql, regex=False).fillna(False).astype(bool)
        same = lambda s: s.astype("string").str.lower().eq(ql).fillna(False).astype(bool)
        hit = (same(babies["record_id"]) | same(babies["phone1"]) | same(babies["phone2"])
               | has(babies["mother_name"]) | has(babies["father_name"]))
        res = babies[hit]
        st.write(f"{len(res):,} cohort bab{'y' if len(res) == 1 else 'ies'}")
        sel = st.dataframe(res[ID_COLS].head(500), hide_index=True, width="stretch",
                           on_select="rerun", selection_mode="single-row", key="find_tbl")
        rows = sel.selection.rows if sel else []
        if rows:
            rec = res.iloc[rows[0]]
            st.subheader(f"{rec['period']} · Record {rec['record_id']} · baby {rec['baby_no']}")
            if rec["flag_list"]:
                for c in rec["flag_list"]:
                    sev, label, help_ = CHECKS.get(c, ("", c, ""))
                    st.warning(f"**{label}** ({sev}). {help_}")
            st.dataframe(rec.drop(labels=["flag_list"]).astype(str).rename("value").to_frame(), width="stretch")
            adm = sncu[sncu["baby_uid"].eq(rec["baby_uid"])]
            if len(adm):
                st.write("Linked SNCU admissions")
                st.dataframe(adm[SNCU_COLS], hide_index=True, width="stretch")
        s_hit = has(sncu["admission_id"]) | same(sncu["phone"]) | has(sncu["mother_name"]) | has(sncu["father_name"])
        if s_hit.any():
            st.write(f"{int(s_hit.sum()):,} SNCU admissions")
            st.dataframe(sncu.loc[s_hit, SNCU_COLS + ["baby_uid", "link_tier"]], hide_index=True, width="stretch")

with tab_work:
    st.write("Records to check and correct in REDCap, with contact details for follow-up.")
    c1, c2, c3 = st.columns([3, 1, 1])
    choices = [c for c in quality.BABY_CHECKS if babies["flag_list"].map(lambda l, c=c: c in l).any()]
    pick = c1.multiselect("Checks", choices, default=[c for c in ("SNCU_DEATH_NOT_RECORDED", "STATUS_CONFLICT") if c in choices],
                          format_func=lambda c: f"{quality.BABY_CHECKS[c][1]} ({quality.BABY_CHECKS[c][0]})", key="w_checks")
    per = c2.selectbox("Period", ["All"] + sorted(babies["period"].unique()), key="w_period")
    blk = c3.selectbox("Block", ["All"] + sorted(babies["res_block"].unique()), key="w_block")
    m = babies["flag_list"].map(lambda l: any(c in l for c in pick)).astype(bool)
    if per != "All":
        m &= babies["period"].eq(per)
    if blk != "All":
        m &= babies["res_block"].eq(blk)
    w = babies.loc[m, ID_COLS + ["data_source", "reg_collector", "fu_collector"]].copy()
    w["issues"] = babies.loc[m, "flag_list"].map(flag_labels)
    st.write(f"{len(w):,} babies")
    st.dataframe(w, hide_index=True, width="stretch")
    download(w, "sankalp_worklist.csv", "dl_work")

with tab_dup:
    st.write("Records that look like the same baby registered more than once. Keep one, correct or delete the others in REDCap.")
    per = st.selectbox("Period", ["All"] + sorted(babies["period"].unique()), key="d_period")
    d = babies[babies["dup_group"].notna()]
    if per != "All":
        d = d[d["dup_group"].isin(d.loc[d["period"].eq(per), "dup_group"])]
    d = d.sort_values(["dup_group", "period", "record_id"])
    show = ["dup_group", "period", "record_id", "baby_no", "mother_name", "father_name", "phone1", "dob", "village",
            "birth_facility", "outcome", "data_source", "reg_collector"]
    st.write(f"{d['dup_group'].nunique():,} groups, {len(d):,} records")
    st.dataframe(d[show], hide_index=True, width="stretch")
    download(d[show], "sankalp_duplicates.csv", "dl_dup")

with tab_sncu:
    view = st.radio("Show", ["SNCU deaths not recorded in the cohort", "SNCU admissions not found in the cohort"], horizontal=True, key="s_view")
    if view.startswith("SNCU deaths"):
        x = sncu[sncu["flag_list"].map(lambda l: "S_DIED_COHORT_ALIVE" in l)]
        x = x.merge(babies[["baby_uid", "period", "record_id", "baby_no", "outcome", "fu_date", "fu_respondent", "fu_collector"]],
                    on="baby_uid", how="left", suffixes=("", "_cohort"))
        cols = SNCU_COLS[:-1] + ["period", "record_id", "baby_no", "outcome_cohort", "fu_date", "fu_respondent", "fu_collector", "link_tier"]
        st.write(f"{len(x):,} admissions: the SNCU recorded a death, the cohort does not.")
        st.dataframe(x[cols], hide_index=True, width="stretch")
        download(x[cols], "sankalp_sncu_deaths_not_in_cohort.csv", "dl_sd")
    else:
        u = sncu[sncu["flag_list"].map(lambda l: "S_NOT_IN_COHORT" in l)].reset_index(drop=True)
        st.write(f"{len(u):,} district residents admitted to the SNCU with no matching cohort baby. Select one to see possible matches.")
        sel = st.dataframe(u[SNCU_COLS[:-1]], hide_index=True, width="stretch", on_select="rerun",
                           selection_mode="single-row", key="unmatched")
        download(u[SNCU_COLS[:-1]], "sankalp_sncu_not_in_cohort.csv", "dl_un")
        rows = sel.selection.rows if sel else []
        if rows:
            a = u.iloc[rows[0]]
            near = babies[(babies["dob"] - a["dob"]).dt.days.abs().le(10)].copy()
            near["phone_match"] = (near["phone1"].eq(a["phone"]).fillna(False) | near["phone2"].eq(a["phone"]).fillna(False)).astype(bool)
            am, af = _norm(pd.Series([a["mother_name"]])).iat[0], _norm(pd.Series([a["father_name"]])).iat[0]
            near["mother_sim"] = [name_sim(am, v) for v in _norm(near["mother_name"])]
            near["father_sim"] = [name_sim(af, v) for v in _norm(near["father_name"])]
            near["dob_diff"] = (near["dob"] - a["dob"]).dt.days
            near = near[near["phone_match"] | (near["mother_sim"] >= 60)]
            near["score"] = near["mother_sim"] + near["father_sim"] + 60 * near["phone_match"] - 5 * near["dob_diff"].abs()
            st.write("Possible matches (DOB within 10 days, same phone or similar mother's name)")
            st.dataframe(near.sort_values("score", ascending=False).head(15)[
                ["score", "phone_match", "mother_sim", "father_sim", "dob_diff"] + ID_COLS[:-1]], hide_index=True, width="stretch")
