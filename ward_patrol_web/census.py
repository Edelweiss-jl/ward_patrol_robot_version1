"""Persistent bed occupancy keyed by physical bed within a map and floor."""
from datetime import datetime, timezone
import json
from uuid import uuid4


class OccupancyConflict(ValueError):
    pass


def bed_key(map_id, floor_id, bed_id):
    return json.dumps([map_id, floor_id, bed_id], ensure_ascii=False, separators=(',', ':'))


def service_beds(document):
    return {
        obj['id']: bed_key(document['id'], floor['id'], obj['bed_id'])
        for floor in document['floors'] for obj in floor['objects']
        if obj['kind'] == 'service' and obj.get('bed_id')
    }


def physical_beds(document):
    beds = []
    for floor in document['floors']:
        service_names = {}
        for obj in floor['objects']:
            if obj['kind'] == 'service' and obj.get('bed_id'):
                service_names.setdefault(obj['bed_id'], obj.get('name') or obj['id'])
        beds.extend(
            dict(key=bed_key(document['id'], floor['id'], obj['id']), bed_id=obj['id'],
                 name=service_names.get(obj['id']) or obj.get('name') or obj['id'],
                 floor_id=floor['id'], floor=floor.get('name') or floor['id'])
            for obj in floor['objects'] if obj['kind'] == 'bed')
    return beds


class BedCensus:
    def __init__(self, workspace):
        self.workspace = workspace
        self.path = workspace.root / 'bed_census.json'
        self.records = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.samples = {}
        for path in sorted((workspace.root / 'runs').glob('*/events.jsonl'), key=lambda file: file.stat().st_mtime):
            patrols = {}
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict):
                        if event.get('event') == 'patrol_created':
                            patrols.update(dict.fromkeys(event.get('visit_task_ids', []), event.get('patrol_id')))
                        elif event.get('task_id') in patrols:
                            event.setdefault('patrol_id', patrols[event['task_id']])
                        self.record_sample(event)

    @staticmethod
    def _stay(patient):
        return patient.get('stay_id', patient['revision'])

    @staticmethod
    def _status(patient):
        if not patient:
            return 'vacant'
        return 'occupied' if patient.get('admitted_at') else 'pending'

    def list(self, document, *, summary=False):
        with self.workspace.lock:
            beds = physical_beds(document)
            hidden = set() if summary else self.workspace._deleted_patrol_ids(document['id'])
            for bed in beds:
                patient = self.records.get(bed['key'])
                bed.update(patient=patient, status=self._status(patient), assessment=None)
                if patient and summary:
                    bed['patient'] = {field: patient[field] for field in ('name', 'age_months', 'sex')}
                elif patient:
                    bed['assessment'] = next(
                        (sample['assessment'] for sample in self._history(patient, hidden)
                         if sample['profile_revision'] == patient['revision']), None)
            return beds

    def vacant_services(self, locations, services):
        with self.workspace.lock:
            return {service for service in services if service in locations and locations[service] not in self.records}

    def sampling_context(self, key):
        with self.workspace.lock:
            patient = self.records.get(key)
            status = self._status(patient)
            if status != 'occupied':
                return status, None, None
            profile = {field: patient[field] for field in ('age_months', 'sex', 'pregnant', 'revision')}
            return status, self._stay(patient), profile

    def record_sample(self, event):
        if event.get('event') != 'vitals_received':
            return
        payload = event.get('payload', {})
        revision = (payload.get('profile') or {}).get('revision')
        assessment = payload.get('verdict')
        if not revision or not assessment:
            return
        sample = dict(sample_id=payload['sample_id'], source=payload['source'],
                      robot_id=payload.get('robot_id'), task_id=payload.get('task_id'),
                      patrol_id=event.get('patrol_id'),
                      sampled_at=event.get('sampled_at'), sim_time=payload.get('sim_time'),
                      vitals=payload['vitals'], assessment=assessment, profile_revision=revision)
        with self.workspace.lock:
            stay = event.get('stay_id') or revision
            self.samples.setdefault(stay, {}).setdefault(sample['sample_id'], sample)

    def _history(self, patient, hidden):
        samples = self.samples.get(self._stay(patient), {})
        return sorted((sample for sample in reversed(samples.values()) if sample['patrol_id'] not in hidden),
                      key=lambda sample: sample['sampled_at'] or '', reverse=True)

    def history(self, key, revision):
        with self.workspace.lock:
            patient = self.records.get(key)
            if not patient or patient['revision'] != revision:
                raise OccupancyConflict('床位资料已变化，请刷新后查看')
            return self._history(patient, self.workspace._deleted_patrol_ids(json.loads(key)[0]))

    def revisions(self, locations):
        with self.workspace.lock:
            return {service: self.records[key]['revision']
                    if self._status(self.records.get(key)) == 'occupied' else None
                    for service, key in locations.items()}

    def change(self, document, command):
        action, key = command.get('action'), command.get('key')
        if not any(bed['key'] == key for bed in physical_beds(document)):
            raise ValueError('该地图版本中没有此床位')
        if action not in ('register', 'admit', 'check_in', 'edit', 'discharge', 'cancel_registration'):
            raise ValueError('未知床位操作')
        with self.workspace.lock:
            current = self.records.get(key)
            status = self._status(current)
            if action in ('register', 'admit'):
                if current:
                    raise OccupancyConflict('该床位已有登记，请刷新后查看')
            elif current is None or command.get('revision') != current['revision']:
                raise OccupancyConflict('床位资料已变化，请刷新后重试')
            expected = dict(check_in='pending', cancel_registration='pending', discharge='occupied')
            if action in expected and status != expected[action]:
                raise OccupancyConflict('当前床位状态无法执行此操作')

            updated = dict(self.records)
            if action in ('discharge', 'cancel_registration'):
                del updated[key]
                patient = None
            else:
                patient = dict(current) if action == 'check_in' else self._patient(command.get('patient'))
                now = datetime.now(timezone.utc).isoformat()
                patient['admitted_at'] = now if action in ('admit', 'check_in') else (current or {}).get('admitted_at')
                patient['registered_at'] = (current.get('registered_at') or current.get('admitted_at')) if current else now
                patient['revision'] = uuid4().hex
                patient['stay_id'] = self._stay(current) if current else patient['revision']
                updated[key] = patient
            self.workspace._write_json(self.path, updated)
            self.records = updated
            return dict(patient=patient, status=self._status(patient))

    @staticmethod
    def _patient(data):
        if not isinstance(data, dict):
            raise ValueError('请填写患者资料')
        age = data.get('age_months')
        if type(age) is not int or not 0 <= age <= 130 * 12 or (age >= 12 and age % 12):
            raise ValueError('请填写有效的年龄')
        sex, pregnant = data.get('sex'), data.get('pregnant', False)
        if sex not in ('male', 'female', 'unknown') or type(pregnant) is not bool:
            raise ValueError('性别或妊娠资料无效')
        patient = dict(age_months=age, sex=sex, pregnant=pregnant)
        for field, label, limit in (('name', '姓名', 80), ('diagnosis', '诊断信息', 1000),
                                    ('department', '科室', 80), ('notes', '备注', 1000)):
            value = data.get(field, '')
            if not isinstance(value, str) or len(value.strip()) > limit or (field == 'name' and not value.strip()):
                raise ValueError(f'{label}填写有误')
            patient[field] = value.strip()
        return patient
