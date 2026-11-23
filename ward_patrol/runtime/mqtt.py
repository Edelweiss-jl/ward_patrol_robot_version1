"""MQTT sampling transport and idempotent simulated vitals service."""
import json
from pathlib import Path
import time

from ward_patrol_vitals_mqtt.vitals_mqtt.config import load_config
from ward_patrol_vitals_mqtt.vitals_mqtt.mqtt_bus import MqttBus
from ward_patrol.runtime.vitals import SimulatedVitals


class SamplingService:
    def __init__(self, config=None, cache='outputs/vitals/samples.jsonl'):
        self.config = load_config(config)
        self.sampler = SimulatedVitals(self.config)
        self.cache = Path(cache)
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.results = {}
        if self.cache.exists():
            for line in self.cache.read_text(encoding='utf-8').splitlines():
                record = json.loads(line)
                self.results[record['sample_id']] = record
        self.bus = MqttBus(self.config, 'ward-sampling-service')
        self.bus.subscribe(self.config['topics']['arrival'], 1)
        self.bus.on(self.config['topics']['arrival'], self.handle)

    def handle(self, request):
        sample_id = request.get('sample_id')
        if not sample_id or not request.get('bed_id'):
            return
        result = self.results.get(sample_id)
        if result is None:
            result = self.sampler.sample(request)
            with self.cache.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(result, ensure_ascii=False)+'\n')
                stream.flush()
            self.results[sample_id] = result
        if any(result.get(key) != request.get(key) for key in ('run_id','task_id','attempt_id','bed_id','robot_id','source')):
            return
        self.bus.publish(self.config['topics']['status'], result, qos=1)


class SamplingLink:
    def __init__(self, core, config=None):
        self.core = core
        self.last_retry = time.monotonic()
        self.config = load_config(config)
        (core.directory/'mqtt_config.json').write_text(json.dumps(self.config,ensure_ascii=False),encoding='utf-8')
        self.bus = MqttBus(self.config, 'ward-'+core.run_id)
        self.bus.subscribe(self.config['topics']['status'], 1)
        self.bus.on(self.config['topics']['status'], self.receive)
        try:
            self.bus.connect()
        except Exception:
            self.bus.close()
            raise

    def receive(self, payload):
        if payload.get('run_id') == self.core.run_id:
            self.core.submit(dict(action='receipt', payload=payload))

    def flush(self):
        if time.monotonic()-self.last_retry >= 2:
            queued = {request['sample_id'] for request in self.core.outbox}
            for sample_id, sample in self.core.samples.items():
                if not sample['accepted'] and sample_id not in queued:
                    task_id=sample['request']['task_id']
                    task=next((t for t in self.core.tasks if t.task_id==task_id),None)
                    current=task is None or (task.status=='assigned' and sample['request']['attempt_id']==task_id+'-A'+str(self.core.attempts.get(task_id,1)))
                    if current:
                        self.core.outbox.append(sample['request'])
            self.last_retry=time.monotonic()
        while self.core.outbox:
            request = self.core.outbox[0]
            result = self.bus.publish(self.config['topics']['arrival'], request, qos=1)
            if result.rc:
                break
            self.core.outbox.pop(0)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--cache', default='outputs/vitals/samples.jsonl')
    args = parser.parse_args()
    service = SamplingService(args.config, args.cache)
    try:
        service.bus.connect().loop_forever()
    finally:
        service.bus.close()


if __name__ == '__main__':
    main()
