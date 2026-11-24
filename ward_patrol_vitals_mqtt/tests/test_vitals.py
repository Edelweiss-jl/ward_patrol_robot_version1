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
    def test_routine_samples_match_their_reference(self):
        gen = VitalsGenerator(cfg_with(abnormal_rate=0.0))
        analyzer = VitalsAnalyzer(CFG)
        for profile in ({}, {"age_months": 6}, {"age_months": 96},
                        {"age_months": 37 * 12, "sex": "female"}):
            for seq in range(30):
                sample = gen.generate("N1-1", seq=seq, profile=profile)
                verdict = analyzer.analyze(sample["vitals"], profile=profile)
                self.assertEqual(verdict["status"], "normal", (profile, seq, verdict))

    def test_same_bed_is_reproducible(self):
        gen = VitalsGenerator(CFG)
        self.assertEqual(gen.generate("N1-1", seq=1)["vitals"],
                         gen.generate("N1-1", seq=1)["vitals"])

    def test_severe_simulated_scenarios_trigger_an_alert(self):
        generator = VitalsGenerator(CFG)
        analyzer = VitalsAnalyzer(CFG)
        for scenario in CFG["generator"]["scenarios"]:
            for profile in ({}, {"age_months": 96}):
                with self.subTest(scenario=scenario, profile=profile):
                    sample = generator.generate("X1", seq=3, abnormal=True, critical=True,
                                                scenario=scenario, profile=profile)
                    verdict = analyzer.analyze(sample["vitals"], scenario, profile=profile)
                    self.assertTrue(verdict["abnormal"])
                    self.assertTrue(verdict["reasons"])

    def test_age_changes_baseline_and_diagnosis_weights_matching_scenario(self):
        gen = VitalsGenerator(CFG)

        def samples(profile, abnormal):
            return [gen.generate("B1", seq, abnormal=abnormal, profile=profile) for seq in range(200)]

        young = samples({"age": 8}, False)
        older = samples({"age": 75}, False)
        self.assertGreater(sum(row["vitals"]["heart_rate"] for row in young),
                           sum(row["vitals"]["heart_rate"] for row in older))
        self.assertGreater(sum(row["vitals"]["systolic_bp"] for row in older),
                           sum(row["vitals"]["systolic_bp"] for row in young))
        diagnosed = samples({"diagnosis": "高血压"}, True)
        baseline = samples({"diagnosis": "否认高血压"}, True)
        self.assertGreater(sum(row["scenario"] == "hypertension" for row in diagnosed),
                           sum(row["scenario"] == "hypertension" for row in baseline))
        repeated = samples({"diagnosis": "高血压"}, True)
        self.assertEqual([row["vitals"] for row in diagnosed], [row["vitals"] for row in repeated])


class AnalyzerTest(unittest.TestCase):
    def setUp(self):
        self.analyzer = VitalsAnalyzer(CFG)

    def evaluate(self, profile=None, **overrides):
        vitals = dict(heart_rate=70, spo2=97, systolic_bp=120,
                      diastolic_bp=75, respiratory_rate=17, temperature=37)
        return self.analyzer.analyze(dict(vitals, **overrides), profile=profile)

    def test_news2_bands_and_escalation(self):
        for overrides, score, status in (
            ({}, 0, "normal"),
            ({"heart_rate": 91}, 1, "observe"),
            ({"spo2": 91}, 3, "warning"),
            ({"systolic_bp": 90}, 3, "warning"),
            ({"spo2": 92, "respiratory_rate": 21, "heart_rate": 110}, 5, "warning"),
            ({"spo2": 91, "respiratory_rate": 21, "heart_rate": 111}, 7, "critical"),
            ({"diastolic_bp": 100}, 0, "normal"),
        ):
            with self.subTest(overrides=overrides):
                verdict = self.evaluate(**overrides)
                self.assertEqual((verdict["score"], verdict["status"]), (score, status))

    def test_missing_values_and_pregnancy(self):
        for value in (None, float("nan"), 101):
            verdict = self.evaluate(spo2=value)
            self.assertEqual(verdict["status"], "unassessed")
            self.assertIsNone(verdict["score"])
        self.assertEqual(self.evaluate(spo2=None, systolic_bp=90)["status"], "warning")
        self.assertEqual(self.evaluate({"pregnant": True})["status"], "unassessed")

    def test_pediatric_and_sex_specific_reference(self):
        measurements = dict(heart_rate=125, respiratory_rate=27, systolic_bp=85)
        self.assertEqual(self.evaluate({"age_months": 24}, **measurements)["status"], "normal")
        self.assertEqual(self.evaluate({"age_months": 144}, **measurements)["status"], "warning")
        male = self.evaluate({"age_months": 25 * 12, "sex": "male"}, heart_rate=90)
        female = self.evaluate({"age_months": 25 * 12, "sex": "female"}, heart_rate=90)
        self.assertEqual(male["score"], female["score"])
        self.assertTrue(male["findings"][0]["outside_reference"])
        self.assertFalse(female["findings"][0]["outside_reference"])


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
