"""Published reference data used by the simulation."""
from math import floor, isfinite

NEWS2_SOURCE = 'https://www.rcplondon.ac.uk/media/ctulqqbn/news2-executive-summary_0.pdf'
PEDIATRIC_SOURCE = 'https://www.rch.org.au/clinicalguide/guideline_index/Normal_Ranges_for_Physiological_Variables/'
PULSE_SOURCE = 'https://www.cdc.gov/nchs/data/nhsr/nhsr041.pdf'

# NEWS2 chart, SpO2 scale 1. Each row gives inclusive upper limits and scores.
NEWS2_BANDS = {
    'respiratory_rate': ((8, 3), (11, 1), (20, 0), (24, 2), (None, 3)),
    'spo2': ((91, 3), (93, 2), (95, 1), (None, 0)),
    'systolic_bp': ((90, 3), (100, 2), (110, 1), (219, 0), (None, 3)),
    'heart_rate': ((40, 3), (50, 1), (90, 0), (110, 1), (130, 2), (None, 3)),
    'temperature': ((35.0, 3), (36.0, 1), (38.0, 0), (39.0, 1), (None, 2)),
}

# RCH table sampled by the most recent age row in months, through age 15.
PEDIATRIC_BANDS = (
    (0, (60, 95), (120, 170), (25, 60)),
    (3, (60, 105), (115, 170), (25, 60)),
    (6, (75, 105), (110, 170), (20, 55)),
    (12, (70, 105), (105, 150), (20, 45)),
    (24, (70, 105), (95, 150), (20, 40)),
    (48, (75, 110), (80, 150), (17, 30)),
    (72, (80, 115), (75, 140), (16, 30)),
    (96, (80, 115), (70, 130), (16, 30)),
    (120, (85, 120), (60, 130), (15, 25)),
    (144, (90, 120), (65, 120), (15, 25)),
    (168, (90, 125), (60, 115), (14, 25)),
)
PEDIATRIC_METRICS = ('systolic_bp', 'heart_rate', 'respiratory_rate')

# NHANES tables 1–3, P5 to P95. The pooled table is used for unknown sex.
PULSE_BANDS = {
    'male': ((52, 92), (52, 89), (52, 90), (50, 91), (51, 94)),
    'female': ((58, 99), (57, 95), (56, 92), (56, 92), (59, 98)),
    'unknown': ((54, 95), (54, 92), (54, 91), (54, 91), (54, 98)),
}


def age_in_months(profile):
    years = profile.get('age')
    return profile.get('age_months', years * 12 if type(years) is int else None)


def pediatric_ranges(profile):
    age = age_in_months(profile)
    if type(age) is not int or not 0 <= age < 16 * 12:
        return None
    row = next(row for row in reversed(PEDIATRIC_BANDS) if age >= row[0])
    return dict(zip(PEDIATRIC_METRICS, row[1:]))


def resting_pulse_range(profile):
    age = age_in_months(profile)
    if type(age) is not int or age < 16 * 12:
        return None
    group = sum(age >= boundary * 12 for boundary in (20, 40, 60, 80))
    return PULSE_BANDS.get(profile.get('sex'), PULSE_BANDS['unknown'])[group]


def valid_reading(metric, value):
    if type(value) not in (int, float) or not 0 <= value or not isfinite(value):
        return False
    return metric != 'spo2' or value <= 100


def news2_points(metric, value):
    scale = 10 if metric == 'temperature' else 1
    reading = floor(value * scale + 0.5) / scale
    return next(points for limit, points in NEWS2_BANDS[metric] if limit is None or reading <= limit)
