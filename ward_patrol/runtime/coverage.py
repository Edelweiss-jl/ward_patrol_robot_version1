"""Prefer resident robots and restore missing floor coverage after patrols."""
from collections import Counter
from dataclasses import asdict
import math
import time

from ward_patrol.runtime.elevator import Ride
from ward_patrol.simulation.dual_robot_demo import PatrolTask


class FloorCoverage:
    def configure_floor_coverage(self):
        self.coverage_moves = {}
        self.coverage_revision = 0
        self._coverage_counter = 0
        self._coverage_check = None
        self._coverage_job = None
        self.coverage_reason = ''
        self.relocation_until = {}
        self.vacancy_since = {floor:None for floor in self.floors}
        self.coverage_empty_seconds = {floor:0. for floor in self.floors}
        self.coverage_max_empty_seconds = {floor:0. for floor in self.floors}
        self.coverage_ready = {floor:0 for floor in self.floors}
        self.coverage_workload = {floor:0. for floor in self.floors}
        self.coverage_targets = {floor:1 for floor in self.floors}
        self._pressure_since = {floor:None for floor in self.floors}
        self._coverage_monitor_time = self.elapsed
        self._readiness = {}
        self.coverage_deferred_until = {}

    def basic_service_capable(self, identity):
        robot = self.by_robot[identity]
        model = self.models[self.robot_instances[identity]['model_id']]
        charge,reserve = self.available_battery(robot)
        return 'patrol' in model['capabilities'] and charge>reserve+1e-9

    def service_estimate(self, spec):
        estimate = spec['duration']
        if spec['service']=='manual':
            estimate = max(estimate,self.dispatch_policy.manual_service_seconds)
        elif spec['service']=='mqtt':
            estimate = max(estimate,self.dispatch_policy.mqtt_service_seconds)
        return estimate

    def is_urgent(self, spec):
        return spec['priority']>=self.dispatch_policy.emergency_priority

    def note_floor_arrival(self, identity, floor):
        self.relocation_until[identity] = self.elapsed+self.dispatch_policy.relocation_cooldown_seconds

    def service_arrivals(self):
        readiness = {}
        for robot in self.robots:
            identity = robot.robot_id
            if not self.basic_service_capable(identity):
                continue
            if identity in self.passage_escapes or (not robot.task_id and identity in self.elevator_requests
                                                    and identity not in self.parking_moves):
                continue
            parking = self.parking_moves.get(identity)
            cross_floor_return = bool(parking and parking['spot'][0]!=self.robot_floors[identity])
            floor,_,distance,seconds = self._remaining_work(robot,include_parking=cross_floor_return)
            charge,reserve = self.available_battery(robot)
            if floor not in self.floors or charge-distance*self.battery_use_per_meter<=reserve+1e-9:
                continue
            readiness[identity] = floor,seconds
        return readiness

    def update_service_coverage(self):
        readiness = self.service_arrivals()
        ready = Counter(floor for floor,seconds in readiness.values()
                        if seconds<=self.dispatch_policy.coverage_ready_seconds)
        elapsed = max(0.,self.elapsed-self._coverage_monitor_time)
        for floor in self.floors:
            since = self.vacancy_since[floor]
            if since is not None:
                self.coverage_empty_seconds[floor] += elapsed
                self.coverage_max_empty_seconds[floor] = max(self.coverage_max_empty_seconds[floor],self.elapsed-since)
            if ready[floor]:
                self.vacancy_since[floor] = None
            elif since is None:
                self.vacancy_since[floor] = self.elapsed
        self._coverage_monitor_time = self.elapsed
        self.coverage_ready = {floor:ready[floor] for floor in self.floors}
        self._readiness = readiness
        workloads = Counter()
        horizon = self.elapsed+self.dispatch_policy.demand_horizon_seconds
        for task in self.tasks:
            spec = self.task_specs[task.task_id]
            if task.status!='pending' or spec['release']>horizon:
                continue
            visit = self.dispatch_plan.get(task.task_id)
            seconds = (visit['estimated_finish']-visit['estimated_start'] if visit else self.service_estimate(spec)+5.)
            workloads[self.services[task.bed_id][0]] += max(0.,seconds)
        self.coverage_workload = {floor:round(workloads[floor],3) for floor in self.floors}
        targets = {floor:1 for floor in self.floors}
        spare = max(0,sum(self.basic_service_capable(r.robot_id) for r in self.robots)-len(self.floors))
        for _ in range(spare):
            floor = max(self.floors,key=lambda key:(workloads[key]/targets[key],key))
            if workloads[floor]/targets[floor]<=self.dispatch_policy.response_seconds:
                break
            targets[floor] += 1
        self.coverage_targets = targets
        for floor in self.floors:
            if ready[floor]<targets[floor]:
                if self._pressure_since[floor] is None:
                    self._pressure_since[floor] = self.elapsed
            else:
                self._pressure_since[floor] = None

    def task_for(self, robot):
        move = getattr(self,'coverage_moves',{}).get(robot.robot_id)
        if move and move['task'].task_id==robot.task_id:
            return move['task']
        return super().task_for(robot)

    def task_floor(self, task):
        move = self.coverage_moves.get(task.robot_id)
        if move and move['task'] is task:
            return move['floor_id']
        return self.services[task.bed_id][0]

    def projected_robot_floors(self):
        result = {}
        for robot in self.robots:
            task = self.task_for(robot)
            request = self.elevator_requests.get(robot.robot_id)
            result[robot.robot_id] = (self.task_floor(task) if task else
                request.ride.destination if request else self.robot_floors[robot.robot_id])
        return result

    def assignment_rank(self, projected, identity, destination, rides, finish, deadline, distance=0.,
                        priority=0, released_at=None, service=0., origin=None, affinity=None):
        represented = {floor for key,floor in projected.items() if key!=identity and floor in self.floors
                       and self.basic_service_capable(key)}
        represented.add(destination)
        missing = len(self.floors)-len(represented)
        # Safety/capability are checked before scoring. Honor an achievable
        # deadline first, then keep floors covered and minimize actual rides.
        lateness = max(0.,finish-deadline) if deadline is not None else 0.
        urgent = priority>=self.dispatch_policy.emergency_priority
        limit = self.dispatch_policy.urgent_response_seconds if urgent else self.dispatch_policy.response_seconds
        response = max(0.,finish-service-(self.elapsed if released_at is None else released_at))
        excess = max(0.,response-limit)
        stable = int(origin is not None and origin!=destination and self.relocation_until.get(identity,0.)>self.elapsed)
        switched = self.dispatch_policy.group_switch_seconds if affinity and affinity!=identity else 0.
        # Waiting too long may justify support, but small gains keep local work
        # together. Urgent work compares response before coverage preferences.
        response_cost = excess if urgent else int(excess/max(1.,self.dispatch_policy.support_gain_seconds))
        prefix = (lateness>1e-9,lateness,excess>1e-9,response_cost)
        if urgent:
            return (*prefix,finish,missing,rides,stable,finish+switched,distance,identity)
        return (*prefix,missing,rides,stable,finish+switched,finish,distance,identity)

    @staticmethod
    def elevator_rides(actions):
        return sum(isinstance(action,Ride) for action in actions)

    def interrupt_coverage_moves(self, new_task):
        spec = self.task_specs[new_task.task_id]
        destination = self.services[new_task.bed_id][0]
        for identity,move in list(self.coverage_moves.items()):
            urgent = self.is_urgent(spec)
            specified = spec['robot_id']==identity
            # Ordinary arrivals keep a useful relocation underway. A local,
            # unboarded donor may stop if no other compatible robot can respond.
            alternatives = [r for r in self.robots if r.robot_id!=identity and
                set(spec['capabilities']).issubset(self.models[self.robot_instances[r.robot_id]['model_id']]['capabilities'])
                and self.basic_service_capable(r.robot_id) and
                self.projected_robot_floors()[r.robot_id]==destination and
                self._remaining_work(r)[3]<=self.dispatch_policy.response_seconds]
            needed_here = (not alternatives and self.robot_floors[identity]==destination and
                           identity not in self.elevator_requests and move['floor_id']!=destination)
            if not (urgent or specified or needed_here):
                continue
            robot,task = self.by_robot[identity],move['task']
            self.release_task_robot(robot,task,'new_patrol')
            task.status = 'cancelled'
            self.task_released(task,'new_patrol')
            self.lidars[identity].replan_goal = None
            self.coverage_moves.pop(identity,None)
            self.coverage_revision += 1
            self.emit('coverage_move_cancelled',robot,task,reason='紧急、指定或本层无替代车辆的任务到达，安全释放补位车辆')
        self._coverage_check = None
        self._coverage_job = None
        self.coverage_reason = ''

    def finish_coverage_move(self, robot, task):
        move = self.coverage_moves.pop(robot.robot_id)
        task.status,task.completed_at = 'completed',self.elapsed
        robot.task_id,robot.path,robot.status = None,[],'idle'
        self.velocities[robot.robot_id] = 0.
        self.lidars[robot.robot_id].blocked_since = None
        self.lidars[robot.robot_id].replan_goal = None
        self.wait_reasons.pop(task.task_id,None)
        self.coverage_revision += 1
        self._coverage_check = None
        self._coverage_job = None
        self.last_dispatch = -math.inf
        self.note_floor_arrival(robot.robot_id,move['floor_id'])
        self.emit('coverage_move_completed',robot,task,floor_id=move['floor_id'],reason='车辆已到达缺车楼层的安全待命点')

    def coverage_route_failed(self, robot, task):
        move = self.coverage_moves.get(robot.robot_id)
        if not move or move['task'] is not task:
            return
        self.coverage_moves.pop(robot.robot_id)
        self.wait_reasons.pop(task.task_id,None)
        task.status = 'cancelled'
        self.coverage_revision += 1
        self._coverage_check = None
        self._coverage_job = None
        self.emit('coverage_move_cancelled',robot,task,reason='补位路线的电梯不可用，等待恢复后重新评估')

    def _standby_points(self, floor_id, robot):
        planner = self.planning_on(floor_id,self.models[self.robot_instances[robot.robot_id]['model_id']])
        owners = {(item['floor_id'],item['parking_id']):key for key,item in self.robot_instances.items()}
        points = sorted((obj for obj in self.floors[floor_id]['objects'] if obj['kind'] in ('parking','service')),
                        key=lambda obj:(obj['kind']!='parking',obj['id']))
        for obj in points:
            if obj['kind']=='parking' and owners.get((floor_id,obj['id'])) not in (None,robot.robot_id):
                continue
            point = obj['x'],obj['y']
            if obj['kind']=='parking' and not self._parking_open(robot,(floor_id,obj['id'])):
                continue
            if not planner.free(point) or any(gate.floor_id==floor_id and
                planner.inside(point,gate.region,planner.radius) for gate in self.passages.values()):
                continue
            if any(other is not robot and self.robot_floors[other.robot_id]==floor_id and
                   math.dist(point,other.xy)<=planner.radius+self.planners[other.robot_id].radius+.05
                   for other in self.robots):
                continue
            if any(task.status in ('pending','assigned') and self.services[task.bed_id][0]==floor_id and
                   self.task_specs[task.task_id]['release']<=self.elapsed+self.dispatch_policy.demand_horizon_seconds and
                   math.dist(point,task.goal)<=planner.radius*2+.05 for task in self.tasks):
                continue
            yield obj,point

    def rebalance_floor_coverage(self):
        self.update_service_coverage()
        if self.coverage_moves:
            return
        if not self.tasks:
            self.coverage_reason = ''
            self._coverage_check = self._coverage_job = None
            return
        projected = self.projected_robot_floors()
        counts = self.coverage_ready
        deficits = [floor for floor in self.floors if counts[floor]<self.coverage_targets[floor]]
        missing = []
        self.coverage_deferred_until = {}
        for floor in deficits:
            urgent = any(t.status=='pending' and self.task_specs[t.task_id]['release']<=self.elapsed and
                         self.services[t.bed_id][0]==floor and self.is_urgent(self.task_specs[t.task_id]) for t in self.tasks)
            since = self._pressure_since[floor]
            delay = max(self.dispatch_policy.vacancy_grace_seconds if not counts[floor] else 0.,
                        self.dispatch_policy.rebalance_delay_seconds)
            until = (since if since is not None else self.elapsed)+delay
            if not urgent and self.elapsed<until:
                self.coverage_deferred_until[floor] = until
            else:
                missing.append(floor)
        if not missing:
            self.coverage_reason = '观察楼层服务空窗与需求变化，延迟补位以减少往返' if deficits else ''
            self._coverage_check = self._coverage_job = None
            return
        check = (tuple(sorted(projected.items())),tuple(missing),tuple(counts.items()),tuple(self.coverage_targets.items()),
                 self.planning_environment(),self.policy_revision,self.elevator_risk_revision,
                 tuple((r.robot_id,r.xy,r.robot_id in self.parking_pending or r.robot_id in self.parking_moves,
                        r.robot_id in self.elevator_requests,r.robot_id in self.passage_escapes,
                        self.relocation_until.get(r.robot_id,0.)>self.elapsed,round(self.available_battery(r)[0],6))
                       for r in self.robots if not r.task_id))
        if check!=self._coverage_check:
            self._coverage_check = check
            self.coverage_reason = ''
            self._coverage_job = self._find_coverage_move(projected,counts,missing)
        if self._coverage_job is None:
            return
        started = time.perf_counter()
        try:
            while time.perf_counter()-started<self.planning_budget_seconds:
                next(self._coverage_job)
        except StopIteration:
            self._coverage_job = None

    def _find_coverage_move(self, projected, counts, missing):
        candidates = []
        reasons = set()
        for robot in self.robots:
            identity = robot.robot_id
            if (robot.task_id or identity in self.parking_moves or identity in self.parking_pending or
                robot.status=='charging' or identity in self.elevator_requests or identity in self.passage_escapes or
                counts[projected[identity]]<=1):
                continue
            if not self.basic_service_capable(identity):
                reasons.add('补位车辆不具备基本巡查能力或安全电量')
                continue
            model = self.models[self.robot_instances[identity]['model_id']]
            charge,reserve = self.available_battery(robot)
            if charge<=reserve:
                reasons.add('补位车辆电量不足')
                continue
            for destination in missing:
                urgent = any(t.status=='pending' and self.task_specs[t.task_id]['release']<=self.elapsed and
                    self.services[t.bed_id][0]==destination and self.is_urgent(self.task_specs[t.task_id]) for t in self.tasks)
                if self.relocation_until.get(identity,0.)>self.elapsed and not urgent:
                    reasons.add('跨层调动后的稳定期尚未结束')
                    continue
                if any(t.status=='pending' and self.task_specs[t.task_id]['robot_id']==identity and
                    self.task_specs[t.task_id]['release']<=self.elapsed+self.dispatch_policy.relocation_cooldown_seconds
                    for t in self.tasks):
                    reasons.add('车辆近期有指定巡查任务')
                    continue
                if counts[destination]>0 and not any(t.status=='pending' and self.services[t.bed_id][0]==destination and
                    self.task_specs[t.task_id]['release']<=self.elapsed+self.dispatch_policy.demand_horizon_seconds and
                    self.task_specs[t.task_id]['robot_id'] in (None,identity) and
                    set(self.task_specs[t.task_id]['capabilities']).issubset(model['capabilities']) for t in self.tasks):
                    reasons.add('额外支援车辆无法处理目标楼层的待执行任务')
                    continue
                incoming = min((seconds for key,(floor,seconds) in self._readiness.items()
                                if key!=identity and floor==destination),default=math.inf)
                found_point = False
                for obj,point in self._standby_points(destination,robot):
                    found_point = True
                    route,reason = self.find_robot_route(robot,model,destination,point)
                    if not route:
                        reasons.add(reason)
                        yield
                        continue
                    seconds,distance,actions = route
                    wait_margin = 0. if urgent else self.dispatch_policy.support_gain_seconds
                    if counts[destination]==0 and incoming<=seconds+wait_margin:
                        reasons.add('本层车辆将先于补位车辆恢复服务')
                        yield
                        continue
                    if counts[destination]>0 and not urgent:
                        work = self.coverage_workload[destination]
                        gain = work/counts[destination]-(seconds+work/(counts[destination]+1))
                        if gain<self.dispatch_policy.support_gain_seconds:
                            reasons.add('额外支援的预计收益不足以抵消跨层开销')
                            yield
                            continue
                    required = self.parking_requirement(robot,model,destination,point,distance,charge,reserve)
                    if required>charge+1e-9:
                        reasons.add('补位后缺少电量充足且可达的停车点')
                        yield
                        continue
                    score = (self.elevator_rides(actions),obj['kind']!='parking',seconds,distance,identity,destination,obj['id'])
                    candidates.append((score,robot,destination,obj,point,actions))
                    yield
                if not found_point:
                    reasons.add('目标楼层没有未占用的安全待命点')
        if not candidates:
            shortage = max(0,len(self.floors)-len(self.robots))
            service_shortage = max(0,len(self.floors)-sum(self.basic_service_capable(r.robot_id) for r in self.robots))
            self.coverage_reason = (f'机器人数量少于楼层数，至少 {shortage} 层无法同时驻留' if shortage else
                '具备基本能力及安全电量的机器人不足，暂不能补齐接单能力' if service_shortage else
                '暂不能补齐楼层驻留：'+('；'.join(sorted(reasons)) or '等待车辆安全释放或配置可达的待命点'))
            return
        score,robot,destination,obj,point,actions = min(candidates,key=lambda item:item[0])
        self._coverage_counter += 1
        task = PatrolTask(f'COV{self._coverage_counter:04d}',obj['id'],point,self.elapsed,
                          status='assigned',robot_id=robot.robot_id,assigned_at=self.elapsed)
        self.coverage_moves[robot.robot_id] = dict(task=task,floor_id=destination,point_id=obj['id'],
                                                  elevator_rides=score[0])
        robot.task_id,robot.status = task.task_id,'moving'
        self.connect_robot_route(robot,actions)
        self.coverage_revision += 1
        self.coverage_reason = ''
        self.emit('coverage_move_started',robot,task,floor_id=destination,elevator_rides=score[0],
                  reason='服务空窗或工作量缺口持续存在，从仍有基本接单能力的楼层调车支援')

    def floor_coverage_snapshot(self, plan):
        current = Counter(self.robot_floors.values())
        projected = self.projected_robot_floors()
        for identity in projected:
            visits = [item for item in plan.values() if item['robot_id']==identity]
            if visits:
                final = max(visits,key=lambda item:item['sequence'])
                projected[identity] = final['legs'][-1]['floor_id']
        future = Counter(projected.values())
        return dict(counts={key:current[key] for key in self.floors},
                    projected_counts={key:future[key] for key in self.floors},
                    missing_floors=[key for key in self.floors if not current[key]],
                    projected_missing_floors=[key for key in self.floors if not future[key]],
                    robot_shortage=max(0,len(self.floors)-len(self.robots)),reason=self.coverage_reason,
                    service_robot_shortage=max(0,len(self.floors)-sum(self.basic_service_capable(r.robot_id) for r in self.robots)),
                    ready_counts=dict(self.coverage_ready),target_counts=dict(self.coverage_targets),
                    workload_seconds=dict(self.coverage_workload),deferred_until=dict(self.coverage_deferred_until),
                    vacancy_seconds={floor:round(self.elapsed-since,3) if since is not None else 0.
                                     for floor,since in self.vacancy_since.items()},
                    total_unavailable_seconds={floor:round(value,3) for floor,value in self.coverage_empty_seconds.items()},
                    max_unavailable_seconds={floor:round(value,3) for floor,value in self.coverage_max_empty_seconds.items()},
                    preparing=self._coverage_job is not None,
                    moves=[dict(robot_id=key,floor_id=value['floor_id'],point_id=value['point_id'],
                                elevator_rides=value['elevator_rides'],task=asdict(value['task']))
                           for key,value in self.coverage_moves.items()])
