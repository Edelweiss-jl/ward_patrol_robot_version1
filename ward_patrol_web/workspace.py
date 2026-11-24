"""Persistent map, fleet, template and saved-run HTTP operations."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlparse, parse_qs
from uuid import uuid4
from ward_patrol.maps.geometry import MapStore, blank_map, copy_floor, validate, compile_floor, Planner, DEFAULT_MODELS, legacy_map
from ward_patrol.maps.templates import hospital_templates
from ward_patrol.maps.elevators import elevator_action
from ward_patrol.runtime.editable import normalize_patrol_fields, validate_models, validate_parking_assignments, validate_setup
from ward_patrol.runtime.elevator import Ride, build_elevators, cross_floor_route
from ward_patrol_web.run_visibility import visible_run_data
from ward_patrol_web.census import BedCensus, service_beds


TASK_NUMBER_TIMEZONE = timezone(timedelta(hours=8))
TERMINAL_VISIT_STATES = {'completed', 'cancelled', 'expired'}


class TaskBedConflict(ValueError):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__('\n'.join(f"{item['label']} 重复选择（未完成任务 {item['task_number']}）"
                                  for item in conflicts))


class VacantTaskBeds(ValueError):
    def __init__(self, beds):
        self.conflicts = beds
        super().__init__('空床不能加入巡查队列：' + '、'.join(item['label'] for item in beds))


class Workspace:
    def __init__(self, root='outputs'):
        self.root=Path(root)
        self.maps=MapStore(self.root/'maps')
        self.lock=threading.RLock()
        self.census = BedCensus(self)
        legacy_templates = ('corridor', 'ring')
        templates = list(hospital_templates())
        self.template_ids = {*legacy_templates, *(template['id'] for template in templates)}
        for kind in legacy_templates:
            if not self.maps.has_history(kind):
                self.maps.save(legacy_map(kind))
        for template in templates:
            if not self.maps.has_history(template['id']):
                self.maps.save(template)

    def _is_template(self, version):
        return version['version'] == 1 and version['id'] in self.template_ids

    def census_map(self, map_id, version):
        if not isinstance(map_id, str) or type(version) is not int or version < 1:
            raise ValueError('请选择地图版本')
        document = next((document for document in self.maps.list()
                         if document['id'] == map_id and document['version'] == version), None)
        if document is None:
            raise ValueError('地图版本不可用，请重新选择地图')
        return document

    def _map_index(self, versions):
        return [dict(version, template=self._is_template(version)) for version in versions]

    def save_map(self, data):
        document = dict(data)
        template_draft = document.pop('template', False)
        version = document.get('version', 0)
        if document.get('id') in self.template_ids and (version == 1 or (version == 0 and template_draft is True)):
            document['id'] = uuid4().hex
        return self.maps.save(document)

    def configuration(self):
        path=self.root/'editor_config.json'
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        return dict(models=deepcopy(DEFAULT_MODELS),instances=[],templates=[])

    def save_configuration(self, data):
        validate_parking_assignments(data.get('instances', []))
        with self.lock:
            self._write_configuration(data)
        return data

    def _write_configuration(self, data):
        self._write_json(self.root/'editor_config.json', data)

    def _write_json(self, path, data):
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)

    @property
    def task_queue_path(self):
        return self.root/'editor_tasks.json'

    def _task_records(self):
        path = self.task_queue_path
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

    def _task_bed_locations(self, map_id, version=None):
        document = max((item for item in self.maps.list(include_archived=version is not None)
                        if item['id'] == map_id and (version is None or item['version'] == version)),
                       key=lambda item: item['version'], default=None)
        return service_beds(document) if document else {}

    def _vacant_task_beds(self, task, locations):
        beds = task['beds']
        retained = Counter(int(visit) % len(beds) for visit in task.get('retained_visit_states', {}))
        remaining = [bed for index, bed in enumerate(beds) if retained[index] < task['count']]
        vacant = self.census.vacant_services(locations, remaining)
        return [dict(bed_id=bed, label=label) for bed, label in zip(beds, task['bed_labels']) if bed in vacant]

    def save_editor_task(self, data, runner=None):
        created_at = datetime.now(timezone.utc)
        map_id, request_id = data['map_id'], data['request_id']
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{32}', request_id):
            raise ValueError('保存请求编号无效')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', map_id):
            raise ValueError('地图编号无效')
        fields = normalize_patrol_fields(data)
        labels = data.get('bed_labels', fields['beds'])
        if not isinstance(labels, list) or len(labels) != len(fields['beds']) or any(not isinstance(label, str) for label in labels):
            raise ValueError('床位显示名称不匹配')
        notes = data.get('notes', '')
        if not isinstance(notes, str):
            raise ValueError('备注应为文本')
        record = dict(request_id=request_id, map_id=map_id, bed_labels=labels, notes=notes.strip(), **fields)
        with self.lock:
            records = self._task_records()
            old = next((task for task in records.values() if task.get('request_id') == request_id), None)
            if old:
                if any(old[key] != value for key, value in record.items()):
                    raise ValueError('此保存请求已用于另一份任务内容')
                return old
            version = data.get('map_version')
            locations = service_beds(self.census_map(map_id, version)) if version is not None else self._task_bed_locations(map_id)
            vacant = self._vacant_task_beds(record, locations)
            if vacant:
                raise VacantTaskBeds(vacant)
            state = runner.snapshot() if runner is not None else {}
            self._reconcile_task_publications(records, state)
            self._check_unfinished_bed_conflicts(record, records, state)
            day = created_at.astimezone(TASK_NUMBER_TIMEZONE).strftime('%Y%m%d')
            prefix = f'PATROL-{day}-'
            display_numbers = {task.get('display_number') or task['id']
                               for task in records.values() if task['status'] != 'deleted'}
            number = 1
            while f'{prefix}{number:04d}' in display_numbers:
                number += 1
            display_number = f'{prefix}{number:04d}'
            # A deleted patrol's internal ID can still be present in run snapshots.
            while f'{prefix}{number:04d}' in records:
                number += 1
            task_id = f'{prefix}{number:04d}'
            if display_number != task_id:
                record['display_number'] = display_number
            records[task_id] = dict(record, id=task_id, created_at=created_at.isoformat(), status='queued')
            self._write_json(self.task_queue_path, records)
            return records[task_id]

    def _task_bed_occupancy(self, map_id, records, state):
        relevant = [task for task in records.values() if task['map_id'] == map_id]
        if not relevant and state.get('map_id') != map_id:
            return {}, {}, {}, {}
        bed_keys = {}
        maps = [document for document in self.maps.list(include_archived=True) if document['id'] == map_id]
        active_run = state.get('run_id') if state.get('map_id') == map_id else None
        if active_run and self.maps.was_deleted(map_id, state.get('map_version')):
            try:
                document = json.loads((self.root/'runs'/active_run/'map.json').read_text(encoding='utf-8'))
                if 'floors' in document:
                    maps.append(document)
            except (OSError, ValueError):
                pass
        for document in sorted(maps, key=lambda item: item['version'], reverse=True):
            for floor in document['floors']:
                for obj in floor['objects']:
                    if obj['kind'] == 'service':
                        bed_keys.setdefault(obj['id'], (floor['id'], obj.get('bed_id') or obj['id']))

        def key(bed):
            return bed_keys.get(bed, (None, bed))

        def groups(snapshot):
            specs = snapshot.get('task_specs', {})
            visits = {}
            for task in snapshot.get('tasks', []):
                task_id = task['task_id']
                patrol_id = specs.get(task_id, {}).get('patrol_id') or task_id
                visits.setdefault(patrol_id, []).append(task)
            return visits

        active_id = state.get('run_id')
        active_groups = groups(state) if state.get('map_id') == map_id else {}
        run_groups = {active_id: active_groups}
        occupied, conflicts_by_task, visit_states = {}, {}, {}
        known_ids = {task['id'] for task in relevant}
        for patrol_id, visits in active_groups.items():
            if patrol_id not in known_ids and any(task['status'] != 'completed' for task in visits):
                for task in visits:
                    occupied.setdefault(key(task['bed_id']), patrol_id)

        # Preserve existing assignments before evaluating older queued records for conflicts.
        ordered = sorted(relevant, key=lambda task: task['status'] not in ('published', 'publishing'))
        for task in ordered:
            if task.get('archived') or task['status'] == 'deleted':
                continue
            statuses = list(task.get('retained_visit_states', {}).values())
            if task['status'] == 'published':
                run_id = task.get('run_id')
                if run_id not in run_groups:
                    run_groups[run_id] = groups(self._latest_task_snapshot(run_id))
                visits = run_groups[run_id].get(task['id'], [])
                statuses.extend(visit['status'] for visit in visits)
            if statuses:
                visit_states[task['id']] = statuses
            if len(statuses) == len(task['beds'])*task['count'] and all(status == 'completed' for status in statuses):
                continue
            conflicts = self._task_bed_conflicts(task, bed_keys, occupied)
            if conflicts:
                conflicts_by_task[task['id']] = conflicts
            for bed in task['beds']:
                occupied.setdefault(key(bed), task.get('display_number') or task['id'])
        return bed_keys, occupied, visit_states, conflicts_by_task

    @staticmethod
    def _task_bed_conflicts(record, bed_keys, occupied):
        conflicts = []
        for bed, label in zip(record['beds'], record['bed_labels']):
            owner = occupied.get(bed_keys.get(bed, (None, bed)))
            if owner:
                conflicts.append(dict(bed_id=bed, label=label, task_number=owner))
        return conflicts

    def _check_unfinished_bed_conflicts(self, record, records, state):
        bed_keys, occupied, _, _ = self._task_bed_occupancy(record['map_id'], records, state)
        conflicts = self._task_bed_conflicts(record, bed_keys, occupied)
        if conflicts:
            raise TaskBedConflict(conflicts)

    def _latest_task_snapshot(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch('[a-f0-9]{32}', run_id):
            return {}
        folder = self.root/'runs'/run_id
        final = folder/'snapshot.json'
        if final.exists():
            try:
                return json.loads(final.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                pass
        snapshots = self._read_json_lines(folder/'snapshots.jsonl')
        return snapshots[-1] if snapshots else {}

    def _reconcile_task_publications(self, records, state):
        active_id = state.get('run_id')
        if not active_id:
            return
        pending = {}
        for task in records.values():
            if task['status'] == 'publishing':
                pending.setdefault(task['run_id'], []).append(task)
        changed = False
        for run_id, tasks in pending.items():
            if run_id == active_id:
                events = state.get('events', [])
            else:
                path = self.root/'runs'/run_id/'events.jsonl'
                events = self._read_json_lines(path)
            results = {event['command_id']: event for event in events
                       if event['event'] in ('command_applied', 'command_rejected')}
            for task in tasks:
                event = results.get(task['command_id'])
                if event and event['event'] == 'command_applied':
                    task['status'] = 'published'
                    changed = True
                elif event or run_id != active_id:
                    automatic = 'request_id' in task
                    task['status'] = 'queued' if automatic else 'saved'
                    task['error'] = event['reason'] if event else (
                        '原巡查运行已结束，等待进入新的运行。' if automatic else '原巡查运行已结束，请重新发布。')
                    changed = True
        if self._recover_interrupted_tasks(records, None if state.get('ended') else active_id) or changed:
            self._write_json(self.task_queue_path, records)

    def _recover_interrupted_tasks(self, records, active_id):
        old_runs = {}
        changed = False
        for task in records.values():
            run_id = task.get('run_id')
            if (task['status'] != 'published' or task.get('archived') or not run_id or run_id == active_id):
                continue
            if run_id not in old_runs:
                old_runs[run_id] = self._recovery_snapshot(run_id)
            snapshot = old_runs[run_id]
            retained = dict(task.get('retained_visit_states', {}))
            specs = snapshot.get('task_specs', {})
            visits = [visit for visit in snapshot.get('tasks', [])
                      if specs.get(visit['task_id'], {}).get('patrol_id') == task['id']]
            available = [index for index in range(len(task['beds'])*task['count']) if str(index) not in retained]
            if (not visits or len(visits) != len(available)
                    or all(visit['status'] in TERMINAL_VISIT_STATES for visit in visits)):
                continue
            for index, visit in zip(available,visits):
                actual = specs[visit['task_id']].get('visit_index',index)
                if visit['status'] in ('completed','cancelled','expired'):
                    retained[str(actual)] = visit['status']
            task.update(status='queued', retained_visit_states=retained, resumed_from=run_id)
            task.pop('error', None)
            changed = True
        return changed

    def _recovery_snapshot(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch('[a-f0-9]{32}', run_id):
            return {}
        folder = self.root/'runs'/run_id
        # A final snapshot is authoritative. After interruption, complete the last snapshot from the event log.
        snapshot = self._latest_task_snapshot(run_id)
        if (folder/'snapshot.json').is_file():
            return snapshot
        visits = {visit['task_id']:dict(visit) for visit in snapshot.get('tasks', [])}
        specs = {key:dict(value) for key,value in snapshot.get('task_specs', {}).items()}
        last_event_id = snapshot.get('events', [{}])[-1].get('event_id',0) if snapshot.get('events') else 0
        statuses = {'task_completed':'completed','task_cancelled':'cancelled'}
        commands = {entry['command']['command_id']:entry['command']
                    for entry in self._read_json_lines(folder/'commands.jsonl')
                    if entry['command'].get('action')=='retry_task'}
        for event in self._read_json_lines(folder/'events.jsonl'):
            if event.get('event_id',0)<=last_event_id:
                continue
            task_id = event.get('task_id')
            name = event['event']
            if name == 'task_created':
                visits.setdefault(task_id,dict(task_id=task_id,bed_id=event['bed_id'],status='pending'))
            elif name == 'patrol_created':
                for visit_id in event.get('visit_task_ids', []):
                    specs.setdefault(visit_id,{})['patrol_id'] = event['patrol_id']
            elif name in statuses and task_id in visits:
                visits[task_id]['status'] = statuses[name]
            elif name == 'command_applied' and event.get('command_id') in commands:
                retry_id = commands[event['command_id']]['task_id']
                if retry_id in visits and visits[retry_id]['status']!='completed':
                    visits[retry_id]['status'] = 'pending'
        return dict(tasks=list(visits.values()),task_specs=specs)

    def editor_tasks(self, map_id, runner, map_version=None):
        with self.lock:
            records = self._task_records()
            state = runner.snapshot()
            self._reconcile_task_publications(records, state)
            if self._assign_legacy_task_numbers(records):
                self._write_json(self.task_queue_path, records)
            _, _, visit_states, conflicts = self._task_bed_occupancy(map_id, records, state)
            version = map_version or (state.get('map_version') if state.get('map_id') == map_id else None)
            locations = self._task_bed_locations(map_id, version)
            results = []
            for task in records.values():
                if task['map_id'] != map_id or task['status'] == 'deleted':
                    continue
                statuses = visit_states.get(task['id'], [])
                vacant = self._vacant_task_beds(task, locations) if task['status'] in ('queued', 'saved') else []
                results.append(dict(task, completed=bool(statuses) and all(status == 'completed' for status in statuses),
                                    vacant_beds=vacant,
                                    visit_states=statuses, bed_conflicts=conflicts.get(task['id'], [])))
            return results

    def archived_tasks(self):
        with self.lock:
            records = self._task_records()
            archived = [task for task in records.values() if task.get('archived')]
            if not archived:
                return []
            if self._assign_legacy_task_numbers(records):
                self._write_json(self.task_queue_path, records)
            tasks = [dict(id=task['id'], number=task.get('display_number') or task['id'], map_id=task['map_id'],
                          request_id=task.get('request_id'),
                          beds=task.get('bed_labels', task.get('beds', [])),
                          created_at=task.get('created_at'), archived_at=task.get('archived_at'),
                          run_id=task.get('run_id')) for task in archived]
        return sorted(tasks, key=lambda task: task['archived_at'] or task['created_at'] or '', reverse=True)

    def delete_editor_task(self, data, runner, *, permanent=False):
        task_id = data['id']
        with self.lock:
            records = self._task_records()
            state = runner.snapshot()
            self._reconcile_task_publications(records, state)
            task = records.get(task_id)
            if task is None or task['status'] == 'deleted':
                return {'deleted': False}
            if task['map_id'] != data['map_id'] or task.get('request_id') != data.get('request_id'):
                raise ValueError('任务记录已变化，请刷新队列后重试')
            if task.get('archived'):
                if permanent:
                    return self._delete_published_task(records, task)
                return {'deleted': False, 'archived': True}
            if task['status'] == 'published':
                _, _, visit_states, _ = self._task_bed_occupancy(task['map_id'], records, state)
                statuses = visit_states.get(task_id, [])
                if (statuses and len(statuses) == len(task['beds']) * task['count']
                        and all(status in TERMINAL_VISIT_STATES for status in statuses)):
                    if permanent:
                        return self._delete_published_task(records, task)
                    task['archived'] = True
                    task['archived_at'] = datetime.now(timezone.utc).isoformat()
                    self._write_json(self.task_queue_path, records)
                    return {'deleted': True, 'archived': True}
            if task['status'] not in ('saved', 'queued'):
                raise ValueError('任务尚未结束，无法删除')
            if task.get('resumed_from'):
                return self._delete_published_task(records, task)
            del records[task_id]
            self._write_json(self.task_queue_path, records)
            return {'deleted': True}

    def _delete_published_task(self, records, task):
        # The stable ID keeps task data filtered across all runs, including interrupted runs.
        records[task['id']] = dict(id=task['id'], map_id=task['map_id'], status='deleted')
        self._write_json(self.task_queue_path, records)
        return {'deleted': True}

    def _deleted_patrol_ids(self, map_id):
        with self.lock:
            return {task['id'] for task in self._task_records().values()
                    if task['map_id'] == map_id and task['status'] == 'deleted'}

    def visible_snapshot(self, snapshot):
        frames, _ = visible_run_data([snapshot], snapshot.get('events', []),
                                     self._deleted_patrol_ids(snapshot.get('map_id')))
        return frames[0]

    @staticmethod
    def _assign_legacy_task_numbers(records):
        used = {task['display_number'] for task in records.values() if task.get('display_number')}
        next_number = {}
        changed = False
        for task_id, task in records.items():
            if task['status'] == 'deleted' or task.get('display_number') or not re.fullmatch(r'TASK-[a-f0-9]{32}', task_id):
                continue
            day = 'LEGACY'
            try:
                timestamp = datetime.fromisoformat(task.get('created_at') or '')
            except ValueError:
                pass
            else:
                if timestamp.tzinfo is not None:
                    day = timestamp.astimezone(TASK_NUMBER_TIMEZONE).strftime('%Y%m%d')
            prefix = f'PATROL-{day}-L'
            number = next_number.get(prefix, 1)
            while f'{prefix}{number:04d}' in used:
                number += 1
            alias = f'{prefix}{number:04d}'
            task['display_number'] = alias
            used.add(alias)
            next_number[prefix] = number + 1
            changed = True
        return changed

    def publish_editor_tasks(self, data, runner):
        ids = data.get('ids')
        if not isinstance(ids, list) or not ids or any(not isinstance(task_id, str) for task_id in ids):
            raise ValueError('请先勾选要发布的任务')
        with self.lock:
            state = runner.snapshot()
            if state.get('ended') or not state.get('map_id') or any(state.get(key) != data.get(key) for key in ('run_id','map_id','map_version')):
                raise ValueError('请为当前地图版本准备巡查后再发布')
            records = self._task_records()
            self._reconcile_task_publications(records, state)
            tasks = [records.get(task_id) for task_id in dict.fromkeys(ids)]
            if any(task is None or task['map_id'] != state['map_id'] for task in tasks):
                raise ValueError('所选任务不属于当前地图')
            tasks = [task for task in tasks if task['status'] in ('saved', 'queued')]
            if not tasks:
                return {'submitted': 0}
            if sum(task['count'] * len(task['beds']) for task in tasks) > 1000:
                raise ValueError('单次最多发布 1000 个床位巡检项，请分批选择')
            _, _, _, conflicts = self._task_bed_occupancy(state['map_id'], records, state)
            blocked = [item for task in tasks for item in conflicts.get(task['id'], [])]
            if blocked:
                raise TaskBedConflict(blocked)
            locations = self._task_bed_locations(state['map_id'], state.get('map_version'))
            vacant = [item for task in tasks for item in self._vacant_task_beds(task, locations)]
            if vacant:
                raise VacantTaskBeds(vacant)
            self._submit_editor_tasks(records, tasks, state['run_id'], runner.submit)
            return {'submitted': len(tasks)}

    def submit_queued_editor_tasks(self, state, submit):
        if not state.get('map_id') or not state.get('started') or state.get('paused'):
            return
        with self.lock:
            records = self._task_records()
            self._reconcile_task_publications(records, state)
            ready = [task for task in records.values() if task['status'] == 'queued'
                     and task['map_id'] == state['map_id'] and task.get('run_id') != state['run_id']]
            if not ready:
                return
            _, _, _, conflicts = self._task_bed_occupancy(state['map_id'], records, state)
            locations = self._task_bed_locations(state['map_id'], state.get('map_version'))
            for task in ready:
                if task['id'] not in conflicts and not self._vacant_task_beds(task, locations):
                    self._submit_editor_tasks(records, [task], state['run_id'], submit)

    def _submit_editor_tasks(self, records, tasks, run_id, submit):
        command_id = uuid4().hex
        for task in tasks:
            task.update(status='publishing', run_id=run_id, command_id=command_id)
            task.pop('error', None)
        self._write_json(self.task_queue_path, records)
        payload = [dict({key: task[key] for key in ('id','beds','count','period','task')},
                        display_number=task.get('display_number'),
                        skip_visits=sorted(map(int,task.get('retained_visit_states', {})))) for task in tasks]
        submit(dict(action='publish_patrols', run_id=run_id, command_id=command_id, records=payload))

    def update_model(self, command):
        with self.lock:
            data = self.configuration()
            models = data['models']
            if command.get('action') == 'save':
                model = command['model']
                if not isinstance(model, dict) or not isinstance(model.get('name'), str) or not model['name'].strip():
                    raise ValueError('请填写车型名称')
                validate_models([model])
                model_id = model['id']
                index = next((i for i, item in enumerate(models) if item['id'] == model_id), len(models))
                models[index:index+1] = [model]
            elif command.get('action') == 'delete':
                model_id = command['id']
                used = [item['id'] for item in data['instances'] if item.get('model_id') == model_id]
                if used:
                    raise ValueError('已保存的车辆 '+ '、'.join(used)+' 正在使用该车型，请先为这些车辆更换车型并保存车队。')
                data['models'] = [item for item in models if item['id'] != model_id]
            else:
                raise ValueError('未知车型操作')
            self._write_configuration(data)
            return data['models']

    @staticmethod
    def _read_json_lines(path):
        if not path.exists():
            return []
        with path.open(encoding='utf-8') as file:
            result = []
            for line in file:
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return result

    def read_run(self, identity):
        if not re.fullmatch('[a-f0-9]{32}',identity):
            raise ValueError('运行 ID 无效')
        folder=self.root/'runs'/identity
        document = json.loads((folder/'map.json').read_text(encoding='utf-8'))
        snapshots, events = visible_run_data(self._read_json_lines(folder/'snapshots.jsonl'),
                                             self._read_json_lines(folder/'events.jsonl'),
                                             self._deleted_patrol_ids(document.get('id') or document.get('map_id')))
        return dict(map=document, snapshots=snapshots, events=events,
                    input=json.loads((folder/'input.json').read_text(encoding='utf-8')))

    def get(self, path):
        url=urlparse(path)
        if url.path=='/api/maps':
            return self._map_index(self.maps.list_with_names())
        if url.path=='/api/maps/manage':
            return self._map_index(self.maps.catalog())
        if url.path=='/api/archives/tasks':
            return self.archived_tasks()
        if url.path=='/api/editor/config':
            return self.configuration()
        if url.path=='/api/editor/models':
            return deepcopy(DEFAULT_MODELS[0])
        if url.path=='/api/runs/summary':
            records=[]
            for path in (self.root/'runs').glob('*/map.json'):
                try:
                    document=json.loads(path.read_text(encoding='utf-8'))
                    snapshots=path.parent/'snapshots.jsonl'
                    records.append(dict(id=path.parent.name,name=document.get('name',document.get('map_id','历史病区')),
                        version=document.get('version',1),created_at=path.stat().st_mtime,
                        has_snapshots=snapshots.is_file() and snapshots.stat().st_size>0))
                except (OSError,ValueError):
                    continue
            return sorted(records,key=lambda record:record['created_at'],reverse=True)
        if url.path=='/api/runs':
            return [p.parent.name for p in (self.root/'runs').glob('*/map.json')]
        if url.path=='/api/replay':
            return self.read_run(parse_qs(url.query).get('run_id',[''])[0])
        return None

    def post(self, path, data):
        if path=='/api/maps/manage':
            return self.maps.manage_versions(data.get('action'), data.get('versions'))
        if path=='/api/maps/elevators':
            models = data.get('models',DEFAULT_MODELS)
            validate_models(models)
            return elevator_action(data,models)
        if path=='/api/maps/blank':
            return blank_map(data.get('name','新病区'))
        if path=='/api/maps/save':
            return self.save_map(data)
        if path=='/api/maps/rename':
            return self.maps.rename_version(data.get('map_id'),data.get('version'),data.get('name'))
        if path=='/api/maps/copy-floor':
            return copy_floor(data['map'],data['floor_id'])
        if path=='/api/maps/validate':
            return validate(data)
        if path=='/api/maps/compile':
            check=validate(data)
            if not check['valid']:
                return dict(validation=check,floors=[])
            return dict(validation=check,floors=[dict(id=f['id'],rectangles=compile_floor(f)) for f in data['floors']])
        if path=='/api/editor/config':
            return self.save_configuration(data)
        if path=='/api/editor/models':
            return self.update_model(data)
        if path=='/api/preview':
            document=data['map']
            check=validate(document)
            if not check['valid']:
                return dict(validation=check,results=[])
            validate_setup(document,data['models'],data['instances'])
            models={m['id']:m for m in data['models']}
            floors={f['id']:f for f in document['floors']}
            lifts=build_elevators(floors,document.get('elevators'))
            levels={floor:index for index,floor in enumerate(floors)}
            services={o['id']:(f['id'],o) for f in document['floors'] for o in f['objects'] if o['kind']=='service'}
            results=[]
            for instance in data['instances']:
                if not instance.get('enabled',True):
                    continue
                model = models[instance['model_id']]
                planners = {floor:Planner(item,model) for floor,item in floors.items()}
                for service_id,(floor_id,service) in services.items():
                    origin = instance['floor_id']
                    target = service['x'],service['y']
                    row = dict(robot_id=instance['id'], model_id=model['id'], floor_id=floor_id, service_id=service_id)
                    if floor_id==origin:
                        results.append(dict(row,**planners[floor_id].route(instance['pose'][:2],target)))
                        continue
                    route = cross_floor_route(lifts,levels,planners,model,origin,instance['pose'][:2],floor_id,target)
                    if not route:
                        results.append(dict(row,path=[],reason='无可用电梯路线'))
                        continue
                    seconds, _, actions = route
                    segments, shafts = [], []
                    current = origin
                    for action in actions:
                        if isinstance(action,Ride):
                            current = action.destination
                            shafts.append(action.elevator_id)
                            segments.append(dict(floor_id=current,path=action.clearance))
                        else:
                            segments.append(dict(floor_id=current,path=action))
                    results.append(dict(row,path=[],segments=segments,
                                        reason='可达，经 '+ ' → '.join(shafts)+f'，预计 {seconds:.1f} 秒'))
            return dict(validation=check,results=results)
        return None

    def setup(self, data):
        document=next((m for m in self.maps.list() if m['id']==data['map_id'] and m['version']==data['version']),None)
        if document is None:
            raise ValueError('地图版本不可用，请选择可用版本、恢复归档版本或保存新版本')
        validate_setup(document,data['models'],data['instances'])
        return dict(document=document,models=data['models'],instances=data['instances'])
