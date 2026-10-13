"""Link SNCU admissions to cohort babies.

Matching uses identifiers only inside the pipeline; the outputs keep just the link.
Tiers, strongest first:
  1 phone   - same family mobile number and date of birth within 2 days
  2 names   - mother and father names similar (>= 85 / >= 80) and date of birth within 2 days
  3 phone+  - same mobile, date of birth within 7 days and either name similar (>= 70)
Among candidates the best tier wins, then the highest score; twins are told apart by sex and weight.
"""
import re

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

_STOP = re.compile(r"\b(bai|devi|ben|kumari|bee|bi|smt|shri|w/o|s/o|baby|of)\b")


def _norm(s: pd.Series) -> pd.Series:
    t = s.astype("string").str.lower().str.replace(r"[^a-z ]", " ", regex=True)
    return t.str.replace(_STOP, " ", regex=True).str.replace(r"\s+", " ", regex=True).str.strip().fillna("")


def name_sim(a: str, b: str) -> float:
    """0-100 similarity of two normalised names, tolerant of word order, extra words and spacing
    ("Mohan Lal" = "Mohanlal")."""
    if not a or not b:
        return 0
    return max(fuzz.token_set_ratio(a, b), fuzz.ratio(a.replace(" ", ""), b.replace(" ", "")))


def link(babies: pd.DataFrame, sncu: pd.DataFrame) -> pd.DataFrame:
    """Returns one row per SNCU admission: admission index, baby_uid, tier, score (unmatched rows have NA)."""
    b = babies[["baby_uid", "dob", "phone1", "phone2", "sex", "bw_g"]].copy()
    b["m"] = _norm(babies["mother_name"]).to_numpy()
    b["f"] = _norm(babies["father_name"]).to_numpy()
    b = b[b["dob"].notna()].reset_index(drop=True)
    s = sncu[["dob", "phone", "sex", "bw_g"]].copy()
    s["m"], s["f"] = _norm(sncu["mother_name"]), _norm(sncu["father_name"])
    s["sidx"] = sncu.index

    # Candidate pairs: same phone (any DOB), or DOB within 2 days and a similar mother's name.
    phones = pd.concat([b[["baby_uid", "phone1"]].rename(columns={"phone1": "phone"}),
                        b[["baby_uid", "phone2"]].rename(columns={"phone2": "phone"})]).dropna()
    pairs = [s.dropna(subset=["phone"]).merge(phones, on="phone")[["sidx", "baby_uid"]]]
    day = b["dob"].to_numpy().astype("datetime64[D]").astype(np.int64)
    order = np.argsort(day, kind="stable")
    day_sorted, names, uids = day[order], b["m"].to_numpy()[order], b["baby_uid"].to_numpy()[order]
    found = []
    for sidx, d, m in zip(s["sidx"], s["dob"], s["m"]):
        if pd.isna(d) or not m:
            continue
        d = np.datetime64(d, "D").astype(np.int64)
        lo, hi = np.searchsorted(day_sorted, d - 2, "left"), np.searchsorted(day_sorted, d + 2, "right")
        for _, _, j in process.extract(m, names[lo:hi], scorer=fuzz.token_set_ratio, score_cutoff=70, limit=None):
            found.append((sidx, uids[lo + j]))
    pairs.append(pd.DataFrame(found, columns=["sidx", "baby_uid"]))
    cand = pd.concat(pairs).drop_duplicates()
    cand = cand.merge(s, on="sidx").merge(b, on="baby_uid", suffixes=("_s", "_b"))

    cand["dob_diff"] = (cand["dob_s"] - cand["dob_b"]).dt.days.abs()
    same = cand["phone"].eq(cand["phone1"]).fillna(False) | cand["phone"].eq(cand["phone2"]).fillna(False)
    cand["phone_eq"] = same.to_numpy(dtype=bool)
    cand["m_sim"] = [name_sim(x, y) for x, y in zip(cand["m_s"], cand["m_b"])]
    cand["f_sim"] = [name_sim(x, y) for x, y in zip(cand["f_s"], cand["f_b"])]
    cand["sex_eq"] = cand["sex_s"].eq(cand["sex_b"]).to_numpy(dtype=bool)
    bwd = (cand["bw_g_s"] - cand["bw_g_b"]).abs()

    tier = pd.Series(np.nan, index=cand.index)
    t3 = cand["phone_eq"] & (cand["dob_diff"] <= 7) & ((cand["m_sim"] >= 70) | (cand["f_sim"] >= 70))
    t2 = (cand["m_sim"] >= 85) & (cand["f_sim"] >= 80) & (cand["dob_diff"] <= 2)
    t1 = cand["phone_eq"] & (cand["dob_diff"] <= 2)
    tier[t3], tier[t2], tier[t1] = 3, 2, 1
    cand["tier"] = tier
    cand["score"] = (cand["m_sim"] + cand["f_sim"] - 10 * cand["dob_diff"] + 30 * cand["phone_eq"]
                     + 10 * cand["sex_eq"] - (bwd.fillna(500) / 100).clip(upper=10))
    best = (cand.dropna(subset=["tier"]).sort_values(["sidx", "tier", "score"], ascending=[True, True, False])
            .drop_duplicates("sidx"))
    out = pd.DataFrame(index=sncu.index)
    best = best.set_index("sidx")
    out["baby_uid"] = best["baby_uid"]
    out["link_tier"] = best["tier"]
    out["link_score"] = best["score"]
    out["link_dob_diff"] = best["dob_diff"]
    out["link_sex_eq"] = best["sex_eq"]
    return out
