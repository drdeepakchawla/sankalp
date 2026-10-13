"""2024 Khargone cohort (SankalpKhargone_DATA_LABELS_*.csv): one row per pregnancy -> one row per baby."""
import pandas as pd

from . import config as C
from . import harmonise as H

PERIOD = "2024"
BORN_ALIVE = "Was baby born alive (cried, had any heart rate or moved any part of body)?"


def _col(df, base, occurrence):
    """pandas names repeated headers 'X', 'X.1', 'X.2' ... in order of appearance."""
    name = base if occurrence == 0 else f"{base}.{occurrence}"
    return df[name] if name in df.columns else pd.Series(pd.NA, index=df.index, dtype="string")


# Baby slot -> occurrence index of each repeated question. The 28-day blocks share
# question text with the mother's 42-day block (occurrence 1), so babies 2 and 3 skip it.
_BABY_OCC = {0: dict(baby=0, fu=0), 1: dict(baby=1, fu=2), 2: dict(baby=2, fu=3)}


def _place_of_birth(raw: pd.Series) -> tuple[pd.Series, pd.Series]:
    t = raw.astype("string").str.strip()
    ptype = pd.Series("Public facility", index=t.index, dtype=object)
    ptype[t.eq("Home")] = "Home"
    ptype[t.eq("During transport")] = "On the way"
    ptype[t.eq("Outside district")] = "Outside district"
    ptype[t.eq("Private Health Facility")] = "Private facility"
    ptype[t.isna()] = C.UNKNOWN
    fac = H.facility(t).where(ptype.eq("Public facility"))
    return ptype, fac


def load(path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, low_memory=False, encoding_errors="replace")
    ptype, fac = _place_of_birth(df["Place of birth"])
    fac_other = H.clean_text(df["Place of birth if private health facility within district"]).fillna(
        H.clean_text(df["Place of birth, if outside district"]))
    reg_raw = H.clean_text(df["Who registered birth in Sankalp?"])
    reg_collector, = H.code_people(reg_raw, prefix="R24-")
    fu_people = [H.clean_text(_col(df, "Who collected 28 days outcome?", k)) for k in range(3)]
    fu_codes = H.code_people(*fu_people, prefix="F24-")
    n_babies = H.to_num(df["Number of babies born"])

    mother = pd.DataFrame({
        "record_id": df["Record ID"].astype(str),
        "data_access_group": H.clean_text(df["Data Access Group"]),
        "mother_name": H.clean_text(df["Name of pregnant woman"]),
        "father_name": H.clean_text(df["Husband name"]),
        "phone1": H.phone10(df["Primary mobile number"]),
        "phone2": H.phone10(df["Additional mobile number"]),
        "village": H.clean_text(df["City or village name"]),
        "res_block": H.block(df["Resident of which block"]),
        "res_type": pd.NA,
        "dob": H.to_date(df["Date of delivery"]),
        "lmp": H.to_date(df["Date of LMP"]),
        "ga_wk": H.to_num(df["Calculated period of gestation in completed weeks"]),
        "ga_source": "LMP",
        "gravida": H.to_num(df["Gravida"]),
        "birth_place_type": ptype,
        "birth_facility": fac,
        "birth_facility_other": fac_other,
        "delivery_type": pd.NA,
        "n_babies": n_babies,
        "birth_info_source": H.clean_text(df["Source of confirmation of birth data"]),
        "reg_collector": reg_collector,
        "reg_collector_name": reg_raw,
        "mother_alive_d42": H.clean_text(df["Was mother alive on day 42"]),
        "caste": pd.NA,
        "religion": pd.NA,
    })

    babies = []
    for slot, occ in _BABY_OCC.items():
        b, f = occ["baby"], occ["fu"]
        born = H.clean_text(_col(df, BORN_ALIVE, b))
        present = born.notna() | (n_babies > slot) if slot else pd.Series(True, index=df.index)
        x = mother.copy()
        x["baby_no"] = slot + 1
        x["born_status"] = born.map({"Yes": "Live born", "No": "Stillborn"}).astype("string")
        x["bw_g"] = H.to_num(_col(df, "Birth weight (g)", b))
        x["sex"] = H.sex(_col(df, "Gender", b))
        x["preterm_reported"] = pd.NA
        x["admitted_after_birth"] = H.clean_text(_col(df, "Was baby admitted to any health facility after birth?", b))
        x["fu_collector"] = fu_codes[slot]
        x["fu_collector_name"] = fu_people[slot]
        x["fu_date"] = H.to_date(_col(df, "Date of collection of information", f))
        x["fu_respondent"] = H.clean_text(_col(df, "Source of information", f))
        x["fu_connected"] = pd.NA
        x["alive_d28_reported"] = H.clean_text(_col(df, "Was baby alive on day 28", b))
        x["dod"] = H.to_date(_col(df, "If died, date of death", f))
        x["status_detail"] = ("Born alive: " + born.fillna("not recorded") + "; alive on day 28: "
                              + x["alive_d28_reported"].fillna("not recorded")
                              + (", died " + x["dod"].dt.strftime("%d-%m-%Y")).astype("string").fillna(""))
        pod = H.clean_text(_col(df, "If died, place of death", f))
        dfac = H.clean_text(_col(df, "Died at which health facility in district?", f))
        outside = H.clean_text(_col(df, "If died in a facility outside district, where?", f))
        private = H.clean_text(_col(df, "If died in a private hospital in district, where?", f))
        dpt = pod.map({"Health facility": "Public facility", "Home": "Home",
                       "During transport": "On the way"}).astype("string")
        dpt[dfac.eq("Outside district") | outside.notna()] = "Outside district"
        dpt[private.notna()] = "Private facility"
        x["death_place_type"] = dpt
        x["death_facility"] = H.facility(dfac.where(dfac.ne("Outside district"))).where(
            dpt.eq("Public facility")).fillna(outside).fillna(private)
        x["death_factors"] = [[] for _ in range(len(x))]
        x["death_factor_other_text"] = pd.NA
        x["status_conflict"] = False
        x["death_date_conflict"] = False
        x["death_after_call"] = False
        babies.append(x[present.fillna(False)])

    out = pd.concat(babies, ignore_index=True)
    out["period"] = PERIOD
    out["baby_uid"] = PERIOD + "-" + out["record_id"] + "-" + out["baby_no"].astype(str)
    out["plurality"] = out.groupby("record_id")["baby_no"].transform("max").map(
        {1: "Single", 2: "Twins", 3: "Triplets"})
    return _outcome(out)


def _outcome(x: pd.DataFrame) -> pd.DataFrame:
    """Day-28 outcome from the 2024 form, which records stillbirths as 'not alive on day 28'."""
    rep = x["alive_d28_reported"]
    x["outcome"] = "Unknown - not followed up"
    x.loc[rep.eq("Not known"), "outcome"] = "Unknown - not known"
    x.loc[rep.eq("Yes"), "outcome"] = "Alive"
    x.loc[rep.eq("No"), "outcome"] = "Died"
    x.loc[x["born_status"].eq("Stillborn"), "outcome"] = "Stillbirth"
    x["stillbirth_alive_later"] = x["born_status"].eq("Stillborn").fillna(False) & rep.eq("Yes").fillna(False)
    x["death_reported_after_d28"] = False
    return x
