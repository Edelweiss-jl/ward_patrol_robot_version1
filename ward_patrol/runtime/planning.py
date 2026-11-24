"""Cooperative, deterministic look-ahead queues for the editable fleet.

Queues are estimates, not execution reservations. The existing dispatcher still
checks release time, bed exclusion, geometry, resources and battery at departure.
"""
from copy import deepcopy
from collections import deque
import heapq
import math
import time
from types import SimpleNamespace

from ward_patrol.runtime.elevator import Ride, path_length


class FleetPlanning:
    planning_budget_seconds = .008

    def configure_planning(self):
        self.dispatch_plan = {}
        self._plan_job = None
        self._plan_key = None
        self.planning_metrics = dict(status='idle', revision=0, planned=0,
                                     computation_ms=0., last_slice_ms=0.,improvements=0,improvement_ms=0.)

    def planning_environment(self):
        closures = tuple(sorted((key, item['floor_id'],item['x'],item['y'],item['width'],item['height'])
                                for key,item in self.road_closures.items()))
        observed = tuple(sorted((floor,tuple(sorted({tuple(cell)
            for report in self.observed_blockages.values() if report['floor_id']==floor
            for cell in report['cells']}))) for floor in self.floors))
        lifts = tuple((key,lift.mode,tuple(sorted(lift.blocked_exits))) for key,lift in sorted(self.elevators.items()))
        return closures,observed,lifts

    def planning_key(self):
        # Normal progress deliberately does not invalidate all downstream routes.
        # Cancellation, retries, new work and changed navigation rules do.
        tasks = tuple((t.task_id,t.status=='cancelled',self.attempts.get(t.task_id,1),
                       self.task_specs[t.task_id]['release']<=self.elapsed) for t in self.tasks)
        escaping = tuple(r.robot_id for r in self.robots if r.task_id is None and self.parking_preemption_blocked(r))
        period = int(self.elapsed/self.dispatch_policy.replan_interval_seconds) if any(t.status=='pending' for t in self.tasks) else 0
        return (tasks,self.planning_environment(),escaping,self.coverage_revision,self.policy_revision,
                self.elevator_risk_revision,period,int(self.elapsed//3600)%24)

    def advance_planning(self):
        key = self.planning_key()
        if key != self._plan_key:
            self._plan_key = key
            self.dispatch_plan = {}
            self._plan_job = self._build_fleet_plan()
            self.planning_metrics.update(status='planning',revision=self.planning_metrics['revision']+1,
                                         planned=0,computation_ms=0.,improvements=0,improvement_ms=0.)
        if self._plan_job is None:
            return
        start = time.perf_counter()
        try:
            # Yield after every candidate route. The budget bounds work between
            # searches; a single cold A* search can exceed the slice budget.
            while time.perf_counter()-start < self.planning_budget_seconds:
                next(self._plan_job)
        except StopIteration:
            self._plan_job = None
            self.planning_metrics['status'] = 'ready'
        duration = (time.perf_counter()-start)*1000
        self.planning_metrics['last_slice_ms'] = round(duration,3)
        self.planning_metrics['computation_ms'] = round(self.planning_metrics['computation_ms']+duration,3)
        self.planning_metrics['planned'] = len(self.dispatch_plan)

    def _remaining_work(self, robot, *, include_parking=False):
        task = self.task_for(robot)
        if task is None or (not include_parking and robot.robot_id in self.parking_moves
                            and not self.parking_preemption_blocked(robot)):
            return self.robot_floors[robot.robot_id],robot.xy,0.,0.
        model = self.models[self.robot_instances[robot.robot_id]['model_id']]
        distance = path_length([robot.xy,*robot.path])
        lift_seconds = 0.
        request = self.elevator_requests.get(robot.robot_id)
        if request:
            lift = self.elevators[request.ride.elevator_id]
            if lift.phase!='exiting' or lift.rider is not request:
                distance += path_length(request.ride.clearance)
                if request in lift.riders:
                    if lift.phase in ('boarding','permission'):
                        floors = abs(self.floor_levels[request.ride.origin]-self.floor_levels[request.ride.destination])
                        lift_seconds += max(0,lift.boarding_deadline-self.step)*self.sim_dt+2*floors+1
                    else:
                        lift_seconds += max(0,lift.motion_total-lift.motion_steps)*self.sim_dt+1
                    if lift.mode=='fault' or request.ride.destination in lift.blocked_exits:
                        lift_seconds += self.elevator_wait_estimate(request.ride.elevator_id,request.ride.origin)
                else:
                    lift_seconds += (2*abs(self.floor_levels[request.ride.origin]-self.floor_levels[request.ride.destination])+1+
                                     self.elevator_wait_estimate(request.ride.elevator_id,request.ride.origin))
        for action in self.route_actions.get(robot.robot_id,[]):
            if isinstance(action,Ride):
                distance += path_length(action.clearance)
                lift_seconds += (2*abs(self.floor_levels[action.origin]-self.floor_levels[action.destination])+1+
                                 self.elevator_wait_estimate(action.elevator_id,action.origin))
            else:
                distance += path_length(action)
        spec = self.task_specs.get(task.task_id)
        budget = self.service_estimate(spec) if spec else 0.
        service = max(0.,budget-(self.elapsed-self.service_started.get(task.task_id,self.elapsed)))
        if spec and spec['service']!='dwell' and service<=0 and task.status=='assigned':
            service = max(budget,self.dispatch_policy.coverage_ready_seconds+self.dispatch_policy.response_seconds)
        return self.task_floor(task),task.goal,distance,distance/model['speed']+lift_seconds+service

    def _route_legs(self, origin, actions):
        legs, floor = [],origin
        for action in actions:
            if isinstance(action,Ride):
                floor = action.destination
                legs.append(dict(floor_id=floor,path=deepcopy(action.clearance)))
            else:
                legs.append(dict(floor_id=floor,path=deepcopy(action)))
        return legs

    def task_order_key(self, task):
        spec = self.task_specs[task.task_id]
        return (spec['release']>self.elapsed,spec['release'] if spec['release']>self.elapsed else 0.,
                -spec['priority'],spec['deadline'] if spec['deadline'] is not None else math.inf,
                task.created_at,task.task_id)

    def _spatial_next(self, pending, previous, spatial, remaining, states):
        first = pending[0]
        if previous is None or previous['size']>=self.dispatch_policy.spatial_batch_size:
            return first,None
        identity = previous['robot_id']
        model = self.models[self.robot_instances[identity]['model_id']]
        if self.task_order_key(first)[:4]!=previous['order']:
            return first,None
        compatible = []
        for (_,capabilities,pinned),queue in spatial.get((previous['order'],previous['floor_id']),{}).items():
            while queue and queue[0].task_id not in remaining:
                queue.popleft()
            if queue and (not pinned or pinned==identity) and set(capabilities).issubset(model['capabilities']):
                compatible.append(queue[0])
        # Euclidean distance is a shortlist bound only. Membership and ordering
        # use actual directed floor paths, including walls and one-way regions.
        compatible = heapq.nsmallest(self.dispatch_policy.spatial_candidates,compatible,
            key=lambda task:(math.dist(previous['goal'],task.goal),task.created_at,task.task_id))
        positioned = {(state['floor'],tuple(state['position'])) for state in states.values()}
        if compatible and all((previous['floor_id'],tuple(task.goal)) in positioned for task in compatible):
            # These beds already have a queue ending at the same point. Keep
            # their zero-travel continuation instead of searching between rooms.
            return first,None
        best = None
        planner = self.planning_on(previous['floor_id'],model)
        for task in compatible:
            if math.dist(previous['goal'],task.goal)>self.dispatch_policy.spatial_radius_m:
                break
            path = planner.route(previous['goal'],task.goal)['path']
            distance = path_length(path) if path else math.inf
            if distance<=self.dispatch_policy.spatial_radius_m:
                candidate = (distance,task.created_at,task.task_id,task)
                if best is None or candidate[:3]<best[:3]:
                    best = candidate
            yield
            if best is not None and best[0]<1e-9:
                break
        return (best[3],identity) if best else (first,None)

    def _build_fleet_plan(self):
        states,bed_ready = {},{}
        projected = self.projected_robot_floors()
        for robot in self.robots:
            if self.unavailable_for_patrol(robot.robot_id):
                continue
            if robot.task_id is None and self.parking_preemption_blocked(robot):
                continue
            floor,position,distance,seconds = self._remaining_work(robot)
            charge,reserve = self.available_battery(robot)
            states[robot.robot_id] = dict(floor=floor,position=position,available=self.elapsed+seconds,
                charge=charge-distance*self.battery_use_per_meter,reserve=reserve,sequence=0)
            task = self.task_for(robot)
            if task and robot.robot_id not in self.parking_moves:
                bed_ready[task.bed_id] = self.elapsed+seconds

        pending = sorted((t for t in self.tasks if t.status=='pending'),key=self.task_order_key)
        remaining = {task.task_id for task in pending}
        spatial = {}
        for task in pending:
            spec = self.task_specs[task.task_id]
            bucket = self.task_order_key(task)[:4],self.services[task.bed_id][0]
            point = tuple(task.goal),tuple(sorted(spec['capabilities'])),spec['robot_id']
            spatial.setdefault(bucket,{}).setdefault(point,deque()).append(task)
        previous = None
        while pending:
            task,affinity = yield from self._spatial_next(pending,previous,spatial,remaining,states)
            pending.remove(task)
            remaining.remove(task.task_id)
            if task.status!='pending':
                continue
            spec = self.task_specs[task.task_id]
            service = self.service_estimate(spec)
            destination,_ = self.services[task.bed_id]
            candidates = []
            def lower_bound(item):
                identity,state = item
                model = self.models[self.robot_instances[identity]['model_id']]
                travel = math.dist(state['position'],task.goal)/model['speed'] if state['floor']==destination else 0.
                finish = max(self.elapsed,state['available'],spec['release'],bed_ready.get(task.bed_id,0.))+travel+service
                return self.assignment_rank(projected,identity,destination,int(state['floor']!=destination),
                                            finish,spec['deadline'],priority=spec['priority'],
                                            released_at=max(task.created_at,spec['release']),service=service,origin=state['floor'],affinity=affinity)

            for identity,state in sorted(states.items(),key=lambda item:(lower_bound(item),item[0])):
                model = self.models[self.robot_instances[identity]['model_id']]
                if (spec['robot_id'] and spec['robot_id']!=identity or
                    not set(spec['capabilities']).issubset(model['capabilities']) or state['charge']<state['reserve']-1e-9):
                    continue
                if candidates and lower_bound((identity,state))>min(item[0] for item in candidates):
                    continue
                planner = self.planner_on(destination,model)
                if any(gate.floor_id==destination and planner.inside(task.goal,gate.region,planner.radius)
                       for gate in self.passages.values()):
                    continue
                virtual = SimpleNamespace(robot_id=identity,xy=state['position'])
                route,_ = self.find_robot_route(virtual,model,destination,task.goal,origin=state['floor'])
                if route:
                    seconds,distance,actions = route
                    required = self.parking_requirement(self.by_robot[identity],model,destination,task.goal,
                                                        distance,state['charge'],state['reserve'])
                    if required<=state['charge']+1e-9:
                        start = max(self.elapsed,state['available'],spec['release'],bed_ready.get(task.bed_id,0.))
                        finish = start+seconds+service
                        rank = self.assignment_rank(projected,identity,destination,self.elevator_rides(actions),
                                                    finish,spec['deadline'],distance,priority=spec['priority'],
                                                    released_at=max(task.created_at,spec['release']),service=service,origin=state['floor'],affinity=affinity)
                        candidates.append((rank,finish,distance,identity,start,actions))
                yield
            if not candidates or task.status!='pending':
                previous = None
                yield
                continue
            _,finish,distance,identity,start,actions = min(candidates,key=lambda item:item[0])
            state = states[identity]
            state['sequence'] += 1
            grouped = affinity==identity and previous is not None
            group_id = previous['group_id'] if grouped else task.task_id
            group_size = previous['size']+1 if grouped else 1
            self.dispatch_plan[task.task_id] = dict(robot_id=identity,sequence=state['sequence'],
                estimated_start=round(start,3),estimated_finish=round(finish,3),
                estimated_distance=round(distance,3),
                elevator_rides=self.elevator_rides(actions),
                elevator_wait_budget=self.route_wait_budget(actions),
                group_id=group_id,group_position=group_size,
                deadline_risk=spec['deadline'] is not None and finish>spec['deadline'],
                legs=self._route_legs(state['floor'],actions))
            state.update(floor=destination,position=task.goal,available=finish,
                         charge=state['charge']-distance*self.battery_use_per_meter)
            projected[identity] = destination
            bed_ready[task.bed_id] = finish
            previous = dict(robot_id=identity,floor_id=destination,goal=task.goal,group_id=group_id,size=group_size,
                            order=self.task_order_key(task)[:4])
            yield
        yield from self._improve_fleet_plan()

    def _plan_objective(self, plan):
        tasks = {task.task_id:task for task in self.tasks}
        late,excess = [],[]
        projected = self.projected_robot_floors()
        for key,visit in plan.items():
            spec = self.task_specs[key]
            late.append(max(0.,visit['estimated_finish']-spec['deadline']) if spec['deadline'] is not None else 0.)
            limit = self.dispatch_policy.urgent_response_seconds if self.is_urgent(spec) else self.dispatch_policy.response_seconds
            arrival = visit['estimated_finish']-self.service_estimate(spec)
            excess.append(max(0.,arrival-max(tasks[key].created_at,spec['release'])-limit))
        for identity in projected:
            queue = [item for item in plan.values() if item['robot_id']==identity]
            if queue:
                projected[identity] = max(queue,key=lambda item:item['sequence'])['legs'][-1]['floor_id']
        missing = len(self.floors)-len(set(floor for identity,floor in projected.items() if self.basic_service_capable(identity)))
        return (sum(value>1e-6 for value in late),round(sum(late),3),sum(value>1e-6 for value in excess),
                sum(int(value/max(1.,self.dispatch_policy.support_gain_seconds)) for value in excess),missing,
                sum(item['elevator_rides'] for item in plan.values()),
                round(sum(item['estimated_distance'] for item in plan.values()),3),
                max((item['estimated_finish'] for item in plan.values()),default=self.elapsed))

    def _improve_fleet_plan(self):
        if not self.dispatch_plan or not self.dispatch_policy.improvement_trials or not self.dispatch_policy.improvement_budget_ms:
            return
        queues = {robot.robot_id:[] for robot in self.robots}
        tasks = {task.task_id:task for task in self.tasks if task.status=='pending'}
        for key,visit in sorted(self.dispatch_plan.items(),key=lambda item:item[1]['sequence']):
            queues[visit['robot_id']].append(key)
        proposals = []
        identities = [key for key,value in queues.items() if value]
        # Exchange a few unstarted queue heads, then try adjacent visit swaps.
        for index,first in enumerate(identities):
            for second in identities[index+1:]:
                proposals.append((first,0,second,0))
        for identity in identities:
            proposals.extend((identity,index,identity,index+1) for index in range(min(3,len(queues[identity])-1)))
        budget = dict(used_ms=0.)
        best = self._plan_objective(self.dispatch_plan)
        trials = 0
        for first,a,second,b in proposals:
            if trials>=self.dispatch_policy.improvement_trials or budget['used_ms']>=self.dispatch_policy.improvement_budget_ms:
                break
            left,right = tasks.get(queues[first][a]),tasks.get(queues[second][b])
            if left is None or right is None or self.task_order_key(left)[:4]!=self.task_order_key(right)[:4]:
                continue
            if self.services[left.bed_id][0]!=self.services[right.bed_id][0]:
                continue
            trial = {key:list(value) for key,value in queues.items()}
            trial[first][a],trial[second][b] = trial[second][b],trial[first][a]
            trials += 1
            candidate = yield from self._replay_plan(trial,tasks,budget)
            if candidate is not None:
                score = self._plan_objective(candidate)
                if score<best:
                    self.dispatch_plan,queues,best = candidate,trial,score
                    self.planning_metrics['improvements'] += 1
        self.planning_metrics['improvement_ms'] = round(budget['used_ms'],3)

    def _replay_plan(self, queues, tasks, budget):
        states,bed_ready,result = {},{},{}
        for robot in self.robots:
            if self.unavailable_for_patrol(robot.robot_id):
                continue
            floor,position,distance,seconds = self._remaining_work(robot)
            charge,reserve = self.available_battery(robot)
            states[robot.robot_id] = dict(floor=floor,position=position,available=self.elapsed+seconds,
                charge=charge-distance*self.battery_use_per_meter,reserve=reserve)
            active = self.task_for(robot)
            if active and robot.robot_id not in self.parking_moves:
                bed_ready[active.bed_id] = self.elapsed+seconds
        indices = {key:0 for key in queues}
        while any(indices[key]<len(queue) for key,queue in queues.items()):
            started = time.perf_counter()
            if budget['used_ms']>=self.dispatch_policy.improvement_budget_ms:
                return None
            choices = [(self.task_order_key(tasks[queue[indices[key]]]),key) for key,queue in queues.items()
                       if indices[key]<len(queue)]
            _,identity = min(choices)
            key = queues[identity][indices[identity]]
            task,spec,state = tasks[key],self.task_specs[key],states[identity]
            model = self.models[self.robot_instances[identity]['model_id']]
            if ((spec['robot_id'] and spec['robot_id']!=identity) or
                not set(spec['capabilities']).issubset(model['capabilities']) or task.status!='pending'):
                return None
            floor = self.services[task.bed_id][0]
            planner = self.planner_on(floor,model)
            if any(gate.floor_id==floor and planner.inside(task.goal,gate.region,planner.radius) for gate in self.passages.values()):
                return None
            route,_ = self.find_robot_route(SimpleNamespace(robot_id=identity,xy=state['position']),model,
                                           floor,task.goal,origin=state['floor'])
            if route is None:
                budget['used_ms'] += (time.perf_counter()-started)*1000
                return None
            seconds,distance,actions = route
            required = self.parking_requirement(self.by_robot[identity],model,floor,task.goal,
                                                distance,state['charge'],state['reserve'])
            budget['used_ms'] += (time.perf_counter()-started)*1000
            if required>state['charge']+1e-9:
                return None
            start = max(self.elapsed,state['available'],spec['release'],bed_ready.get(task.bed_id,0.))
            finish = start+seconds+self.service_estimate(spec)
            previous_key = queues[identity][indices[identity]-1] if indices[identity] else None
            previous = result.get(previous_key)
            grouped = (previous is not None and previous['legs'][-1]['floor_id']==floor and
                       previous['group_position']<self.dispatch_policy.spatial_batch_size and
                       self.task_order_key(tasks[previous_key])[:4]==self.task_order_key(task)[:4] and
                       self.elevator_rides(actions)==0 and distance<=self.dispatch_policy.spatial_radius_m)
            result[key] = dict(robot_id=identity,sequence=indices[identity]+1,estimated_start=round(start,3),
                estimated_finish=round(finish,3),estimated_distance=round(distance,3),
                elevator_rides=self.elevator_rides(actions),elevator_wait_budget=self.route_wait_budget(actions),
                deadline_risk=spec['deadline'] is not None and finish>spec['deadline'],
                group_id=previous['group_id'] if grouped else key,
                group_position=previous['group_position']+1 if grouped else 1,
                legs=self._route_legs(state['floor'],actions))
            state.update(floor=floor,position=task.goal,available=finish,charge=state['charge']-distance*self.battery_use_per_meter)
            bed_ready[task.bed_id] = finish
            indices[identity] += 1
            yield
        return result

    def planning_snapshot(self):
        pending = {t.task_id for t in self.tasks if t.status=='pending'}
        valid = self._plan_key == self.planning_key()
        plan = {key:value for key,value in self.dispatch_plan.items() if key in pending} if valid else {}
        queues = {r.robot_id:[] for r in self.robots}
        for key,visit in sorted(plan.items(),key=lambda item:(item[1]['robot_id'],item[1]['sequence'])):
            queues[visit['robot_id']].append(key)
        metrics = dict(self.planning_metrics,planned=len(plan))
        if not valid:
            metrics['status'] = 'pending'
        return dict(dispatch_plan=deepcopy(plan),robot_queues=queues,planning=metrics)
