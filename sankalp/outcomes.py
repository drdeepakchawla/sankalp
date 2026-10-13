"""Neonatal outcome derivation shared by both cohorts."""
import pandas as pd

from . import config as C
from . import harmonise as H

KNOWN = ["Alive", "Died", "Died after day 27"]


def finalise(b: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    b = b.copy()
    b["fu_connected"] = b["fu_connected"].astype("boolean") if "fu_connected" in b else pd.NA
    # A baby with no birth status but a day-28 outcome was born alive.
    b["born_status_missing"] = b["born_status"].isna()
    b.loc[b["born_status_missing"] & b["outcome"].isin(KNOWN), "born_status"] = "Live born"
    age = (b["dod"] - b["dob"]).dt.days
    died = b["outcome"].eq("Died")
    b["age_death_days"] = age.where(died)
    post = died & (age > C.NEONATAL_MAX_AGE_DAYS)
    b.loc[post, "outcome"] = "Died after day 27"
    b["death_reported_after_d28"] = post & b["alive_d28_reported"].eq("No")

    unknown = b["outcome"].str.startswith("Unknown")
    not_due = b["dob"] + pd.Timedelta(days=C.FOLLOWUP_DUE_DAYS) > as_of
    b.loc[unknown & not_due, "outcome"] = "Pending (under 28 days)"

    b["live_born"] = b["born_status"].eq("Live born").fillna(False)
    b["stillborn"] = b["born_status"].eq("Stillborn").fillna(False)
    b["outcome_known"] = b["live_born"] & b["outcome"].isin(KNOWN)
    b["nnd"] = b["live_born"] & b["outcome"].eq("Died")
    agek = b["age_death_days"]
    b["early_nnd"] = b["nnd"] & agek.between(0, C.EARLY_NEONATAL_MAX_AGE_DAYS)
    b["late_nnd"] = b["nnd"] & agek.between(C.EARLY_NEONATAL_MAX_AGE_DAYS + 1, C.NEONATAL_MAX_AGE_DAYS)
    b["death_age_band"] = H.age_band(agek.where(b["nnd"]))
    b.loc[b["nnd"] & b["death_age_band"].isna(), "death_age_band"] = "Age unknown"

    bw_ok = b["bw_g"].between(C.BW_MIN_G, C.BW_MAX_G)
    ga_ok = b["ga_wk"].between(C.GA_MIN_WK, C.GA_MAX_WK)
    b["bw_band"] = H.band(b["bw_g"].where(bw_ok), C.BW_BANDS, "Missing/implausible")
    b["ga_band"] = H.band(b["ga_wk"].where(ga_ok), C.GA_BANDS, "Missing/implausible")
    b["lbw"] = (b["bw_g"] < 2500).where(bw_ok)
    pre = (b["ga_wk"] < 37).where(ga_ok)
    rep = b["preterm_reported"].map({"Preterm": True, "Term": False})
    b["preterm"] = pre.astype("boolean").fillna(rep.astype("boolean"))
    b["dob_month"] = b["dob"].dt.to_period("M").astype(str).where(b["dob"].notna())
    b["fu_days"] = (b["fu_date"] - b["dob"]).dt.days
    return b


def nmr(df: pd.DataFrame) -> dict:
    """Neonatal mortality per 1,000 live births with a known day-28 outcome."""
    known = int(df["outcome_known"].sum())
    deaths = int(df["nnd"].sum())
    lb = int(df["live_born"].sum())
    births = int((df["live_born"] | df["stillborn"]).sum())
    sb = int(df["stillborn"].sum())
    return dict(
        births=births, live_births=lb, known=known, deaths=deaths,
        early=int(df["early_nnd"].sum()), late=int(df["late_nnd"].sum()),
        nmr=1000 * deaths / known if known else None,
        enmr=1000 * int(df["early_nnd"].sum()) / known if known else None,
        stillbirths=sb, sbr=1000 * sb / births if births else None,
        coverage=known / lb if lb else None,
    )
