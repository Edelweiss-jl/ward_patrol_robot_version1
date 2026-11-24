"""Reproducible synthetic bedside measurements and correlated scenarios."""
from __future__ import annotations

import random
import re
import zlib

from . import protocol
from .vitals_reference import age_in_months, pediatric_ranges, resting_pulse_range


ROUTINE = {
    'heart_rate': (60, 90), 'spo2': (96, 100), 'systolic_bp': (111, 135),
    'diastolic_bp': (60, 85), 'respiratory_rate': (12, 20), 'temperature': (36.1, 37.4),
}
# Each scenario has two simulation intensities. The analyzer assigns the actual level.
SCENARIOS = {
    'hypoxia': (
        dict(spo2=(92, 93), heart_rate=(91, 110), respiratory_rate=(21, 24)),
        dict(spo2=(85, 91), heart_rate=(111, 130), respiratory_rate=(25, 28))),
    'hypertension': (
        dict(systolic_bp=(160, 179), diastolic_bp=(90, 105)),
        dict(systolic_bp=(220, 230), diastolic_bp=(110, 125))),
    'fever': (
        dict(temperature=(38.1, 39.0), heart_rate=(91, 110), respiratory_rate=(21, 24)),
        dict(temperature=(39.1, 40.0), heart_rate=(111, 130), respiratory_rate=(25, 28))),
    'bradycardia': (
        dict(heart_rate=(41, 50)),
        dict(heart_rate=(30, 40))),
    'hypotension': (
        dict(systolic_bp=(91, 100), diastolic_bp=(45, 55)),
        dict(systolic_bp=(70, 90), diastolic_bp=(35, 49), heart_rate=(111, 130),
             respiratory_rate=(21, 24))),
}
PEDIATRIC_DIRECTIONS = {
    'hypoxia': dict(heart_rate=1, respiratory_rate=1),
    'fever': dict(heart_rate=1, respiratory_rate=1),
    'hypertension': dict(systolic_bp=1),
    'bradycardia': dict(heart_rate=-1),
    'hypotension': dict(systolic_bp=-1),
}

# 诊断关键词只用于选择模拟情景。体征范围和分级仍来自配置。
DIAGNOSIS_TERMS = {
    "hypoxia": ("低氧", "肺炎", "慢阻肺", "慢性阻塞性肺", "哮喘", "copd", "hypoxia", "pneumonia", "asthma"),
    "hypertension": ("高血压", "hypertension"),
    "fever": ("发热", "高热", "感染", "fever", "infection"),
    "bradycardia": ("心动过缓", "心率过缓", "bradycardia"),
    "hypotension": ("低血压", "hypotension"),
}


def _diagnosis_scenarios(profile):
    diagnosis = profile.get("diagnosis")
    if not isinstance(diagnosis, str):
        return set()
    clauses = re.split(r"[,，、;；。\n]+", diagnosis.casefold())
    positive = [part.strip() for part in clauses if part.strip()
                and not part.strip().startswith(("无", "否认", "排除", "no "))]
    return {scenario for scenario, terms in DIAGNOSIS_TERMS.items()
            if any(term in part for term in terms for part in positive)}


def _normal_modes(profile, scenarios):
    age = age_in_months(profile)
    shifts = {}
    if type(age) is int and 0 <= age < 13 * 12:
        shifts.update(heart_rate=.25, respiratory_rate=.25, systolic_bp=-.2, diastolic_bp=-.15)
    elif type(age) is int and 65 * 12 <= age <= 130 * 12:
        shifts.update(systolic_bp=.2, spo2=-.15)
    for scenario in sorted(scenarios):
        for key, band in SCENARIOS[scenario][0].items():
            shift = .18 if sum(band) > sum(ROUTINE[key]) else -.18
            shifts[key] = shifts.get(key, 0) + shift
    return {key: min(.95, max(.05, .5 + shift)) for key, shift in shifts.items()}


class VitalsGenerator:
    def __init__(self, cfg):
        gen = cfg.get('generator', {})
        self.abnormal_rate = float(gen.get('abnormal_rate', 0.3))
        self.critical_ratio = float(gen.get('critical_ratio', 0.35))
        self.seed = int(gen.get('seed') or 0)
        self.scenarios = [name for name in (gen.get('scenarios') or SCENARIOS) if name in SCENARIOS]
        self.metrics = cfg['metrics']

    def generate(self, bed_id, seq=0, robot_id=None, sim_time=None,
                 abnormal=None, critical=None, scenario=None, profile=None):
        seq = int(seq)
        rng = random.Random(self.seed + zlib.crc32(str(bed_id).encode('utf-8')) + seq * 7919)
        profile = profile if isinstance(profile, dict) else {}
        pool = self.scenarios or ['hypoxia']
        matching = _diagnosis_scenarios(profile).intersection(pool)
        modes = _normal_modes(profile, matching)
        pediatric = pediatric_ranges(profile)
        bands = dict(ROUTINE)
        if pediatric:
            bands.update(pediatric)
            bands['diastolic_bp'] = (35, 65)
        elif (pulse := resting_pulse_range(profile)):
            bands['heart_rate'] = (max(pulse[0], 51), min(pulse[1], 90))

        if abnormal is None:
            rate = self.abnormal_rate
            if matching:
                rate = 2 * rate / (1 + rate)
            abnormal = rng.random() < rate
        chosen = 'routine'
        if abnormal:
            if critical is None:
                critical = rng.random() < self.critical_ratio
            if scenario in SCENARIOS:
                chosen = scenario
            elif matching:
                chosen = rng.choices(pool, weights=[8 if name in matching else 1 for name in pool])[0]
            else:
                chosen = rng.choice(pool)
            deviations = dict(SCENARIOS[chosen][bool(critical)])
            if pediatric:
                for key in pediatric:
                    deviations.pop(key, None)
                for key, direction in PEDIATRIC_DIRECTIONS[chosen].items():
                    lo, hi = pediatric[key]
                    edge = hi if direction > 0 else lo
                    distance = 12 if critical else 4
                    deviations[key] = tuple(sorted((edge + direction, edge + direction * distance)))
            bands.update(deviations)

        vitals = {}
        for key, band in bands.items():
            if key in self.metrics:
                digits = 1 if key in ('spo2', 'temperature') else 0
                lo, hi = band
                mode = modes.get(key)
                value = rng.uniform(lo, hi) if mode is None else rng.triangular(lo, hi, lo + (hi - lo) * mode)
                vitals[key] = round(value, digits)
        if 'systolic_bp' in vitals and 'diastolic_bp' in vitals:
            vitals['diastolic_bp'] = min(vitals['diastolic_bp'], vitals['systolic_bp'] - 5)
        return protocol.vitals_message(bed_id, vitals, chosen, robot_id=robot_id,
                                       seq=seq, sim_time=sim_time)
