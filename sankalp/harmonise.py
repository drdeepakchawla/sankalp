"""Shared cleaning helpers: dates, numbers, phones, blocks, facilities and bands."""
import re

import numpy as np
import pandas as pd

from . import config as C

_BLOCK_ALIASES = {
    "barwah": "Barwah", "barwaha": "Barwah",
    "bhagwanpura": "Bhagwanpura",
    "bhikangaon": "Bhikangaon", "bhikangonn": "Bhikangaon", "bhikagaon": "Bhikangaon",
    "gogaon": "Gogaon", "gogoan": "Gogaon", "gogawa": "Gogaon",
    "jhirniya": "Jhirniya", "jhirnya": "Jhirniya", "zirniya": "Jhirniya",
    "kasrawad": "Kasrawad", "kasrwad": "Kasrawad",
    "khargone": "Khargone",
    "maheshwar": "Maheshwar", "maheswar": "Maheshwar",
    "segaon": "Segaon", "seagaon": "Segaon", "seagoan": "Segaon", "segoan": "Segaon",
    "outofdistrict": C.OUT_OF_DISTRICT, "notausualresidentofdistrict": C.OUT_OF_DISTRICT,
}


def to_date(s: pd.Series, dayfirst: bool = False) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", dayfirst=dayfirst, format="mixed").dt.normalize()


def to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype("string").str.strip(), errors="coerce")


def clean_text(s: pd.Series) -> pd.Series:
    return s.astype("string").str.replace(r"\s+", " ", regex=True).str.strip().replace("", pd.NA)


def phone10(s: pd.Series) -> pd.Series:
    """Last 10 digits of an Indian mobile number, or NA if not a plausible mobile."""
    d = s.astype("string").str.replace(r"\D", "", regex=True).str[-10:]
    one_digit = d.map(lambda v: isinstance(v, str) and len(set(v)) == 1, na_action="ignore")
    ok = d.str.fullmatch(r"[6-9]\d{9}").fillna(False) & ~one_digit.fillna(False).astype(bool)
    return d.where(ok)


def block(s: pd.Series) -> pd.Series:
    key = s.astype("string").str.lower().str.replace(r"[^a-z]", "", regex=True)
    return key.map(_BLOCK_ALIASES).fillna(C.UNKNOWN).astype(str)


_FAC_TYPES = {"DH": "DH", "SDH": "SDH", "CH": "SDH", "CHC": "CHC", "PHC": "PHC", "SHC": "SHC"}
_FAC_NAME_ALIASES = {"chouli": "Choli", "zirniya": "Zirniya", "jhiranya": "Zirniya",
                     "bhikkangaon": "Bhikangaon", "khargaone": "Khargone"}


def facility(s: pd.Series) -> pd.Series:
    """Canonical public facility name, e.g. 'Jhirnya-CHC-Zirniya' / 'CHC- Zirniya' -> 'CHC Zirniya'."""
    def one(v):
        if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
            return pd.NA
        t = str(v).strip()
        m = re.search(r"\b(SDH|DH|CHC|CH|PHC|SHC)\b\s*-?\s*(.+)$", t, flags=re.I)
        if not m:
            return t
        typ = _FAC_TYPES[m.group(1).upper()]
        name = re.sub(r"\s+", " ", m.group(2)).strip(" -")
        name = _FAC_NAME_ALIASES.get(name.lower().replace(" ", ""), name.title())
        return f"{typ} {name}"
    return s.map(one).astype("string")


def band(values: pd.Series, bands, missing_label: str) -> pd.Series:
    out = pd.Series(missing_label, index=values.index, dtype=object)
    for label, lo, hi in bands:
        out[(values >= lo) & (values < hi)] = label
    return out


def age_band(age_days: pd.Series) -> pd.Series:
    out = pd.Series(pd.NA, index=age_days.index, dtype=object)
    for label, lo, hi in C.AGE_AT_DEATH_BANDS:
        out[(age_days >= lo) & (age_days <= hi)] = label
    return out


def code_people(*cols: pd.Series, prefix: str) -> list[pd.Series]:
    """Replace staff names/IDs with stable codes (DC01, DC02 ... by frequency)."""
    allv = pd.concat([c.dropna() for c in cols])
    order = allv.value_counts().index
    mapping = {v: f"{prefix}{i + 1:02d}" for i, v in enumerate(order)}
    return [c.map(mapping).astype("string") for c in cols]


def sex(s: pd.Series) -> pd.Series:
    k = s.astype("string").str.strip().str.lower()
    m = {"male": "Male", "m": "Male", "1": "Male", "female": "Female", "f": "Female", "2": "Female",
         "ambiguous": "Ambiguous", "a": "Ambiguous"}
    return k.map(m).fillna(C.UNKNOWN).astype(str)
