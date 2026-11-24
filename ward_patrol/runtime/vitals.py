"""Generate and classify one simulated bedside sample."""
from ward_patrol_vitals_mqtt.vitals_mqtt import VitalsAnalyzer, VitalsGenerator


def bed_check_without_vitals(request):
    status = request.get('bed_status')
    if request.get('vacant'):
        reason = '患者待入住，跳过体征采样' if status == 'pending' else '空床，跳过体征采样'
        return dict(request, vitals={}, verdict=dict(status='vacant', abnormal=False,
                    reasons=[reason], score=None))
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
        profile = request.get('profile')
        sample = self.generator.generate(request['bed_id'], seq=request['seq'], profile=profile)
        verdict = self.analyzer.analyze(sample['vitals'], sample['scenario'], profile=profile)
        result = dict(request)
        if not (profile or {}).get('revision'):
            result.pop('profile', None)
        return dict(result, vitals=sample['vitals'], verdict=verdict)
