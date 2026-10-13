"""2025-26 NHRP cohort (NHRPsankalpUpdated_DATA_LABELS_*.csv): one row per mother -> one row per baby.

The export holds 14 REDCap forms side by side, each closed by a 'Complete?' column:
  form 0  birth notification (mother + up to 3 babies)
  form 1  mother registration
  forms 2-4  newborn registration, baby 1-3
  forms 5-13 day-28 follow-up: 3 sets (repeat calls) x baby 1-3; set 3 is the main one.
Columns are found by question number inside each form, because REDCap repeats the
same question text across forms and pandas renames the repeats.
"""
import re

import numpy as np
import pandas as pd

from . import config as C
from . import harmonise as H

PERIOD = "2025-26"


def _base(col):
    return re.sub(r"\.\d+$", "", col)


def _forms(df):
    cols = list(df.columns)
    ends = [i for i, c in enumerate(cols) if _base(c).strip() == "Complete?"]
    forms, start = [], 0
    for e in ends:
        forms.append(cols[start:e])
        start = e + 1
    if len(forms) != 14:
        raise ValueError(f"Expected 14 REDCap forms in the NHRP export, found {len(forms)}")
    return forms


def _match(form_cols, q):
    pat = re.compile(rf"^\s*{q}\.", re.I) if q.startswith("Q") else re.compile(rf"^\s*{re.escape(q)}", re.I)
    return [c for c in form_cols if pat.search(_base(c))]


def _get(df, form_cols, q):
    """First column for question q in this form, NA series if absent."""
    m = _match(form_cols, q)
    return df[m[0]] if m else pd.Series(pd.NA, index=df.index, dtype="string")


def _coalesce(df, form_cols, q):
    """First non-empty value across all columns for question q (e.g. one facility list per block)."""
    out = pd.Series(pd.NA, index=df.index, dtype="string")
    for c in _match(form_cols, q):
        out = out.fillna(df[c])
    return out


def _factors(df, form_cols, q, other_q):
    """Returns f(rows) -> (list of death factors ticked per row, 'Other, specify' text).

    Evaluated lazily for the rows of babies who died, because walking every row is slow.
    """
    ticked = []
    for c in _match(form_cols, q):
        m = re.search(r"\(choice=(.+?)\)", c)
        if m:
            ticked.append((C.DEATH_FACTORS.get(m.group(1).strip(), m.group(1).strip()), df[c].eq("Checked").to_numpy()))
    other_txt = H.clean_text(_get(df, form_cols, other_q))

    def at(rows):
        out = {}
        for i in rows:
            f = {lab for lab, s in ticked if s[i]}
            oc = _classify_other(other_txt.iat[i].lower() if isinstance(other_txt.iat[i], str) else None)
            if isinstance(oc, str):
                f = (f - {"Other"}) | {oc}
            out[i] = f
        return out, other_txt
    return at


def _classify_other(text):
    if not isinstance(text, str):
        return pd.NA
    for pattern, label in C.OTHER_FACTOR_KEYWORDS:
        if re.search(pattern, text):
            return label
    return pd.NA


def load(path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, low_memory=False, encoding_errors="replace")
    F = _forms(df)
    f0, f1 = F[0], F[1]

    loc = H.clean_text(_get(df, f0, "Q41"))
    ptype = loc.map({"Public health facility": "Public facility", "Private health facility": "Private facility",
                     "Home": "Home", "On the way": "On the way"}).fillna(C.UNKNOWN)
    pub = H.clean_text(_coalesce(df, f0, "Q43"))
    fac = H.facility(pub.where(pub.ne("Other"))).where(ptype.eq("Public facility"))
    fac[ptype.eq("Public facility") & pub.eq("Other")] = "Other public facility"

    domicile = H.clean_text(_get(df, f0, "Q22"))
    res_block = H.block(df["Block / Taluk Name "])
    res_block[res_block.eq(C.UNKNOWN) & domicile.eq("No")] = C.OUT_OF_DISTRICT

    ga_usg = H.to_num(_get(df, f0, "Q38a"))
    ga_lmp = H.to_num(_get(df, f0, "Q35"))
    ga_clin = H.to_num(_get(df, f0, "Q36"))
    ga = ga_usg.fillna(ga_lmp).fillna(ga_clin)
    ga_src = np.select([ga_usg.notna(), ga_lmp.notna(), ga_clin.notna()], ["USG", "LMP", "Clinical"], None)

    mother_dead = (H.clean_text(_get(df, f0, "Q27")).eq("Dead") | H.clean_text(_get(df, f0, "Q29")).eq("Dead")
                   | H.clean_text(_get(df, f1, "Q23")).eq("Dead"))
    fu_status_mother = [H.clean_text(_get(df, F[5 + i], "Q13")) for i in range(9)]
    for s in fu_status_mother:
        mother_dead |= s.eq("Dead")

    people = [H.clean_text(_get(df, f0, "Q10"))] + [H.clean_text(_get(df, F[5 + i], "Q10")) for i in range(9)]
    codes = H.code_people(*people, prefix="T25-")
    n_babies = H.clean_text(_get(df, f0, "Q45")).map({"Single": 1, "Twins": 2, "Triplets": 3})

    mother = pd.DataFrame({
        "record_id": df["Record ID"].astype(str),
        "data_access_group": pd.NA,
        "data_source": H.clean_text(_get(df, f0, "Q2")),
        "mother_name": H.clean_text(_get(df, f0, "Q14")),
        "father_name": H.clean_text(_get(df, f0, "Q15")),
        "phone1": H.phone10(_get(df, f0, "Q16")),
        "phone2": H.phone10(_get(df, f0, "Q17")),
        "village": H.clean_text(df["Village Name"]),
        "res_block": res_block,
        "res_type": H.clean_text(df["Resident type"]),
        "dob": H.to_date(_get(df, f0, "Q33")),
        "lmp": H.to_date(_get(df, f0, "Q32")),
        "ga_wk": ga,
        "ga_source": ga_src,
        "gravida": np.nan,
        "birth_place_type": ptype,
        "birth_facility": fac,
        "birth_facility_other": H.clean_text(_get(df, f0, "Q44")),
        "delivery_type": H.clean_text(_get(df, f0, "Q39")).replace(
            {"Spontaneous Vaginal Delivery with episiotomy": "Spontaneous Vaginal Delivery"}),
        "n_babies": n_babies,
        "birth_info_source": H.clean_text(_get(df, f0, "Q2")),
        "notif_date": H.to_date(_get(df, f0, "Q7")),
        "reg_collector": codes[0],
        "reg_collector_name": people[0],
        "mother_died": mother_dead,
        "caste": H.clean_text(_get(df, f1, "Q19")),
        "religion": H.clean_text(_get(df, f1, "Q18")),
    })

    notif_q = {0: ("Q47", "Q48", "Q49", "Q50", "Q51"), 1: ("Q53", "Q54", "Q55", "Q56", "Q57"),
               2: ("Q59", "Q60", "Q61", "Q62", "Q63")}
    babies = []
    for slot in range(3):
        reg = F[2 + slot]
        q_status, q_sex, q_bw, q_now, q_dod = notif_q[slot]
        born_n = H.clean_text(_get(df, f0, q_status))
        born_r = H.clean_text(_get(df, reg, "Q4"))
        born = born_r.fillna(born_n)
        present = born.notna() | (n_babies > slot) if slot else pd.Series(True, index=df.index)

        x = mother.copy()
        x["baby_no"] = slot + 1
        x["born_status"] = born.map({"Live Born (Well)": "Live born", "Live Born (Sick)": "Live born",
                                     "Still Born / IUD": "Stillborn"}).astype("string")
        x["born_sick"] = born.eq("Live Born (Sick)")
        x["notif_sex"] = H.sex(_get(df, f0, q_sex))
        x["notif_bw"] = H.to_num(_get(df, f0, q_bw))
        x["sex"] = H.sex(_get(df, reg, "Q8").fillna(_get(df, f0, q_sex)))
        x["bw_g"] = H.to_num(_get(df, reg, "Q9")).fillna(x["notif_bw"])
        x["preterm_reported"] = H.clean_text(_get(df, reg, "Q10"))
        x["kmc_initiated"] = H.clean_text(_get(df, reg, "Q13"))
        x["location_at_reg"] = H.clean_text(_get(df, reg, "Q15"))
        x["admitted_after_birth"] = pd.NA

        # Every source that can report the baby's status, with its date and death details.
        src = [dict(name="notification", status=H.clean_text(_get(df, f0, q_now)),
                    dod=H.to_date(_get(df, f0, q_dod)), date=x["notif_date"], connected=None),
               dict(name="registration", status=H.clean_text(_get(df, reg, "Q16")),
                    dod=H.to_date(_get(df, reg, "Q17")), date=H.to_date(_get(df, f1, "Q3")), connected=None,
                    place=H.clean_text(_get(df, reg, "Q19")), factors=_factors(df, reg, "Q20", "Q20a"))]
        for g in (2, 1, 0):  # main follow-up set first
            fu = F[5 + 3 * g + slot]
            src.append(dict(
                name=f"followup{g + 1}", status=H.clean_text(_get(df, fu, "Q15")),
                dod=H.to_date(_get(df, fu, "Q16")), date=H.to_date(_get(df, fu, "Q9")),
                connected=H.clean_text(_get(df, fu, "Q11")).str.replace(" ", "").map(
                    {"Connected": True, "NotConnected": False}),
                respondent=H.clean_text(_get(df, fu, "Q12")),
                collector=codes[1 + 3 * g + slot], collector_name=people[1 + 3 * g + slot],
                place=H.clean_text(_get(df, fu, "Q18")),
                place_pub=H.clean_text(_coalesce(df, fu, "Q20")).fillna(H.clean_text(_get(df, fu, "Q21"))),
                place_pvt=H.clean_text(_get(df, fu, "Q22")),
                factors=_factors(df, fu, "Q23", "Q24"),
                fu_sex=H.sex(_get(df, fu, "Q7")), fu_bw=H.to_num(_get(df, fu, "Q8")),
                asha_visit=H.clean_text(_get(df, fu, "Q29"))))
        _combine(x, src)
        x["status_detail"] = ("At birth: " + born.astype("string") + "; ").fillna("") + x["status_detail"]
        babies.append(x[present.fillna(False)])

    out = pd.concat(babies, ignore_index=True)
    out["period"] = PERIOD
    out["baby_uid"] = PERIOD + "-" + out["record_id"] + "-" + out["baby_no"].astype(str)
    out["plurality"] = out["n_babies"].map({1: "Single", 2: "Twins", 3: "Triplets"}).fillna(
        out.groupby("record_id")["baby_no"].transform("max").map({1: "Single", 2: "Twins", 3: "Triplets"}))
    return out


def _combine(x, src):
    """Reconcile notification, registration and follow-up reports into one day-28 outcome."""
    idx = x.index
    dead = pd.DataFrame({s["name"]: s["status"].eq("Dead").fillna(False) for s in src}, index=idx)
    dods = pd.DataFrame({s["name"]: s["dod"] for s in src}, index=idx)
    fus = [s for s in src if s["name"].startswith("followup")]
    alive_dates = pd.DataFrame({s["name"]: s["date"].where(s["status"].isin(["Healthy", "Sick"]) & s["connected"].fillna(True).astype(bool))
                                for s in fus}, index=idx)
    attempted = pd.concat([s["connected"].notna() for s in fus], axis=1).any(axis=1)

    any_dead = dead.any(axis=1)
    x["dod"] = dods.min(axis=1)
    spread = (dods.max(axis=1) - dods.min(axis=1)).dt.days
    x["death_date_conflict"] = spread > C.DEATH_DATE_TOLERANCE_DAYS
    last_alive = alive_dates.max(axis=1)
    x["status_conflict"] = any_dead & last_alive.notna() & (last_alive > x["dod"] + pd.Timedelta(days=1))
    x["death_after_call"] = False
    for s in fus:
        x["death_after_call"] |= s["status"].eq("Dead").fillna(False) & (s["dod"] > s["date"]).fillna(False)

    outcome = pd.Series("Unknown - not followed up", index=idx, dtype=object)
    outcome[attempted] = "Unknown - not reachable"
    outcome[last_alive.notna()] = "Alive"
    outcome[any_dead] = "Died"
    outcome[x["born_status"].eq("Stillborn")] = "Stillbirth"
    x["outcome"] = outcome
    x["stillbirth_alive_later"] = x["born_status"].eq("Stillborn").fillna(False) & last_alive.notna()
    x["alive_d28_reported"] = pd.NA

    # Follow-up details: from the follow-up that reported the death, else the latest alive call.
    x["fu_date"] = last_alive
    any_conn = pd.concat([s["connected"].eq(True) for s in fus], axis=1).any(axis=1)
    x["fu_connected"] = any_conn.astype("boolean").where(attempted)
    for col in ("fu_respondent", "fu_collector", "fu_collector_name", "death_place_type", "death_facility",
                "death_factor_other_text", "asha_visit"):
        x[col] = pd.Series(pd.NA, index=idx, dtype=object)
    factors = [[] for _ in range(len(x))]
    for s in fus:
        alive_here = alive_dates[s["name"]].notna() & alive_dates[s["name"]].eq(last_alive)
        died_here = s["status"].eq("Dead").fillna(False)
        use = (died_here | alive_here) & x["fu_respondent"].isna()
        x.loc[use, "fu_respondent"] = s["respondent"][use]
        x.loc[use, "fu_collector"] = s["collector"][use]
        x.loc[use, "fu_collector_name"] = s["collector_name"][use]
        x.loc[use, "asha_visit"] = s["asha_visit"][use]
        x.loc[died_here & x["fu_date"].isna(), "fu_date"] = s["date"][died_here & x["fu_date"].isna()]
    for s in [s for s in src if "place" in s]:
        place = s["place"].map({"Public health facility": "Public facility", "Private health facility": "Private facility",
                                "Home": "Home", "On the way": "On the way", "Outside District": "Outside district",
                                "Outside district": "Outside district"})
        fill = x["death_place_type"].isna() & place.notna() & any_dead
        x.loc[fill, "death_place_type"] = place[fill]
        if "place_pub" in s:
            pub = s["place_pub"].where(s["place_pub"].ne("Other"))
            name = H.facility(pub).where(place.eq("Public facility")).fillna(s["place_pvt"].where(place.eq("Private facility")))
            fill = x["death_facility"].isna() & name.notna() & any_dead
            x.loc[fill, "death_facility"] = name[fill]
        flist, ftxt = s["factors"](np.flatnonzero(any_dead.to_numpy()))
        for i, f in flist.items():
            factors[i] = sorted(set(factors[i]) | f)
        fill = x["death_factor_other_text"].isna() & ftxt.notna()
        x.loc[fill, "death_factor_other_text"] = ftxt[fill]
    x["death_factors"] = factors
    main = fus[0]
    x["fu_sex"] = main["fu_sex"]
    x["fu_bw"] = main["fu_bw"]
    x["death_reported_after_d28"] = False
    x["status_detail"] = _status_trail(src)


_SOURCE_LABELS = {"notification": "Notification", "registration": "Registration", "followup3": "Day-28 call",
                  "followup2": "Day-28 call (set 2)", "followup1": "Day-28 call (set 1)"}


def _status_trail(src) -> pd.Series:
    """What each form said, e.g. 'Registration: Alive on 02-03-2025; Day-28 call: Dead on 05-04-2025, died 20-03-2025'."""
    parts = []
    for s in src:
        txt = s["status"].astype("string")
        if s["connected"] is not None:
            txt = txt.fillna(s["connected"].map({False: "not connected"}).astype("string"))
        on = (" on " + s["date"].dt.strftime("%d-%m-%Y")).astype("string").fillna("")
        died = (", died " + s["dod"].dt.strftime("%d-%m-%Y")).astype("string").fillna("")
        parts.append((_SOURCE_LABELS[s["name"]] + ": " + txt + on + died).where(txt.notna()))
    return pd.concat(parts, axis=1).apply(lambda r: "; ".join(v for v in r if isinstance(v, str)), axis=1)
