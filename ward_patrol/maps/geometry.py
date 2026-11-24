"""Versioned metric geometry shared by editors, A* and physics."""
from copy import deepcopy
from collections import OrderedDict
from functools import lru_cache
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import threading
import uuid
from ward_patrol.maps.elevators import catalog_errors, normalize_elevators

KINDS = {'wall', 'door', 'bed', 'furniture', 'parking', 'service', 'elevator', 'waiting', 'exit', 'forbidden', 'one_way', 'single_lane'}
DEFAULT_MODELS = [
    dict(id='small', name='小型巡查车', width=.4, length=.5, speed=.8, acceleration=.6,
         deceleration=.8, turning='differential', angular_speed=2., margin=.05,
         sensors=dict(range=4., frequency=10.), capabilities=['patrol', 'vitals']),
    dict(id='large', name='大型巡查车', width=.9, length=1.1, speed=.6, acceleration=.4,
         deceleration=.6, turning='differential', angular_speed=1., margin=.08,
         sensors=dict(range=5., frequency=10.), capabilities=['patrol', 'vitals'])]


def blank_map(name='新病区'):
    return dict(schema=3, elevators=[], id=uuid.uuid4().hex, version=0, name=name,
                floors=[dict(id='F1', name='一层', width=20., height=16., objects=[], background=None)])


def copy_floor(document, floor_id):
    result = deepcopy(document)
    source = next(f for f in result['floors'] if f['id'] == floor_id)
    floor = deepcopy(source)
    floor['id'] = 'F-' + uuid.uuid4().hex[:8]
    floor['name'] += ' 副本'
    mapping = {o['id']: uuid.uuid4().hex for o in floor['objects']}
    for obj in floor['objects']:
        if obj['kind'] == 'bed':
            obj.pop('patient', None)
            if obj.get('bed_status') == 'occupied':
                obj['bed_status'] = ''
        obj['id'] = mapping[obj['id']]
        for key in ('wall_id', 'bed_id', 'waiting_id', 'exit_id', 'elevator_id'):
            if obj.get(key) in mapping:
                obj[key] = mapping[obj[key]]
        if 'service_floors' in obj:
            obj['service_floors'] = [floor['id'] if fid == floor_id else fid for fid in obj['service_floors']]
    result['floors'].append(floor)
    for obj in floor['objects']:
        if obj['kind']=='elevator' and obj.get('lift_id'):
            lift = next((item for item in result.get('elevators',[]) if item['id']==obj['lift_id']),None)
            if lift:
                lift['served_floors'].append(floor['id'])
                lift.setdefault('landings',{})[floor['id']] = dict(entrance_id=obj['id'],waiting_id=obj['waiting_id'],
                    exit_id=obj['exit_id'],confirmed=False)
    return result


def valid_patient_details(patient):
    if not isinstance(patient, dict):
        return False
    age = patient.get('age')
    if type(age) is not int or not 0 <= age <= 130:
        return False
    if patient.get('sex') not in ('female', 'male', 'other', 'unknown'):
        return False
    for key, limit in (('name', 80), ('id', 80), ('diagnosis', 200)):
        value = patient.get(key)
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
            return False
    notes = patient.get('notes', '')
    return isinstance(notes, str) and len(notes) <= 500


def validate(document):
    structure, geometry = [], []
    if not isinstance(document, dict) or not isinstance(document.get('floors'), list) or not document['floors']:
        return dict(structure=['地图必须包含楼层数组'], geometry=[], valid=False)
    if any(not isinstance(f,dict) or not isinstance(f.get('id'),str) or not isinstance(f.get('objects'),list) for f in document['floors']):
        return dict(structure=['楼层必须包含字符串 ID 和对象数组'],geometry=[],valid=False)
    if any(not isinstance(o,dict) or not isinstance(o.get('id'),str) for f in document['floors'] for o in f['objects']):
        return dict(structure=['对象必须包含字符串 ID'],geometry=[],valid=False)
    identifiers = set()
    floor_ids = {f.get('id') for f in document['floors'] if isinstance(f, dict)}
    for floor in document['floors']:
        if not isinstance(floor, dict):
            structure.append('楼层格式无效')
            continue
        objects = floor.get('objects', [])
        by_id = {o.get('id'): o for o in objects if isinstance(o, dict)}
        for entity in [floor] + objects:
            if not isinstance(entity, dict) or not isinstance(entity.get('id'), str) or entity['id'] in identifiers:
                structure.append('对象和楼层 ID 必须唯一且为字符串')
                continue
            identifiers.add(entity['id'])
        for key in ('width', 'height'):
            value = floor.get(key)
            if not isinstance(value, (float, int)) or not math.isfinite(value) or not 1 <= value <= 100:
                geometry.append(f"{floor.get('id')} 楼层尺寸应在 1 至 100 米")
        room_numbers = set()
        parking_numbers = set()
        charger_numbers = set()
        shaft_numbers = set()
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            identity = obj.get('id', '?')
            if obj.get('kind') not in KINDS:
                structure.append(f'{identity} 未知对象类型')
            for key in ('x', 'y', 'rotation', 'width', 'height'):
                value = obj.get(key, 0 if key == 'rotation' else None)
                if not isinstance(value, (float, int)) or not math.isfinite(value):
                    geometry.append(f'{identity} {key} 必须是有限数值')
                elif key in ('width', 'height') and value <= 0:
                    geometry.append(f'{identity} 尺寸必须大于零')
            for key, kind in [('wall_id', 'wall'), ('bed_id', 'bed'), ('waiting_id', 'waiting'), ('exit_id', 'exit'), ('elevator_id', 'elevator')]:
                if obj.get(key) and (obj[key] not in by_id or by_id[obj[key]].get('kind') != kind):
                    structure.append(f'{identity} 的 {key} 引用无效')
            if not isinstance(obj.get('models',[]),list) or not all(isinstance(v,str) for v in obj.get('models',[])):
                structure.append(f'{identity} 型号限制应为字符串数组')
            if obj.get('kind') == 'parking' and 'parking_number' in obj:
                number = obj['parking_number']
                if not isinstance(number, str) or not 1 <= len(number.strip()) <= 24:
                    structure.append(f'{identity} 的停车点编号须为 1 至 24 个字符')
                elif number.strip().casefold() in parking_numbers:
                    structure.append(f"同一楼层的停车点编号「{number.strip()}」重复")
                else:
                    parking_numbers.add(number.strip().casefold())
            if obj.get('kind') == 'bed' and 'patient' in obj:
                if obj.get('bed_status') != 'occupied' or not valid_patient_details(obj['patient']):
                    structure.append(f'{identity} 的入住患者资料无效')
            if 'charger' in obj:
                charger = obj['charger']
                if obj.get('kind') != 'parking' or not isinstance(charger, dict):
                    structure.append(f'{identity} 充电桩必须绑定停车点')
                else:
                    number, rate = charger.get('number'), charger.get('rate')
                    if not isinstance(number, str) or not 1 <= len(number.strip()) <= 24:
                        structure.append(f'{identity} 充电桩编号须为 1 至 24 个字符')
                    elif number.strip().casefold() in charger_numbers:
                        structure.append(f'本楼层充电桩编号「{number.strip()}」重复')
                    else:
                        charger_numbers.add(number.strip().casefold())
                    if type(rate) not in (int, float) or not 0 < rate <= 100:
                        structure.append(f'{identity} 充电速率须大于 0 且不超过 100')
            if obj.get('kind') == 'door':
                if not obj.get('wall_id'):
                    structure.append(f'{identity} 门必须引用墙')
                room_number = obj.get('room_number', '')
                if not isinstance(room_number, str) or len(room_number.strip()) > 24:
                    structure.append(f'{identity} 的病房编号必须为不超过 24 个字符的文本')
                elif room_number.strip():
                    number = room_number.strip().casefold()
                    if number in room_numbers:
                        structure.append(f"本楼层的病房编号「{room_number.strip()}」重复")
                    room_numbers.add(number)
            if obj.get('kind') == 'elevator':
                shaft_id = obj.get('shaft_id', '')
                if not isinstance(shaft_id, str) or len(shaft_id.strip()) > 32:
                    structure.append(f'{identity} 电梯编号须为不超过 32 个字符的文本')
                elif shaft_id.strip():
                    if shaft_id.strip() in shaft_numbers:
                        structure.append(f"同一楼层的电梯编号「{shaft_id.strip()}」重复")
                    shaft_numbers.add(shaft_id.strip())
                if not obj.get('waiting_id') or not obj.get('exit_id'):
                    structure.append(f'{identity} 电梯必须关联候梯点和出梯区域')
                if not obj.get('lift_id') and (not isinstance(obj.get('service_floors'),list) or not obj['service_floors'] or not all(isinstance(fid,str) and fid in floor_ids for fid in obj['service_floors'])):
                    structure.append(f'{identity} 电梯服务楼层引用无效')
    structure.extend(catalog_errors(document))
    if not structure and not geometry:
        for floor in document['floors']:
            by_id = {o['id']: o for o in floor['objects']}
            door_intervals = {}
            for obj in floor['objects']:
                angle=math.radians(obj.get('rotation',0))
                extent_x=(abs(math.cos(angle))*obj['width']+abs(math.sin(angle))*obj['height'])/2
                extent_y=(abs(math.sin(angle))*obj['width']+abs(math.cos(angle))*obj['height'])/2
                attached_elevator = obj['kind']=='elevator' and obj.get('wall_id')
                tolerance=.2 if obj['kind']=='wall' or attached_elevator else 1e-6
                if abs(obj['x'])+extent_x>floor['width']/2+tolerance or abs(obj['y'])+extent_y>floor['height']/2+tolerance:
                    geometry.append(f"{obj['id']} 几何轮廓超出楼层边界")
                if obj['kind'] == 'door' or attached_elevator:
                    wall = by_id[obj['wall_id']]
                    axis = dict(wall)
                    if attached_elevator and wall['height'] > wall['width']:
                        axis.update(width=wall['height'], height=wall['width'], rotation=wall.get('rotation',0)+90)
                    label = '电梯入口' if attached_elevator else '门洞'
                    if abs(math.sin(math.radians(obj.get('rotation',0)-axis.get('rotation',0))))>.001:
                        geometry.append(f"{obj['id']} {label}方向必须与墙一致")
                    offset, across = local_point((obj['x'], obj['y']), axis)
                    if abs(across) > axis['height']/2 + .01 or abs(offset)+obj['width']/2 > axis['width']/2+.001:
                        geometry.append(f"{obj['id']} {label}必须位于所属墙范围内")
                    interval = (offset-obj['width']/2, offset+obj['width']/2)
                    for previous in door_intervals.setdefault(wall['id'], []):
                        if max(interval[0], previous[0]) < min(interval[1], previous[1]):
                            geometry.append(f"{obj['id']} 与已有门洞或电梯入口重叠")
                    door_intervals[wall['id']].append(interval)
                if abs(obj['x']) > floor['width']/2 or abs(obj['y']) > floor['height']/2:
                    geometry.append(f"{obj['id']} 中心超出楼层边界")
    if not structure and not geometry:
        for floor in document['floors']:
            rectangles=compile_floor(floor)
            chargers = [point for point in floor['objects'] if 'charger' in point]
            if chargers:
                planner = Planner(floor, DEFAULT_MODELS[0])
                for point in chargers:
                    error = charger_placement_error(floor, point, planner)
                    if error:
                        geometry.append(point['charger']['number'] + '：' + error)
            for index, first in enumerate(rectangles):
                for second in rectangles[index+1:]:
                    if first['kind']=='wall' and second['kind']=='wall':
                        continue
                    if rectangles_overlap(first,second):
                        geometry.append(first['id']+' 与 '+second['id']+' 实体重叠')
    return dict(structure=structure, geometry=geometry, valid=not structure and not geometry)



def rectangles_overlap(first, second):
    def corners(rectangle):
        angle=math.radians(rectangle.get('rotation',0))
        return [(rectangle['x']+x*math.cos(angle)-y*math.sin(angle),
                 rectangle['y']+x*math.sin(angle)+y*math.cos(angle))
                for x,y in ((-rectangle['width']/2,-rectangle['height']/2),
                            (rectangle['width']/2,-rectangle['height']/2),
                            (rectangle['width']/2,rectangle['height']/2),
                            (-rectangle['width']/2,rectangle['height']/2))]
    a,b=corners(first),corners(second)
    for rectangle in (first,second):
        for direction in (0,90):
            angle=math.radians(rectangle.get('rotation',0)+direction)
            axis=(math.cos(angle),math.sin(angle))
            pa=[x*axis[0]+y*axis[1] for x,y in a]
            pb=[x*axis[0]+y*axis[1] for x,y in b]
            if min(max(pa),max(pb))-max(min(pa),min(pb))<=1e-7:
                return False
    return True


def local_point(point, rectangle):
    angle = math.radians(rectangle.get('rotation', 0))
    dx, dy = point[0]-rectangle['x'], point[1]-rectangle['y']
    return dx*math.cos(angle)+dy*math.sin(angle), -dx*math.sin(angle)+dy*math.cos(angle)


def compile_floor(floor):
    rectangles = []
    for obj in floor['objects']:
        if obj['kind'] not in ('wall', 'bed', 'furniture'):
            continue
        if obj['kind'] != 'wall':
            rectangles.append(deepcopy(obj))
            continue
        cuts = sorted((local_point((door['x'], door['y']), obj)[0]-door['width']/2,
                       local_point((door['x'], door['y']), obj)[0]+door['width']/2)
                      for door in floor['objects'] if door['kind'] == 'door' and door.get('wall_id') == obj['id'])
        cursor = -obj['width']/2
        angle = math.radians(obj.get('rotation', 0))
        for lo, hi in cuts + [(obj['width']/2, obj['width']/2)]:
            if lo > cursor + 1e-8:
                rectangle = deepcopy(obj)
                center = (cursor+lo)/2
                rectangle.update(x=obj['x']+center*math.cos(angle), y=obj['y']+center*math.sin(angle), width=lo-cursor)
                rectangles.append(rectangle)
            cursor = max(cursor, hi)
    return rectangles


def footprint(model):
    return math.hypot(model['width'], model['length'])/2 + model.get('margin', 0)


def charger_approach(point, radius):
    angle = math.radians(point.get('rotation', 0))
    distance = max(.6, 2 * radius)
    return point['x'] - distance * math.cos(angle), point['y'] - distance * math.sin(angle)


def charger_placement_error(floor, point, planner):
    goal = point['x'], point['y']
    approach = charger_approach(point, planner.radius)
    envelope = max(planner.radius, math.hypot(point['width'], point['height']) / 2)
    by_id = {obj['id']: obj for obj in floor['objects']}
    for obj in floor['objects']:
        if obj['kind'] not in ('elevator', 'waiting', 'exit', 'single_lane', 'forbidden'):
            continue
        # Keep a maneuvering apron on both sides of the elevator threshold.
        radius = envelope + (1.0 if obj['kind'] == 'elevator' else 0.)
        if Planner._touches(approach, goal, obj, radius):
            return ('充电位置和对接路线须避开电梯门口、候梯点及出梯区'
                    if obj['kind'] in ('elevator', 'waiting', 'exit') else '充电位置和对接路线须避开禁行区及窄通道')
        if obj['kind'] == 'elevator':
            for identity in (obj.get('waiting_id'), obj.get('exit_id')):
                marker = by_id.get(identity)
                if marker:
                    dx, dy = marker['x'] - obj['x'], marker['y'] - obj['y']
                    passage = dict(x=obj['x'] + dx / 2, y=obj['y'] + dy / 2,
                                   width=math.hypot(dx, dy), height=2 * planner.radius,
                                   rotation=math.degrees(math.atan2(dy, dx)))
                    if Planner._touches(approach, goal, passage, envelope):
                        return '充电位置和对接路线须保留电梯进出通道'
    if not planner.segment(approach, goal):
        return '充电桩对接路线不可通行，请调整停车点或朝向'
    return None


class Planner:
    def __init__(self, floor, model, resolution=.15, extra_rectangles=()):
        self.floor, self.model, self.resolution = floor, model, resolution
        self.radius = footprint(model)
        self.rectangles = [*compile_floor(floor), *extra_rectangles]
        self.regions = [o for o in floor['objects'] if o['kind'] in ('forbidden', 'one_way') or o.get('models')]
        # Caches belong to this immutable floor/model/closure snapshot. Direction
        # is part of the key because one-way regions make edges asymmetric.
        self._edges = lru_cache(maxsize=16384)(self._grid_edge)
        self._routes = OrderedDict()

    @staticmethod
    def inside(point, rectangle, radius=0):
        x, y = local_point(point, rectangle)
        dx, dy = max(abs(x)-rectangle['width']/2, 0), max(abs(y)-rectangle['height']/2, 0)
        return math.hypot(dx, dy) <= radius + 1e-9

    def free(self, point):
        if abs(point[0])+self.radius >= self.floor['width']/2 or abs(point[1])+self.radius >= self.floor['height']/2:
            return False
        if any(self.inside(point, box, self.radius) for box in self.rectangles):
            return False
        return not any(self.inside(point, region, self.radius) and
                       (region['kind'] == 'forbidden' or (region.get('models') and self.model['id'] not in region['models']))
                       for region in self.regions)

    def segment(self, start, end):
        # A swept circle against rectangles is both faster and more conservative
        # than sampling every 4 cm (which could miss very thin obstacles).
        if any(abs(point[0])+self.radius >= self.floor['width']/2 or
               abs(point[1])+self.radius >= self.floor['height']/2 for point in (start,end)):
            return False
        if any(self._touches(start,end,box,self.radius) for box in self.rectangles):
            return False
        for region in self.regions:
            restricted = region['kind']=='forbidden' or (region.get('models') and self.model['id'] not in region['models'])
            if region['kind']=='one_way':
                angle = math.radians(region.get('rotation',0))
                restricted = restricted or ((end[0]-start[0])*math.cos(angle)+(end[1]-start[1])*math.sin(angle)<-1e-8)
            if restricted and self._touches(start,end,region,self.radius):
                return False
        return True

    @staticmethod
    def _touches(start, end, rectangle, radius):
        ax,ay = local_point(start,rectangle)
        bx,by = local_point(end,rectangle)
        w,h = rectangle['width']/2,rectangle['height']/2
        radius += 1e-9
        if max(ax,bx)<-w-radius or min(ax,bx)>w+radius or max(ay,by)<-h-radius or min(ay,by)>h+radius:
            return False
        dx,dy = bx-ax,by-ay
        lo,hi = 0.,1.
        for origin,delta,extent in ((ax,dx,w),(ay,dy,h)):
            if abs(delta)<1e-15:
                if abs(origin)>extent:
                    break
            else:
                first,last = sorted(((-extent-origin)/delta,(extent-origin)/delta))
                lo,hi = max(lo,first),min(hi,last)
                if lo>hi:
                    break
        else:
            return True
        radius2 = radius*radius
        if any(max(abs(x)-w,0)**2+max(abs(y)-h,0)**2<=radius2 for x,y in ((ax,ay),(bx,by))):
            return True
        length2 = dx*dx+dy*dy
        if length2:
            for x,y in ((-w,-h),(-w,h),(w,-h),(w,h)):
                t = max(0.,min(1.,((x-ax)*dx+(y-ay)*dy)/length2))
                if (ax+t*dx-x)**2+(ay+t*dy-y)**2<=radius2:
                    return True
        return False

    def _grid_edge(self, node, nxt):
        grid = self.resolution
        return self.segment((node[0]*grid,node[1]*grid),(nxt[0]*grid,nxt[1]*grid))

    def route(self, start, goal):
        key = tuple(start),tuple(goal)
        if key in self._routes:
            self._routes.move_to_end(key)
            return deepcopy(self._routes[key])
        result = self._route(start,goal)
        self._routes[key] = deepcopy(result)
        if len(self._routes)>256:
            self._routes.popitem(last=False)
        return result

    def _route(self, start, goal):
        if not self.free(start):
            return dict(path=[], reason='起点与障碍、禁行区或车型限制冲突')
        if not self.free(goal):
            return dict(path=[], reason='服务点与障碍、禁行区或车型限制冲突')
        if self.segment(start, goal):
            return dict(path=[list(start), list(goal)], reason='可达')
        grid = self.resolution
        seed = tuple(round(v/grid) for v in start)
        costs, previous, queue = {}, {}, []
        world = lambda node: (node[0]*grid, node[1]*grid)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                node = (seed[0]+dx, seed[1]+dy)
                if self.segment(start, world(node)):
                    costs[node] = math.dist(start, world(node))
                    heapq.heappush(queue, (costs[node]+math.dist(world(node), goal), node))
        closed = set()
        while queue:
            _, node = heapq.heappop(queue)
            if node in closed:
                continue
            closed.add(node)
            position = world(node)
            if math.dist(position, goal) <= grid*2 and self.segment(position, goal):
                path = [list(goal), position]
                while node in previous:
                    node = previous[node]
                    path.append(world(node))
                path = [list(start)]+list(reversed(path))
                # Keep only visible bends; every shortcut uses the same geometry
                # and direction checks as execution.
                simplified, index = [path[0]], 0
                while index<len(path)-1:
                    end = len(path)-1
                    while end>index+1 and not self.segment(path[index],path[end]):
                        end -= 1
                    simplified.append(path[end])
                    index = end
                return dict(path=simplified, reason='可达')
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nxt = (node[0]+dx, node[1]+dy)
                cost = costs[node]+grid*math.hypot(dx, dy)
                if cost < costs.get(nxt, math.inf) and self._edges(node,nxt):
                    costs[nxt], previous[nxt] = cost, node
                    heapq.heappush(queue, (cost+math.dist(world(nxt), goal), nxt))
        narrow = [o['id'] for o in self.floor['objects'] if o['kind']=='door' and o['width'] < self.radius*2]
        reason = f'无可达路线；车型保守通行直径 {self.radius*2:.2f} m'
        if narrow:
            reason += '；不足宽度门洞 ' + ', '.join(narrow)
        return dict(path=[], reason=reason+'；同时检查禁行、单向及型号限制')


class MapStore:
    def __init__(self, root='outputs/maps'):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.status_path = self.root/'map-status.json'
        self._remove_deleted_files(self._statuses())

    def _statuses(self):
        if not self.status_path.exists():
            return {}
        return json.loads(self.status_path.read_text(encoding='utf-8'))

    def _write_statuses(self, statuses):
        temporary = self.root/f'.{uuid.uuid4().hex}.tmp'
        try:
            temporary.write_text(json.dumps(statuses, ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.status_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _remove_deleted_files(self, statuses):
        pending = 0
        for identity, entries in statuses.items():
            for version, status in entries.items():
                if status != 'deleted':
                    continue
                try:
                    for extension in ('json', 'name'):
                        (self.root/identity/f'{version}.{extension}').unlink(missing_ok=True)
                except OSError:
                    pending += 1
        return pending

    def has_history(self, identity):
        with self.lock:
            return bool(self._statuses().get(identity)) or any((self.root/identity).glob('*.json'))

    def was_deleted(self, identity, version):
        with self.lock:
            return self._statuses().get(identity, {}).get(str(version)) == 'deleted'

    def save(self, document):
        check = validate(document)
        if not check['valid']:
            raise ValueError(json.dumps(check, ensure_ascii=False))
        result = normalize_elevators(document)
        check = validate(result)
        if not check['valid']:
            raise ValueError(json.dumps(check,ensure_ascii=False))
        result.pop('digest', None)
        result.pop('display_name', None)
        for floor in result['floors']:
            linked_beds = {obj.get('bed_id') for obj in floor['objects'] if obj['kind'] == 'service'}
            used_numbers = {obj['parking_number'].strip().casefold() for obj in floor['objects']
                            if obj['kind'] == 'parking' and 'parking_number' in obj}
            next_number = 1
            for obj in floor['objects']:
                if obj['kind'] == 'parking' and 'parking_number' not in obj:
                    while f'p{next_number}' in used_numbers:
                        next_number += 1
                    obj['parking_number'] = f'P{next_number}'
                    used_numbers.add(f'p{next_number}')
                if obj['kind'] == 'bed' and obj['id'] in linked_beds:
                    obj.pop('name', None)
        identity = result.get('id', '')
        if not identity or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in identity):
            raise ValueError('地图 ID 只允许字母、数字、下划线和连字符')
        with self.lock:
            folder = self.root/identity
            folder.mkdir(exist_ok=True)
            resolved = folder.resolve()
            if resolved.parent != self.root.resolve() or resolved.name != identity:
                raise ValueError('地图 ID 与现有目录不匹配')
            files = [int(p.stem) for p in folder.glob('*.json')]
            managed = [int(version) for version in self._statuses().get(identity, {})]
            version = max(files + managed, default=0)+1
            result['version'] = version
            payload = json.dumps(result, ensure_ascii=False, sort_keys=True)
            result['digest'] = hashlib.sha256(payload.encode()).hexdigest()
            path = folder/f'{version}.json'
            temporary=folder/('.'+uuid.uuid4().hex+'.tmp')
            try:
                with temporary.open('x',encoding='utf-8') as stream:
                    json.dump(result,stream,ensure_ascii=False,indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary,path)
            except FileExistsError as exc:
                raise ValueError('其他进程已保存该版本，请重试保存') from exc
            finally:
                temporary.unlink(missing_ok=True)
        return result

    def _versions(self, include_archived):
        statuses = self._statuses()
        for path in sorted(self.root.glob('*/*.json')):
            status = statuses.get(path.parent.name, {}).get(path.stem, 'active')
            if status == 'active' or (include_archived and status == 'archived'):
                yield path, status

    def list(self, include_archived=False):
        with self.lock:
            return [json.loads(path.read_text(encoding='utf-8'))
                    for path, _ in self._versions(include_archived)]

    @staticmethod
    def _read_named_version(path):
        document = json.loads(path.read_text(encoding='utf-8'))
        name_path = path.with_suffix('.name')
        if name_path.is_file():
            document['display_name'] = name_path.read_text(encoding='utf-8')
        return document

    def list_with_names(self):
        with self.lock:
            return [self._read_named_version(path) for path, _ in self._versions(False)]

    def catalog(self):
        with self.lock:
            entries = []
            for path, status in self._versions(True):
                document = self._read_named_version(path)
                entries.append(dict(id=document['id'], version=document['version'],
                                    name=document.get('display_name') or document['name'],
                                    template=bool(document.get('template')), status=status))
            return entries

    @staticmethod
    def _version_identity(identity, version):
        if not isinstance(identity, str) or not identity or any(
            c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in identity
        ) or type(version) is not int or version < 1:
            raise ValueError('地图版本无效')
        return identity, str(version)

    def manage_versions(self, action, entries):
        target = {'archive': 'archived', 'restore': 'active', 'delete': 'deleted'}
        if not isinstance(action, str) or action not in target:
            raise ValueError('未知地图管理操作')
        if not isinstance(entries, list) or not entries or any(not isinstance(entry, dict) for entry in entries):
            raise ValueError('请选择要操作的地图版本')
        selected = {self._version_identity(entry.get('map_id'), entry.get('version')) for entry in entries}
        next_status = target[action]
        with self.lock:
            statuses = self._statuses()
            changed = 0
            for identity, version in selected:
                versions = statuses.setdefault(identity, {})
                current = versions.get(version, 'active')
                if current == 'deleted' and next_status == 'deleted':
                    continue
                folder = self.root/identity
                resolved = folder.resolve()
                if (current == 'deleted' or resolved.parent != self.root.resolve() or resolved.name != identity
                        or not (folder/f'{version}.json').is_file()):
                    raise ValueError(f'地图 {identity} v{version} 已不存在，请刷新列表后重试')
                if current == next_status:
                    continue
                if next_status == 'active':
                    versions.pop(version)
                else:
                    versions[version] = next_status
                changed += 1
            if changed:
                self._write_statuses({identity: versions for identity, versions in statuses.items() if versions})
            pending = self._remove_deleted_files(statuses) if action == 'delete' else 0
            return dict(changed=changed, cleanup_pending=pending)

    def rename_version(self, identity, version, name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise ValueError('版本名称应为 1 至 60 个字符')
        self._version_identity(identity, version)
        title = name.strip()
        folder = self.root/identity
        with self.lock:
            if self._statuses().get(identity, {}).get(str(version)) == 'deleted' or not (folder/f'{version}.json').is_file():
                raise ValueError('找不到要改名的地图版本')
            temporary = folder/f'.{uuid.uuid4().hex}.tmp'
            try:
                temporary.write_text(title, encoding='utf-8')
                temporary.replace(folder/f'{version}.name')
            finally:
                temporary.unlink(missing_ok=True)
        return dict(map_id=identity, version=version, display_name=title)


def legacy_map(kind):
    from ward_patrol.simulation.complex_ward_demo import Ward
    ward = Ward(kind)
    document = blank_map(kind)
    document['id'] = kind
    floor = document['floors'][0]
    floor.update(width=ward.hx*2, height=ward.hy*2)
    service_names = {name for name, _ in ward.stops}
    front_y = 2 if kind == 'corridor' else 4
    for index, box in enumerate(ward.boxes):
        if abs(abs(box.y)-front_y)<.001 and abs(box.sy-.16)<.001:
            continue
        object_kind = 'bed' if box.name in service_names else 'wall' if box.height>=1.5 and (box.sx<=.2 or box.sy<=.2) else 'furniture'
        floor['objects'].append(dict(id=f'{kind}-box-{index}', kind=object_kind, name=box.name,
                                     x=box.x, y=box.y, width=box.sx, height=box.sy, rotation=0, z=box.height))
    centers = (-6,0,6) if kind=='corridor' else (-8.25,-2.75,2.75,8.25)
    span = 6 if kind=='corridor' else 5.5
    for sign in (1,-1):
        for index,x in enumerate(centers):
            wall_id=f'{kind}-front-{sign}-{index}'
            floor['objects'].append(dict(id=wall_id,kind='wall',x=x,y=sign*front_y,width=span,height=.16,rotation=0,z=1.55))
            floor['objects'].append(dict(id=wall_id+'-door',kind='door',wall_id=wall_id,x=x if kind=='corridor' else x+.65,
                                         y=sign*front_y,width=1.9,height=.16,rotation=0))
    for name, point in ward.stops:
        bed = next(o for o in floor['objects'] if o.get('name')==name and o['kind']=='bed')
        floor['objects'].append(dict(id=name, name=name,kind='service',bed_id=bed['id'],x=point[0], y=point[1], width=.2, height=.2, rotation=0))
    for index, point in enumerate([ward.start, (ward.hx-1, 0)]):
        floor['objects'].append(dict(id=f'P{index+1}', kind='parking', x=point[0], y=point[1], width=.2, height=.2, rotation=0))
    return document
