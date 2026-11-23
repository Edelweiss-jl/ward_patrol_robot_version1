"""模拟体征生成：心率、血氧、血压（收缩/舒张）、呼吸频率、体温。

正常值按用户给定的区间采样：
心率 60~100 bpm、血氧 95~100%、收缩压 90~139 mmHg、
舒张压 60~89 mmHg、呼吸 16~20 次/分、体温 36.0~37.0 ℃。

异常不是逐项随机抖动，而是按临床情景成组出现（低氧、高血压、
发热、心动过缓、低血压），这样多个指标之间有关联，判定结果更可信。
"""

from __future__ import annotations

import random
import re
import zlib

from . import protocol

# 情景 -> 受影响的指标。severe 表示沿用本次抽到的严重度，mild 固定为预警。
SCENARIOS = {
    "hypoxia": [("spo2", "low", "severe"),
                ("heart_rate", "high", "mild"),
                ("respiratory_rate", "high", "mild")],
    "hypertension": [("systolic_bp", "high", "severe"),
                     ("diastolic_bp", "high", "mild")],
    "fever": [("temperature", "high", "severe"),
              ("heart_rate", "high", "mild"),
              ("respiratory_rate", "high", "mild")],
    "bradycardia": [("heart_rate", "low", "severe")],
    "hypotension": [("systolic_bp", "low", "severe"),
                    ("diastolic_bp", "low", "mild")],
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
    age = profile.get("age")
    shifts = {}
    if type(age) is int and 0 <= age < 13:
        shifts.update(heart_rate=.25, respiratory_rate=.25, systolic_bp=-.2, diastolic_bp=-.15)
    elif type(age) is int and 65 <= age <= 130:
        shifts.update(systolic_bp=.2, spo2=-.15)
    for scenario in sorted(scenarios):
        for key, direction, _ in SCENARIOS[scenario]:
            shift = .18 if direction == "high" else -.18
            shifts[key] = shifts.get(key, 0) + shift
    return {key: min(.95, max(.05, .5 + shift)) for key, shift in shifts.items()}


def _decimals(spec):
    return int(spec.get("decimals", 0))


def _step(spec):
    """最小可分辨间隔：整数型指标为 1，带小数的为其精度。"""
    d = _decimals(spec)
    return 1 if d <= 0 else 10 ** -d


def _round(spec, value):
    return round(value, _decimals(spec))


class VitalsGenerator:
    """按床位生成一组体征；同一床位可复现（seed + 床位号 + 序号）。"""

    def __init__(self, cfg):
        self.cfg = cfg
        gen = cfg.get("generator", {})
        self.abnormal_rate = float(gen.get("abnormal_rate", 0.3))
        self.critical_ratio = float(gen.get("critical_ratio", 0.35))
        self.seed = gen.get("seed")
        self.scenarios = list(gen.get("scenarios") or SCENARIOS.keys())
        self.metrics = cfg["metrics"]

    # 同一床位的随机流互不干扰：用床位名做稳定散列，不用内置 hash。
    def _rng(self, bed_id, seq):
        base = int(self.seed) if self.seed is not None else 0
        return random.Random(base + zlib.crc32(str(bed_id).encode("utf-8")) + int(seq) * 7919)

    def _normal(self, spec, rng, mode=None):
        lo, hi = map(float, spec["normal"])
        value = rng.uniform(lo, hi) if mode is None else rng.triangular(lo, hi, lo + (hi - lo) * mode)
        return _round(spec, value)

    def _band(self, spec, direction, critical):
        """返回 (下界, 上界)；区间无效时返回 None（如血氧不会偏高）。"""
        lo_n, hi_n = float(spec["normal"][0]), float(spec["normal"][1])
        step = _step(spec)
        span = max((hi_n - lo_n) * 0.4, step * 3)
        if direction == "high":
            top = float(spec["critical_above"])
            warn = (hi_n + step, top - step)
            crit = (top, top + span)
        else:
            bottom = float(spec["critical_below"])
            warn = (bottom + step, lo_n - step)
            crit = (max(0.0, bottom - span), bottom - step)
        lo, hi = crit if critical else warn
        if hi <= lo:
            return (lo, lo) if hi == lo else None
        return (lo, hi)

    def _abnormal_value(self, spec, direction, critical, rng):
        band = self._band(spec, direction, critical)
        if band is None:
            return None
        lo, hi = band
        return _round(spec, rng.uniform(lo, hi))

    def generate(self, bed_id, seq=0, robot_id=None, sim_time=None,
                 abnormal=None, critical=None, scenario=None, profile=None):
        """生成一次采样，返回 protocol.vitals_message 格式的消息。

        abnormal / critical / scenario 可显式指定，便于演示与测试；
        提供患者年龄和诊断时，调整正常区间内的取值与异常情景的采样权重。
        """
        seq = int(seq)
        rng = self._rng(bed_id, seq)
        profile = profile if isinstance(profile, dict) else {}
        pool = [s for s in self.scenarios if s in SCENARIOS] or ["hypoxia"]
        matching = _diagnosis_scenarios(profile).intersection(pool)
        modes = _normal_modes(profile, matching)
        chosen_scenario = "routine"
        touched = {}

        if abnormal is None:
            rate = self.abnormal_rate
            if matching:
                rate = 2 * rate / (1 + rate)
            abnormal = rng.random() < rate
        if abnormal:
            if critical is None:
                critical = rng.random() < self.critical_ratio
            if scenario in SCENARIOS:
                chosen_scenario = scenario
            elif matching:
                chosen_scenario = rng.choices(pool, weights=[8 if s in matching else 1 for s in pool])[0]
            else:
                chosen_scenario = rng.choice(pool)
            for key, direction, severity in SCENARIOS[chosen_scenario]:
                spec = self.metrics.get(key)
                if spec is None:
                    continue
                value = self._abnormal_value(spec, direction, critical and severity == "severe", rng)
                # 预警档区间可能为空（例如血氧偏高），此时退回正常值。
                if value is not None:
                    touched[key] = value

        vitals = {}
        for key, spec in self.metrics.items():
            vitals[key] = touched[key] if key in touched else self._normal(spec, rng, modes.get(key))

        return protocol.vitals_message(bed_id, vitals, chosen_scenario,
                                       robot_id=robot_id, seq=seq, sim_time=sim_time)
