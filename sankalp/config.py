"""Definitions used across the pipeline. Change them here, not in the code."""

# Neonatal death = live-born baby who died at age 0-27 completed days (WHO).
# A death on the day the programme calls "day 28" (DOB + 28) is post-neonatal.
NEONATAL_MAX_AGE_DAYS = 27
EARLY_NEONATAL_MAX_AGE_DAYS = 6

# A day-28 follow-up is due once the baby is this many days old.
FOLLOWUP_DUE_DAYS = 28
# Follow-ups more than this many days after birth are flagged as late (recall risk).
FOLLOWUP_LATE_DAYS = 90

# Plausibility limits.
BW_MIN_G, BW_MAX_G = 400, 6000
GA_MIN_WK, GA_MAX_WK = 22, 44

# Two death dates for the same baby that differ by more than this are a conflict.
DEATH_DATE_TOLERANCE_DAYS = 2

BLOCKS = [
    "Barwah", "Bhagwanpura", "Bhikangaon", "Gogaon", "Jhirniya",
    "Kasrawad", "Khargone", "Maheshwar", "Segaon",
]
OUT_OF_DISTRICT = "Out of district"
UNKNOWN = "Unknown"

BW_BANDS = [  # (label, lower bound inclusive, upper bound exclusive)
    ("<1000 g", 0, 1000),
    ("1000-1499 g", 1000, 1500),
    ("1500-1999 g", 1500, 2000),
    ("2000-2499 g", 2000, 2500),
    ("2500-3999 g", 2500, 4000),
    (">=4000 g", 4000, 99999),
]
GA_BANDS = [
    ("<28 wk", 0, 28),
    ("28-31 wk", 28, 32),
    ("32-33 wk", 32, 34),
    ("34-36 wk", 34, 37),
    ("37-41 wk", 37, 42),
    (">=42 wk", 42, 99),
]
AGE_AT_DEATH_BANDS = [
    ("Day 0", 0, 0),
    ("Day 1", 1, 1),
    ("Day 2-6", 2, 6),
    ("Day 7-13", 7, 13),
    ("Day 14-27", 14, 27),
]

# Factors associated with newborn deaths (NHRP checkbox choices) -> short labels.
DEATH_FACTORS = {
    "Prematurity": "Prematurity",
    "Low Birth Weight": "Low birth weight",
    "Infection": "Infection/sepsis",
    "Birth Asphyxia": "Birth asphyxia",
    "Injury": "Injury",
    "Birth Defects": "Birth defect/anomaly",
    "Congenital Anomalies": "Birth defect/anomaly",
    "Diarrhoeal diseases": "Diarrhoea",
    "Unknown": "Unknown",
    "Other": "Other",
}
# Keyword rules that re-classify "Other, specify" free text into a factor.
OTHER_FACTOR_KEYWORDS = [
    (r"sepsis|infect|fever|pneumon|mening", "Infection/sepsis"),
    (r"asphyx|hie|not cr(y|ied)|roya nahi|meconium|\bmas\b", "Birth asphyxia"),
    (r"respirat|\brds\b|hmd|breath|saans", "Respiratory distress"),
    (r"preterm|prematur|pre ?mature", "Prematurity"),
    (r"lbw|low birth|weight", "Low birth weight"),
    (r"anomal|malform|defect|congenital|heart|dil", "Birth defect/anomaly"),
    (r"jaundice|hyperbili", "Jaundice"),
    (r"aspirat|choke|feed", "Aspiration/feeding"),
    (r"hypotherm|cold", "Hypothermia"),
]
