"""Generate and classify one simulated bedside sample."""
from ward_patrol_vitals_mqtt.vitals_mqtt import VitalsAnalyzer, VitalsGenerator


class SimulatedVitals:
    def __init__(self, config):
        self.generator = VitalsGenerator(config)
        self.analyzer = VitalsAnalyzer(config)

    def sample(self, request):
        sample = self.generator.generate(request['bed_id'], seq=request['seq'])
        verdict = self.analyzer.analyze(sample['vitals'], sample['scenario'])
        return dict(request, vitals=sample['vitals'], verdict=verdict)
