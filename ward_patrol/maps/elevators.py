"""Building-wide lift definitions and per-floor landing references (schema 3)."""
from copy import deepcopy
import math
import uuid


LANDING_KEYS = ('entrance_id','waiting_id','exit_id')
DEFAULT_ELEVATOR_CAPACITY = 2
MIGRATION_WARNING = '旧入口的停靠设置不一致，已保留原通行关系；请在统一面板确认停靠楼层。'


def normalize_elevators(document):
    result = deepcopy(document)
    result['schema'] = max(3,result.get('schema',2))
    lifts = result.setdefault('elevators',[])
    if not isinstance(lifts,list):
        raise ValueError('电梯管理数据必须为数组')
    if any(not isinstance(item,dict) or not isinstance(item.get('id'),str) or not isinstance(item.get('name'),str) for item in lifts):
        raise ValueError('电梯必须包含有效的内部标识和名称')
    known = {item['id']:item for item in lifts}
    floor_ids = {floor['id'] for floor in result['floors']}
    groups = {}
    for floor in result['floors']:
        for obj in floor['objects']:
            if obj['kind']=='elevator' and not obj.get('lift_id'):
                key = obj.get('shaft_id','').strip() or obj['id']
                groups.setdefault(key,[]).append((floor['id'],obj))
    used = {lift['name'].casefold() for lift in lifts}
    used.update(key.casefold() for key,items in groups.items() if items[0][1].get('shaft_id','').strip())
    for key,items in groups.items():
        if key in known:
            raise ValueError('旧电梯编号与现有电梯内部标识冲突，请重新关联入口')
        linked = bool(items[0][1].get('shaft_id','').strip())
        number = 1
        while f'E{number}'.casefold() in used:
            number += 1
        name = key if linked else f'E{number}'
        used.add(name.casefold())
        served,landings = [],{}
        actual = {floor:obj for floor,obj in items}
        if len(actual)!=len(items):
            raise ValueError('同一楼层不能有同一部电梯的两个入口')
        for floor,obj in items:
            for fid in [floor,*obj.get('service_floors',[])]:
                if fid in floor_ids and fid not in served:
                    served.append(fid)
            landings[floor] = dict(entrance_id=obj['id'],waiting_id=obj.get('waiting_id'),
                                   exit_id=obj.get('exit_id'),confirmed=True)
            obj['lift_id'] = key
        width = items[0][1].get('width',1.8)
        if type(width) not in (int,float) or not math.isfinite(width) or not .4<=width<=5:
            width = 1.8
        lift = dict(id=key,name=name,served_floors=served,default_width=width,landings=landings)
        connections = {floor:[other for other,target in actual.items() if other!=floor and
            other in obj.get('service_floors',[]) and floor in target.get('service_floors',[])]
            for floor,obj in items}
        if len(items)>1 and any(len(others)!=len(items)-1 for others in connections.values()):
            lift.update(legacy_connections=connections,migration_warning=MIGRATION_WARNING)
        lifts.append(lift)
        for _,obj in items:
            obj.pop('shaft_id',None)
            obj.pop('service_floors',None)
    return result


def catalog_errors(document):
    errors = []
    catalog = document.get('elevators',[])
    if not isinstance(catalog,list):
        return ['电梯管理数据必须为数组']
    floors = {floor['id']:floor for floor in document['floors']}
    known,names,used_markers = {},set(),set()
    for lift in catalog:
        if not isinstance(lift,dict) or not isinstance(lift.get('id'),str) or not lift['id'] or lift['id'] in known:
            errors.append('电梯内部标识必须唯一且非空')
            continue
        known[lift['id']] = lift
        name = lift.get('name')
        if not isinstance(name,str) or not 1<=len(name.strip())<=60 or name.strip().casefold() in names:
            errors.append('电梯名称须为 1 至 60 字且不可重复')
        else:
            names.add(name.strip().casefold())
        width = lift.get('default_width',1.8)
        if type(width) not in (int,float) or not math.isfinite(width) or not .4<=width<=5:
            errors.append('电梯默认入口宽度应为 0.4 至 5 米')
        capacity = lift.get('capacity',DEFAULT_ELEVATOR_CAPACITY)
        if type(capacity) is not int or capacity<1:
            errors.append('电梯每趟最多搭载车辆数须为正整数')
        served = lift.get('served_floors')
        if (not isinstance(served,list) or not served or any(not isinstance(fid,str) or fid not in floors for fid in served)
            or len(set(served))!=len(served)):
            errors.append('电梯停靠楼层必须存在且不可重复')
            continue
        landings = lift.get('landings',{})
        if not isinstance(landings,dict) or any(fid not in served for fid in landings):
            errors.append('电梯入口只能关联已选择的停靠楼层')
            continue
        for fid,landing in landings.items():
            if not isinstance(landing,dict) or type(landing.get('confirmed',False)) is not bool:
                errors.append('电梯入口定位状态无效')
                continue
            by_id = {obj['id']:obj for obj in floors[fid]['objects']}
            if not landing.get('entrance_id'):
                if landing.get('confirmed') or any(landing.get(key) for key in LANDING_KEYS):
                    errors.append('尚未定位的电梯入口不能启用')
                continue
            for key,kind in zip(LANDING_KEYS,('elevator','waiting','exit')):
                marker = landing.get(key)
                obj = by_id.get(marker)
                if obj is None or obj.get('kind')!=kind or (fid,marker) in used_markers:
                    errors.append(f'{lift.get("name",lift["id"])} 的 {fid} 入口或关联点无效、重复')
                used_markers.add((fid,marker))
            entry = by_id.get(landing.get('entrance_id'),{})
            if entry.get('lift_id')!=lift['id'] or any(entry.get(key)!=landing.get(key) for key in ('waiting_id','exit_id')):
                errors.append('电梯入口与统一管理的关联不一致')
            for key in ('waiting_id','exit_id'):
                marker = by_id.get(landing.get(key),{})
                if marker.get('elevator_id') not in (None,entry.get('id')):
                    errors.append('候梯点或出梯点关联了另一入口')
        connections = lift.get('legacy_connections')
        if connections is not None and (not isinstance(connections,dict) or any(
            origin not in served or not isinstance(targets,list) or any(target not in served for target in targets)
            for origin,targets in connections.items())):
            errors.append('旧版电梯通行关系无效')
    per_floor = set()
    for floor in floors.values():
        for obj in floor['objects']:
            if obj.get('kind')!='elevator' or not obj.get('lift_id'):
                continue
            key = obj['lift_id']
            if not isinstance(key,str) or key not in known:
                errors.append('本层入口引用了不存在的电梯')
                continue
            landings = known[key].get('landings',{})
            landing = landings.get(floor['id'],{}) if isinstance(landings,dict) else {}
            if not isinstance(landing,dict):
                landing = {}
            if (floor['id'],key) in per_floor or landing.get('entrance_id')!=obj['id']:
                errors.append('同一部电梯每层只能关联一个入口，且须登记在统一管理中')
            per_floor.add((floor['id'],key))
    return errors


def remove_landing(document, lift, floor_id):
    landing = lift.get('landings',{}).pop(floor_id,{})
    ids = {landing.get(key) for key in LANDING_KEYS}
    floor = next((item for item in document['floors'] if item['id']==floor_id),None)
    if floor:
        floor['objects'] = [obj for obj in floor['objects'] if obj['id'] not in ids]


def landing_reports(document, models):
    from ward_patrol.maps.geometry import Planner, validate
    check = validate(document)
    errors = check['structure']+check['geometry']
    reports = {}
    for lift in document.get('elevators',[]):
        rows = []
        for fid in lift['served_floors']:
            floor = next(item for item in document['floors'] if item['id']==fid)
            landing = lift.get('landings',{}).get(fid,{})
            row = dict(floor_id=fid,status='missing',issues=[],models=[])
            rows.append(row)
            by_id = {obj['id']:obj for obj in floor['objects']}
            if not landing.get('entrance_id'):
                if landing.get('placement_issue'):
                    row['issues'].append(landing['placement_issue'])
                continue
            points = [by_id.get(landing.get(key)) for key in LANDING_KEYS]
            row['issues'] = [error for error in errors if any(str(landing.get(key)) in error for key in LANDING_KEYS)]
            if any(point is None for point in points):
                row.update(status='invalid',issues=['入口、候梯点或出梯点缺失'])
                continue
            entry,wait,exit_point = points
            for model in models:
                planner = Planner(floor,model)
                waiting = wait['x'],wait['y']
                exiting = exit_point['x'],exit_point['y']
                if entry['width']<model['width']+2*model['margin'] or (entry.get('models') and model['id'] not in entry['models']):
                    continue
                reach = math.hypot(exit_point['width'],exit_point['height'])/2+planner.radius+.2
                clear = [tuple(exiting[k]+reach*direction[k] for k in (0,1)) for direction in
                         ((1,0),(-1,0),(0,1),(0,-1),(.707,.707),(.707,-.707),(-.707,.707),(-.707,-.707))]
                if not planner.free(waiting) or not planner.free(exiting) or not any(planner.segment(exiting,point) for point in clear):
                    continue
                anchors = [obj for obj in floor['objects'] if obj['kind'] in ('parking','service')]
                anchors.sort(key=lambda obj:math.dist(waiting,(obj['x'],obj['y'])))
                if anchors and not any(planner.route((obj['x'],obj['y']),waiting)['path'] and
                                       planner.route(exiting,(obj['x'],obj['y']))['path'] for obj in anchors):
                    continue
                row['models'].append(model['id'])
            if not row['models']:
                row['issues'].append('未找到能通过入口、候梯及出梯净空并连接服务/停车点的车型')
            if row['issues']:
                row['status'] = 'invalid'
            else:
                row['status'] = 'ready' if landing.get('confirmed') else 'proposed'
        reports[lift['id']] = rows
    return reports


def fill_missing_landings(document, lift, source_floor_id):
    from ward_patrol.maps.geometry import local_point, validate

    floors = {floor['id']:floor for floor in document['floors']}
    source = lift['landings'].get(source_floor_id,{})
    if not source.get('entrance_id') or source_floor_id not in floors:
        raise ValueError('请先在参考楼层放置入口')
    originals = {obj['id']:obj for obj in floors[source_floor_id]['objects']}
    pieces = [originals[source[key]] for key in LANDING_KEYS]
    for fid in lift['served_floors']:
        if lift['landings'].get(fid,{}).get('entrance_id'):
            continue
        floor = floors[fid]
        copies = deepcopy(pieces)
        ids = {obj['id']:uuid.uuid4().hex for obj in copies}
        for obj in copies:
            obj['id'] = ids[obj['id']]
            for key in ('waiting_id','exit_id','elevator_id'):
                if obj.get(key) in ids:
                    obj[key] = ids[obj[key]]
        entrance = copies[0]
        if entrance.get('wall_id'):
            matching_wall = None
            for wall in floor['objects']:
                if wall['kind']!='wall':
                    continue
                axis = wall
                if wall['height']>wall['width']:
                    axis = dict(wall,width=wall['height'],height=wall['width'],rotation=wall.get('rotation',0)+90)
                if abs(math.sin(math.radians(axis.get('rotation',0)-entrance.get('rotation',0))))>.001:
                    continue
                along,across = local_point((entrance['x'],entrance['y']),axis)
                if abs(across)<=axis['height']/2+.01 and abs(along)+entrance['width']/2<=axis['width']/2+.001:
                    matching_wall = wall
                    break
            if matching_wall is None:
                lift['landings'][fid] = dict(confirmed=False,placement_issue='此层没有匹配墙体，请在该层定位入口')
                continue
            entrance['wall_id'] = matching_wall['id']
        floor['objects'].extend(copies)
        lift['landings'][fid] = dict(zip(LANDING_KEYS,(obj['id'] for obj in copies)),confirmed=False)
        if not validate(document)['valid']:
            remove_landing(document,lift,fid)
            lift['landings'][fid] = dict(confirmed=False,placement_issue='自动生成位置存在几何冲突，请在该层定位入口')


def confirm_ready_landings(lift, rows, floor_ids=None):
    for row in rows:
        if row['status']=='proposed' and (floor_ids is None or row['floor_id'] in floor_ids):
            lift['landings'][row['floor_id']]['confirmed'] = True
            row['status'] = 'ready'


def elevator_action(data, models):
    from ward_patrol.maps.geometry import validate

    document = normalize_elevators(data['map'])
    action = data.get('action','inspect')
    lift = next((item for item in document['elevators'] if item['id']==data.get('lift_id')),None)
    reports = None
    if action in ('create','update'):
        if action=='create':
            lift = dict(id=uuid.uuid4().hex,landings={})
            document['elevators'].append(lift)
        elif lift is None:
            raise ValueError('电梯不存在')
        served = data.get('served_floors',[])
        if not isinstance(served,list) or not served or any(fid not in {f['id'] for f in document['floors']} for fid in served):
            raise ValueError('请至少选择一个有效停靠楼层')
        for fid in list(lift.get('landings',{})):
            if fid not in served:
                remove_landing(document,lift,fid)
        lift.update(name=data.get('name','').strip(),served_floors=served,default_width=data.get('default_width',1.8),
                    capacity=data.get('capacity',lift.get('capacity',DEFAULT_ELEVATOR_CAPACITY)))
        lift.pop('legacy_connections',None)
        lift.pop('migration_warning',None)
        sources = [fid for fid in served if lift['landings'].get(fid,{}).get('entrance_id')]
        if sources and len(sources)<len(served):
            source = next((fid for fid in sources if lift['landings'][fid].get('confirmed')),sources[0])
            fill_missing_landings(document,lift,source)
        if any(lift['landings'][fid].get('confirmed') for fid in sources):
            reports = landing_reports(document,models)
            rows = reports[lift['id']]
            if any(row['status']=='ready' for row in rows):
                confirm_ready_landings(lift,rows)
    elif action=='delete':
        if lift is None:
            raise ValueError('电梯不存在')
        for fid in list(lift['landings']):
            remove_landing(document,lift,fid)
        document['elevators'].remove(lift)
        lift = None
    elif action in ('place','copy'):
        if lift is None:
            raise ValueError('电梯不存在')
        source = data.get('source_floor')
        confirm_source = action=='place' or data.get('confirm_source') is True
        if confirm_source:
            check = validate(document)
            if not check['valid']:
                raise ValueError((check['structure']+check['geometry'])[0])
        fill_missing_landings(document,lift,source)
        if confirm_source:
            reports = landing_reports(document,models)
            rows = reports[lift['id']]
            row = next(row for row in rows if row['floor_id']==source)
            if row['status'] in ('ready','proposed'):
                confirm_ready_landings(lift,rows)
    elif action=='confirm':
        if lift is None:
            raise ValueError('电梯不存在')
        requested = data.get('floor_ids',[])
        if not isinstance(requested,list) or not requested or any(fid not in lift['served_floors'] for fid in requested):
            raise ValueError('请选择需要确认的停靠楼层')
        reports = landing_reports(document,models)
        rows = reports[lift['id']]
        for row in rows:
            if row['floor_id'] in requested and row['status'] not in ('ready','proposed'):
                raise ValueError('此层入口检查未通过：'+'；'.join(row['issues'] or ['尚未定位']))
        confirm_ready_landings(lift,rows,requested)
    elif action!='inspect':
        raise ValueError('未知电梯管理操作')
    errors = catalog_errors(document)
    if errors:
        raise ValueError('；'.join(errors))
    return dict(map=document,lift_id=lift['id'] if lift else None,
                reports=reports if reports is not None else landing_reports(document,models))
