"""De-identified, compact export for the published dashboard.

Kept: REDCap Record ID / SNCU admission ID (for looking records up), month of birth,
block, facility, clinical and outcome fields, coded staff IDs.
Dropped: names, phone numbers, village, GP/ward, exact dates, free text.
"""
import base64
import gzip
import json

import pandas as pd

from . import quality as Q

FACTOR_LIST = ["Prematurity", "Low birth weight", "Infection/sepsis", "Birth asphyxia", "Respiratory distress",
               "Birth defect/anomaly", "Injury", "Diarrhoea", "Jaundice", "Aspiration/feeding", "Hypothermia",
               "Other", "Unknown"]
BABY_FLAGS = list(Q.BABY_CHECKS)
SNCU_FLAGS = list(Q.SNCU_CHECKS)


def _cat(s: pd.Series):
    s = s.astype("object").where(s.notna(), None)
    d = sorted({v for v in s if v is not None}, key=str)
    pos = {v: i for i, v in enumerate(d)}
    return {"t": "c", "d": d, "v": [pos[v] if v is not None else -1 for v in s]}


def _num(s: pd.Series, digits=0):
    s = pd.to_numeric(s, errors="coerce")
    return {"t": "n", "v": [None if pd.isna(v) else (round(float(v), digits) if digits else int(round(v))) for v in s]}


def _bits(lists, vocab):
    pos = {v: i for i, v in enumerate(vocab)}
    if len(vocab) > 31:
        raise ValueError("bitmask supports at most 31 codes")
    return {"t": "n", "v": [sum(1 << pos[x] for x in set(l) if x in pos) for l in lists]}


def baby_table(b: pd.DataFrame) -> dict:
    return {
        "rid": {"t": "s", "v": b["record_id"].astype(str).tolist()},
        "bn": _num(b["baby_no"]),
        "period": _cat(b["period"]),
        "month": _cat(b["dob_month"]),
        "block": _cat(b["res_block"]),
        "res_type": _cat(b["res_type"]),
        "place": _cat(b["birth_place_type"]),
        "facility": _cat(b["birth_facility"]),
        "delivery": _cat(b["delivery_type"]),
        "plurality": _cat(b["plurality"]),
        "sex": _cat(b["sex"]),
        "bw": _num(b["bw_g"]),
        "bw_band": _cat(b["bw_band"]),
        "ga": _num(b["ga_wk"]),
        "ga_band": _cat(b["ga_band"]),
        "preterm": _cat(b["preterm"].map({True: "Preterm", False: "Term"})),
        "born_sick": _num(b["born_sick"].fillna(False).astype(int)) if "born_sick" in b else None,
        "outcome": _cat(b["outcome"]),
        "lb": _num(b["live_born"].astype(int)),
        "sb": _num(b["stillborn"].astype(int)),
        "known": _num(b["outcome_known"].astype(int)),
        "nnd": _num(b["nnd"].astype(int)),
        "early": _num(b["early_nnd"].astype(int)),
        "age_death": _num(b["age_death_days"].where(b["nnd"] | b["outcome"].eq("Died after day 27"))),
        "death_age": _cat(b["death_age_band"]),
        "death_place": _cat(b["death_place_type"].where(b["nnd"])),
        "death_facility": _cat(b["death_facility"].where(b["nnd"])),
        "factors": _bits(b["death_factors"], FACTOR_LIST),
        "fu_days": _num(b["fu_days"]),
        "fu_by": _cat(b["fu_respondent"].replace({"Hospital record (choose this option only if death in hospital)": "Hospital record"})),
        "reg_staff": _cat(b["reg_collector"]),
        "fu_staff": _cat(b["fu_collector"]),
        "caste": _cat(b["caste"]),
        "religion": _cat(b["religion"]),
        "source": _cat(b["birth_info_source"]),
        "sncu_n": _num(b["sncu_n"]),
        "sncu_outcome": _cat(b["sncu_outcome"]),
        "sncu_cod": _cat(b["sncu_cod"]),
        "sncu_ind": _cat(b["sncu_indication"]),
        "sncu_dx": _cat(b["sncu_dx"]),
        "sncu_type": _cat(b["sncu_type"]),
        "mother_died": _num(b["mother_died"].fillna(False).astype(int)),
        "flags": _bits(b["flags"], BABY_FLAGS),
    }


def sncu_table(s: pd.DataFrame, baby_pos: pd.Series) -> dict:
    return {
        "aid": {"t": "s", "v": s["admission_id"].fillna("").astype(str).tolist()},
        "month": _cat(s["adm_month"]),
        "block": _cat(s["res_block"]),
        "sex": _cat(s["sex"]),
        "type": _cat(s["admission_type"]),
        "pod": _cat(s["place_of_delivery"]),
        "transport": _cat(s["transport"]),
        "maturity": _cat(s["maturity"]),
        "ga": _num(s["ga_wk"]),
        "ga_band": _cat(s["ga_band"]),
        "bw": _num(s["bw_g"]),
        "bw_band": _cat(s["bw_band"]),
        "age_adm": _num(s["age_at_adm_days"]),
        "indication": _cat(s["indication"]),
        "outcome": _cat(s["outcome"].fillna("Not recorded")),
        "los": _num(s["los_days"]),
        "dx": _cat(s["final_dx"]),
        "cod": _cat(s["cause_of_death"]),
        "ref_reason": _cat(s["referral_reason"]),
        "age_death": _num(s["age_at_death_days"]),
        "caste": _cat(s["caste"]),
        "resus": _cat(s["resuscitation"]),
        "link_tier": _num(s["link_tier"].fillna(0)),
        "baby": _num(s["baby_uid"].map(baby_pos)),
        "flags": _bits(s["flags"], SNCU_FLAGS),
    }


def payload(babies: pd.DataFrame, sncu: pd.DataFrame, meta: dict) -> dict:
    pos = pd.Series(range(len(babies)), index=babies["baby_uid"])
    return {
        "meta": meta,
        "factors": FACTOR_LIST,
        "baby_flags": [{"code": k, "severity": v[0], "label": v[1], "help": v[2]} for k, v in Q.BABY_CHECKS.items()],
        "sncu_flags": [{"code": k, "severity": v[0], "label": v[1], "help": v[2]} for k, v in Q.SNCU_CHECKS.items()],
        "babies": {k: v for k, v in baby_table(babies).items() if v is not None},
        "sncu": sncu_table(sncu, pos),
    }


def encode(obj: dict) -> str:
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.b64encode(gzip.compress(raw, 9)).decode()
