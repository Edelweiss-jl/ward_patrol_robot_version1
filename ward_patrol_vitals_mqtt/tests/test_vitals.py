"""体征生成与判定的回归测试：python tests/run_tests.py"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vitals_mqtt import load_config  # noqa: E402
from vitals_mqtt import protocol  # noqa: E402
from vitals_mqtt.bed_registry import BedRegistry  # noqa: E402
from vitals_mqtt.vitals_analyzer import VitalsAnalyzer  # noqa: E402
from vitals_mqtt.vitals_generator import VitalsGenerator  # noqa: E402

CFG = load_config()


def cfg_with(**generator):
    cfg = load_config()
    cfg["generator"].update(generator)
    return cfg


class GeneratorTest(unittest.TestCase):
    def test_normal_sample_stays_in_ranges(self):
        gen = VitalsGenerator(cfg_with(abnormal_rate=0.0))
        for i in range(30):
            msg = gen.generate(f"BED-{i}", seq=i)
            for key, spec in CFG["metrics"].items():
                value = msg["vitals"][key]
                lo, hi = spec["normal"]
                self.assertGreaterEqual(value, lo, f"{key} below normal: {value}")
                self.assertLessEqual(value, hi, f"{key} above normal: {value}")

    def test_same_bed_is_reproducible(self):
        gen = VitalsGenerator(cfg_with(abnormal_rate=0.0))
        self.assertEqual(gen.generate("N1-1", seq=1)["vitals"],
                         gen.generate("N1-1", seq=1)["vitals"])

    def test_abnormal_scenarios_are_detected(self):
        analyzer = VitalsAnalyzer(CFG)
        for scenario in cfg_with()["generator"]["scenarios"]:
            for critical in (False, True):
                gen = VitalsGenerator(cfg_with(abnormal_rate=1.0))
                msg = gen.generate("X1", seq=3, abnormal=True, critical=critical, scenario=scenario)
                verdict = analyzer.analyze(msg["vitals"], msg["scenario"])
                self.assertTrue(verdict["abnormal"], f"{scenario}/{critical} not abnormal")
                self.assertEqual(verdict["status"], "critical" if critical else "warning",
                                 f"{scenario} unexpected status {verdict['status']}")
                self.assertGreater(len(verdict["reasons"]), 0)

    def test_abnormal_rate_controls_share(self):
        gen = VitalsGenerator(cfg_with(abnormal_rate=1.0, critical_ratio=0.0))
        analyzer = VitalsAnalyzer(CFG)
        abnormal = sum(analyzer.analyze(gen.generate(f"B{i}", seq=i)["vitals"])["abnormal"]
                       for i in range(40))
        self.assertEqual(abnormal, 40)

        gen2 = VitalsGenerator(cfg_with(abnormal_rate=0.0))
        abnormal = sum(analyzer.analyze(gen2.generate(f"B{i}", seq=i)["vitals"])["abnormal"]
                       for i in range(40))
        self.assertEqual(abnormal, 0)


class AnalyzerTest(unittest.TestCase):
    def setUp(self):
        self.analyzer = VitalsAnalyzer(CFG)

    def _metrics(self, **overrides):
        base = {key: sum(spec["normal"]) / 2 for key, spec in CFG["metrics"].items()}
        base.update(overrides)
        return base

    def test_all_normal(self):
        verdict = self.analyzer.analyze(self._metrics())
        self.assertEqual(verdict["status"], "normal")
        self.assertFalse(verdict["abnormal"])
        self.assertEqual(verdict["reasons"], [])

    def test_boundary_values(self):
        # 心率 60 与 100 都在正常区间内，101 才是预警
        self.assertEqual(self.analyzer.analyze(self._metrics(heart_rate=60))["status"], "normal")
        self.assertEqual(self.analyzer.analyze(self._metrics(heart_rate=100))["status"], "normal")
        self.assertEqual(self.analyzer.analyze(self._metrics(heart_rate=101))["status"], "warning")
        # 预警上限 110，超过才进危急
        self.assertEqual(self.analyzer.analyze(self._metrics(heart_rate=110))["status"], "warning")
        self.assertEqual(self.analyzer.analyze(self._metrics(heart_rate=111))["status"], "critical")
        # 血氧 95 正常，94.9 预警，89 危急
        self.assertEqual(self.analyzer.analyze(self._metrics(spo2=95))["status"], "normal")
        self.assertEqual(self.analyzer.analyze(self._metrics(spo2=94.9))["status"], "warning")
        self.assertEqual(self.analyzer.analyze(self._metrics(spo2=89))["status"], "critical")

    def test_blood_pressure_counts_as_two_fields(self):
        verdict = self.analyzer.analyze(self._metrics(systolic_bp=150, diastolic_bp=95))
        self.assertEqual(verdict["status"], "warning")
        self.assertEqual(len(verdict["reasons"]), 2)

    def test_critical_wins_over_warning(self):
        verdict = self.analyzer.analyze(self._metrics(heart_rate=101, spo2=88))
        self.assertEqual(verdict["status"], "critical")

    def test_abnormal_color_is_red(self):
        for status in ("warning", "critical"):
            color = self.analyzer.analyze(self._metrics(spo2=88))["color"] if status == "critical" \
                else self.analyzer.analyze(self._metrics(heart_rate=105))["color"]
            self.assertGreater(color[0], color[1], f"{status} color is not red: {color}")
            self.assertGreater(color[0], color[2], f"{status} color is not red: {color}")


class RegistryTest(unittest.TestCase):
    def test_change_detection_and_summary(self):
        reg = BedRegistry()
        seen = []
        reg.add_listener(seen.append)
        reg.update("A", {"status": "normal", "abnormal": False})
        self.assertTrue(reg.update("A", {"status": "critical", "abnormal": True}))
        self.assertFalse(reg.update("A", {"status": "critical", "abnormal": True}))
        reg.update("B", {"status": "warning", "abnormal": True})
        # 每次写入都会通知监听者，变化与否只体现在返回值上
        self.assertEqual(len(seen), 4)
        summary = reg.summary()
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["abnormal"], 2)
        self.assertEqual(sorted(reg.abnormal_beds()), ["A", "B"])


class ProtocolTest(unittest.TestCase):
    def test_round_trip(self):
        msg = protocol.arrival_message("N1-1", robot_id="R1", sim_time=12.345, seq=2)
        back = protocol.loads(protocol.dumps(msg))
        self.assertEqual(back["bed_id"], "N1-1")
        self.assertEqual(back["sim_time"], 12.345)
        self.assertIsNone(protocol.loads(b"not-json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
