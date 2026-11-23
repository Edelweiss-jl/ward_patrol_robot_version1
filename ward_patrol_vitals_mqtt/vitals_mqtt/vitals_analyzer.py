"""体征异常判定：逐项比对正常区间，给出等级、原因与床位颜色。

等级：normal（正常）/ warning（预警）/ critical（危急）。
warning 与 critical 都算异常，床位标红（预警亮红、危急深红）。
"""

from __future__ import annotations

from . import protocol
from .config import color_for


def _fmt(spec, value):
    d = int(spec.get("decimals", 0))
    return f"{value:.{d}f}" if d else str(int(round(value)))


class VitalsAnalyzer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.metrics = cfg["metrics"]

    def classify(self, value, spec):
        """单项判定：超出危急界为 critical，超出正常界为 warning。"""
        if value is None:
            return "normal"
        lo, hi = float(spec["normal"][0]), float(spec["normal"][1])
        if value < float(spec["critical_below"]) or value > float(spec["critical_above"]):
            return "critical"
        if value < lo or value > hi:
            return "warning"
        return "normal"

    @staticmethod
    def _combine(level_a, level_b):
        return level_a if protocol.LEVEL_ORDER[level_a] >= protocol.LEVEL_ORDER[level_b] else level_b

    def analyze(self, vitals, scenario="routine"):
        """返回判定结果字典，可直接交给 protocol.status_message。"""
        findings = []
        reasons = []
        status = "normal"

        for key, spec in self.metrics.items():
            value = vitals.get(key)
            level = self.classify(value, spec)
            lo, hi = spec["normal"]
            item = {
                "metric": key,
                "label": spec.get("label", key),
                "value": value,
                "unit": spec.get("unit", ""),
                "normal": [lo, hi],
                "status": level,
            }
            findings.append(item)
            status = self._combine(status, level)
            if level != "normal":
                shown = _fmt(spec, value) if value is not None else "-"
                direction = "高于" if value is not None and value > hi else "低于"
                tag = "危急" if level == "critical" else "预警"
                reasons.append(
                    f"{spec.get('label', key)} {shown}{spec.get('unit', '')}"
                    f"{direction}正常范围 {lo}~{hi}（{tag}）"
                )

        return {
            "status": status,
            "abnormal": status in protocol.ABNORMAL_LEVELS,
            "color": color_for(self.cfg, status),
            "reasons": reasons,
            "findings": findings,
            "vitals": dict(vitals),
            "scenario": scenario,
        }
