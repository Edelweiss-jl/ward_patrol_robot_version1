"""Editable fleet execution using versioned metric maps."""
from copy import deepcopy
from dataclasses import asdict
import json
import math
from types import SimpleNamespace
import pybullet as p

from ward_patrol.maps.geometry import Planner, compile_floor, footprint, validate
from ward_patrol.runtime.core import Runtime, DT
from ward_patrol.runtime.coverage import FloorCoverage
from ward_patrol.runtime.dispatch_policy import DispatchPolicy
from ward_patrol.runtime.elevator_risk import ElevatorRisk
from ward_patrol.runtime.elevator import ElevatorExecution
from ward_patrol.runtime.passage import PassageExecution
from ward_patrol.runtime.parking import ParkingExecution
from ward_patrol.runtime.perception import PerceptionExecution, sensor_settings
from ward_patrol.runtime.planning import FleetPlanning
from ward_patrol.simulation.dual_robot_demo import RobotState


# Simulated percentage points consumed per meter actually driven.
BATTERY_USE_PER_METER = 0.1
DEFAULT_BATTERY_PERCENT = 100
DEFAULT_SAFETY_PERCENT = 20
VEHICLE_COLORS = {'red': 'da4651', 'yellow': 'ecb629', 'blue': '3279cf',
                  'green': '36a269', 'purple': '894fbc'}


def battery_limits(instance):
    charge = instance.get('battery_percent', DEFAULT_BATTERY_PERCENT)
    reserve = instance.get('safety_battery_percent', DEFAULT_SAFETY_PERCENT)
    if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100
           for value in (charge, reserve)):
        raise ValueError(f"车辆 {instance.get('id', '')} 的初始电量和最低安全电量须在 0 至 100% 之间")
    return charge, reserve


def validate_parking_assignments(instances):
    if not isinstance(instances, (list, tuple)) or any(not isinstance(vehicle, dict) for vehicle in instances):
        raise ValueError('车辆实例必须是列表')
    assigned = {}
    for vehicle in instances:
        parking = vehicle.get('parking_id')
        if not parking:
            continue
        floor = vehicle.get('floor_id')
        if not isinstance(floor, str) or not isinstance(parking, str):
            raise ValueError('停车点必须关联楼层和停车点编号')
        key = (floor, parking)
        identity = vehicle.get('id', '')
        if key in assigned:
            raise ValueError(f'车辆 {assigned[key]} 与 {identity} 选择了同一个停车点，每个停车点只能停一台车')
        assigned[key] = identity


def validate_models(models):
    model_ids = set()
    for model in models:
        if not model.get('id') or model['id'] in model_ids:
            raise ValueError('型号 ID 必须唯一')
        model_ids.add(model['id'])
        for key in ('width', 'length', 'speed', 'acceleration', 'deceleration', 'angular_speed'):
            value = model.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"型号 {model['id']} 的 {key} 必须为正数")
        if not isinstance(model.get('margin'), (int, float)) or not math.isfinite(model['margin']) or model['margin'] < 0:
            raise ValueError('安全余量必须为非负数')
        if model.get('turning') not in ('differential', 'holonomic'):
            raise ValueError('本阶段支持 differential 和 holonomic 转向')
        if not isinstance(model.get('capabilities'), list) or not isinstance(model.get('sensors'), dict):
            raise ValueError('型号必须包含能力列表和传感器配置')
        sensor_settings(model['sensors'])


def validate_setup(document, models, instances):
    DispatchPolicy.read(document.get('dispatch_policy'))
    validate_parking_assignments(instances)
    result = validate(document)
    errors = result['structure'] + result['geometry']
    if errors:
        raise ValueError('; '.join(errors))
    validate_models(models)
    floors = {f['id']: f for f in document['floors']}
    known_models = {m['id']: m for m in models}
    identities = set()
    active = []
    for instance in instances:
        if not instance.get('id') or instance['id'] in identities:
            raise ValueError('实例 ID 必须唯一')
        identities.add(instance['id'])
        battery_limits(instance)
        color = instance.get('color', 'blue')
        if not isinstance(color, str) or color not in VEHICLE_COLORS:
            raise ValueError('车辆颜色须选择红、黄、蓝、绿或紫')
        if instance.get('enabled') is False and not instance.get('parking_id'):
            continue
        if instance.get('model_id') not in known_models or instance.get('floor_id') not in floors:
            raise ValueError('实例引用的型号或楼层不存在')
        floor, model = floors[instance['floor_id']], known_models[instance['model_id']]
        pose = instance.get('pose', [])
        if len(pose) != 3 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in pose):
            raise ValueError('实例位姿应为 [x, y, 朝向角度]')
        parking = next((o for o in floor['objects'] if o['id']==instance.get('parking_id') and o['kind']=='parking'), None)
        if parking is None:
            raise ValueError('实例必须引用本楼层的停车点')
        if not instance.get('enabled', True):
            continue
        planner = Planner(floor, model)
        if not planner.free(pose[:2]):
            raise ValueError(f"{instance['id']} 初始位姿不可通行")
        if any(item['kind']=='single_lane' and planner.inside(pose[:2],item,planner.radius) for item in floor['objects']):
            raise ValueError(f"{instance['id']} 初始位置必须设在窄通道外")
        for previous, radius in active:
            if previous['floor_id']==instance['floor_id'] and math.dist(previous['pose'][:2], pose[:2]) <= radius+planner.radius:
                raise ValueError('启用车辆的初始位置重叠')
        active.append((instance, planner.radius))
    if not active:
        raise ValueError('至少启用一台机器人')
    return True


def normalize_task_fields(fields):
    spec = dict(content='巡查',service='mqtt',duration=1.,release=0.,priority=0,deadline=None,
                capabilities=[],robot_id=None)
    spec.update(deepcopy(fields))
    # Legacy task records/templates may still carry a retry cap. Ignore it so
    # existing saved work receives the same unlimited retry behavior as new work.
    spec.pop('retry',None)
    if spec['service'] not in ('mqtt','dwell','manual'):
        raise ValueError('服务方式应为 mqtt、dwell 或 manual')
    for key in ('duration','release'):
        if not isinstance(spec[key],(int,float)) or not math.isfinite(spec[key]) or spec[key]<0:
            raise ValueError(key+' 必须为非负数')
    if not isinstance(spec['priority'],int) or not isinstance(spec['capabilities'],list):
        raise ValueError('优先级为整数，能力要求为数组')
    if spec['deadline'] is not None and (not isinstance(spec['deadline'],(int,float)) or not math.isfinite(spec['deadline']) or spec['deadline']<spec['release']):
        raise ValueError('截止时刻必须不早于发布时间')
    return spec


def normalize_patrol_fields(record):
    beds, count, period = record.get('beds'), record.get('count'), record.get('period')
    if not isinstance(beds, list) or not beds or any(not isinstance(bed, str) or not bed for bed in beds):
        raise ValueError('请至少选择一个床位或服务点')
    if len(set(beds)) != len(beds):
        raise ValueError('同一任务不可重复选择床位或服务点')
    if type(count) is not int or count < 1 or count * len(beds) > 1000:
        raise ValueError('单次最多发布 1000 个床位巡检项')
    if not isinstance(period, (int, float)) or not math.isfinite(period) or period < 0:
        raise ValueError('发布间隔应为非负数')
    spec = normalize_task_fields(record.get('task', {}))
    delay = (count - 1) * period
    deadline = spec['deadline'] if spec['deadline'] is not None else spec['release']
    if not math.isfinite(deadline + delay):
        raise ValueError('周期任务的发布时间或截止时刻超出范围')
    return dict(beds=beds, count=count, period=period, task=spec)


class EditableRuntime(ParkingExecution, FloorCoverage, ElevatorRisk, FleetPlanning, PerceptionExecution,
                      ElevatorExecution, PassageExecution, Runtime):
    sim_dt = DT
    battery_use_per_meter = BATTERY_USE_PER_METER
    def __init__(self, document, models, instances, output='outputs/runs', gui=False, policy=None, local_sampling=False):
        validate_setup(document, models, instances)
        self.dispatch_policy = DispatchPolicy.read(policy if policy is not None else document.get('dispatch_policy'))
        self.policy_revision = 0
        self.document = deepcopy(document)
        self.models = {m['id']: deepcopy(m) for m in models}
        self.instances = deepcopy(instances)
        self.task_specs = {}
        self.wait_reasons = {}
        self.service_started = {}
        self.velocities = {}
        self.headings = {}
        self.last_dispatch = -1.
        self._building = True
        super().__init__(output=output, gui=gui, local_sampling=local_sampling)
        self._building = False
        p.resetSimulation(physicsClientId=self.client)
        p.setTimeStep(DT, physicsClientId=self.client)
        self.floors = {f['id']: f for f in document['floors']}
        self.floor_z = {floor_id: index*4 for index, floor_id in enumerate(self.floors)}
        self.services = {o['id']: (floor['id'], o) for floor in document['floors'] for o in floor['objects'] if o['kind']=='service'}
        self.physical_beds = {(floor['id'], obj['id']): obj for floor in self.document['floors']
                              for obj in floor['objects'] if obj['kind'] == 'bed'}
        self.ward = SimpleNamespace(kind=document['id'], stops=[(key, (obj['x'],obj['y'])) for key, (_, obj) in self.services.items()])
        self.robots = []
        self.robot_instances = {}
        self.planners = {}
        self.physics_geometry = []
        for floor in document['floors']:
            z = self.floor_z[floor['id']]
            self.body((0,0,z-.08), (floor['width'],floor['height'],.12), (0.9,0.93,0.95,1))
            for rectangle in compile_floor(floor):
                height = rectangle.get('z', 1.5 if rectangle['kind']=='wall' else .6)
                color = (.5,.6,.7,1) if rectangle['kind']=='wall' else (.3,.65,.65,1)
                body = self.body((rectangle['x'],rectangle['y'],z+height/2),
                                 (rectangle['width'],rectangle['height'],height),color,rectangle.get('rotation',0))
                self.physics_geometry.append(dict(floor_id=floor['id'], object_id=rectangle['id'], body=body, geometry=rectangle))
        for instance in (item for item in instances if item.get('enabled',True)):
            model, floor = self.models[instance['model_id']], self.floors[instance['floor_id']]
            position = tuple(instance['pose'][:2])
            hex_color = VEHICLE_COLORS[instance.get('color', 'blue')]
            color = tuple(int(hex_color[i:i+2], 16)/255 for i in (0,2,4)) + (1,)
            body = self.body((*position,self.floor_z[floor['id']]+.25), (model['length'],model['width'],.5),color,instance['pose'][2])
            parking = next(o for o in floor['objects'] if o['id']==instance['parking_id'])
            robot = RobotState(instance['id'],position,(parking['x'],parking['y']),body,-1,color)
            self.robots.append(robot)
            self.robot_instances[robot.robot_id] = instance
            self.planners[robot.robot_id] = Planner(floor,model)
            self.velocities[robot.robot_id] = 0.
            self.headings[robot.robot_id] = math.radians(instance['pose'][2])
        self.configure_elevators()
        self.configure_passages()
        self.configure_perception()
        self.configure_planning()
        self.configure_floor_coverage()
        self.configure_elevator_risk()
        self.configure_parking()
        (self.directory/'map.json').write_text(json.dumps(self.document,ensure_ascii=False),encoding='utf-8')
        (self.directory/'input.json').write_text(json.dumps(dict(map_id=document['id'],map_version=document['version'],map_digest=document.get('digest'),
            models=models,instances=instances,dt=DT,seed=1000,dispatch_policy=self.dispatch_policy.snapshot()),ensure_ascii=False),encoding='utf-8')
        self.emit('map_bound', map_id=document['id'], map_version=document['version'])
        p.resetDebugVisualizerCamera(28,0,-68,[0,0,0],physicsClientId=self.client)

    def body(self, position, size, color, rotation=0):
        collision = p.createCollisionShape(p.GEOM_BOX,halfExtents=[v/2 for v in size],physicsClientId=self.client)
        visual = p.createVisualShape(p.GEOM_BOX,halfExtents=[v/2 for v in size],rgbaColor=color,physicsClientId=self.client)
        return p.createMultiBody(baseMass=0,baseCollisionShapeIndex=collision,baseVisualShapeIndex=visual,
                                 basePosition=position,baseOrientation=p.getQuaternionFromEuler([0,0,math.radians(rotation)]),physicsClientId=self.client)

    def normalize_task(self, bed, fields):
        if bed not in self.services:
            raise ValueError('地图中找不到服务点 '+bed)
        spec = normalize_task_fields(fields)
        if spec['robot_id'] and spec['robot_id'] not in self.robot_instances:
            raise ValueError('指定车辆未启用或不存在')
        return spec

    def add_task(self, bed_id, **fields):
        if self._building:
            return super().add_task(bed_id)
        spec = self.normalize_task(bed_id, fields)
        task = super().add_task(bed_id)
        self.task_specs[task.task_id] = spec
        self.attempts[task.task_id] = 1
        self.interrupt_coverage_moves(task)
        self.last_dispatch = -math.inf
        return task

    def handle_command(self, command):
        if command.get('action')=='set_dispatch_policy':
            if command.get('run_id',self.run_id)!=self.run_id:
                raise ValueError('巡查运行已切换，请刷新后重试')
            self.dispatch_policy = DispatchPolicy.read(dict(self.dispatch_policy.snapshot(),**command['policy']))
            self.policy_revision += 1
            self._coverage_check = self._coverage_job = None
            self.last_dispatch = -math.inf
            return True
        if command.get('action')=='set_elevator_traffic':
            self.set_elevator_traffic(command)
            return True
        if command.get('action') in ('upsert_obstacle','remove_obstacle','set_road_closure','clear_road_closure'):
            self.perception_command(command)
            return True
        if command.get('action') == 'set_passage_exit_blocked':
            self.passage_command(command)
            return True
        if command.get('action') in ('set_elevator_state','set_elevator_exit_blocked'):
            self.elevator_command(command)
            return True
        if command.get('action') in ('create_patrols', 'publish_patrols'):
            self.create_patrols(command)
            return True
        if command.get('action')=='confirm_service':
            task = next((t for t in self.tasks if t.task_id==command.get('task_id')),None)
            if task is None or self.task_specs[task.task_id]['service']!='manual':
                raise ValueError('请选择人工确认任务')
            if task.status=='completed':
                return True
            if task.task_id not in self.service_started:
                raise ValueError('车辆尚未到站')
            robot = next(r for r in self.robots if r.task_id==task.task_id)
            self.finish(task,robot,'manual_confirmation')
            return True
        if command.get('action')=='create_batch':
            tasks = command.get('tasks',[])
            if not tasks or len(tasks)>1000:
                raise ValueError('批量任务数应为 1 至 1000')
            for item in tasks:
                self.normalize_task(item['bed'],item.get('task',{}))
            for item in tasks:
                self.add_task(item['bed'],**item.get('task',{}))
            return True
        return False

    def create_patrols(self, command):
        if command.get('run_id') != self.run_id:
            raise ValueError('巡查运行已切换，请重新提交任务')
        records = command['records'] if command['action'] == 'publish_patrols' else [command]
        plan = []
        existing = {spec.get('patrol_id') for spec in self.task_specs.values()}
        total = 0
        for record in records:
            source_id = record.get('id') if command['action'] == 'publish_patrols' else None
            if source_id and source_id in existing:
                continue
            if source_id:
                existing.add(source_id)
            normalized = normalize_patrol_fields(record)
            beds, count, period = normalized['beds'], normalized['count'], normalized['period']
            size = count * len(beds)
            skipped = record.get('skip_visits', []) if source_id else []
            if (not isinstance(skipped,list) or any(type(index) is not int or not 0<=index<size for index in skipped)
                    or len(set(skipped))!=len(skipped)):
                raise ValueError('恢复任务的历史床位进度无效')
            skipped = set(skipped)
            remaining = [(index,beds[index%len(beds)]) for index in range(size) if index not in skipped]
            total += len(remaining)
            if total > 1000:
                raise ValueError('单次最多发布 1000 个床位巡检项')
            visits = []
            for index,bed in remaining:
                spec = self.normalize_task(bed, normalized['task'])
                robot_id = spec['robot_id']
                if (robot_id and self.robot_floors[robot_id] != self.services[bed][0]
                        and not any(len(lift.landings)>1 for lift in self.elevators.values())):
                    raise ValueError('指定车辆无法覆盖所选楼层，请改用自动分配')
                visits.append((index,bed,spec))
            plan.append((source_id, record.get('display_number') if source_id else None,
                         len(beds), visits, count, period))

        for source_id, display_number, width, visits, count, period in plan:
            for index in range(count):
                tasks = []
                for visit_index,bed,spec in visits:
                    if visit_index//width != index:
                        continue
                    offset = index * period
                    fields = dict(spec, release=spec['release'] + offset,
                                  deadline=spec['deadline'] + offset if spec['deadline'] is not None else None,
                                  visit_index=visit_index)
                    tasks.append(self.add_task(bed, **fields))
                if not tasks:
                    continue
                patrol_id = source_id or tasks[0].task_id
                for task in tasks:
                    spec = self.task_specs[task.task_id]
                    spec['patrol_id'] = patrol_id
                    if display_number:
                        spec['display_number'] = display_number
                self.emit('patrol_created', task=tasks[0], patrol_id=patrol_id,
                          visit_task_ids=[task.task_id for task in tasks])

    def validate_command(self, command):
        if command.get('action')=='retry_task':
            task_id = command.get('task_id')
            if task_id not in self.task_specs:
                raise ValueError('任务不存在')

    def task_released(self, task, action):
        self.last_dispatch = -math.inf
        self.release_elevator_task(task)
        self.service_started.pop(task.task_id,None)
        self.wait_reasons.pop(task.task_id,None)

    def release_task_robot(self, robot, task, action):
        request = self.elevator_requests.get(robot.robot_id)
        if request and request in self.elevators[request.ride.elevator_id].riders:
            robot.task_id = None
            self.emit('robot_wait',robot,task,reason='任务取消或重试，车辆先安全出梯')
        elif self.release_passage_task(robot):
            super().release_task_robot(robot,task,action)
        else:
            robot.task_id = None
            self.emit('robot_wait',robot,task,reason='任务取消或重试，车辆先安全驶离窄通道')

    def available_battery(self, robot):
        charge, reserve = battery_limits(self.robot_instances[robot.robot_id])
        charge += self.recharged.get(robot.robot_id,0.)-robot.distance*BATTERY_USE_PER_METER
        return max(0., min(100.,charge)), reserve

    def _set_dispatch_wait(self, task, reason, event='task_waiting'):
        if self.wait_reasons.get(task.task_id) != reason:
            self.wait_reasons[task.task_id] = reason
            self.emit(event, task=task, reason=reason)

    def dispatch(self):
        active = {t.bed_id for t in self.tasks if t.status=='assigned'}
        projected = self.projected_robot_floors()
        def dispatch_order(task):
            spec = self.task_specs[task.task_id]
            deadline = spec['deadline']
            return (-spec['priority'], deadline if deadline is not None else math.inf,
                    task.created_at, task.task_id)

        pending = sorted((task for task in self.tasks if task.status == 'pending'), key=dispatch_order)
        plan_valid = self._plan_key == self.planning_key() and self._plan_job is None
        queue_heads = {}
        if plan_valid:
            for task in pending:
                visit = self.dispatch_plan.get(task.task_id)
                if visit:
                    identity = visit['robot_id']
                    queue_heads[identity] = min(queue_heads.get(identity,math.inf),visit['sequence'])
        for task in pending:
            spec = self.task_specs[task.task_id]
            service = self.service_estimate(spec)
            if self.elapsed < spec['release']:
                self._set_dispatch_wait(task, f"等待发布时间（仿真第 {spec['release']:g} 秒）")
                continue
            if task.bed_id in active:
                self._set_dispatch_wait(task, '该床位正在执行另一项巡检')
                continue
            candidates, reasons, top_ups = [], [], []
            planned = self.dispatch_plan.get(task.task_id) if plan_valid else None
            plan_failed = False
            if planned and planned['sequence']!=queue_heads[planned['robot_id']]:
                self._set_dispatch_wait(task,'等待车辆 '+planned['robot_id']+' 队列中的前序床位')
                continue
            floor_id, _ = self.services[task.bed_id]
            def candidate_order(robot):
                model = self.models[self.robot_instances[robot.robot_id]['model_id']]
                return (projected[robot.robot_id]!=floor_id,
                        math.dist(robot.xy,task.goal)/model['speed'],robot.robot_id)

            for robot in sorted(self.robots,key=candidate_order):
                instance = self.robot_instances[robot.robot_id]
                model = self.models[instance['model_id']]
                if planned and planned['robot_id']!=robot.robot_id:
                    continue
                if spec['robot_id'] and spec['robot_id']!=robot.robot_id:
                    continue
                if not set(spec['capabilities']).issubset(model['capabilities']):
                    reasons.append(robot.robot_id+' 能力不匹配')
                    continue
                charge, reserve = self.available_battery(robot)
                if charge < reserve-1e-9:
                    reasons.append(f'{robot.robot_id} 电量 {charge:.1f}% 低于最低安全电量 {reserve:.1f}%')
                    plan_failed = bool(planned)
                    continue
                deferred = bool(robot.task_id or self.parking_preemption_blocked(robot))
                origin,position,available = self.robot_floors[robot.robot_id],robot.xy,self.elapsed
                if deferred:
                    reasons.append('车辆暂时繁忙（'+robot.robot_id+' 正在执行任务）')
                    if planned or projected[robot.robot_id]!=floor_id or not robot.task_id:
                        continue
                    origin,position,remaining,seconds = self._remaining_work(robot)
                    charge -= remaining*BATTERY_USE_PER_METER
                    available += seconds
                optimistic = available+service
                if origin==floor_id:
                    optimistic += math.dist(position,task.goal)/model['speed']
                bound = self.assignment_rank(projected,robot.robot_id,floor_id,int(origin!=floor_id),
                                             optimistic,spec['deadline'],priority=spec['priority'],
                                             released_at=max(task.created_at,spec['release']),service=service,origin=origin)
                if candidates and bound>min(item[0] for item in candidates):
                    continue
                planning_robot = SimpleNamespace(robot_id=robot.robot_id,xy=position) if deferred else robot
                route, reason = self.find_robot_route(planning_robot,model,floor_id,task.goal,origin=origin)
                goal_planner = self.planner_on(floor_id,model)
                if route and any(gate.floor_id==floor_id and goal_planner.inside(task.goal,gate.region,goal_planner.radius)
                                 for gate in self.passages.values()):
                    route,reason = None,'服务点必须设在窄通道外'
                if route:
                    cost,distance,actions = route
                    can_charge = not deferred and charge<100. and self.charging_spot(robot) is not None
                    required = self.parking_requirement(robot,model,floor_id,task.goal,distance,charge,reserve,
                                                        allow_top_up=can_charge)
                    if required>charge+1e-9:
                        if can_charge and math.isfinite(required):
                            top_ups.append((required-charge,robot.robot_id))
                            reasons.append(f'{robot.robot_id} 等待补电至 {required:.1f}% 后可执行并返停')
                        else:
                            reasons.append(f'{robot.robot_id} 执行后无电量充足且安全可达的空闲停车点')
                        plan_failed = bool(planned)
                        continue
                    finish = available+cost+service
                    rank = self.assignment_rank(projected,robot.robot_id,floor_id,self.elevator_rides(actions),
                                                finish,spec['deadline'],distance,priority=spec['priority'],
                                                released_at=max(task.created_at,spec['release']),service=service,origin=origin)
                    candidates.append((rank,robot,actions,deferred))
                else:
                    reasons.append('本轮路径规划失败（'+robot.robot_id+'：'+reason+'）')
                    plan_failed = bool(planned)
            if not candidates:
                if top_ups:
                    self.charge_requested.add(min(top_ups)[1])
                if plan_failed:
                    self._plan_key = None
                    plan_valid = False
                reason='；'.join(reasons) or '无符合指定条件的车辆'
                self._set_dispatch_wait(task, reason, event='task_unreachable')
                continue
            _, robot, actions, deferred = min(candidates,key=lambda value:value[0])
            if deferred:
                self._set_dispatch_wait(task,'车辆暂时繁忙（'+robot.robot_id+' 正在执行任务）；优先等待同层车辆，减少乘梯并保留楼层覆盖')
                continue
            returning = self.leave_parking(robot)
            if returning:
                self._parking_event('parking_return_interrupted',robot,returning['spot'])
            task.status,task.robot_id,task.assigned_at='assigned',robot.robot_id,self.elapsed
            robot.task_id,robot.status=task.task_id,'moving'
            self.connect_robot_route(robot,actions)
            active.add(task.bed_id)
            projected[robot.robot_id] = floor_id
            self.wait_reasons.pop(task.task_id,None)
            self.emit('task_assigned',robot,task,elevator_rides=self.elevator_rides(actions),
                      reason='按能力、通行及电量筛选后，优先保留楼层覆盖、减少乘梯，再比较预计完成时间')
            if self._plan_job is not None:
                self._plan_key = None

    def finish(self, task, robot, reason=None, **fields):
        self.last_dispatch = -math.inf
        if reason is not None:
            fields['reason'] = reason
        super().finish(task,robot,**fields)
        self.parking_pending.add(robot.robot_id)
        self.velocities[robot.robot_id]=0
        self.lidars[robot.robot_id].blocked_since = None
        self.lidars[robot.robot_id].replan_goal = None

    def receipt(self, message):
        super().receipt(message)
        self.last_dispatch = -math.inf

    def sample_bed_info(self, bed):
        floor_id, service = self.services[bed]
        return self.physical_beds.get((floor_id, service.get('bed_id')))

    def advance_robot(self, robot):
        self.advance_charging(robot)
        task = self.task_for(robot)
        self.replan_observed_path(robot,task)
        if robot.robot_id in self.passage_escapes:
            self.move_robot(robot,task)
            return
        if self.advance_passage_yield(robot,task):
            return
        if self.advance_elevator_route(robot,task):
            return
        if robot.robot_id in self.parking_moves:
            self.advance_parking_move(robot,task)
            return
        if task is None:
            return
        move = self.coverage_moves.get(robot.robot_id)
        if move and move['task'] is task:
            if self.robot_floors[robot.robot_id]==move['floor_id'] and math.dist(robot.xy,task.goal)<.01:
                self.finish_coverage_move(robot,task)
            else:
                self.move_robot(robot,task)
            return
        spec = self.task_specs[task.task_id]
        if math.dist(robot.xy,task.goal)<.01:
            if task.task_id not in self.service_started:
                self.service_started[task.task_id]=self.elapsed
                self.emit('task_arrived',robot,task)
                self.emit('service_started',robot,task,service=spec['service'])
                robot.status='servicing'
                if spec['service']=='mqtt':
                    self.request_sample(task.bed_id,'task',task,robot)
                elif self.services[task.bed_id][1].get('bed_id'):
                    self.request_sample(task.bed_id,'task',task,robot,observe_only=True)
            if spec['service']=='dwell' and self.elapsed-self.service_started[task.task_id]+1e-9>=spec['duration']:
                self.finish(task,robot,'dwell_elapsed')
            return
        self.move_robot(robot,task)

    def move_robot(self, robot, task):
        while robot.path and math.dist(robot.xy,robot.path[0])<1e-6:
            robot.path.pop(0)
        if not robot.path:
            return
        instance = self.robot_instances[robot.robot_id]
        model = self.models[instance['model_id']]
        target = robot.path[0]
        distance = math.dist(robot.xy,target)
        heading = math.atan2(target[1]-robot.xy[1],target[0]-robot.xy[0])
        current = self.headings[robot.robot_id]
        delta = (heading-current+math.pi)%(2*math.pi)-math.pi
        turn = min(abs(delta),model['angular_speed']*DT)
        self.headings[robot.robot_id]=current+math.copysign(turn,delta)
        speed=self.velocities[robot.robot_id]
        remaining=distance
        desired=min(model['speed'],math.sqrt(2*model['deceleration']*remaining))
        if model['turning']=='differential' and abs(delta)>.05:
            desired=0
        desired=self.perception_speed_limit(robot,task,model,heading,desired)
        change=(model['acceleration'] if desired>speed else model['deceleration'])*DT
        speed=max(0,speed+max(-change,min(change,desired-speed)))
        step=min(distance,speed*DT)
        position=tuple(robot.xy[k]+(target[k]-robot.xy[k])*step/distance for k in (0,1))
        safe=self.planners[robot.robot_id].segment(robot.xy,position)
        floor_id = self.robot_floors[robot.robot_id]
        if safe:
            safe=self.vehicle_safety_clear(robot,task,position)
        if safe:
            safe=self.passage_allows_step(robot,task,position)
        if safe:
            safe=self.dynamic_safety_clear(robot,task,position)
        if not safe:
            self.velocities[robot.robot_id]=0
            if robot.status!='waiting':
                self.emit('robot_wait',robot,task,reason='车型几何或其他车辆占用阻止本步移动')
            robot.status='waiting'
            return
        if robot.status=='waiting':
            self.emit('robot_released',robot,task,reason='本步几何和车辆间距校验通过')
        robot.status='returning' if robot.robot_id in self.parking_moves else 'moving'
        robot.xy=position
        robot.distance+=step
        self.velocities[robot.robot_id]=0 if step>=distance-1e-9 else speed
        self.place_robot(robot,position,self.floor_z[floor_id])
        self.update_passage_occupancy(robot,task)

    def place_robot(self, robot, position, z):
        p.resetBasePositionAndOrientation(robot.body,[*position,z+.25],
            p.getQuaternionFromEuler([0,0,self.headings[robot.robot_id]]),physicsClientId=self.client)

    def tick(self):
        self.elapsed=self.step*DT
        self.tick_perception()
        if self.elapsed-self.last_dispatch>=.5:
            self.dispatch()
            self.last_dispatch=self.elapsed
        self.start_parking_returns()
        self.advance_planning()
        self.rebalance_floor_coverage()
        for robot in self.robots:
            self.advance_robot(robot)
        self.tick_elevators()
        p.stepSimulation(physicsClientId=self.client)
        self.audit_obstacle_clearance()

    def snapshot(self):
        state=super().snapshot()
        if self._building:
            return state
        state.update(map_id=self.document['id'],map_version=self.document['version'],task_specs=deepcopy(self.task_specs),wait_reasons=deepcopy(self.wait_reasons))
        state.update(self.planning_snapshot())
        state['floor_coverage'] = self.floor_coverage_snapshot(state['dispatch_plan'])
        state['dispatch_policy'] = self.dispatch_policy.snapshot()
        state['elevator_wait_risk'] = {identity:{floor:self.elevator_wait_risk(identity,floor) for floor in lift.landings}
                                      for identity,lift in self.elevators.items()}
        state['elevators']=[lift.snapshot() for lift in self.elevators.values()]
        state['passages']=[gate.snapshot() for gate in self.passages.values()]
        state['parking_resources']=self.parking_snapshot()
        state['perception']=self.perception_snapshot()
        state['dynamic_obstacles']=[{key:data[key] for key in ('id','kind','floor_id','xy','size')}
                                    for data in self.scene_obstacles.values()]
        state['road_closures']=list(self.road_closures.values())
        state['perception_metrics']=deepcopy(self.perception_metrics)
        state['blockage_reports']=deepcopy(self.observed_blockages)
        for robot, actual in zip(state['robots'], self.robots):
            instance=self.robot_instances[robot['id']]
            charge, reserve = self.available_battery(actual)
            robot.update(battery_percent=round(charge,2),safety_battery_percent=reserve)
            robot.update(floor_id=self.robot_floors[robot['id']],model_id=instance['model_id'],yaw=self.headings[robot['id']],speed=self.velocities[robot['id']])
            robot.update(self.robot_parking_snapshot(robot['id']))
            request = self.elevator_requests.get(robot['id'])
            if request:
                robot['elevator_id'] = request.ride.elevator_id
        return state

    def close(self):
        if getattr(self,'elevator_timeline',None):
            self.elevator_timeline.close()
            self.elevator_timeline = None
        super().close()
