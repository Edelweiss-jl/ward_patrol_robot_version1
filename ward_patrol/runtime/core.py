"""Fixed-step runtime shared by HTTP and command-line clients."""
from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path
from queue import Queue, Empty
import uuid

from ward_patrol.simulation.dual_robot_demo import DualRobotSimulation, DT


class Runtime(DualRobotSimulation):
    def __init__(self, output='outputs/runs', seed=1000, gui=False, local_sampling=False):
        self.run_id = uuid.uuid4().hex
        self.step = 0
        self.started = True
        self.ended = False
        self.commands = Queue()
        self.speed = 1.0
        self.samples = {}
        self.local_sampling = local_sampling
        self.vitals_sampler = None
        self.attempts = {}
        self.applied_commands = set()
        self.outbox = []
        self.beds_path = Path(output)/'beds.json'
        self.bed_info = json.loads(self.beds_path.read_text(encoding='utf-8')) if self.beds_path.exists() else {}
        self.directory = Path(output) / self.run_id
        self.directory.mkdir(parents=True)
        super().__init__('corridor', gui=gui, beds=['N1-1'], people=False, verbose=False)
        self.tasks.clear()
        self.events.clear()
        self.task_counter = 0
        self.event_file = (self.directory / 'events.jsonl').open('w', encoding='utf-8')
        self.input_file = (self.directory / 'commands.jsonl').open('w', encoding='utf-8')
        self.snapshot_file = (self.directory / 'snapshots.jsonl').open('w', encoding='utf-8')
        (self.directory / 'input.json').write_text(json.dumps(dict(seed=seed, map_id='corridor', map_version=1, dt=DT, robots=['R1','R2'])), encoding='utf-8')
        (self.directory/'map.json').write_text(json.dumps(dict(map_id='corridor',version=1,boxes=[asdict(b) for b in self.ward.boxes],stops=self.ward.stops)),encoding='utf-8')
        self.emit('run_created', reason='user_request')

    def emit(self, event, robot=None, task=None, **extra):
        if event == 'all_tasks_completed' and not self.tasks:
            return
        super().emit(event, robot, task, **extra)
        record = self.events[-1]
        record.update(run_id=self.run_id, step=self.step)
        record.setdefault('reason', event)
        if task:
            record['attempt_id'] = task.task_id + '-A' + str(self.attempts.get(task.task_id, 1))
        if hasattr(self, 'event_file'):
            self.event_file.write(json.dumps(record, ensure_ascii=False)+'\n')
            self.event_file.flush()

    def submit(self, command):
        command = deepcopy(command)
        command.setdefault('command_id', uuid.uuid4().hex)
        self.commands.put(command)
        return command['command_id']

    def advance_robot(self, robot):
        task = self.task_for(robot)
        if task and math.dist(robot.xy, task.goal) < .025:
            if robot.status != 'sampling':
                self.emit('task_arrived', robot, task)
                robot.status = 'sampling'
                self.emit('service_started', robot, task)
                self.request_sample(task.bed_id, 'task', task, robot)
            return False
        return super().advance_robot(robot)

    def request_sample(self, bed, source, task=None, robot=None, *, observe_only=False):
        sample_id = self.run_id + '-S' + str(len(self.samples)+1)
        request = dict(sample_id=sample_id, run_id=self.run_id, bed_id=bed,
                       task_id=task.task_id if task else None,
                       attempt_id=task.task_id+'-A'+str(self.attempts.get(task.task_id,1)) if task else None,
                       robot_id=robot.robot_id if robot else None, source=source,
                       seq=len(self.samples)+1, sim_time=self.elapsed)
        self.samples[sample_id] = dict(request=request, accepted=False)
        self.emit('sample_requested', sample_id=sample_id, source=source)
        if not (self.local_sampling or observe_only):
            self.outbox.append(request)
            return
        if self.vitals_sampler is None:
            from ward_patrol.runtime.vitals import SimulatedVitals
            from ward_patrol_vitals_mqtt.vitals_mqtt import load_config

            self.vitals_sampler = SimulatedVitals(load_config())
        result = self.vitals_sampler.sample(request)
        if observe_only:
            self.record_sample(self.samples[sample_id], result, task)
        else:
            self.submit(dict(action='receipt', payload=result))

    def record_sample(self, sample, message, task):
        sample['accepted'] = True
        sample['result'] = deepcopy(message)
        self.emit('vitals_received', task=task, sample_id=message['sample_id'],
                  source=sample['request']['source'], payload=message)

    def receipt(self, message):
        sample = self.samples.get(message.get('sample_id'))
        if not sample or any(message.get(k) != sample['request'][k] for k in ('run_id','task_id','attempt_id','bed_id','robot_id','source')):
            self.emit('receipt_unmatched', payload=message)
            return
        request = sample['request']
        task = next((t for t in self.tasks if t.task_id == request['task_id']), None)
        if task and (request['attempt_id'] != task.task_id+'-A'+str(self.attempts.get(task.task_id,1)) or task.status == 'cancelled'):
            self.emit('receipt_late', payload=message)
            return
        if sample['accepted']:
            self.emit('receipt_duplicate', sample_id=message['sample_id'])
            return
        request = sample['request']
        task = next((t for t in self.tasks if t.task_id == request['task_id']), None)
        if task and task.status != 'assigned':
            self.emit('receipt_late', payload=message)
            return
        if not isinstance(message.get('vitals'), dict) or not message['vitals']:
            self.emit('receipt_invalid', payload=message)
            return
        self.record_sample(sample, message, task)
        if task:
            robot = next(r for r in self.robots if r.robot_id == task.robot_id)
            task.status, task.completed_at = 'completed', self.elapsed
            self.emit('task_completed', robot, task, sample_id=message['sample_id'])
            robot.task_id = None
            robot.status = 'idle'
            robot.path = []
            robot.completed_tasks += 1

    def advance(self):
        # Control commands are applied at the frozen boundary while paused.
        if self.ended:
            return
        pending = []
        while True:
            try:
                pending.append(self.commands.get_nowait())
            except Empty:
                break
        for command in pending:
            action = command.get('action')
            if command['command_id'] in self.applied_commands:
                self.emit('command_duplicate', command_id=command['command_id'])
                continue
            if self.paused and action == 'receipt':
                self.commands.put(command)
                continue
            try:
                if self.ended:
                    raise ValueError('本次巡查已结束')
                self.validate_command(command)
                if action == 'create_task':
                    task = self.add_task(command['bed'], **command.get('task', {}))
                    self.attempts[task.task_id] = 1
                elif action in ('cancel_task','retry_task'):
                    task = next((t for t in self.tasks if t.task_id == command['task_id']),None)
                    if task is None:
                        raise ValueError('unknown task')
                    if task.status == 'completed':
                        raise ValueError('completed tasks cannot be retried or cancelled')
                    for robot in self.robots:
                        if robot.task_id == task.task_id:
                            self.release_task_robot(robot, task, action)
                    if action == 'retry_task':
                        self.attempts[task.task_id] = self.attempts.get(task.task_id,1)+1
                        task.status = 'pending'
                        task.robot_id = None
                        task.assigned_at = None
                        self.task_released(task, action)
                    elif task.status != 'cancelled':
                        task.status = 'cancelled'
                        self.emit('task_cancelled', task=task, reason='user_request')
                        self.task_released(task, action)
                elif action == 'receipt':
                    self.receipt(command['payload'])
                elif action in ('pause','resume'):
                    self.paused = action == 'pause'
                    if action == 'resume':
                        self.started = True
                elif action == 'end_run':
                    if command.get('run_id') != self.run_id or not self.started:
                        raise ValueError('没有可结束的本次巡查')
                    self.started = self.paused = False
                    self.ended = True
                elif action == 'set_speed':
                    speed = float(command['speed'])
                    if not math.isfinite(speed) or not .25 <= speed <= 8:
                        raise ValueError('speed must be between 0.25 and 8')
                    self.speed = speed
                elif action == 'trigger_sample':
                    if command['bed'] not in dict(self.ward.stops):
                        raise ValueError('unknown bed')
                    self.request_sample(command['bed'], 'manual')
                elif action == 'update_bed':
                    if command['bed'] not in dict(self.ward.stops) or not isinstance(command['fields'],dict):
                        raise ValueError('invalid bed metadata')
                    self.bed_info[command['bed']] = deepcopy(command['fields'])
                    (self.directory/'beds.json').write_text(json.dumps(self.bed_info,ensure_ascii=False),encoding='utf-8')
                    temporary = self.beds_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(self.bed_info,ensure_ascii=False),encoding='utf-8')
                    temporary.replace(self.beds_path)
                elif self.handle_command(command):
                    pass
                else:
                    raise ValueError('unsupported command')
                if action in ('create_task','create_batch','create_patrols','publish_patrols') and self.tasks:
                    self.started = True
                self.applied_commands.add(command['command_id'])
                self.emit('command_applied', command_id=command['command_id'], action=action)
                self.input_file.write(json.dumps(dict(command=command, step=self.step))+'\n')
                self.input_file.flush()
            except (ValueError, KeyError, TypeError) as exc:
                self.emit('command_rejected', command_id=command['command_id'], reason=str(exc))
        if self.ended:
            self.record_snapshot()
        elif self.started and not self.paused:
            self.step += 1
            self.done = False
            self.tick()
            if self.step % 6 == 0:
                self.record_snapshot()

    def record_snapshot(self):
        snapshot = self.snapshot()
        snapshot.pop('events')
        self.snapshot_file.write(json.dumps(snapshot,ensure_ascii=False)+'\n')
        self.snapshot_file.flush()

    def release_task_robot(self, robot, task, action):
        robot.task_id,robot.path,robot.status = None,[],'idle'
        self.emit('robot_released',robot,task,reason=action)

    def task_released(self, task, action):
        pass

    def handle_command(self, command):
        return False

    def validate_command(self, command):
        pass

    def snapshot(self):
        return dict(run_id=self.run_id, step=self.step, elapsed=self.elapsed,
                    started=self.started, paused=self.paused, ended=self.ended, speed=self.speed, tasks=[asdict(t) for t in self.tasks],
                    robots=[dict(id=r.robot_id, xy=r.xy, path=r.path, color=r.color, status=r.status,
                                 task_id=r.task_id) for r in self.robots],
                    beds=deepcopy(self.bed_info), attempts=deepcopy(self.attempts),
                    samples=deepcopy(self.samples), events=deepcopy(self.events))

    def close(self):
        if hasattr(self,'event_file'):
            (self.directory/'snapshot.json').write_text(json.dumps(self.snapshot(),ensure_ascii=False),encoding='utf-8')
        for name in ('event_file', 'input_file', 'snapshot_file'):
            handle = getattr(self, name, None)
            if handle:
                handle.close()
        super().close()
