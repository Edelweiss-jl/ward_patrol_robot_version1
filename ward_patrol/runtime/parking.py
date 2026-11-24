"""Interruptible parking returns and simulated charging for the editable fleet."""
from dataclasses import dataclass
import math
from types import SimpleNamespace

from ward_patrol.simulation.dual_robot_demo import PatrolTask


CHARGE_THRESHOLD = 50.
CHARGE_PER_SECOND = 1.


@dataclass(frozen=True)
class ParkingRoute:
    spot: tuple
    goal: tuple
    seconds: float
    distance: float
    actions: tuple


class ParkingExecution:
    def configure_parking(self):
        self.parking_pending = set()
        self.parking_moves = {}
        self.parking_retry_at = {}
        self.parking_counter = 0
        self.recharged = {}
        self.charge_requested = set()

    def task_for(self, robot):
        move = getattr(self,'parking_moves',{}).get(robot.robot_id)
        return move['task'] if move else super().task_for(robot)

    def task_floor(self, task):
        move = self.parking_moves.get(task.robot_id)
        return move['spot'][0] if move and move['task'] is task else super().task_floor(task)

    def parking_preemption_blocked(self, robot):
        identity = robot.robot_id
        if identity in self.passage_escapes:
            return True
        request = self.elevator_requests.get(identity)
        if identity not in self.parking_moves:
            return request is not None
        return self.robot_has_passage(identity) or (
            request is not None and request in self.elevators[request.ride.elevator_id].riders)

    def _parking_open(self, robot, spot):
        floor, _ = spot
        point = self.parking_resources[spot]
        if 'charger' in point or any(other != robot.robot_id and job.get('parking') == spot
                                     for other, job in self.charge_jobs.items()):
            return False
        if any(other != robot.robot_id and move['spot']==spot for other,move in self.parking_moves.items()):
            return False
        if any(other != robot.robot_id and (move['floor_id'],move['point_id'])==spot
               for other,move in self.coverage_moves.items()):
            return False
        goal = point['x'],point['y']
        radius = self.planners[robot.robot_id].radius
        return not any(other is not robot and self.robot_floors[other.robot_id]==floor and
                       (self.planners[other.robot_id].inside(other.xy,point) or
                        math.dist(other.xy,goal)<=radius+self.planners[other.robot_id].radius+.05)
                       for other in self.robots)

    def _parking_routes(self, robot, model, origin, position, max_distance=math.inf):
        virtual = SimpleNamespace(robot_id=robot.robot_id,xy=position)
        for spot,point in sorted(self.parking_resources.items(),
                                 key=lambda item:(item[0][0]!=origin,item[0])):
            if not self._parking_open(robot,spot):
                continue
            floor,_ = spot
            goal = point['x'],point['y']
            if floor==origin and math.dist(position,goal)>max_distance+1e-9:
                continue
            planner = self.planner_on(floor,model)
            if any(gate.floor_id==floor and planner.inside(goal,gate.region,planner.radius)
                   for gate in self.passages.values()):
                continue
            # Use the same runtime route estimates for dispatch and actual returns.
            route,_ = self.find_robot_route(virtual,model,floor,goal,origin=origin,fastest=True)
            if route:
                seconds,distance,actions = route
                if distance<=max_distance+1e-9:
                    yield ParkingRoute(spot,goal,seconds,distance,actions)

    def parking_requirement(self, robot, model, floor, goal, travel, charge, reserve, *, allow_top_up=False):
        """Return the charge needed to reach the task and then a free parking point."""
        if self.chargers:
            return reserve + self.patrol_energy_needed(robot.robot_id, floor, goal, travel)
        ceiling = 100. if allow_top_up else charge
        remaining = (ceiling-reserve)/self.battery_use_per_meter-travel
        if remaining < -1e-9:
            return math.inf
        current_range = (charge-reserve)/self.battery_use_per_meter-travel
        required = math.inf
        for route in self._parking_routes(robot,model,floor,goal,remaining):
            required = min(required,reserve+(travel+route.distance)*self.battery_use_per_meter)
            if route.distance<=current_range+1e-9:
                return required
        return required

    def _parking_priority(self, identity, route, arrivals):
        floor,_ = route.spot
        if floor==self.robot_floors[identity]:
            return 0
        represented = any(other!=identity and other_floor==floor and eta<=route.seconds
                          for other,(other_floor,eta) in arrivals.items())
        return 2 if represented else 1

    def start_parking_returns(self):
        candidates = {}
        margins = {}
        for robot in self.robots:
            identity = robot.robot_id
            if (identity not in self.parking_pending or robot.task_id or
                self.parking_preemption_blocked(robot) or self.elapsed<self.parking_retry_at.get(identity,0.)):
                continue
            model = self.models[self.robot_instances[identity]['model_id']]
            charge,reserve = self.available_battery(robot)
            margins[identity] = charge-reserve
            distance = max(0.,margins[identity]/self.battery_use_per_meter)
            candidates[identity] = list(self._parking_routes(robot,model,self.robot_floors[identity],robot.xy,distance))
        if not candidates:
            return
        arrivals = self.service_arrivals()
        while candidates:
            identity = min(candidates,key=lambda key:(len(candidates[key]),margins[key],key))
            robot = self.by_robot[identity]
            routes = candidates.pop(identity)
            if not routes:
                if robot.status!='waiting_parking':
                    self.emit('parking_wait',robot,reason='暂时没有空闲且安全可达的停车点')
                robot.status = 'waiting_parking'
                self.parking_retry_at[identity] = self.elapsed+1.
                continue
            route = min(routes,key=lambda item:(self._parking_priority(identity,item,arrivals),item.seconds,item.spot))
            self._begin_parking_return(robot,route)
            arrivals = self.service_arrivals()
            for other,options in candidates.items():
                candidates[other] = [option for option in options if option.spot!=route.spot]

    def _begin_parking_return(self, robot, route):
        identity = robot.robot_id
        self.parking_counter += 1
        task = PatrolTask(f'PARK{self.parking_counter:04d}',route.spot[1],route.goal,self.elapsed,
                          status='assigned',robot_id=identity,assigned_at=self.elapsed)
        self.parking_moves[identity] = dict(spot=route.spot,task=task)
        self.parking_pending.remove(identity)
        self.parking_retry_at.pop(identity,None)
        robot.status = 'returning'
        self.connect_robot_route(robot,route.actions)
        self._parking_event('parking_return_started',robot,route.spot)

    def _parking_event(self, event, robot, spot):
        self.emit(event,robot,floor_id=spot[0],parking_id=spot[1])

    def leave_parking(self, robot):
        identity = robot.robot_id
        self.parking_pending.discard(identity)
        self.parking_retry_at.pop(identity,None)
        self.charge_requested.discard(identity)
        move = self.parking_moves.get(identity)
        if move:
            self.release_elevator_task(move['task'])
            self.release_passage_task(robot)
            self.parking_moves.pop(identity)
            self.route_actions.pop(identity,None)
            self.wait_reasons.pop(move['task'].task_id,None)
            self.velocities[identity] = 0.
            self.lidars[identity].blocked_since = None
            self.lidars[identity].replan_goal = None
        return move

    def parking_route_failed(self, robot, task):
        identity = robot.robot_id
        move = self.parking_moves.get(identity)
        if not move or move['task'] is not task:
            return False
        self.leave_parking(robot)
        robot.path,robot.status = [],'waiting_parking'
        self.parking_pending.add(identity)
        self.parking_retry_at[identity] = self.elapsed+1.
        self._parking_event('parking_wait',robot,move['spot'])
        return True

    def advance_parking_move(self, robot, task):
        spot = self.parking_moves[robot.robot_id]['spot']
        if not self.parking_preemption_blocked(robot) and not self._parking_open(robot,spot):
            self.parking_route_failed(robot,task)
        elif self.robot_floors[robot.robot_id]==spot[0] and math.dist(robot.xy,task.goal)<1e-6:
            self.leave_parking(robot)
            robot.path,robot.status = [],'parked'
            self._parking_event('parking_arrived',robot,spot)
            self.advance_charging(robot)
        else:
            self.move_robot(robot,task)

    def charging_spot(self, robot):
        if self.chargers or robot.status not in ('idle','parked','charging') or robot.robot_id in self.parking_pending:
            return None
        floor = self.robot_floors[robot.robot_id]
        return next((key for key,point in self.parking_resources.items() if key[0]==floor and
                     self.planners[robot.robot_id].inside(robot.xy,point)),None)

    def advance_charging(self, robot):
        spot = self.charging_spot(robot)
        if spot is None:
            return
        identity = robot.robot_id
        charge,reserve = self.available_battery(robot)
        if robot.status!='charging':
            robot.status = 'parked'
            if charge>=100. or (charge>=CHARGE_THRESHOLD and charge>reserve and identity not in self.charge_requested):
                return
            self.charge_requested.discard(identity)
            robot.status = 'charging'
            self._parking_event('charging_started',robot,spot)
        added = min(100.-charge,CHARGE_PER_SECOND*self.sim_dt)
        self.recharged[identity] = self.recharged.get(identity,0.)+added
        if charge+added>=100.-1e-9:
            self.charge_requested.discard(identity)
            robot.status = 'parked'
            self._parking_event('charging_completed',robot,spot)

    def robot_parking_snapshot(self, identity):
        move = self.parking_moves.get(identity)
        spot = move['spot'] if move else (None,None)
        return dict(parking_floor_id=spot[0],parking_id=spot[1],returning_to_parking=bool(move))
