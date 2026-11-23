"""Fixed-step lidar, local occupancy, and the simulated obstacle environment."""
from dataclasses import dataclass, field
import math
import random

import pybullet as p

from ward_patrol.maps.geometry import Planner


CELL = .20
SENSOR_DEFAULTS = dict(range=4., frequency=10., fov=160., rays=41, noise=0., dropout=0., delay=0., ttl=1.)
SENSOR_BOUNDS = dict(range=(.5,20), frequency=(1,30), fov=(45,360), rays=(9,181),
                     noise=(0,.5), dropout=(0,1), delay=(0,3), ttl=(.25,10))
OBSTACLE_SIZES = {'cart':(.65,.55,.9), 'person':(.35,.35,1.55)}


def sensor_settings(stored):
    settings = SENSOR_DEFAULTS.copy()
    for key,(low,high) in SENSOR_BOUNDS.items():
        if key not in stored:
            continue
        value = stored[key]
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError(f'测距参数 {key} 允许范围为 {low} 至 {high}')
        settings[key] = value
    if int(settings['rays']) != settings['rays']:
        raise ValueError('测距射线数量须为整数')
    settings['rays'] = int(settings['rays'])
    return settings


def grid_key(point):
    return tuple(math.floor(value/CELL) for value in point)


def grid_center(cell):
    return tuple(round((index+.5)*CELL,3) for index in cell)


def angle_difference(a, b):
    return (a-b+math.pi)%(2*math.pi)-math.pi


@dataclass
class Lidar:
    config: dict
    random: random.Random
    floor_id: str = None
    next_step: int = 0
    frames: list = field(default_factory=list)
    frame: dict = None
    grid: dict = field(default_factory=dict)
    decision: str = '等待测距'
    blocked_since: int = None
    visible_hits: bool = False
    first_hit_step: int = None
    first_stop_step: int = None
    next_replan: int = 0
    replan_goal: tuple = None
    braking: bool = False
    stopped: bool = False
    local_view_key: tuple = None
    local_view: dict = field(default_factory=dict)


class PerceptionExecution:
    def configure_perception(self):
        self.lidars = {robot.robot_id:Lidar(sensor_settings(self.models[self.robot_instances[robot.robot_id]['model_id']]['sensors']),
                                           random.Random('1000:'+robot.robot_id)) for robot in self.robots}
        self.scene_obstacles = {}
        self.obstacle_bodies = {}
        self.road_closures = {}
        self.observed_blockages = {}
        self._observed_planners = {}
        self.truth_guard_active = set()
        self.perception_metrics = {robot.robot_id:dict(min_clearance=None, contact_steps=0, truth_interventions=0,
                                                       vehicle_guard_steps=0)
                                   for robot in self.robots}

    def _sample_lidar(self, robot, lidar):
        settings = lidar.config
        yaw = self.headings[robot.robot_id]
        half_fov = math.radians(settings['fov']/2)
        origin = (*robot.xy,self.floor_z[lidar.floor_id]+.32)
        angles = [yaw-half_fov+2*half_fov*i/(settings['rays']-1) for i in range(settings['rays'])]
        radius = settings['range']
        ends = [(origin[0]+radius*math.cos(angle),origin[1]+radius*math.sin(angle),origin[2]) for angle in angles]
        p.setCollisionFilterGroupMask(robot.body,-1,0,0, physicsClientId=self.client)
        try:
            hits = p.rayTestBatch([origin]*len(angles),ends,physicsClientId=self.client)
        finally:
            p.setCollisionFilterGroupMask(robot.body,-1,1,-1, physicsClientId=self.client)
        beams = []
        for angle, hit in zip(angles,hits):
            if settings['dropout'] and lidar.random.random()<settings['dropout']:
                continue
            identity, fraction = hit[0],hit[2]
            kind = self.obstacle_bodies.get(identity,'solid' if identity>=0 else 'free')
            distance = radius*fraction
            if settings['noise'] and identity>=0:
                distance = max(0.,min(radius,distance+lidar.random.gauss(0,settings['noise'])))
            point = (origin[0]+distance*math.cos(angle),origin[1]+distance*math.sin(angle))
            beams.append(dict(angle=angle,end=point,kind=kind,distance=distance))
        return dict(step=self.step, floor_id=lidar.floor_id, origin=origin[:2], yaw=yaw, beams=beams)

    def _apply_lidar_frame(self, robot, lidar, frame):
        lidar.frame = frame
        occupied, clear = {}, set()
        x,y = frame['origin']
        for beam in frame['beams']:
            distance, angle, kind = beam['distance'],beam['angle'],beam['kind']
            samples = max(0,math.floor((distance-(CELL if kind!='free' else 0))/CELL))
            for index in range(1,samples+1):
                clear.add(grid_key((x+index*CELL*math.cos(angle),y+index*CELL*math.sin(angle))))
            if kind!='free':
                occupied[grid_key(beam['end'])] = kind
        for key in clear.difference(occupied):
            lidar.grid[key] = ('free',frame['step'])
        for key,kind in occupied.items():
            lidar.grid[key] = (kind,frame['step'])
        visible = any(kind in OBSTACLE_SIZES for kind in occupied.values())
        if visible and not lidar.visible_hits:
            if lidar.first_hit_step is None:
                lidar.first_hit_step = self.step
            self.emit('obstacle_detected',robot,self.task_for(robot),floor_id=lidar.floor_id,
                      scan_step=frame['step'],reason='测距首次看到动态障碍')
        lidar.visible_hits = visible

    def tick_perception(self):
        self._advance_people()
        self.observed_blockages = {identity:report for identity,report in self.observed_blockages.items()
                                  if self.step<report['expires_step']}
        for robot in self.robots:
            lidar = self.lidars[robot.robot_id]
            floor_id = self.robot_floors[robot.robot_id]
            if floor_id != lidar.floor_id:
                lidar.floor_id,lidar.frame,lidar.next_step = floor_id,None,self.step
                lidar.frames.clear()
                lidar.grid.clear()
                lidar.blocked_since = None
                lidar.replan_goal = None
            if floor_id is None:
                continue
            if self.step>=lidar.next_step:
                latency = round(lidar.config['delay']/self.sim_dt)
                lidar.frames.append((self.step+latency,self._sample_lidar(robot,lidar)))
                lidar.next_step = self.step+max(1,round(1/(lidar.config['frequency']*self.sim_dt)))
            while lidar.frames and lidar.frames[0][0]<=self.step:
                self._apply_lidar_frame(robot,lidar,lidar.frames.pop(0)[1])
            max_age = round((lidar.config['ttl']+lidar.config['delay'])/self.sim_dt)
            lidar.grid = {key:value for key,value in lidar.grid.items() if self.step-value[1]<=max_age}
            report = self.observed_blockages.get(robot.robot_id)
            if report and not any(lidar.grid.get(key,('unknown',))[0] in OBSTACLE_SIZES for key in report['cells']):
                del self.observed_blockages[robot.robot_id]

    def _observed_cells(self, lidar):
        return [key for key,(kind,_) in lidar.grid.items() if kind in OBSTACLE_SIZES]

    def perception_speed_limit(self, robot, task, model, direction, desired):
        lidar = self.lidars[robot.robot_id]
        frame = lidar.frame
        if not frame or not frame['beams'] or self.step-frame['step']>(lidar.config['ttl']+lidar.config['delay'])/self.sim_dt:
            lidar.decision = '等待有效测距'
            return 0.
        forward = (math.cos(direction),math.sin(direction))
        margin = self.planners[robot.robot_id].radius+CELL*.75
        beams = [beam for beam in frame['beams'] if abs(angle_difference(beam['angle'],direction))<=math.radians(12)]
        if not beams:
            lidar.decision = '转向完成后确认前方视野'
            return 0.
        age = (self.step-frame['step'])*self.sim_dt
        travel = math.dist(robot.xy,frame['origin'])
        # The visible range also caps speed near occluding geometry.
        visible_beam = min(beams,key=lambda beam:abs(angle_difference(beam['angle'],direction)))
        clear = visible_beam['distance']-travel-margin
        dynamic_clear = math.inf
        for key in self._observed_cells(lidar):
            x,y = grid_center(key)
            dx,dy = x-robot.xy[0],y-robot.xy[1]
            ahead,side = dx*forward[0]+dy*forward[1], dx*forward[1]-dy*forward[0]
            if ahead>=0 and abs(side)<=margin:
                dynamic_clear = min(dynamic_clear,ahead-math.sqrt(max(0.,margin*margin-side*side)))
        # Keep static A* wall following usable at tight corners. Static hits limit lookahead
        # speed, while the known-map swept-footprint check remains the stopping guard.
        if visible_beam['kind']=='free':
            visibility_limit = max(0.,clear)
        else:
            visibility_limit = max(.12,clear)
        response = age+1/lidar.config['frequency']+self.sim_dt
        brake = model['deceleration']
        gap = max(0.,min(visibility_limit,dynamic_clear))
        limit = max(0.,math.sqrt((brake*response)**2+2*brake*gap)-brake*response)
        limited = min(desired,limit)
        braking = dynamic_clear<=visibility_limit and limited<desired-1e-6
        if braking and not lidar.braking:
            self.emit('obstacle_braking',robot,task,floor_id=lidar.floor_id,reason='已测到的障碍进入制动区')
        lidar.braking = braking
        blocked = dynamic_clear<=.06 and desired>0
        if blocked:
            if lidar.blocked_since is None:
                lidar.blocked_since = self.step
            lidar.decision = '停止并等待障碍通行'
            if self.velocities[robot.robot_id]<=.02 and not lidar.stopped:
                if lidar.first_stop_step is None:
                    lidar.first_stop_step = self.step
                lidar.stopped = True
                self.emit('obstacle_stopped',robot,task,floor_id=lidar.floor_id,reason='车辆按测距停车')
        else:
            if lidar.blocked_since is not None:
                self.emit('obstacle_clear',robot,task,floor_id=lidar.floor_id,reason='当前参考方向脱离已观测的堵塞区')
            lidar.blocked_since = None
            lidar.stopped = False
            lidar.decision = '按可见距离限速' if limited<desired-1e-6 else '沿参考路线行驶'
        return limited

    def _cell_boxes(self, cells):
        return [dict(id=f'scan-{key[0]}-{key[1]}',x=grid_center(key)[0],y=grid_center(key)[1],
                     width=CELL,height=CELL,rotation=0) for key in sorted(cells)]

    def closures_on(self, floor_id):
        return [data for data in self.road_closures.values() if data['floor_id']==floor_id]

    def planning_on(self, floor_id, model, baseline=None):
        cells = {key for report in self.observed_blockages.values() if report['floor_id']==floor_id
                 for key in report['cells']}
        if not cells:
            return baseline or self.planner_on(floor_id,model)
        baseline = baseline or self.planner_on(floor_id,model)
        key = floor_id,model['id']
        signature = baseline,frozenset(cells)
        cached = self._observed_planners.get(key)
        if cached is None or cached[0]!=signature:
            cached = signature,Planner(self.floors[floor_id],model,
                extra_rectangles=[*self.closures_on(floor_id),*self._cell_boxes(cells)])
            self._observed_planners[key] = cached
        return cached[1]

    def replan_observed_path(self, robot, task):
        lidar = self.lidars[robot.robot_id]
        if not task or robot.robot_id in self.elevator_requests or robot.robot_id in self.yield_paths or self.robot_has_passage(robot.robot_id):
            return
        if self.step<lidar.next_replan:
            return
        if lidar.blocked_since is None and lidar.replan_goal is None:
            return
        if lidar.blocked_since is not None and (self.step-lidar.blocked_since)*self.sim_dt<.6:
            return
        goal = lidar.replan_goal or (robot.path[-1] if robot.path else None)
        if goal is None:
            return
        model = self.models[self.robot_instances[robot.robot_id]['model_id']]
        lidar.next_replan = self.step+round(1/self.sim_dt)
        cells = set(self._observed_cells(lidar))
        if cells and lidar.blocked_since is not None:
            report = dict(floor_id=lidar.floor_id,cells=sorted(cells),expires_step=self.step+round(2/self.sim_dt))
            if robot.robot_id not in self.observed_blockages:
                self.emit('blockage_reported',robot,task,**report,reason='持续测得堵塞，向规划器发布局部观测证据')
                self.emit('route_invalidated',robot,task,reason='测距证据与参考路线冲突')
            self.observed_blockages[robot.robot_id] = report
        # First try reconnecting to a nearby reference waypoint, then replan the full floor leg.
        cells.update(key for report in self.observed_blockages.values() if report['floor_id']==lidar.floor_id
                     for key in report['cells'])
        planner = Planner(self.floors[lidar.floor_id],model,extra_rectangles=[*self.closures_on(lidar.floor_id),*self._cell_boxes(cells)])
        for index,waypoint in enumerate(robot.path[:-1]):
            if math.dist(robot.xy,waypoint)>2.5:
                break
            suffix = robot.path[index:]
            if not all(planner.segment(a,b) for a,b in zip(suffix,suffix[1:])):
                continue
            local = planner.route(robot.xy,waypoint)['path']
            if local:
                robot.path = local+suffix[1:]
                self.emit('route_replanned',robot,task,reason='局部绕行后接回参考路线')
                self.wait_reasons.pop(task.task_id,None)
                lidar.replan_goal = None
                lidar.blocked_since = None
                return
        path = planner.route(robot.xy,goal)['path']
        if path:
            robot.path = path
            self.emit('route_replanned',robot,task,reason='根据已发布管理事件和观测证据重规划楼层路线')
            self.wait_reasons.pop(task.task_id,None)
            lidar.replan_goal = None
            lidar.blocked_since = None
        else:
            lidar.replan_goal = tuple(goal)
            self._set_dispatch_wait(task,'已知堵塞或封路，等待可通行路线')

    def _scene_pose(self, data, size):
        floor_id = data.get('floor_id')
        x,y = data.get('x'),data.get('y')
        if floor_id not in self.floors or any(type(v) not in (int,float) or not math.isfinite(v) for v in (x,y)):
            raise ValueError('请选择楼层并填写有效的米制坐标')
        floor = self.floors[floor_id]
        if abs(x)+size[0]/2>floor['width']/2 or abs(y)+size[1]/2>floor['height']/2:
            raise ValueError('障碍物必须放在楼层范围内')
        return floor_id,(x,y)

    def _scene_overlaps_robot(self, floor_id, point, size):
        radius = math.hypot(*size[:2])/2
        return any(self.robot_floors[robot.robot_id]==floor_id and
                   math.dist(robot.xy,point)<radius+self.planners[robot.robot_id].radius
                   for robot in self.robots)

    def perception_command(self, command):
        if command.get('run_id',self.run_id)!=self.run_id:
            raise ValueError('巡查运行已切换，请刷新视图')
        identity = command.get('id')
        if not isinstance(identity,str) or not identity.strip() or len(identity)>32:
            raise ValueError('障碍或封路编号须为 1 至 32 个字符')
        action = command['action']
        if action in ('set_road_closure','clear_road_closure'):
            self._change_road_closure(command,identity)
            return
        previous = self.scene_obstacles.get(identity)
        if action=='remove_obstacle':
            if previous:
                p.removeBody(previous['body'],physicsClientId=self.client)
                del self.obstacle_bodies[previous['body']]
                del self.scene_obstacles[identity]
                self.emit('obstacle_removed',obstacle_id=identity,floor_id=previous['floor_id'],reason='场景操作移除障碍')
            return
        kind = command.get('kind',previous['kind'] if previous else 'cart')
        if kind not in OBSTACLE_SIZES:
            raise ValueError('仅支持推车和行人')
        size = OBSTACLE_SIZES[kind]
        floor_id,point = self._scene_pose(command,size)
        if self._scene_overlaps_robot(floor_id,point,size):
            raise ValueError('障碍位置与当前车辆重叠')
        if any(item['floor_id']==floor_id and Planner.inside(point,item['geometry'],max(size[:2])/2)
               for item in self.physics_geometry):
            raise ValueError('障碍位置与墙体或家具重叠')
        target = None
        if kind=='person' and command.get('target') is not None:
            target_data = command['target']
            if not isinstance(target_data,list) or len(target_data)!=2:
                raise ValueError('请输入行人终点 X 和 Y')
            _,target = self._scene_pose(dict(floor_id=floor_id,x=target_data[0],y=target_data[1]),size)
        if previous:
            p.removeBody(previous['body'],physicsClientId=self.client)
            del self.obstacle_bodies[previous['body']]
        body = self.body((*point,self.floor_z[floor_id]+size[2]/2),size,
                         (1,.56,.13,1) if kind=='cart' else (.7,.3,.65,1))
        self.scene_obstacles[identity] = dict(id=identity,kind=kind,floor_id=floor_id,xy=point,
                                              size=size,body=body,target=target)
        self.obstacle_bodies[body] = kind
        self.emit('obstacle_moved' if previous else 'obstacle_added',obstacle_id=identity,
                  floor_id=floor_id,xy=point,kind=kind,reason='场景真值已更新，等待车辆扫描发现')

    def _advance_people(self):
        for data in self.scene_obstacles.values():
            target = data['target']
            if target is None:
                continue
            start = data['xy']
            length = math.dist(start,target)
            fraction = min(1.,.65*self.sim_dt/max(length,1e-9))
            point = tuple(a+(b-a)*fraction for a,b in zip(start,target))
            if self._scene_overlaps_robot(data['floor_id'],point,data['size']):
                continue
            if any(item['floor_id']==data['floor_id'] and
                   Planner.inside(point,item['geometry'],max(data['size'][:2])/2) for item in self.physics_geometry):
                data['target'] = None
                continue
            z = self.floor_z[data['floor_id']]+data['size'][2]/2
            p.resetBasePositionAndOrientation(data['body'],[*point,z],[0,0,0,1],physicsClientId=self.client)
            data['xy'] = point
            if fraction>=1.:
                data['target'] = None

    def _change_road_closure(self, command, identity):
        old = self.road_closures.get(identity)
        if command['action']=='clear_road_closure':
            if old is None:
                return
            del self.road_closures[identity]
            floors = {old['floor_id']}
        else:
            width,height = command.get('width'),command.get('height')
            if any(type(value) not in (int,float) or not math.isfinite(value) or value<=0 for value in (width,height)):
                raise ValueError('封路范围须为正数')
            floor_id,point = self._scene_pose(command,(width,height))
            if self._scene_overlaps_robot(floor_id,point,(width,height)):
                raise ValueError('封路范围不能覆盖当前车辆')
            floors = {floor_id} | ({old['floor_id']} if old else set())
            self.road_closures[identity] = dict(id=identity,floor_id=floor_id,x=point[0],y=point[1],
                                                width=width,height=height,rotation=0)
        self.floor_planners = {key:planner for key,planner in self.floor_planners.items() if key[0] not in floors}
        self.emit('road_closure_changed',closure_id=identity,floor_ids=sorted(floors),
                  blocked=identity in self.road_closures,reason='管理封路立即更新已知通行规则')
        for robot in self.robots:
            floor_id = self.robot_floors[robot.robot_id]
            if floor_id not in floors:
                continue
            model = self.models[self.robot_instances[robot.robot_id]['model_id']]
            self.planners[robot.robot_id] = self.planner_on(floor_id,model)
            if robot.path and robot.robot_id not in self.elevator_requests and not self.robot_has_passage(robot.robot_id):
                lidar = self.lidars[robot.robot_id]
                lidar.replan_goal = tuple(robot.path[-1])
                lidar.next_replan = self.step
                self.emit('route_invalidated',robot,self.task_for(robot),reason='管理事件改变通行状态')

    def dynamic_safety_clear(self, robot, task, position):
        """Simulator interlock only. Contacts and guards do not feed either planner or lidar."""
        if position==robot.xy:
            return True
        floor_id = self.robot_floors[robot.robot_id]
        radius = self.planners[robot.robot_id].radius
        for item in self.scene_obstacles.values():
            if item['floor_id']!=floor_id:
                continue
            x,y = item['xy']
            w,h = item['size'][:2]
            gap = math.hypot(max(abs(position[0]-x)-w/2,0),max(abs(position[1]-y)-h/2,0))-radius
            if gap<=0:
                self._truth_intervention(robot,task,'truth_interventions','物理安全层拦截可能碰撞的动态障碍')
                self.lidars[robot.robot_id].decision = '物理安全拦截'
                return False
        self.truth_guard_active.discard((robot.robot_id,'truth_interventions'))
        return True

    def vehicle_safety_clear(self, robot, task, position):
        identity = robot.robot_id
        floor_id = self.robot_floors[identity]
        for other in self.robots:
            if other is robot or self.robot_floors[other.robot_id]!=floor_id:
                continue
            radius = self.planners[identity].radius+self.planners[other.robot_id].radius
            if math.dist(position,other.xy)<=radius:
                if position!=robot.xy:
                    self._truth_intervention(robot,task,'vehicle_guard_steps','原有多车物理间距联锁')
                return False
        self.truth_guard_active.discard((identity,'vehicle_guard_steps'))
        return True

    def _truth_intervention(self, robot, task, metric, reason):
        identity = robot.robot_id
        self.perception_metrics[identity][metric] += 1
        key = identity, metric
        if key not in self.truth_guard_active:
            self.truth_guard_active.add(key)
            self.emit('truth_intervention',robot,task,floor_id=self.robot_floors[identity],guard=metric,reason=reason)

    def audit_obstacle_clearance(self):
        for robot in self.robots:
            floor_id = self.robot_floors[robot.robot_id]
            metrics = self.perception_metrics[robot.robot_id]
            for obstacle in self.scene_obstacles.values():
                if obstacle['floor_id']!=floor_id:
                    continue
                x,y = obstacle['xy']
                w,h = obstacle['size'][:2]
                gap = math.hypot(max(abs(robot.xy[0]-x)-w/2,0),max(abs(robot.xy[1]-y)-h/2,0))-self.planners[robot.robot_id].radius
                if metrics['min_clearance'] is None or gap<metrics['min_clearance']:
                    metrics['min_clearance'] = round(gap,4)
                if p.getClosestPoints(robot.body,obstacle['body'],0,physicsClientId=self.client):
                    metrics['contact_steps'] += 1

    def perception_snapshot(self):
        observations = {}
        for identity,lidar in self.lidars.items():
            frame = lidar.frame
            key = (frame['step'] if frame else None,len(lidar.grid))
            if lidar.local_view_key != key:
                scan = None if not frame else dict(step=frame['step'],floor_id=frame['floor_id'],
                    origin=tuple(round(value,3) for value in frame['origin']),beams=[
                        dict(end=tuple(round(value,3) for value in beam['end']),kind=beam['kind']) for beam in frame['beams']])
                lidar.local_view = dict(scan=scan,cell_size=CELL,
                    occupied=[grid_center(cell) for cell in self._observed_cells(lidar)],
                    free=[grid_center(cell) for cell,(kind,_) in lidar.grid.items() if kind=='free'])
                lidar.local_view_key = key
            observations[identity] = dict(lidar.local_view,decision=lidar.decision,
                first_hit_step=lidar.first_hit_step,first_stop_step=lidar.first_stop_step)
        return observations
