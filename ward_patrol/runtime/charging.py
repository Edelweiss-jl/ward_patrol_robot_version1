"""Automatic charging on shared parking points."""
import math
from types import SimpleNamespace

from ward_patrol.maps.geometry import charger_approach, charger_placement_error
from ward_patrol.simulation.dual_robot_demo import PatrolTask

CHARGE_TRIGGER_MARGIN = 5.0
CHARGE_TARGET = 80.0
DOCK_RESERVE = 1.0
CROSS_FLOOR_MARGIN_SECONDS = 3.0


class ChargingExecution:
    def configure_charging(self):
        self.chargers = {key: point for key, point in self.parking_resources.items() if 'charger' in point}
        self.charge_reservations = {}
        self.charge_jobs = {}
        self.charge_requested = set()
        self.charge_waits = {}
        self.charge_credit = {}
        self.charge_retry = {}
        self.charge_avoid = {}
        self.next_charge_check = 0.
        self.charge_counter = 0

    def task_for(self, robot):
        job = getattr(self, 'charge_jobs', {}).get(robot.robot_id)
        return job['task'] if job else super().task_for(robot)

    def task_floor(self, task):
        job = self.charge_jobs.get(task.robot_id)
        return job['floor'] if job and job['task'] is task else super().task_floor(task)

    def unavailable_for_patrol(self, identity):
        return identity in self.charge_jobs or identity in self.charge_waits

    def charge_target(self, reserve):
        return min(100., max(CHARGE_TARGET, reserve + 2 * CHARGE_TRIGGER_MARGIN))

    def charger_route(self, robot, key, origin=None):
        floor, _ = key
        point = self.chargers[key]
        model = self.models[self.robot_instances[robot.robot_id]['model_id']]
        planner = self.planning_on(floor, model)
        if charger_placement_error(self.floors[floor], point, planner):
            return None
        goal = point['x'], point['y']
        approach = charger_approach(point, planner.radius)
        route, _ = self.find_robot_route(robot, model, floor, approach, origin=origin)
        if not route:
            return None
        seconds, meters, actions = route
        docking = math.dist(approach, goal)
        return seconds + docking / model['speed'], meters + docking, (*actions[:-1], [*actions[-1], goal])

    def patrol_energy_needed(self, identity, floor, goal, meters):
        if self.chargers:
            probe = SimpleNamespace(robot_id=identity, xy=goal)
            distances = (route[1] for key in self.chargers if (route := self.charger_route(probe, key, origin=floor)))
            meters += min(distances, default=math.inf)
        return meters * self.battery_use_per_meter

    def _charger_clear(self, robot, key):
        floor, _ = key
        point = self.chargers[key]
        position = point['x'], point['y']
        return all(other is robot or self.robot_floors[other.robot_id] != floor or
                   math.dist(other.xy, position) > self.planners[robot.robot_id].radius + self.planners[other.robot_id].radius
                   for other in self.robots)

    def _charge_wait(self, robot, reason):
        identity = robot.robot_id
        if self.charge_waits.get(identity) != reason:
            self.charge_waits[identity] = reason
            self.coverage_revision += 1
            self.emit('charging_waiting', robot, reason=reason)
        robot.status = 'waiting_charge'

    def _charge_route_start(self, robot, job, floor, goal, actions, phase):
        self.charge_counter += 1
        task = PatrolTask(f'CHARGE{self.charge_counter:04d}', job['dock'][1], goal, self.elapsed,
                          status='assigned', robot_id=robot.robot_id, assigned_at=self.elapsed)
        job.update(task=task, floor=floor, phase=phase, progress_at=self.elapsed, progress_m=robot.distance)
        robot.task_id, robot.status = task.task_id, 'moving'
        self.connect_robot_route(robot, actions)
        self.coverage_revision += 1

    def schedule_charging(self):
        if not self.chargers or self.elapsed < self.next_charge_check:
            return
        self.next_charge_check = self.elapsed + .5
        robots = sorted(self.robots, key=lambda robot: (self.available_battery(robot)[0], robot.robot_id))
        for robot in robots:
            identity = robot.robot_id
            if (self.robot_floors[identity] is None or identity in self.elevator_requests
                    or self.parking_preemption_blocked(robot) or self.robot_has_passage(identity)
                    or self.elapsed < self.charge_retry.get(identity, 0.)):
                continue
            charge, reserve = self.available_battery(robot)
            if robot.task_id and not self._release_patrol_for_charge(robot, charge, reserve):
                continue
            if charge > min(self.charge_target(reserve) - 1., reserve + CHARGE_TRIGGER_MARGIN) and identity not in self.charge_requested:
                continue
            candidates = []
            reachable = []
            for key, point in self.chargers.items():
                if self.elapsed < self.charge_avoid.get((identity, key), 0.):
                    continue
                route = self.charger_route(robot, key)
                if not route or (route[1] > 0 and charge - route[1] * self.battery_use_per_meter < DOCK_RESERVE - 1e-9):
                    continue
                reachable.append(key)
                owner = self.charge_reservations.get(key)
                free = owner is None and self._charger_clear(robot, key)
                delay = 0.
                if not free:
                    job = self.charge_jobs.get(owner)
                    if not job or job['phase'] != 'charging':
                        continue
                    remaining = job['target'] - self.available_battery(self.by_robot[owner])[0]
                    delay = remaining * 60 / point['charger']['rate'] + 4.
                start = max(route[0], delay)
                cross_floor = key[0] != self.robot_floors[identity]
                candidates.append((start + CROSS_FLOOR_MARGIN_SECONDS * cross_floor, cross_floor, not free, key, route))
            if not candidates:
                if identity in self.parking_moves:
                    continue
                self._charge_wait(robot, '无可安全到达的空闲充电桩，等待资源或人工处理')
                self._park_while_waiting(robot, reachable)
                continue
            _, _, busy, key, (_, _, actions) = min(candidates)
            if busy:
                if identity in self.parking_moves:
                    continue
                self._charge_wait(robot, '等待充电桩释放')
                self._park_while_waiting(robot, reachable)
                continue
            self.charge_waits.pop(identity, None)
            self.leave_parking(robot)
            self.charge_requested.discard(identity)
            self.charge_reservations[key] = identity
            job = self.charge_jobs[identity] = dict(dock=key, target=self.charge_target(reserve))
            point = self.chargers[key]
            self._charge_route_start(robot, job, key[0], (point['x'], point['y']), actions, 'to_charger')
            self.emit('charger_reserved', robot, charger_id=key[1], floor_id=key[0],
                      reason='已预约充电点并规划行驶路线')

    def _release_patrol_for_charge(self, robot, charge, reserve):
        identity = robot.robot_id
        task = self.task_for(robot)
        if (identity in self.charge_jobs or not task or task.task_id not in self.task_specs
                or task.task_id in self.service_started or identity in self.yield_paths):
            return False
        floor, goal, remaining, _ = self._remaining_work(robot)
        needed = self.patrol_energy_needed(identity, floor, goal, remaining)
        if charge - needed >= reserve - 1e-9:
            return False
        self.release_task_robot(robot, task, 'recharge')
        self.task_released(task, 'recharge')
        task.status, task.robot_id, task.assigned_at = 'pending', None, None
        self.attempts[task.task_id] = self.attempts.get(task.task_id, 1) + 1
        self.charge_requested.add(identity)
        self.coverage_revision += 1
        self.emit('patrol_deferred_for_charging', robot, task, reason='路线变化后安全电量不足，任务退回队列')
        return True

    def charge_transit_safe(self, robot):
        identity = robot.robot_id
        job = self.charge_jobs.get(identity)
        if not job or job['phase'] != 'to_charger' or self.robot_has_passage(identity):
            return True
        request = self.elevator_requests.get(identity)
        if request:
            lift = self.elevators[request.ride.elevator_id]
            if request in lift.riders or lift.permit is request:
                return True
            if (self.step - request.arrived_step) * self.sim_dt > 30:
                self._stop_charge_route(robot, '等梯时间过长，重新选择充电桩')
                return False
        _, _, meters, _ = self._remaining_work(robot)
        if meters > .01 and self.available_battery(robot)[0] - meters * self.battery_use_per_meter < DOCK_RESERVE - 1e-9:
            self._stop_charge_route(robot, '剩余电量无法安全到达充电桩，车辆已停靠')
            return False
        return True

    def _release_charger(self, identity, key):
        if self.charge_reservations.get(key) == identity:
            del self.charge_reservations[key]
            self.emit('charger_released', self.by_robot[identity], charger_id=key[1], floor_id=key[0])

    def _stop_charge_route(self, robot, reason):
        identity = robot.robot_id
        job = self.charge_jobs.pop(identity)
        self.release_elevator_task(job['task'])
        self.route_actions.pop(identity, None)
        robot.task_id, robot.path = None, []
        self.velocities[identity] = 0.
        self.wait_reasons.pop(job['task'].task_id, None)
        self.lidars[identity].replan_goal = self.lidars[identity].blocked_since = None
        self._release_charger(identity, job['dock'])
        self.coverage_revision += 1
        self.last_dispatch = -math.inf
        if reason:
            self.charge_requested.add(identity)
            self.charge_retry[identity] = self.elapsed + 1.
            self.charge_avoid[identity, job['dock']] = self.elapsed + 8.
            self._charge_wait(robot, reason)
        else:
            robot.status = 'idle'

    def coverage_route_failed(self, robot, task):
        job = self.charge_jobs.get(robot.robot_id)
        if job and job['task'] is task:
            if job['phase'] == 'leaving':
                self._stop_charge_route(robot, None)
            else:
                self._stop_charge_route(robot, '电梯路线不可用，等待重新找桩')
        else:
            super().coverage_route_failed(robot, task)

    def _leave_charger(self, robot, job):
        if not self._send_to_parking(robot, job):
            robot.status = 'charging_exit_blocked'

    def _park_while_waiting(self, robot, reachable):
        if not reachable:
            return
        identity = robot.robot_id
        floor = self.robot_floors[identity]
        if any(key[0] == floor and key not in self.chargers and
               math.dist(robot.xy, (point['x'], point['y'])) < .15
               for key, point in self.parking_resources.items()):
            return
        job = {'dock': reachable[0]}
        if self._send_to_parking(robot, job, reachable):
            self.charge_jobs[identity] = job

    def _send_to_parking(self, robot, job, reachable=()):
        identity = robot.robot_id
        floor = self.robot_floors[identity]
        instance = self.robot_instances[identity]
        model = self.models[instance['model_id']]
        owned = {(item['floor_id'], item['parking_id']) for key, item in self.robot_instances.items() if key != identity}
        owned.update(other['parking'] for key, other in self.charge_jobs.items()
                     if key != identity and other['phase'] in ('leaving', 'waiting_parking'))
        options = [key for key in self.parking_resources if key not in owned and key not in self.chargers
                   and self._parking_open(robot, key)
                   and (key[0] == floor or (not reachable and key == (instance['floor_id'], instance['parking_id'])))]
        charge, reserve = self.available_battery(robot)
        candidates = []
        for key in options:
            point = self.parking_resources[key]
            position = point['x'], point['y']
            if any(other is not robot and self.robot_floors[other.robot_id] == key[0]
                   and math.dist(other.xy, position) <= self.planners[identity].radius + self.planners[other.robot_id].radius
                   for other in self.robots):
                continue
            route, _ = self.find_robot_route(robot, model, key[0], position)
            if not route:
                continue
            arrival = charge - route[1] * self.battery_use_per_meter
            if reachable:
                probe = SimpleNamespace(robot_id=identity, xy=position)
                can_continue = any(arrival - result[1] * self.battery_use_per_meter >= DOCK_RESERVE
                                   for dock in reachable if (result := self.charger_route(probe, dock, origin=key[0])))
                if not can_continue:
                    continue
            elif arrival < reserve:
                continue
            candidates.append((key[0] != floor, route[0], key, position, route[2]))
        if not candidates:
            return False
        _, _, key, position, actions = min(candidates)
        job['parking'] = key
        self._charge_route_start(robot, job, key[0], position, actions, 'waiting_parking' if reachable else 'leaving')
        return True

    def advance_charge_job(self, robot):
        identity = robot.robot_id
        job = self.charge_jobs.get(identity)
        if not job:
            return False
        task, key, phase = job['task'], job['dock'], job['phase']
        point = self.chargers[key]
        at_goal = self.robot_floors[identity] == job['floor'] and math.dist(robot.xy, task.goal) < .01
        if phase == 'waiting_parking' and at_goal:
            self._stop_charge_route(robot, None)
            robot.status = 'waiting_charge'
            return True
        if phase == 'leaving':
            distance = math.dist(robot.xy, (point['x'], point['y']))
            if self.robot_floors[identity] != key[0] or distance > 2 * self.planners[identity].radius:
                self._release_charger(identity, key)
            if at_goal:
                self._stop_charge_route(robot, None)
                return True
        if at_goal and phase == 'to_charger':
            heading = math.radians(point.get('rotation', 0))
            error = (heading - self.headings[identity] + math.pi) % (2 * math.pi) - math.pi
            model = self.models[self.robot_instances[identity]['model_id']]
            turn = min(abs(error), model['angular_speed'] * self.sim_dt)
            self.headings[identity] += math.copysign(turn, error)
            self.place_robot(robot, robot.xy, self.floor_z[key[0]])
            if abs(error) > turn + 1e-9:
                robot.status = 'docking'
                return True
            self.velocities[identity] = 0.
            robot.path.clear()
            job['phase'] = phase = 'charging'
            self.emit('charging_started', robot, charger_id=key[1], floor_id=key[0])
        if phase == 'charging':
            charge, _ = self.available_battery(robot)
            delta = min(job['target'] - charge, point['charger']['rate'] * self.sim_dt / 60)
            self.charge_credit[identity] = self.charge_credit.get(identity, 0.) + max(0., delta)
            robot.status = 'charging'
            if charge + delta >= job['target'] - 1e-9:
                job.update(phase='charged', next_exit=self.elapsed)
                self.emit('charging_completed', robot, charger_id=key[1], floor_id=key[0],
                          battery_percent=round(charge + delta, 2))
            return True
        if phase == 'charged':
            if self.elapsed >= job['next_exit']:
                job['next_exit'] = self.elapsed + 1.
                self._leave_charger(robot, job)
            return True
        if robot.distance > job['progress_m'] + .01:
            job.update(progress_m=robot.distance, progress_at=self.elapsed)
        if (self.elapsed - job['progress_at'] > 10 and identity not in self.elevator_requests
                and not self.robot_has_passage(identity)):
            if phase == 'waiting_parking':
                self._stop_charge_route(robot, '无法到达待命停车点，等待充电资源')
            elif phase == 'leaving' and self.charge_reservations.get(key) != identity:
                self._stop_charge_route(robot, None)
            elif phase == 'leaving':
                job.update(phase='charged', next_exit=self.elapsed + 1.)
                robot.path.clear()
                self.route_actions.pop(identity, None)
            else:
                self._stop_charge_route(robot, '前往充电桩的路线受阻，重新选择充电桩')
            return True
        self.move_robot(robot, task)
        return True

    def charging_snapshot(self):
        return [dict(id=key[1], floor_id=key[0], **point['charger'],
                     robot_id=(owner := self.charge_reservations.get(key)),
                     status=self.charge_jobs[owner]['phase'] if owner else 'free')
                for key, point in self.chargers.items()]
