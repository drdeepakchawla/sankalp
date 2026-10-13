"""SNCU admission register (DH Khargone): sheet 'working' = all admissions, 'Death_636' = deaths list."""
import pandas as pd

from . import config as C
from . import harmonise as H

_SNCU_BLOCKS = {"khargoneurban": "Khargone", "oon": "Khargone", "badwah": "Barwah",
                "maheshware": "Maheshwar", "segawa": "Segaon", "gogawa": "Gogaon"}
_TAIL = ["Outcome", "Duration of Stay", "Final Diagnosis", "Cause of Death", "Discharge ", "Doctor In Charge"]


def load(path) -> pd.DataFrame:
    xl = pd.ExcelFile(path)
    w = xl.parse("working", dtype=str)
    deaths = xl.parse(xl.sheet_names[1], dtype=str) if len(xl.sheet_names) > 1 else pd.DataFrame()

    # A few rows were pasted one column to the right: their outcome block sits in 'Unnamed: 53..58'.
    shifted = w["Outcome"].isna() & w.get("Unnamed: 53", pd.Series(dtype=str)).notna()
    for i, c in enumerate(_TAIL):
        extra = f"Unnamed: {53 + i}"
        if extra in w:
            w.loc[shifted, c] = w.loc[shifted, extra]

    raw_block = H.clean_text(w["Block"])
    key = raw_block.str.lower().str.replace(r"[^a-z]", "", regex=True)
    blk = key.map(_SNCU_BLOCKS).fillna(H.block(raw_block))
    blk[blk.eq(C.UNKNOWN) & raw_block.notna() & ~key.eq("urban")] = C.OUT_OF_DISTRICT

    s = pd.DataFrame({
        "admission_id": H.clean_text(w["Admission ID"]),
        "adm_date": H.to_date(w["Adm.  Date"]),
        "dob": H.to_date(w["Date of Birth"]),
        "mother_name": H.clean_text(w["Mother's Name"]),
        "father_name": H.clean_text(w["Father's Name"]),
        "phone": H.phone10(w["Contact No."]),
        "marked_duplicate": H.clean_text(w["Duplicate"]).str.lower().eq("duplicate").fillna(False),
        "res_block": blk,
        "village": H.clean_text(w["Village"]),
        "sex": H.sex(w["Sex"]),
        "caste": H.clean_text(w["Category"]),
        "place_of_delivery": H.clean_text(w["Place of Delivery"]),
        "transport": H.clean_text(w["Mode of Transport"]),
        "admission_type": H.clean_text(w["Type of Admission"]).str.replace(r"\s*\(", " (", regex=True),
        "maturity": H.clean_text(w["Maturity"]).str.extract(r"^(\w+)", expand=False).str.title(),
        "ga_wk": H.to_num(w["Gestational Age"]),
        "age_at_adm_days": H.to_num(w["Age"]),
        "bw_g": (H.to_num(w["Weight"]) * 1000).round(),
        "indication": H.clean_text(w["Indication of Admission"]),
        "outcome": H.clean_text(w["Outcome"]),
        "los_days": H.to_num(w["Duration of Stay"]),
        "final_dx": H.clean_text(w["Final Diagnosis"]),
        "cause_or_reason": H.clean_text(w["Cause of Death"]),
        "discharge_date": H.to_date(w["Discharge "]),
        "anc_visits": H.to_num(w["ANC Visits"]),
        "resuscitation": H.clean_text(w["Resuscitation "]),
    })
    s["admission_type"] = s["admission_type"].replace({"Outborn (Community Referred)": "Outborn (community)",
                                                       "Outborn (Health Facility Referred)": "Outborn (facility referred)"})
    s["in_death_sheet"] = s["admission_id"].isin(set(H.clean_text(deaths.get("Admission ID", pd.Series(dtype=str))).dropna()))
    s["died"] = s["outcome"].eq("EXPIRED")
    s["cause_of_death"] = s["cause_or_reason"].where(s["died"])
    s["referral_reason"] = s["cause_or_reason"].where(s["outcome"].eq("REFERRED"))
    s["age_at_death_days"] = (s["discharge_date"] - s["dob"]).dt.days.where(s["died"])
    s["adm_month"] = s["adm_date"].dt.to_period("M").astype(str).where(s["adm_date"].notna())
    s["bw_band"] = H.band(s["bw_g"].where(s["bw_g"].between(C.BW_MIN_G, C.BW_MAX_G)), C.BW_BANDS, "Missing/implausible")
    s["ga_band"] = H.band(s["ga_wk"].where(s["ga_wk"].between(C.GA_MIN_WK, C.GA_MAX_WK)), C.GA_BANDS, "Missing/implausible")
    s["inborn"] = s["admission_type"].eq("Inborn")
    return s
