"""Evidence-based interpretation of simulated bedside observations."""
from .config import color_for
from .protocol import ABNORMAL_LEVELS
from .vitals_reference import (
    NEWS2_BANDS, NEWS2_SOURCE, PEDIATRIC_SOURCE, PULSE_SOURCE,
    news2_points, pediatric_ranges, resting_pulse_range, valid_reading,
)


class VitalsAnalyzer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.metrics = cfg['metrics']

    def analyze(self, vitals, scenario='routine', profile=None):
        profile = profile or {}
        pediatric = pediatric_ranges(profile)
        pregnant = profile.get('pregnant', False)
        rule, source = ('pregnancy_unassessed', None) if pregnant else (
            ('pediatric_reference', PEDIATRIC_SOURCE) if pediatric else ('news2', NEWS2_SOURCE))
        required = () if pregnant else (pediatric if pediatric else NEWS2_BANDS)
        findings, reasons, missing = [], [], []
        scores = []
        pulse_range = resting_pulse_range(profile)
        for key in dict.fromkeys((*self.metrics, *required)):
            spec = self.metrics.get(key, {})
            raw = vitals.get(key)
            value = raw if valid_reading(key, raw) else None
            label, unit = spec.get('label', key), spec.get('unit', '')
            item = dict(metric=key, label=label, value=value, unit=unit)
            if key == 'heart_rate' and pulse_range:
                item.update(reference=list(pulse_range), reference_source=PULSE_SOURCE)
                if value is not None:
                    item['outside_reference'] = not pulse_range[0] <= value <= pulse_range[1]
            if key in required:
                if value is None:
                    missing.append(label)
                elif pediatric:
                    lo, hi = pediatric[key]
                    item['reference'] = [lo, hi]
                    if not lo <= value <= hi:
                        reasons.append(f'{label} {value:g}{unit} 超出该年龄参考范围 {lo}–{hi}')
                else:
                    points = news2_points(key, value)
                    item['points'] = points
                    scores.append(points)
                    if points:
                        reasons.append(f'{label} {value:g}{unit}（{points} 分）')
            findings.append(item)

        score = None
        if pregnant:
            status = 'unassessed'
            reasons.append('妊娠期仿真资料，需采用产科专用评估')
        elif pediatric:
            status = 'warning' if reasons else 'unassessed' if missing else 'normal'
        else:
            total = sum(scores)
            score = None if missing else total
            if total >= 7:
                status = 'critical'
            elif total >= 5 or 3 in scores:
                status = 'warning'
            elif missing:
                status = 'unassessed'
            else:
                status = 'observe' if total else 'normal'
        if missing:
            reasons.append('有效测量缺失：' + '、'.join(missing))

        return dict(status=status, abnormal=status in ABNORMAL_LEVELS,
                    color=color_for(self.cfg, status), reasons=reasons,
                    findings=findings, vitals={item['metric']: item['value'] for item in findings},
                    scenario=scenario, rule=rule, source=source, score=score)
