"""Single-capacity floor passages with queued admission and safe clearance."""
from dataclasses import dataclass, field
import math

from ward_patrol.maps.geometry import local_point


@dataclass
class Passage:
    floor_id: str
    region: dict
    queue: list = field(default_factory=list)
    permit: str = None
    occupant: str = None
    blocked: bool = False

    def snapshot(self):
        return dict(id=self.region['id'], name=self.region.get('name') or self.region['id'], floor_id=self.floor_id,
                    waiting_robot_ids=list(self.queue), permit_robot_id=self.permit,
                    occupant_robot_id=self.occupant, exit_blocked=self.blocked)


class PassageExecution:
    def configure_passages(self):
        self.passages = {obj['id']:Passage(floor_id,obj) for floor_id,floor in self.floors.items()
                         for obj in floor['objects'] if obj['kind']=='single_lane'}
        self.yield_paths = {}
        self.passage_escapes = set()
        self.parking_resources = {(floor_id, obj['id']):obj for floor_id,floor in self.floors.items()
                                  for obj in floor['objects'] if obj['kind']=='parking'}

    def parking_snapshot(self):
        result = []
        reservations = {(item['floor_id'],item['parking_id']):identity
                        for identity,item in self.robot_instances.items()}
        returns = {move['spot']:identity for identity,move in self.parking_moves.items()}
        for (floor_id,identity), point in self.parking_resources.items():
            occupants = [robot.robot_id for robot in self.robots if self.robot_floors[robot.robot_id]==floor_id
                         and self.planners[robot.robot_id].inside(robot.xy,point)]
            result.append(dict(id=identity,floor_id=floor_id,reserved_robot_id=reservations.get((floor_id,identity)),
                               returning_robot_id=returns.get((floor_id,identity)),occupant_robot_ids=occupants))
        return result

    def passage_command(self, command):
        if command.get('run_id',self.run_id) != self.run_id:
            raise ValueError('巡查运行已切换，请刷新窄通道状态')
        gate = self.passages.get(command.get('passage_id'))
        blocked = command.get('blocked')
        if gate is None or type(blocked) is not bool:
            raise ValueError('请选择窄通道和出口状态')
        if gate.blocked != blocked:
            gate.blocked = blocked
            gate.permit = None
            self.emit('passage_exit_status',passage_id=gate.region['id'],floor_id=gate.floor_id,
                      blocked=blocked,reason='管理命令设置窄通道出口状态')

    def _passage_event(self, event, gate, robot, task, reason):
        self.emit(event,robot,task,passage_id=gate.region['id'],floor_id=gate.floor_id,reason=reason)

    def _yield_beside_passage(self, gate, robot):
        """Keep an oncoming waiter out of the current occupant's exit path."""
        identity = robot.robot_id
        planner = self.planners[identity]
        region = gate.region
        along, across = local_point(robot.xy,region)
        angle = math.radians(region.get('rotation',0))
        cos, sin = math.cos(angle),math.sin(angle)
        rank = gate.queue.index(identity)
        # Try both sides. The point must stay clear of the physical lane and walkway obstacles.
        for sign in (1,-1) if across>=0 else (-1,1):
            side = sign*(region['height']/2+planner.radius*3+.35)
            back = math.copysign(region['width']/2+planner.radius+.35+rank*planner.radius*2,along)
            point = (region['x']+cos*back-sin*side,region['y']+sin*back+cos*side)
            if not planner.inside(point,region,planner.radius) and planner.segment(robot.xy,point):
                self.yield_paths[identity] = (gate,list(robot.path),point)
                robot.path = [point]
                break

    def advance_passage_yield(self, robot, task):
        identity = robot.robot_id
        info = self.yield_paths.get(identity)
        if info:
            gate, path, staging = info
            if math.dist(robot.xy,staging)>1e-6:
                self.move_robot(robot,task)
                return True
            if gate.blocked or gate.occupant or (gate.queue and gate.queue[0]!=identity):
                return True
            self.yield_paths.pop(identity,None)
            planner = self.planners[identity]
            route = planner.route(robot.xy,path[0])['path'] if path else []
            robot.path = list(route)+path[1:] if route else path
        return False

    def passage_allows_step(self, robot, task, position):
        identity = robot.robot_id
        planner = self.planners[identity]
        for gate in self.passages.values():
            if self.robot_floors[identity] != gate.floor_id:
                continue
            inside = planner.inside(position,gate.region,planner.radius)
            if gate.occupant == identity:
                if not inside and gate.blocked:
                    return False
                continue
            if not inside:
                continue
            if identity not in gate.queue:
                gate.queue.append(identity)
                self._passage_event('passage_reserved',gate,robot,task,'车辆在窄通道外申请进入')
            if gate.blocked or gate.occupant or gate.queue[0] != identity:
                if gate.occupant and identity not in self.yield_paths:
                    self._yield_beside_passage(gate,robot)
                if task:
                    self._set_dispatch_wait(task,'窄通道出口堵塞' if gate.blocked else '等待窄通道放行')
                return False
            if gate.permit != identity:
                gate.permit = identity
                self._passage_event('passage_entry_permitted',gate,robot,task,'出口可用，容量允许')
                return False
        return True

    def update_passage_occupancy(self, robot, task):
        identity = robot.robot_id
        planner = self.planners[identity]
        for gate in self.passages.values():
            if self.robot_floors[identity] != gate.floor_id:
                continue
            inside = planner.inside(robot.xy,gate.region,planner.radius)
            if inside and gate.permit == identity:
                gate.permit,gate.occupant = None,identity
                gate.queue.remove(identity)
                if task:
                    self.wait_reasons.pop(task.task_id,None)
                self._passage_event('passage_occupied',gate,robot,task,'车辆进入通道，形成实际占用')
            elif not inside and gate.occupant == identity:
                gate.occupant = None
                self._passage_event('passage_released',gate,robot,task,'车辆实际驶离通道')
        if identity in self.passage_escapes and not self.robot_has_passage(identity):
            self.passage_escapes.remove(identity)
            robot.path,robot.status = [],'idle'

    def robot_has_passage(self, identity):
        return any(gate.occupant==identity for gate in self.passages.values())

    def release_passage_task(self, robot):
        identity = robot.robot_id
        self.yield_paths.pop(identity,None)
        for gate in self.passages.values():
            if identity in gate.queue:
                gate.queue.remove(identity)
            if gate.permit == identity:
                gate.permit = None
            if gate.occupant == identity:
                self.passage_escapes.add(identity)
                return False
        return True
