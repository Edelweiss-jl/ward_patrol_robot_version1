"""Versioned elevator landings, route search, and fixed-step admission state."""
from dataclasses import dataclass, field
from heapq import heappop, heappush
from itertools import count
import json
import math

from ward_patrol.maps.elevators import DEFAULT_ELEVATOR_CAPACITY
from ward_patrol.maps.geometry import Planner
from ward_patrol.simulation.dual_robot_demo import DT


BOARDING_WAIT_SECONDS = 5


def xy(obj):
    return obj['x'], obj['y']


@dataclass(frozen=True)
class Landing:
    entrance: dict
    waiting: dict
    exit: dict


@dataclass(frozen=True)
class Ride:
    elevator_id: str
    origin: str
    destination: str
    clearance: tuple


@dataclass
class Request:
    robot_id: str
    task_id: str
    ride: Ride
    arrived_step: int
    permit_step: int = 0
    cancelled: bool = False


@dataclass
class Elevator:
    identity: str
    landings: dict
    floor: str
    queue: list = field(default_factory=list)
    batch: set = field(default_factory=set)
    direction: int = 0
    mode: str = 'enabled'
    phase: str = 'idle'
    riders: list = field(default_factory=list)
    permit: Request = None
    boarding_deadline: int = 0
    origin: str = None
    destination: str = None
    motion_steps: int = 0
    motion_total: int = 0
    blocked_exits: set = field(default_factory=set)
    external_busy_until: float = 0.
    name: str = ''
    capacity: int = DEFAULT_ELEVATOR_CAPACITY

    @property
    def rider(self):
        return self.riders[0] if self.riders else None

    def snapshot(self):
        return dict(id=self.identity, name=self.name or self.identity, floor_id=self.floor, mode=self.mode, phase=self.phase,
                    capacity=self.capacity,
                    service_direction=self.direction, origin_floor_id=self.origin,
                    destination_floor_id=self.destination,
                    progress=(self.motion_steps/self.motion_total if self.motion_total else None),
                    permit_robot_id=self.permit.robot_id if self.permit else None,
                    occupant_robot_id=self.rider.robot_id if self.rider else None,
                    occupant_robot_ids=[request.robot_id for request in self.riders],
                    waiting_robot_ids=[item.robot_id for item in self.queue],
                    service_floor_ids=list(self.landings),
                    blocked_exit_floors=sorted(self.blocked_exits),external_busy_until=self.external_busy_until)


def build_elevators(floors, catalog=None):
    shafts = {}
    definitions = {lift['id']:lift for lift in (catalog or [])}
    display_names = {identity:lift['name'] for identity,lift in definitions.items()}
    reserved_names = {name.casefold() for name in display_names.values()}
    reserved_names.update(item.get('shaft_id','').strip().casefold() for floor in floors.values()
                          for item in floor['objects'] if item['kind']=='elevator' and item.get('shaft_id','').strip())
    for identity,lift in definitions.items():
        for floor_id in lift['served_floors']:
            landing = lift.get('landings',{}).get(floor_id,{})
            if not landing.get('confirmed') or floor_id not in floors:
                continue
            by_id = {obj['id']:obj for obj in floors[floor_id]['objects']}
            pieces = [by_id.get(landing.get(key)) for key in ('entrance_id','waiting_id','exit_id')]
            if any(piece is None for piece in pieces):
                continue
            entrance = dict(pieces[0],service_floors=lift.get('legacy_connections',{}).get(floor_id,[])
                            if 'legacy_connections' in lift else list(lift['served_floors']))
            shafts.setdefault(identity,{})[floor_id] = Landing(entrance,pieces[1],pieces[2])
    for floor_id, floor in floors.items():
        by_id = {item['id']: item for item in floor['objects']}
        for item in floor['objects']:
            if item['kind'] != 'elevator' or item.get('lift_id'):
                continue
            # Existing unlinked entrances remain local until assigned a common shaft number.
            identity = item.get('shaft_id', '').strip() or item['id']
            if identity not in display_names:
                number = 1
                while f'E{number}'.casefold() in reserved_names:
                    number += 1
                name = item.get('shaft_id','').strip() or f'E{number}'
                display_names[identity] = name
                reserved_names.add(name.casefold())
            shafts.setdefault(identity, {})[floor_id] = Landing(item, by_id[item['waiting_id']], by_id[item['exit_id']])
    return {identity: Elevator(identity, landings, next(iter(landings)),name=display_names[identity],
                               capacity=definitions.get(identity,{}).get('capacity',DEFAULT_ELEVATOR_CAPACITY))
            for identity, landings in shafts.items()}


def path_length(path):
    return sum(math.dist(start,end) for start,end in zip(path,path[1:]))


def cross_floor_route(elevators, levels, planners, model, origin, start, destination, goal, wait_budgets=None,
                      *, fastest=False):
    """Search by ride count for patrols or by estimated travel time for parking."""
    source, target = (origin, 'start', ''), (destination, 'goal', '')
    nodes = {source:start, target:goal}
    passages = {}
    for lift in elevators.values():
        if lift.mode != 'enabled':
            continue
        for floor, landing in lift.landings.items():
            entry = landing.entrance
            if entry.get('models') and model['id'] not in entry['models']:
                continue
            if entry['width'] + 1e-9 < model['width'] + 2*model['margin']:
                continue
            planner = planners[floor]
            wait = xy(landing.waiting)
            exit_point = xy(landing.exit)
            if not planner.free(wait) or not planner.free(exit_point):
                continue
            reach = math.hypot(landing.exit['width'], landing.exit['height'])/2 + planner.radius + .2
            exits = [(exit_point[0]+reach*math.cos(i*math.pi/4),
                      exit_point[1]+reach*math.sin(i*math.pi/4)) for i in range(8)]
            clearance = []
            for point in sorted(exits, key=lambda p: math.dist(p,goal if floor==destination else wait)):
                if planner.segment(exit_point,point):
                    clearance = [exit_point,point]
                    break
            if not clearance:
                continue
            nodes[floor,'wait',lift.identity] = wait
            nodes[floor,'exit',lift.identity] = clearance[-1]
            passages[lift.identity,floor] = tuple(clearance)

    order = count()
    best = {source:(0,0.)}
    queue = [(best[source],next(order),source,(),0,0.,0.)]
    while queue:
        rank,_,node,actions,rides,cost,distance = heappop(queue)
        if rank != best[node]:
            continue
        if node == target:
            return cost, distance, actions
        floor, kind, identity = node
        edges = []
        for candidate, point in nodes.items():
            if candidate[0] != floor or candidate[1] not in ('wait','goal') or candidate == node:
                continue
            path = planners[floor].route(nodes[node],point)['path']
            if path:
                length = path_length(path)
                edges.append((candidate, length/model['speed'], length, path))
        if kind == 'wait':
            lift = elevators[identity]
            for other, landing in lift.landings.items():
                if (other == floor or (identity,other) not in passages or other in lift.blocked_exits
                        or other not in lift.landings[floor].entrance['service_floors']
                        or floor not in landing.entrance['service_floors']):
                    continue
                length = path_length(passages[identity,other])
                ride = Ride(identity,floor,other,passages[identity,other])
                base_floor = lift.destination or lift.floor or floor
                wait = abs(levels[base_floor]-levels[floor])*2 + 4*len(lift.queue) + (4 if lift.rider else 0)
                if wait_budgets is not None:
                    wait = max(wait,wait_budgets.get((identity,floor),0.))
                ride_time = 2*abs(levels[other]-levels[floor])+1
                edges.append(((other,'exit',identity), wait+ride_time+length/model['speed'], length, ride))
        for candidate, seconds, meters, action in edges:
            new_cost = cost+seconds
            new_rides = rides+isinstance(action,Ride)
            rank = (new_cost,new_rides) if fastest else (new_rides,new_cost)
            if rank < best.get(candidate,(math.inf,math.inf)):
                best[candidate] = rank
                heappush(queue,(rank,next(order),candidate,(*actions,action),new_rides,new_cost,distance+meters))
    return None


class ElevatorExecution:
    def configure_elevators(self):
        self.floor_levels = {floor: index for index,floor in enumerate(self.floors)}
        self.elevators = build_elevators(self.floors,self.document.get('elevators'))
        self.by_robot = {robot.robot_id:robot for robot in self.robots}
        self.robot_floors = {identity:item['floor_id'] for identity,item in self.robot_instances.items()}
        self.floor_planners = {}
        for robot in self.robots:
            key = self.robot_floors[robot.robot_id],self.robot_instances[robot.robot_id]['model_id']
            self.planners[robot.robot_id] = self.floor_planners.setdefault(key,self.planners[robot.robot_id])
        self.route_actions = {}
        self.elevator_requests = {}
        self.elevator_timeline = None
        if self.elevators:
            self.elevator_timeline = (self.directory/'elevators.jsonl').open('w', encoding='utf-8')
            self.record_elevators()

    def record_elevators(self):
        if self.elevator_timeline:
            entry = dict(step=self.step, elapsed=self.step*DT,
                         elevators=[lift.snapshot() for lift in self.elevators.values()])
            self.elevator_timeline.write(json.dumps(entry, ensure_ascii=False)+'\n')
            self.elevator_timeline.flush()

    def planner_on(self, floor, model):
        key = floor, model['id']
        if key not in self.floor_planners:
            self.floor_planners[key] = Planner(self.floors[floor], model, extra_rectangles=self.closures_on(floor))
        return self.floor_planners[key]

    def find_robot_route(self, robot, model, destination, goal, origin=None, *, fastest=False):
        origin = origin or self.robot_floors[robot.robot_id]
        if origin == destination:
            baseline = self.planners[robot.robot_id] if origin==self.robot_floors[robot.robot_id] else None
            planner = self.planning_on(origin,model,baseline)
            result = planner.route(robot.xy,goal)
            if result['path']:
                distance = path_length(result['path'])
                return (distance/model['speed'],distance,(result['path'],)), ''
            return None, result['reason']
        if not any(len(lift.landings)>1 for lift in self.elevators.values()):
            return None, '未配置连接楼层的电梯'
        planners = {floor:self.planning_on(floor,model) for floor in self.floors}
        route = cross_floor_route(self.elevators,self.floor_levels,planners,model,origin,robot.xy,destination,goal,
                                  wait_budgets=self.elevator_wait_budgets(),fastest=fastest)
        return route, '未找到可用的跨层路线，检查电梯服务楼层、运行状态和通行几何'

    def connect_robot_route(self, robot, actions):
        robot.path = list(actions[0])
        if len(actions)>1:
            self.route_actions[robot.robot_id] = list(actions[1:])
        else:
            self.route_actions.pop(robot.robot_id,None)

    def elevator_event(self, event, lift, request=None, **fields):
        fields.setdefault('elevator_name',lift.name or lift.identity)
        robot = self.by_robot[request.robot_id] if request else None
        task = next((task for task in self.tasks if task.task_id==request.task_id),None) if request else None
        if task is None and robot:
            task = self.task_for(robot)
        if task and task.task_id!=request.task_id:
            task = None
        if request and task is None:
            fields.setdefault('task_id',request.task_id)
        self.emit(event,robot,task,elevator_id=lift.identity,**fields)

    def elevator_command(self, command):
        if command.get('run_id',self.run_id) != self.run_id:
            raise ValueError('巡查运行已切换，请刷新电梯状态')
        lift = self.elevators.get(command.get('elevator_id'))
        if lift is None:
            raise ValueError('电梯编号不存在')
        if command['action'] == 'set_elevator_state':
            mode = command.get('mode')
            if mode not in ('enabled','out_of_service','fault'):
                raise ValueError('电梯状态无效')
            if lift.mode != mode:
                lift.mode = mode
                self.elevator_event('elevator_state_changed',lift,mode=mode,reason='管理命令设置电梯状态')
                for rider in lift.riders:
                    task = self.task_for(self.by_robot[rider.robot_id])
                    if task and mode == 'fault':
                        self._set_dispatch_wait(task,'所在电梯故障（'+lift.identity+'）')
                    elif task and self.wait_reasons.get(task.task_id,'').startswith('所在电梯故障'):
                        self.wait_reasons.pop(task.task_id,None)
                if mode != 'enabled':
                    for request in list(lift.queue):
                        self._drop_elevator_request(lift,request,replan=True)
        else:
            floor, blocked = command.get('floor_id'), command.get('blocked')
            if floor not in lift.landings or type(blocked) is not bool:
                raise ValueError('请选择电梯服务楼层和出口状态')
            if blocked != (floor in lift.blocked_exits):
                if blocked:
                    lift.blocked_exits.add(floor)
                    for request in list(lift.queue):
                        if request.ride.destination == floor:
                            self._drop_elevator_request(lift,request,replan=True)
                else:
                    lift.blocked_exits.remove(floor)
                self.elevator_event('elevator_exit_status',lift,floor_id=floor,blocked=blocked,reason='管理命令设置出梯区域')

    def _drop_elevator_request(self, lift, request, replan=False):
        if request in lift.queue:
            lift.queue.remove(request)
        lift.batch.discard(request.robot_id)
        if lift.permit is request:
            lift.permit = None
            lift.phase = 'boarding' if lift.riders else 'idle'
        if not lift.batch and not lift.rider:
            lift.direction = 0
        self.elevator_requests.pop(request.robot_id,None)
        self.route_actions.pop(request.robot_id,None)
        self.elevator_event('elevator_reservation_released',lift,request,
                            reason='电梯不可用，重新规划' if replan else '任务已释放')
        if replan:
            robot = self.by_robot[request.robot_id]
            task = self.task_for(robot)
            if task:
                if self.parking_route_failed(robot,task):
                    return
                task.status,task.robot_id,task.assigned_at = 'pending',None,None
                robot.task_id,robot.status,robot.path = None,'idle',[]
                self._set_dispatch_wait(task,'原电梯不可用，等待重新规划')
                if hasattr(self,'coverage_route_failed'):
                    self.coverage_route_failed(robot,task)

    def release_elevator_task(self, task):
        for request in list(self.elevator_requests.values()):
            if request.task_id != task.task_id:
                continue
            lift = self.elevators[request.ride.elevator_id]
            if request in lift.riders:
                request.cancelled = True
                self.route_actions.pop(request.robot_id,None)
                if lift.phase == 'exiting' and lift.rider is request:
                    self.by_robot[request.robot_id].path = [request.ride.clearance[-1]]
            else:
                self._drop_elevator_request(lift,request)
        for robot in self.robots:
            if self.task_for(robot) is None:
                self.route_actions.pop(robot.robot_id,None)

    def advance_elevator_route(self, robot, task):
        identity = robot.robot_id
        request = self.elevator_requests.get(identity)
        if request:
            lift = self.elevators[request.ride.elevator_id]
            if lift.rider is request and lift.phase == 'exiting':
                if lift.mode == 'fault' or request.ride.destination in lift.blocked_exits:
                    self.velocities[identity] = 0
                    return True
                if math.dist(robot.xy,request.ride.clearance[-1])>1e-6:
                    self.move_robot(robot,task)
                    return True
                self.elevator_event('elevator_released',lift,request,reason='车辆完全驶离出梯区域',floor_id=lift.floor)
                lift.riders.pop(0)
                lift.phase = 'at_exit' if lift.riders else 'idle'
                lift.batch.discard(identity)
                if not lift.batch:
                    lift.direction = 0
                self.elevator_requests.pop(identity)
                if request.cancelled:
                    robot.status = 'idle'
                    return True
                actions = self.route_actions.pop(identity,[])
                if actions:
                    self.connect_robot_route(robot,actions)
                return False
            return True
        actions = self.route_actions.get(identity)
        if not task or not actions:
            return False
        if robot.path:
            # The waiting marker is shared. Register from the final approach so two
            # vehicles converging on the marker cannot block each other's admission.
            arrival_radius = 2*self.planners[identity].radius if len(robot.path)==1 else 1e-6
            if math.dist(robot.xy,robot.path[-1])>arrival_radius:
                self.move_robot(robot,task)
                return True
        ride = actions.pop(0)
        lift = self.elevators[ride.elevator_id]
        request = Request(identity,task.task_id,ride,self.step)
        robot.path, robot.status = [],'waiting_elevator'
        self.velocities[identity] = 0
        self.elevator_requests[identity] = request
        lift.queue.append(request)
        self.elevator_event('elevator_reserved',lift,request,origin_floor_id=ride.origin,
                            destination_floor_id=ride.destination,reason='车辆到达候梯点，加入预约队列')
        if lift.mode != 'enabled' or ride.destination in lift.blocked_exits:
            self._drop_elevator_request(lift,request,replan=True)
        else:
            self._set_dispatch_wait(task,'正在等待电梯资源（'+lift.identity+'）')
        return True

    def _direction(self, request):
        return 1 if self.floor_levels[request.ride.destination]>self.floor_levels[request.ride.origin] else -1

    def _start_elevator_motion(self, lift, destination, phase):
        lift.origin,lift.destination,lift.floor = lift.floor,destination,None
        lift.phase = phase
        lift.motion_steps = 0
        lift.motion_total = max(1, round(2*abs(self.floor_levels[destination]-self.floor_levels[lift.origin])/DT))
        self.elevator_event('elevator_departed',lift,lift.rider,origin_floor_id=lift.origin,
                            destination_floor_id=destination,occupant_robot_ids=[rider.robot_id for rider in lift.riders],
                            reason='载客行驶' if lift.riders else '空梯前往接车楼层')

    def _advance_elevator_motion(self, lift):
        lift.motion_steps += 1
        for request in lift.riders:
            robot = self.by_robot[request.robot_id]
            fraction = lift.motion_steps/lift.motion_total
            start, end = self.floor_z[lift.origin],self.floor_z[lift.destination]
            self.place_robot(robot,robot.xy,start+(end-start)*fraction)
        if lift.motion_steps >= lift.motion_total:
            lift.floor = lift.destination
            lift.origin = lift.destination = None
            lift.motion_steps = lift.motion_total = 0
            lift.phase = 'at_exit' if lift.rider else 'idle'
            self.elevator_event('elevator_arrived',lift,lift.rider,floor_id=lift.floor,
                                occupant_robot_ids=[rider.robot_id for rider in lift.riders],reason='电梯到达目标楼层')

    def _admit_elevator_request(self, lift):
        if self.elapsed<lift.external_busy_until:
            return
        queued = sorted(lift.queue,key=lambda item:(item.arrived_step,item.robot_id))
        batch = [request for request in queued if request.robot_id in lift.batch]
        if not batch:
            lift.direction = self._direction(queued[0]) if queued else 0
            batch = [request for request in queued if self._direction(request) == lift.direction]
            lift.batch = {item.robot_id for item in batch}
        if not batch:
            return
        request = batch[0]
        if lift.floor != request.ride.origin:
            self._start_elevator_motion(lift,request.ride.origin,'repositioning')
            return
        self._permit_elevator_request(lift,request)

    def _permit_elevator_request(self, lift, request):
        lift.permit = request
        lift.phase = 'permission'
        request.permit_step = self.step
        self.elevator_event('elevator_entry_permitted',lift,request,wait_steps=self.step-request.arrived_step,
                            wait_seconds=(self.step-request.arrived_step)*DT,reason='方向、楼层和容量满足放行条件')

    @staticmethod
    def _same_elevator_trip(ride, trip):
        return (isinstance(ride,Ride) and ride.elevator_id==trip.elevator_id
                and ride.origin==trip.origin and ride.destination==trip.destination)

    def _continue_elevator_boarding(self, lift):
        first = lift.rider
        destination = first.ride.destination
        if (len(lift.riders)<lift.capacity and self._direction(first)>0 and self.step<lift.boarding_deadline
                and lift.mode=='enabled' and self.elapsed>=lift.external_busy_until
                and destination not in lift.blocked_exits):
            companion = next((request for request in lift.queue
                              if self._same_elevator_trip(request.ride,first.ride)),None)
            if companion:
                lift.batch.add(companion.robot_id)
                self._permit_elevator_request(lift,companion)
                return
            # Boarding removes the first vehicle from the floor so a following vehicle can reach the shared waiting point.
            if any(actions and identity not in self.elevator_requests
                   and self.robot_floors[identity]==first.ride.origin
                   and self._same_elevator_trip(actions[0],first.ride)
                   for identity,actions in self.route_actions.items()):
                return
        self._start_elevator_motion(lift,destination,'riding')

    def _board_elevator(self, lift):
        request = lift.permit
        self.record_elevator_wait(lift.identity,request.ride.origin,(self.step-request.arrived_step)*DT,
                                  at=request.arrived_step*DT)
        robot = self.by_robot[request.robot_id]
        task = self.task_for(robot)
        if task:
            self.wait_reasons.pop(task.task_id,None)
        lift.queue.remove(request)
        lift.permit = None
        if not lift.riders:
            lift.boarding_deadline = self.step+round(BOARDING_WAIT_SECONDS/DT)
        lift.riders.append(request)
        lift.phase = 'boarding'
        self.robot_floors[robot.robot_id] = None
        robot.status = 'riding_elevator'
        self.elevator_event('elevator_occupied',lift,request,reason='机器人进入电梯，形成实际占用')
        self._continue_elevator_boarding(lift)

    def _open_elevator_exit(self, lift):
        request = lift.rider
        robot = self.by_robot[request.robot_id]
        floor = lift.floor
        exit_point = request.ride.clearance[0]
        model = self.models[self.robot_instances[robot.robot_id]['model_id']]
        planner = self.planner_on(floor,model)
        blocked = floor in lift.blocked_exits or not planner.free(exit_point)
        for other in self.robots:
            if self.robot_floors[other.robot_id] == floor:
                clearance = planner.radius+self.planners[other.robot_id].radius
                if math.dist(exit_point,other.xy)<=clearance:
                    blocked = True
        task = self.task_for(robot)
        if blocked:
            if robot.status!='waiting_elevator_exit':
                self.elevator_event('elevator_exit_wait',lift,request,floor_id=floor,reason='出口被占用，保留电梯占用')
            robot.status = 'waiting_elevator_exit'
            if task:
                self._set_dispatch_wait(task,'电梯出口堵塞（'+lift.identity+'）')
            return
        if task:
            self.wait_reasons.pop(task.task_id,None)
        self.robot_floors[robot.robot_id] = floor
        self.planners[robot.robot_id] = planner
        robot.xy,robot.path,robot.status = exit_point,list(request.ride.clearance),'exiting_elevator'
        self.place_robot(robot,exit_point,self.floor_z[floor])
        lift.phase = 'exiting'
        self.note_floor_arrival(robot.robot_id,floor)
        self.elevator_event('elevator_exit_started',lift,request,floor_id=floor,reason='目标层出口可用，开始驶离')

    def tick_elevators(self):
        for lift in self.elevators.values():
            if lift.mode == 'fault':
                continue
            if lift.phase in ('riding','repositioning'):
                self._advance_elevator_motion(lift)
            elif lift.phase == 'at_exit':
                self._open_elevator_exit(lift)
            elif lift.phase == 'permission':
                self._board_elevator(lift)
            elif lift.phase == 'boarding':
                self._continue_elevator_boarding(lift)
            elif lift.phase == 'idle' and lift.mode == 'enabled':
                self._admit_elevator_request(lift)
        self.record_elevators()
