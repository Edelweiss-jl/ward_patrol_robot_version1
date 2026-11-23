"""Generate and classify one simulated bedside sample."""
from ward_patrol_vitals_mqtt.vitals_mqtt import VitalsAnalyzer, VitalsGenerator


def bed_check_without_vitals(request):
    status = request.get('bed_status')
    if status in ('vacant', 'unrecorded'):
        return dict(request, verdict=dict(status=status))
    return None


class SimulatedVitals:
    def __init__(self, config):
        self.generator = VitalsGenerator(config)
        self.analyzer = VitalsAnalyzer(config)

    def sample(self, request):
        result = bed_check_without_vitals(request)
        if result is not None:
            return result
        sample = self.generator.generate(request['bed_id'], seq=request['seq'],
                                         profile=request.get('profile'))
        verdict = self.analyzer.analyze(sample['vitals'], sample['scenario'])
        result = {key: value for key, value in request.items() if key != 'profile'}
        return dict(result, vitals=sample['vitals'], verdict=verdict)
