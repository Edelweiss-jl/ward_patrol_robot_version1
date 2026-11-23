"""Editable examples for common hospital layouts, using meter coordinates."""
from ward_patrol.maps.geometry import blank_map


def hospital_templates():
    yield _double_ward()
    yield _outpatient()
    yield _emergency()
    yield sensor_demo_map()
    yield elevator_demo_map()


def sensor_demo_map():
    document, floor = _example('sensor-demo','测距避障验收病区','单车狭长通道，推车堵路后可观察停车、上报和恢复。',20,8)
    _object(floor,'wall','sensor-north','北侧通道墙',0,1.15,18,1.2)
    _object(floor,'wall','sensor-south','南侧通道墙',0,-1.15,18,1.2)
    _object(floor,'wall','sensor-west','通道西端',-9,0,.4,2.6)
    _object(floor,'wall','sensor-east','通道东端',9,0,.4,2.6)
    _parking(floor,[(-4,0)])
    _object(floor,'service','sensor-stop','床旁验收点',4,0,.25,.25)
    return document


def elevator_demo_map():
    document = blank_map('两层电梯验收病区')
    document.update(id='elevator-demo', template=True, description='两层各有停车点和床位，共用 E1，适合验证相反方向的巡查请求。')
    document['floors'] = []
    for index, name in enumerate(('一层','二层'),1):
        prefix = f'F{index}'
        floor = dict(id=prefix, name=name, width=14., height=10., objects=[], area_defined=True)
        document['floors'].append(floor)
        for side,x,y,length,rotation in (('north',0,5,14,0),('south',0,-5,14,0),
                                         ('west',-7,0,10,90),('east',7,0,10,90)):
            _object(floor,'wall',f'{prefix}-{side}','楼层外墙',x,y,length,.2,rotation=rotation,boundary_side=side)
        _object(floor,'parking',prefix+'-parking','停车位',-4,-2,.6,.6)
        _bed(floor,prefix+'-bed',4,3.2)
        _object(floor,'elevator',prefix+'-lift','E1 电梯入口',0,-5,1.8,.2,wall_id=prefix+'-south',
                shaft_id='E1',service_floors=['F1','F2'],waiting_id=prefix+'-wait',exit_id=prefix+'-exit')
        _object(floor,'waiting',prefix+'-wait','E1 候梯点',-2,-2,.35,.35,elevator_id=prefix+'-lift')
        _object(floor,'exit',prefix+'-exit','E1 出梯区',2,-2,.8,.8,elevator_id=prefix+'-lift')
    return document


def _example(identity, name, description, width, height):
    document = blank_map(name)
    document.update(id=identity, template=True, description=description)
    floor = document['floors'][0]
    floor.update(width=width, height=height, area_defined=True)
    for side, x, y, length, rotation in (
        ('north', 0, height/2, width, 0), ('south', 0, -height/2, width, 0),
        ('west', -width/2, 0, height, 90), ('east', width/2, 0, height, 90),
    ):
        _object(floor, 'wall', 'wall-'+side, '楼层外墙', x, y, length, .2,
                rotation=rotation, boundary_side=side)
    return document, floor


def _object(floor, kind, identity, name, x, y, width, height, **properties):
    floor['objects'].append(dict(id=identity, kind=kind, name=name, x=x, y=y,
                                 width=width, height=height, rotation=0) | properties)


def _furniture(floor, asset, identity, name, x, y, width, height):
    _object(floor, 'furniture', identity, name, x, y, width, height, asset=asset)


def _front(floor, identity, x, y, span, door_width=1.7):
    _object(floor, 'wall', identity, '房间隔墙', x, y, span, .2)
    _object(floor, 'door', identity+'-door', '房门', x, y, door_width, .2, wall_id=identity)


def _bed(floor, identity, x, y):
    _object(floor, 'bed', identity, identity, x, y, 1.05, 2.1, asset='bed')
    _object(floor, 'service', identity+'-service', identity+' 床旁', x, y-1.85, .25, .25,
            bed_id=identity, auto_link=True)


def _parking(floor, positions):
    for index, (x, y) in enumerate(positions, 1):
        _object(floor, 'parking', 'parking-'+str(index), '停车位 '+str(index), x, y, .6, .6)


def _double_ward():
    document, floor = _example('double-ward', '双床住院病房',
        '两间双床病房共享走廊和医护站，适合床旁巡查。', 14, 12)
    for room, center in enumerate((-3.5, 3.5), 1):
        _front(floor, f'room-{room}', center, 0, 7)
        for bed_number, offset in enumerate((-1.5, 1.5), 1):
            x = center+offset
            _bed(floor, f'{room:02d}-{bed_number}', x, 3.7)
            _furniture(floor, 'cabinet', f'cabinet-{room}-{bed_number}', '床头柜', x+.9, 4.5, .5, .5)
    _object(floor, 'wall', 'partition', '病房隔墙', 0, 3, 6, .2, rotation=90)
    _furniture(floor, 'nurse_station', 'station', '医护站', 0, -3.5, 3, 1.2)
    _parking(floor, [(-5.5,-4),(-3.5,-4),(3.5,-4),(5.5,-4)])
    return document


def _outpatient():
    document, floor = _example('outpatient-clinic', '门诊诊区',
        '三间诊室、候诊区和分诊台，服务点位于各诊室内。', 18, 12)
    for room, center in enumerate((-6,0,6), 1):
        _front(floor, f'clinic-{room}', center, 0, 6)
        _furniture(floor, 'desk', f'desk-{room}', f'诊疗桌 {room}', center-1.3, 4, 1.6, .8)
        _furniture(floor, 'equipment', f'equipment-{room}', '医疗设备', center+1.7, 4.3, .65, .65)
        _object(floor, 'service', f'clinic-stop-{room}', f'诊室 {room} 服务点', center, 2.4, .25, .25)
    for index, x in enumerate((-3,3), 1):
        _object(floor, 'wall', f'clinic-wall-{index}', '诊室隔墙', x, 3, 6, .2, rotation=90)
    _furniture(floor, 'nurse_station', 'triage', '分诊台', 0, -4, 2.8, 1)
    for index, x in enumerate((-6,6), 1):
        _furniture(floor, 'bench', f'bench-{index}', '候诊长椅', x, -4.8, 2.2, .65)
    _parking(floor, [(-7,-2),(-4,-2),(4,-2),(7,-2)])
    return document


def _emergency():
    document, floor = _example('emergency-observation', '急诊留观区',
        '开放式四床留观区与独立处置室，适合比较宽通道和门洞的车型通行。', 18, 14)
    for index, x in enumerate((-6.6,-4.2,-1.8,.6), 1):
        _bed(floor, f'留观床 {index}', x, 4.6)
    _object(floor, 'wall', 'treatment-side', '处置室侧墙', 3, 4, 6, .2, rotation=90)
    _front(floor, 'treatment-front', 6, 1, 6, 2)
    _bed(floor, '处置床', 6, 5)
    _furniture(floor, 'medicine', 'medicine', '药品柜', 7.7, 5.5, 1.2, .5)
    _furniture(floor, 'nurse_station', 'station', '急诊医护站', 0, -2.5, 3.4, 1.2)
    _parking(floor, [(-7,-4),(-4.5,-4),(4.5,-4),(7,-4)])
    return document
