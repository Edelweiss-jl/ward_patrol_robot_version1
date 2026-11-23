"""Cross-floor execution and elevator resource regressions."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ward_patrol.maps.elevators import normalize_elevators
from ward_patrol.maps.geometry import DEFAULT_MODELS, blank_map
from ward_patrol.maps.templates import elevator_demo_map
from ward_patrol.runtime.editable import EditableRuntime
from ward_patrol.runtime.elevator import BOARDING_WAIT_SECONDS, DT


def setup():
    document = elevator_demo_map()
    document['version'] = 1
    instances = [dict(id=f'R{i}', floor_id=f'F{i}', model_id='small', pose=[-4,-2,0],
                      parking_id=f'F{i}-parking') for i in (1,2)]
    return document, DEFAULT_MODELS, instances


def advance_until(core, condition, limit=6000):
    for _ in range(limit):
        core.advance()
        if condition():
            return
    raise AssertionError([(robot.robot_id,robot.status,robot.xy) for robot in core.robots])


class ElevatorTests(unittest.TestCase):
    def test_upstairs_robots_share_trip_or_depart_at_timeout(self):
        scenarios = [
            (2,-3.7,2,False,'large'),(2,3.5,1,False,'small'),(2,-3.7,2,True,'small'),
            (1,-3.7,1,False,'small'),(3,-3.7,3,False,'small'),
        ]
        for capacity, second_y, trip_size, cancel_second, model_id in scenarios:
            with self.subTest(capacity=capacity,trip_size=trip_size,cancel_second=cancel_second,model=model_id), TemporaryDirectory() as root:
                document,models,instances = setup()
                origin, target = document['floors']
                origin['objects'].append(dict(id='R2-parking',kind='parking',x=-2,y=second_y,width=.6,height=.6))
                instances[1].update(floor_id='F1',pose=[-2,second_y,0],parking_id='R2-parking')
                for instance in instances:
                    instance['model_id'] = model_id
                target.update(id='F4',name='四层')
                target['objects'].append(dict(id='other-service',kind='service',x=4,y=-3,width=.3,height=.3))
                document['floors'][1:1] = [dict(id=f'F{i}', name=f'{i}层', width=14., height=10., objects=[])
                                           for i in (2,3)]
                for floor in (origin,target):
                    entrance = next(obj for obj in floor['objects'] if obj['kind']=='elevator')
                    entrance['service_floors'] = ['F1','F4']
                assignments = [('R1','F2-bed-service'),('R2','other-service')]
                if capacity==3:
                    origin['objects'].append(dict(id='R3-parking',kind='parking',x=.3,y=-2,width=.6,height=.6))
                    instances.append(dict(id='R3',floor_id='F1',model_id=model_id,pose=[.3,-2,0],parking_id='R3-parking'))
                    target['objects'].append(dict(id='third-service',kind='service',x=-4,y=-3.4,width=.3,height=.3))
                    assignments.append(('R3','third-service'))
                if capacity!=2:
                    document = normalize_elevators(document)
                    document['elevators'][0]['capacity'] = capacity
                core = EditableRuntime(document,models,instances,output=root)
                try:
                    for robot,bed in assignments:
                        core.submit(dict(action='create_task',bed=bed,
                                         task=dict(robot_id=robot,priority=1,service='dwell',duration=0)))
                    lift = core.elevators['E1']
                    advance_until(core,lambda: lift.phase==('riding' if capacity==1 else 'boarding'))
                    self.assertEqual(lift.snapshot()['capacity'],capacity)
                    self.assertEqual(lift.snapshot()['occupant_robot_ids'],['R1'])
                    if cancel_second:
                        advance_until(core,lambda: lift.phase=='riding')
                        self.assertEqual(lift.snapshot()['occupant_robot_ids'],['R1','R2'])
                        core.submit(dict(action='cancel_task',task_id=core.tasks[1].task_id))
                    outcomes = ['completed','cancelled' if cancel_second else 'completed']
                    if capacity==3:
                        outcomes.append('completed')
                    advance_until(core,lambda: not lift.riders and [task.status for task in core.tasks]==outcomes)
                    events = list(core.events)
                    trips = [event for event in events if event['event']=='elevator_departed' and event['occupant_robot_ids']]
                    boarded = next(event for event in events if event['event']=='elevator_occupied')
                    elapsed = (trips[0]['step']-boarded['step'])*DT
                    if trip_size>1:
                        self.assertEqual(len(trips),1)
                        self.assertCountEqual(trips[0]['occupant_robot_ids'],[robot for robot,_ in assignments])
                        self.assertGreater(elapsed,0)
                        self.assertLessEqual(elapsed,BOARDING_WAIT_SECONDS)
                    else:
                        self.assertEqual([trip['occupant_robot_ids'] for trip in trips],[['R1'],['R2']])
                        self.assertAlmostEqual(elapsed,0 if capacity==1 else BOARDING_WAIT_SECONDS)
                    released = [event['robot_id'] for event in events if event['event']=='elevator_released']
                    self.assertEqual(released,[robot for trip in trips for robot in trip['occupant_robot_ids']])
                    self.assertEqual(core.robot_floors,{robot:'F4' for robot,_ in assignments})
                finally:
                    core.close()

    def test_single_lane_blocks_exit_without_admitting_opposing_vehicle(self):
        document = blank_map('窄通道验收')
        document['version'] = 1
        floor = document['floors'][0]
        floor['objects'] = [dict(id='lane',kind='single_lane',x=0,y=0,width=2,height=1.3)]
        for number, x in enumerate((-3,3),1):
            floor['objects'] += [dict(id=f'P{number}',kind='parking',x=x,y=0,width=.3,height=.3),
                                 dict(id=f'S{number}',kind='service',x=x,y=0,width=.3,height=.3)]
        fleet = [dict(id=f'R{i}',floor_id='F1',model_id='small',pose=[x,0,0],parking_id=f'P{i}')
                 for i,x in enumerate((-3,3),1)]
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,DEFAULT_MODELS,fleet,output=root)
            try:
                for robot,bed in [('R1','S2'),('R2','S1')]:
                    core.submit(dict(action='create_task',bed=bed,task=dict(robot_id=robot,service='dwell',duration=0)))
                gate = core.passages['lane']
                advance_until(core,lambda: bool(gate.occupant))
                first = gate.occupant
                core.submit(dict(action='set_passage_exit_blocked',passage_id='lane',blocked=True))
                advance_until(core,lambda: bool(gate.queue))
                for _ in range(360): core.advance()
                self.assertEqual(gate.occupant,first)
                self.assertIsNone(gate.permit)
                core.submit(dict(action='set_passage_exit_blocked',passage_id='lane',blocked=False))
                advance_until(core,lambda: all(task.status=='completed' for task in core.tasks))
                history = [event['event'] for event in core.events if event['event'] in ('passage_occupied','passage_released')]
                self.assertEqual(history,['passage_occupied','passage_released']*2)
            finally:
                core.close()

    def test_opposite_directions_wait_and_timeline_covers_every_step(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*setup(),output=root)
            try:
                core.submit(dict(action='create_task',bed='F2-bed-service',task=dict(robot_id='R1',service='dwell',duration=0)))
                core.submit(dict(action='create_task',bed='F1-bed-service',task=dict(robot_id='R2',service='dwell',duration=0)))
                advance_until(core,lambda: len(core.tasks)==2 and all(task.status=='completed' for task in core.tasks))
                events = [event for event in core.events if event['event'].startswith('elevator_')]
                permits = [event for event in events if event['event']=='elevator_entry_permitted']
                releases = [event for event in events if event['event']=='elevator_released']
                self.assertEqual([event['robot_id'] for event in permits],['R1','R2'])
                self.assertLessEqual(releases[0]['step'],permits[1]['step'])
                self.assertGreater(permits[1]['wait_seconds'],0)
                self.assertEqual(core.robot_floors,{'R1':'F2','R2':'F1'})
                timeline = [json.loads(line) for line in (Path(root)/core.run_id/'elevators.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertEqual([entry['step'] for entry in timeline],list(range(core.step+1)))
                travelling = [entry['elevators'][0] for entry in timeline if entry['elevators'][0]['phase']=='riding']
                self.assertTrue(travelling)
                self.assertTrue(all(item['floor_id'] is None and item['occupant_robot_id'] for item in travelling))
            finally:
                core.close()

    def test_fault_and_blocked_exit_retain_occupancy_until_clear(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*setup(),output=root)
            try:
                core.submit(dict(action='create_task',bed='F2-bed-service',task=dict(robot_id='R1',service='dwell',duration=0)))
                lift = core.elevators['E1']
                advance_until(core,lambda: lift.phase=='riding')
                core.submit(dict(action='set_elevator_state',elevator_id='E1',mode='fault'))
                movement = lift.motion_steps
                for _ in range(40): core.advance()
                self.assertEqual(lift.motion_steps,movement)
                self.assertEqual(lift.rider.robot_id,'R1')
                core.submit(dict(action='set_elevator_exit_blocked',elevator_id='E1',floor_id='F2',blocked=True))
                core.submit(dict(action='set_elevator_state',elevator_id='E1',mode='out_of_service'))
                advance_until(core,lambda: core.robots[0].status=='waiting_elevator_exit')
                self.assertEqual(lift.rider.robot_id,'R1')
                self.assertEqual(lift.floor,'F2')
                core.submit(dict(action='set_elevator_exit_blocked',elevator_id='E1',floor_id='F2',blocked=False))
                advance_until(core,lambda: core.tasks[0].status=='completed')
                self.assertIsNone(lift.rider)
                self.assertEqual(lift.mode,'out_of_service')
            finally:
                core.close()

    def test_cancel_onboard_preserves_occupancy_until_safe_exit(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*setup(),output=root)
            try:
                core.submit(dict(action='create_task',bed='F2-bed-service',task=dict(robot_id='R1',service='dwell')))
                lift = core.elevators['E1']
                advance_until(core,lambda: lift.phase=='riding')
                for _ in range(2):
                    core.submit(dict(action='cancel_task',task_id=core.tasks[0].task_id))
                core.advance()
                self.assertEqual(core.tasks[0].status,'cancelled')
                self.assertEqual(lift.rider.robot_id,'R1')
                advance_until(core,lambda: lift.rider is None)
                self.assertEqual(core.robot_floors['R1'],'F2')
                self.assertEqual(sum(event['event']=='elevator_released' for event in core.events),1)
            finally:
                core.close()

    def test_revoking_permission_keeps_robot_outside_and_replans_after_restore(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*setup(),output=root)
            try:
                core.submit(dict(action='create_task',bed='F2-bed-service',task=dict(robot_id='R1',service='dwell',duration=0)))
                lift = core.elevators['E1']
                advance_until(core,lambda: lift.phase=='permission')
                core.submit(dict(action='set_elevator_state',elevator_id='E1',mode='out_of_service'))
                core.advance()
                self.assertIsNone(lift.permit)
                self.assertIsNone(lift.rider)
                self.assertEqual(core.robot_floors['R1'],'F1')
                self.assertEqual(core.tasks[0].status,'pending')
                core.submit(dict(action='set_elevator_state',elevator_id='E1',mode='enabled'))
                advance_until(core,lambda: core.tasks[0].status=='completed')
                self.assertTrue(any(event['event']=='elevator_reservation_released' for event in core.events))
            finally:
                core.close()
