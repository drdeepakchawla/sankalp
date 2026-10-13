"""Data-quality checks. Each check adds a code to the record's `flags` list."""
import hashlib

import pandas as pd

from . import config as C
from .link import _norm, name_sim

# code: (severity, short label, what it means / what to do)
BABY_CHECKS = {
    "DOB_MISSING": ("critical", "Date of birth missing", "Cannot place the baby in time or compute age at death."),
    "DOB_FUTURE": ("critical", "Date of birth in the future", "Delivery date is after the data export date."),
    "BIRTH_STATUS_MISSING": ("major", "Birth status missing", "Live/stillborn not recorded; inferred live-born when a day-28 outcome exists."),
    "STILLBIRTH_ALIVE_LATER": ("critical", "Stillbirth reported alive later", "Recorded stillborn, but a later follow-up reports the baby alive."),
    "OUTCOME_UNKNOWN": ("critical", "Day-28 outcome unknown", "Follow-up is due but the outcome is not known, not reachable or not done."),
    "STATUS_CONFLICT": ("critical", "Alive after reported death", "A follow-up reports the baby alive after a recorded date of death."),
    "DEATH_BEFORE_BIRTH": ("critical", "Death before birth", "Date of death is earlier than date of birth."),
    "FU_BEFORE_BIRTH": ("critical", "Follow-up before birth", "Follow-up date is earlier than date of birth."),
    "SNCU_DEATH_NOT_RECORDED": ("critical", "SNCU death not recorded as death", "Linked SNCU admission ended in death, cohort outcome is not a death."),
    "SNCU_STILLBIRTH": ("critical", "Stillbirth admitted to SNCU", "Recorded stillborn, but linked to an SNCU admission."),
    "DEATH_DATE_MISSING": ("major", "Death date missing", "Baby died but the date of death is not recorded."),
    "DEATH_DATE_CONFLICT": ("major", "Death dates disagree", f"Forms give death dates more than {C.DEATH_DATE_TOLERANCE_DAYS} days apart."),
    "DEATH_AFTER_CALL": ("major", "Death after the reporting call", "Date of death is after the call that reported it."),
    "DIED_AFTER_D27_MARKED_DEAD": ("major", "Death after day 27 marked 'not alive on day 28'", "Age at death is 28+ days but day-28 status says not alive."),
    "FU_EARLY": ("major", "Follow-up before day 28", "Baby reported alive at a call made before day 28."),
    "BW_MISSING": ("major", "Birth weight missing", ""),
    "BW_IMPLAUSIBLE": ("major", "Birth weight implausible", f"Outside {C.BW_MIN_G}-{C.BW_MAX_G} g."),
    "GA_IMPLAUSIBLE": ("major", "Gestation implausible", f"Outside {C.GA_MIN_WK}-{C.GA_MAX_WK} weeks (usually a wrong LMP)."),
    "DUPLICATE_SUSPECT": ("major", "Possible duplicate registration", "Another record has the same date of birth and baby number, and the same parents' names or the same phone with a similar mother's name."),
    "GA_MISSING": ("minor", "Gestation missing", ""),
    "BW_GA_INCONSISTENT": ("minor", "Weight and gestation don't fit", ">=3500 g at <32 weeks, or <1000 g at >=37 weeks."),
    "SEX_MISSING": ("minor", "Sex missing", ""),
    "SEX_CONFLICT": ("minor", "Sex differs between forms", "Notification and registration record different sex."),
    "BW_CONFLICT": ("minor", "Weight differs between forms", "Registration and follow-up weights differ by more than 300 g."),
    "BLOCK_MISSING": ("minor", "Residence block missing", ""),
    "DEATH_PLACE_MISSING": ("minor", "Place of death missing", ""),
    "FU_LATE": ("minor", "Follow-up after day 90", "Outcome collected more than 90 days after birth (recall risk); 2025-26 only."),
}

SNCU_CHECKS = {
    "S_ADMISSION_BEFORE_BIRTH": ("critical", "Admission before birth", ""),
    "S_DIED_COHORT_ALIVE": ("critical", "Died in SNCU, cohort says alive/unknown", "Linked cohort baby's outcome is not a death."),
    "S_OUTCOME_MISSING": ("major", "Outcome missing", "No discharge outcome recorded."),
    "S_DEATH_NOT_IN_DEATH_SHEET": ("major", "Death missing from deaths sheet", "Outcome EXPIRED but not in the Death sheet."),
    "S_DISCHARGE_BEFORE_ADMISSION": ("major", "Discharge before admission", ""),
    "S_WEIGHT_IMPLAUSIBLE": ("major", "Weight implausible", f"Outside {C.BW_MIN_G}-{C.BW_MAX_G} g."),
    "S_NOT_IN_COHORT": ("major", "Not found in cohort", "District resident born in the cohort period, but no matching cohort baby."),
    "S_MARKED_DUPLICATE": ("minor", "Marked duplicate", "Marked 'Duplicate' in the register."),
    "S_AGE_MISMATCH": ("minor", "Age at admission doesn't match dates", "Recorded age differs from admission date minus date of birth by >1 day."),
    "S_GA_MATURITY_MISMATCH": ("minor", "Gestation and maturity disagree", "Preterm with GA >=37, or full-term with GA <37."),
}


def _add(flags, mask, code):
    for i in mask[mask.fillna(False).astype(bool)].index:
        flags[i].append(code)


def baby_flags(b: pd.DataFrame, as_of) -> pd.Series:
    flags = {i: [] for i in b.index}
    nnd = b["nnd"]
    _add(flags, b["dob"].isna(), "DOB_MISSING")
    _add(flags, b["dob"] > as_of, "DOB_FUTURE")
    _add(flags, b["born_status_missing"], "BIRTH_STATUS_MISSING")
    _add(flags, b["stillbirth_alive_later"], "STILLBIRTH_ALIVE_LATER")
    _add(flags, b["live_born"] & b["outcome"].str.startswith("Unknown"), "OUTCOME_UNKNOWN")
    _add(flags, b["status_conflict"], "STATUS_CONFLICT")
    _add(flags, b["age_death_days"] < 0, "DEATH_BEFORE_BIRTH")
    _add(flags, b["fu_days"] < 0, "FU_BEFORE_BIRTH")
    _add(flags, nnd & b["dod"].isna(), "DEATH_DATE_MISSING")
    _add(flags, b["death_date_conflict"], "DEATH_DATE_CONFLICT")
    _add(flags, b["death_after_call"], "DEATH_AFTER_CALL")
    _add(flags, b["death_reported_after_d28"], "DIED_AFTER_D27_MARKED_DEAD")
    _add(flags, b["outcome"].eq("Alive") & b["fu_days"].between(0, C.FOLLOWUP_DUE_DAYS - 1), "FU_EARLY")
    _add(flags, b["outcome"].eq("Alive") & (b["fu_days"] > C.FOLLOWUP_LATE_DAYS) & b["period"].eq("2025-26"), "FU_LATE")
    lb = b["live_born"] | b["stillborn"]
    _add(flags, lb & b["bw_g"].isna(), "BW_MISSING")
    _add(flags, b["bw_g"].notna() & ~b["bw_g"].between(C.BW_MIN_G, C.BW_MAX_G), "BW_IMPLAUSIBLE")
    _add(flags, lb & b["ga_wk"].isna(), "GA_MISSING")
    _add(flags, b["ga_wk"].notna() & ~b["ga_wk"].between(C.GA_MIN_WK, C.GA_MAX_WK), "GA_IMPLAUSIBLE")
    ga_ok = b["ga_wk"].between(C.GA_MIN_WK, C.GA_MAX_WK)
    _add(flags, ga_ok & (((b["bw_g"] >= 3500) & (b["ga_wk"] < 32)) | ((b["bw_g"] < 1000) & (b["ga_wk"] >= 37))), "BW_GA_INCONSISTENT")
    _add(flags, b["sex"].eq(C.UNKNOWN), "SEX_MISSING")
    if "notif_sex" in b:
        known = ~b["notif_sex"].isin([C.UNKNOWN, pd.NA]) & ~b["sex"].eq(C.UNKNOWN)
        _add(flags, known & b["notif_sex"].notna() & b["notif_sex"].ne(b["sex"]), "SEX_CONFLICT")
    if "fu_bw" in b:
        _add(flags, (b["fu_bw"] - b["bw_g"]).abs() > 300, "BW_CONFLICT")
    _add(flags, b["res_block"].eq(C.UNKNOWN), "BLOCK_MISSING")
    _add(flags, nnd & b["death_place_type"].isna(), "DEATH_PLACE_MISSING")

    groups = b["dup_group"] if "dup_group" in b else duplicate_groups(b)
    _add(flags, groups.notna(), "DUPLICATE_SUSPECT")
    return pd.Series(flags)


def _key(key) -> str:
    return hashlib.md5(repr(key).encode()).hexdigest()[:8]


def duplicate_groups(b: pd.DataFrame) -> pd.Series:
    """Group key shared by records that look like the same baby registered twice (NA otherwise).

    Same DOB and baby number, and either both parents' names equal, or the same phone with a
    similar mother's name (a shared phone alone is not enough: ASHAs' numbers are often given
    as the family contact)."""
    grp = pd.Series(pd.NA, index=b.index, dtype="object")
    k = pd.DataFrame({"m": _norm(b["mother_name"]), "f": _norm(b["father_name"]), "p": b["phone1"],
                      "dob": b["dob"], "bn": b["baby_no"], "rec": b["period"] + ":" + b["record_id"]})
    named = k[k["m"].ne("") & k["f"].ne("") & k["dob"].notna()]
    for key, g in named[named.duplicated(["m", "f", "dob", "bn"], keep=False)].groupby(["m", "f", "dob", "bn"]):
        if g["rec"].nunique() > 1:
            grp.loc[g.index] = "N" + _key(key)
    phoned = k[k["p"].notna() & k["dob"].notna()]
    for key, g in phoned[phoned.duplicated(["p", "dob", "bn"], keep=False)].groupby(["p", "dob", "bn"]):
        rows = list(g.itertuples())
        for i, x in enumerate(rows):
            for y in rows[i + 1:]:
                if x.rec != y.rec and x.m and y.m and name_sim(x.m, y.m) >= 80:
                    label = grp[x.Index] if pd.notna(grp[x.Index]) else grp[y.Index]
                    label = label if pd.notna(label) else "P" + _key(key)
                    grp.loc[[x.Index, y.Index]] = label
    return grp


def link_flags(b_flags: pd.Series, babies: pd.DataFrame, sncu: pd.DataFrame) -> None:
    """Cross-dataset checks once SNCU admissions are linked (mutates the flag lists)."""
    died = sncu[sncu["died"] & sncu["baby_uid"].notna()]
    out = babies.set_index("baby_uid")["outcome"]
    idx = pd.Series(babies.index, index=babies["baby_uid"])
    for uid in died["baby_uid"].unique():
        if out[uid] not in ("Died", "Died after day 27"):
            b_flags[idx[uid]].append("SNCU_DEATH_NOT_RECORDED")
    for uid in sncu["baby_uid"].dropna().unique():
        if out[uid] == "Stillbirth":
            b_flags[idx[uid]].append("SNCU_STILLBIRTH")


def sncu_flags(s: pd.DataFrame, babies: pd.DataFrame, cohort_start) -> pd.Series:
    flags = {i: [] for i in s.index}
    _add(flags, s["adm_date"] < s["dob"], "S_ADMISSION_BEFORE_BIRTH")
    _add(flags, s["outcome"].isna(), "S_OUTCOME_MISSING")
    _add(flags, s["died"] & ~s["in_death_sheet"], "S_DEATH_NOT_IN_DEATH_SHEET")
    _add(flags, s["discharge_date"] < s["adm_date"], "S_DISCHARGE_BEFORE_ADMISSION")
    _add(flags, s["bw_g"].notna() & ~s["bw_g"].between(C.BW_MIN_G, C.BW_MAX_G), "S_WEIGHT_IMPLAUSIBLE")
    _add(flags, s["marked_duplicate"], "S_MARKED_DUPLICATE")
    _add(flags, ((s["adm_date"] - s["dob"]).dt.days - s["age_at_adm_days"]).abs() > 1, "S_AGE_MISMATCH")
    _add(flags, (s["maturity"].eq("Preterm") & (s["ga_wk"] >= 37)) | (s["maturity"].eq("Fullterm") & (s["ga_wk"] < 37)),
         "S_GA_MATURITY_MISMATCH")
    in_scope = ~s["res_block"].eq(C.OUT_OF_DISTRICT) & (s["dob"] >= cohort_start)
    _add(flags, in_scope & s["baby_uid"].isna(), "S_NOT_IN_COHORT")
    out = babies.set_index("baby_uid")["outcome"]
    linked_out = s["baby_uid"].map(out)
    _add(flags, s["died"] & s["baby_uid"].notna() & ~linked_out.isin(["Died", "Died after day 27"]), "S_DIED_COHORT_ALIVE")
    return pd.Series(flags)
