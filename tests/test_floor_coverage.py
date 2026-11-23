"""Resident assignment, minimum elevator rides, and safe idle redistribution."""
from copy import deepcopy
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ward_patrol.maps.geometry import DEFAULT_MODELS, copy_floor
from ward_patrol.runtime.editable import EditableRuntime
from ward_patrol.runtime.elevator import Elevator, Landing, Ride, cross_floor_route
from tests.test_fast_dispatch import plan_until_ready
from tests.test_stage4 import setup, advance_until


def same_floor_fleet():
    document,models,fleet = deepcopy(setup())
    floor = document['floors'][0]
    floor['objects'].append(dict(id='F1-spare',kind='parking',x=-4,y=0,width=.3,height=.3))
    fleet[1].update(floor_id='F1',parking_id='F1-spare',pose=[-4,0,0])
    document['floors'][1]['objects'].append(dict(id='F2-extra',kind='service',x=4,y=-.5,width=.2,height=.2))
    return document,models,fleet


def local_parking_before_restocking():
    document,models,fleet = setup()
    # F2 can park both vehicles. Restocking F1 then exercises the coverage
    # policy independently of a cross-floor parking return.
    document['floors'][1]['objects'].append(dict(id='F2-extra-parking',kind='parking',
                                                x=-4,y=1,width=.3,height=.3))
    return document,models,fleet


class FloorCoverageTests(unittest.TestCase):
    def test_resident_is_selected_even_when_remote_estimate_is_faster(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*setup(),output=root)
            try:
                task = core.add_task('F2-bed-service',service='dwell')
                original = core.find_robot_route

                def estimates(robot,model,destination,goal,origin=None,**options):
                    route,reason = original(robot,model,destination,goal,origin=origin,**options)
                    if route:
                        _,distance,actions = route
                        route = (1. if robot.robot_id=='R1' else 40.,distance,actions)
                    return route,reason

                with patch.object(core,'find_robot_route',side_effect=estimates):
                    plan = plan_until_ready(core)['dispatch_plan'][task.task_id]
                    self.assertEqual(plan['robot_id'],'R2')
                    self.assertEqual(plan['elevator_rides'],0)
                    core.dispatch()
                self.assertEqual(task.robot_id,'R2')
                self.assertFalse(core.route_actions)
            finally:
                core.close()

    def test_busy_resident_keeps_next_bed_instead_of_borrowing_last_robot(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*same_floor_fleet(),output=root)
            try:
                first = core.add_task('F2-bed-service',service='dwell',duration=0)
                second = core.add_task('F2-extra',service='dwell',duration=0)
                core.dispatch()
                self.assertEqual(first.status,'assigned')
                self.assertEqual(second.status,'pending')
                self.assertIn('同层',core.wait_reasons[second.task_id])
                plan = plan_until_ready(core)['dispatch_plan'][second.task_id]
                self.assertEqual(plan['robot_id'],first.robot_id)
                self.assertEqual(plan['elevator_rides'],0)
                advance_until(core,lambda: all(t.status=='completed' for t in core.tasks),limit=10000)
                state = core.snapshot()
                self.assertTrue(all(state['floor_coverage']['counts'].values()))
                rides = [e for e in core.events if e['event']=='elevator_occupied']
                self.assertEqual(len(rides),1)
                self.assertFalse(core.coverage_moves)
            finally:
                core.close()

    def test_donor_with_spare_robots_is_preferred_over_emptying_another_floor(self):
        document,models,fleet = deepcopy(setup())
        document = copy_floor(document,'F2')
        destination = document['floors'][-1]['id']
        levels = [floor['id'] for floor in document['floors']]
        for floor in document['floors']:
            for obj in floor['objects']:
                if obj['kind']=='elevator':
                    obj['service_floors'] = list(levels)
        document['floors'][1]['objects'].append(dict(id='F2-spare',kind='parking',x=-4,y=0,width=.3,height=.3))
        fleet.append(dict(id='R3',floor_id='F2',model_id='small',pose=[-4,0,0],parking_id='F2-spare'))
        bed = next(obj['id'] for obj in document['floors'][-1]['objects'] if obj['kind']=='service')
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,models,fleet,output=root)
            try:
                task = core.add_task(bed)
                plan = plan_until_ready(core)['dispatch_plan']
                self.assertIn(plan[task.task_id]['robot_id'],('R2','R3'))
                coverage = core.snapshot()['floor_coverage']
                self.assertEqual(coverage['projected_counts'],{'F1':1,'F2':1,destination:1})
                core.dispatch()
                self.assertIn(task.robot_id,('R2','R3'))
            finally:
                core.close()

    def test_explicit_assignment_is_honored_then_missing_floor_is_restocked(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*local_parking_before_restocking(),output=root)
            try:
                task = core.add_task('F2-bed-service',robot_id='R1',service='dwell',duration=0)
                advance_until(core,lambda: bool(core.coverage_moves),limit=10000)
                self.assertEqual(task.robot_id,'R1')
                self.assertEqual(task.status,'completed')
                self.assertEqual(len(core.tasks),1)
                self.assertTrue(any(e['event']=='coverage_move_started' for e in core.events))
                advance_until(core,lambda: not core.coverage_moves and
                              all(core.snapshot()['floor_coverage']['counts'].values()),limit=10000)
                self.assertEqual(sum(r.completed_tasks for r in core.robots),1)
                self.assertEqual(len([e for e in core.events if e['event']=='elevator_occupied']),2)
                self.assertEqual(len([e for e in core.events if e['event']=='task_completed']),1)
                self.assertTrue(any(e['event']=='coverage_move_completed' for e in core.events))
            finally:
                core.close()

    def test_new_patrol_interrupts_restocking_onboard_without_releasing_lift_early(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*local_parking_before_restocking(),output=root)
            try:
                core.add_task('F2-bed-service',robot_id='R1',service='dwell',duration=0)
                lift = core.elevators['E1']
                advance_until(core,lambda: bool(core.coverage_moves) and lift.phase=='riding',limit=10000)
                request = lift.rider
                new = core.add_task('F2-bed-service',service='dwell',duration=0,priority=1)
                self.assertFalse(core.coverage_moves)
                self.assertIs(lift.rider,request)
                self.assertTrue(request.cancelled)
                self.assertIsNone(core.by_robot[request.robot_id].task_id)
                advance_until(core,lambda: new.status=='completed' and lift.rider is None,limit=10000)
                self.assertEqual(len(core.tasks),2)
                self.assertTrue(any(e['event']=='coverage_move_cancelled' for e in core.events))
                self.assertTrue(any(e['event']=='elevator_released' and e.get('task_id')==request.task_id
                                    for e in core.events))
            finally:
                core.close()

    def test_elevator_shutdown_cancels_standby_reservation_and_retries_on_restore(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*local_parking_before_restocking(),output=root)
            try:
                core.add_task('F2-bed-service',robot_id='R1',service='dwell',duration=0)
                lift = core.elevators['E1']
                advance_until(core,lambda: bool(core.coverage_moves) and lift.phase=='permission',limit=10000)
                core.elevator_command(dict(action='set_elevator_state',elevator_id='E1',mode='out_of_service'))
                self.assertFalse(core.coverage_moves)
                self.assertIsNone(lift.permit)
                self.assertTrue(all(r.task_id is None for r in core.robots))
                core.rebalance_floor_coverage()
                self.assertTrue(core.snapshot()['floor_coverage']['reason'])
                core.elevator_command(dict(action='set_elevator_state',elevator_id='E1',mode='enabled'))
                advance_until(core,lambda: any(e['event']=='coverage_move_completed' for e in core.events),limit=10000)
                self.assertTrue(all(core.snapshot()['floor_coverage']['counts'].values()))
            finally:
                core.close()

    def test_shortage_and_battery_constraints_do_not_trigger_pointless_trips(self):
        document,models,fleet = setup()
        for robots in (deepcopy(fleet[:1]),deepcopy(same_floor_fleet()[2])):
            data = (document,models,robots) if len(robots)==1 else same_floor_fleet()
            if len(robots)>1:
                for robot in data[2]:
                    robot.update(battery_percent=20,safety_battery_percent=20)
            with self.subTest(robots=len(robots)),TemporaryDirectory() as root:
                core = EditableRuntime(*data,output=root)
                try:
                    task = core.add_task('F1-bed-service')
                    task.status = 'completed'
                    core.rebalance_floor_coverage()
                    state = core.snapshot()['floor_coverage']
                    self.assertFalse(core.coverage_moves)
                    self.assertTrue(state['reason'])
                    self.assertEqual(state['robot_shortage'],int(len(robots)==1))
                    with patch.object(core,'find_robot_route',side_effect=AssertionError('unnecessary retry')):
                        core.rebalance_floor_coverage()
                finally:
                    core.close()

    def test_deadline_can_require_cross_floor_help(self):
        document,models,fleet = setup()
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,models,fleet,output=root)
            try:
                busy = core.add_task('F2-bed-service',robot_id='R2',service='dwell',duration=1000)
                core.dispatch()
                # A second point avoids the occupied-bed exclusion.
                core.services['extra'] = ('F2',dict(x=4,y=-.5))
                core.ward.stops.append(('extra',(4,-.5)))
                urgent = core.add_task('extra',deadline=100,service='dwell',duration=0)
                core.dispatch()
                self.assertEqual(busy.status,'assigned')
                self.assertEqual(urgent.robot_id,'R1')
            finally:
                core.close()

    def test_capability_requirement_can_override_resident_preference(self):
        document,models,fleet = deepcopy(setup())
        local = dict(deepcopy(models[0]),id='local',capabilities=['patrol'])
        models.append(local)
        fleet[1]['model_id'] = 'local'
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,models,fleet,output=root)
            try:
                task = core.add_task('F2-bed-service',capabilities=['vitals'])
                visit = plan_until_ready(core)['dispatch_plan'][task.task_id]
                self.assertEqual(visit['robot_id'],'R1')
                self.assertEqual(visit['elevator_rides'],1)
                core.dispatch()
                self.assertEqual(task.robot_id,'R1')
            finally:
                core.close()


class ElevatorRidePreferenceTests(unittest.TestCase):
    def test_direct_lift_is_preferred_to_faster_two_lift_transfer(self):
        def landing(floor,floors,x):
            return Landing(dict(width=2,service_floors=floors),dict(x=x,y=0),
                           dict(x=x,y=0,width=.4,height=.4))

        lifts = {}
        for identity,floors,x in [('direct',['F1','F3'],50),('lower',['F1','F2'],0),('upper',['F2','F3'],0)]:
            lifts[identity] = Elevator(identity,{f:landing(f,floors,x) for f in floors},floors[0])
        planner = SimpleNamespace(radius=.2,free=lambda point:True,segment=lambda a,b:True,
                                  route=lambda a,b:dict(path=[a,b]))
        model = dict(DEFAULT_MODELS[0],speed=1.)
        route = cross_floor_route(lifts,{'F1':0,'F2':1,'F3':2},
                                 {floor:planner for floor in ('F1','F2','F3')},model,'F1',(0,0),'F3',(0,0))
        self.assertIsNotNone(route)
        rides = [action for action in route[2] if isinstance(action,Ride)]
        self.assertEqual([ride.elevator_id for ride in rides],['direct'])
        self.assertGreater(route[0],90.)
        fastest = cross_floor_route(lifts,{'F1':0,'F2':1,'F3':2},
                                    {floor:planner for floor in ('F1','F2','F3')},model,
                                    'F1',(0,0),'F3',(0,0),fastest=True)
        self.assertLess(fastest[0],route[0])
        self.assertEqual([ride.elevator_id for ride in fastest[2] if isinstance(ride,Ride)],['lower','upper'])


if __name__=='__main__':
    unittest.main()
