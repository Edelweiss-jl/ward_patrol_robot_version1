"""模拟体征生成：心率、血氧、血压（收缩/舒张）、呼吸频率、体温。

正常值按用户给定的区间采样：
心率 60~100 bpm、血氧 95~100%、收缩压 90~139 mmHg、
舒张压 60~89 mmHg、呼吸 16~20 次/分、体温 36.0~37.0 ℃。

异常不是逐项随机抖动，而是按临床情景成组出现（低氧、高血压、
发热、心动过缓、低血压），这样多个指标之间有关联，判定结果更可信。
"""

from __future__ import annotations

import random
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

    def _normal(self, spec, rng):
        lo, hi = spec["normal"]
        value = rng.uniform(float(lo), float(hi))
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
                 abnormal=None, critical=None, scenario=None):
        """生成一次采样，返回 protocol.vitals_message 格式的消息。

        abnormal / critical / scenario 可显式指定，便于演示与测试；
        不指定时按配置的异常率抽取。
        """
        seq = int(seq)
        rng = self._rng(bed_id, seq)
        chosen_scenario = "routine"
        touched = {}

        if abnormal is None:
            abnormal = rng.random() < self.abnormal_rate
        if abnormal:
            if critical is None:
                critical = rng.random() < self.critical_ratio
            pool = [s for s in self.scenarios if s in SCENARIOS]
            chosen_scenario = scenario if scenario in SCENARIOS else rng.choice(pool or ["hypoxia"])
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
            vitals[key] = touched.get(key) if key in touched else self._normal(spec, rng)

        return protocol.vitals_message(bed_id, vitals, chosen_scenario,
                                       robot_id=robot_id, seq=seq, sim_time=sim_time)
