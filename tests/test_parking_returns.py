"""Parking returns through the editable fleet's normal dispatch and execution loop."""
from tempfile import TemporaryDirectory
import unittest

from ward_patrol.maps.geometry import DEFAULT_MODELS, blank_map, copy_floor
from ward_patrol.runtime.editable import EditableRuntime
from ward_patrol.runtime.parking import ParkingRoute
from tests.test_fast_dispatch import plan_until_ready
from tests.test_stage4 import advance_until, setup


def point(identity, kind, x, y=0):
    return dict(id=identity,kind=kind,x=x,y=y,width=.3,height=.3)


def local_scene(battery=100):
    document = blank_map()
    document['version'] = 1
    document['floors'][0]['objects'] = [
        point('P1','parking',-4),point('P2','parking',4),
        point('near','parking',-1,2),point('far','parking',-4,2),
        point('A','service',0,2),point('B','service',4,2),
    ]
    fleet = [
        dict(id='R1',model_id='small',floor_id='F1',pose=[-4,0,0],parking_id='P1',battery_percent=battery),
        dict(id='R2',model_id='small',floor_id='F1',pose=[4,0,0],parking_id='P2'),
    ]
    return document,DEFAULT_MODELS,fleet


class ParkingReturns(unittest.TestCase):
    def test_dispatch_waits_for_charge_when_only_outbound_trip_is_safe(self):
        document = blank_map()
        document['version'] = 1
        document['floors'][0]['objects'] = [point('P','parking',-4),point('A','service',0)]
        fleet = [dict(id='R1',model_id='small',floor_id='F1',pose=[-4,0,0],parking_id='P',
                      battery_percent=60.03,safety_battery_percent=60)]
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,DEFAULT_MODELS,fleet,output=root)
            try:
                task = core.add_task('A',service='dwell',duration=0)
                self.assertNotIn(task.task_id,plan_until_ready(core)['dispatch_plan'])
                core.advance()
                self.assertEqual(task.status,'pending')
                self.assertEqual(core.by_robot['R1'].status,'charging')
                advance_until(core,lambda: task.status=='assigned')
                self.assertGreaterEqual(core.available_battery(core.by_robot['R1'])[0],60.04-1e-9)
                advance_until(core,lambda: any(e['event']=='parking_arrived' for e in core.events))
            finally:
                core.close()

    def test_parked_robot_below_its_safety_limit_charges_above_fifty(self):
        document,models,fleet = local_scene(55)
        fleet[0]['safety_battery_percent'] = 60
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,models,fleet,output=root)
            try:
                core.advance()
                self.assertEqual(core.by_robot['R1'].status,'charging')
                self.assertGreater(core.available_battery(core.by_robot['R1'])[0],55)
            finally:
                core.close()

    def test_dispatch_prefers_another_robot_over_waiting_for_a_top_up(self):
        document,models,fleet = local_scene(60.025)
        fleet[0]['safety_battery_percent'] = 60
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,models,fleet,output=root)
            try:
                task = core.add_task('A',service='dwell',duration=0)
                core.advance()
                self.assertEqual(task.robot_id,'R2')
                self.assertEqual(core.by_robot['R1'].status,'parked')
            finally:
                core.close()

    def test_batch_parking_protects_the_only_reachable_spot(self):
        document,models,fleet = local_scene()
        document['floors'][0]['objects'] = [point('P1','parking',-4),point('P2','parking',0)]
        fleet[1].update(pose=[0,0,0],battery_percent=20.0075)
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,models,fleet,output=root)
            try:
                core.by_robot['R1'].xy = (1,2)
                core.by_robot['R2'].xy = (-1,0)
                core.parking_pending.update(('R1','R2'))
                core.start_parking_returns()
                self.assertEqual({key:move['spot'][1] for key,move in core.parking_moves.items()},
                                 {'R1':'P1','R2':'P2'})
            finally:
                core.close()

    def test_floor_becomes_represented_only_after_predicted_arrival(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*setup(),output=root)
            try:
                task = core.add_task('F2-bed-service',robot_id='R1',service='dwell',duration=0)
                core.dispatch()
                self.assertEqual(task.status,'assigned')
                self.assertEqual(core.robot_floors['R1'],'F1')
                arrivals = core.service_arrivals()
                floor,eta = arrivals['R1']
                self.assertEqual(floor,'F2')
                # Consider the same F2 stall before and after R1 becomes available there.
                core.robot_floors['R2'] = 'F1'
                for seconds,priority in ((eta/2,1),(eta+1,2)):
                    route = ParkingRoute(('F2','F2-parking'),(-4,-2),seconds,0.,())
                    self.assertEqual(core._parking_priority('R2',route,arrivals),priority)
            finally:
                core.close()

    def test_same_floor_nearest_space_and_new_work_only_interrupts_selected_robot(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*local_scene(),output=root)
            try:
                core.add_task('A',robot_id='R1',service='dwell',duration=0)
                advance_until(core,lambda: 'R1' in core.parking_moves)
                move = core.parking_moves['R1']
                self.assertEqual(move['spot'],('F1','near'))
                other = core.add_task('B',service='dwell',duration=0)
                core.advance()
                self.assertEqual(other.robot_id,'R2')
                self.assertIs(core.parking_moves['R1'],move)
                new = core.add_task('A',service='dwell',duration=0)
                core.advance()
                self.assertEqual(new.robot_id,'R1')
                self.assertNotIn('R1',core.parking_moves)
                self.assertTrue(all(spot['returning_robot_id'] is None for spot in core.parking_snapshot()))
                advance_until(core,lambda: new.status=='completed' and core.by_robot['R1'].status=='parked')
                self.assertEqual(len(core.tasks),3)
            finally:
                core.close()

    def test_cross_floor_return_prefers_empty_floor_and_waits_to_preempt_until_exit(self):
        document,models,fleet = setup()
        document = copy_floor(document,'F2')
        destination = document['floors'][-1]['id']
        floors = [floor['id'] for floor in document['floors']]
        for floor in document['floors']:
            for obj in floor['objects']:
                if obj['kind']=='elevator':
                    obj['service_floors'] = floors
        # F2 has no parking. R2 keeps F1 represented while R1's original stall is empty.
        second_floor = document['floors'][1]
        second_floor['objects'] = [obj for obj in second_floor['objects'] if obj['kind']!='parking']
        document['floors'][0]['objects'].append(point('spare','parking',-4,2))
        fleet[1].update(floor_id='F1',pose=[-4,2,0],parking_id='spare')
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,models,fleet,output=root,policy={'rebalance_delay_seconds':90})
            try:
                first = core.add_task('F2-bed-service',robot_id='R1',service='dwell',duration=0)
                advance_until(core,lambda: 'R1' in core.parking_moves)
                self.assertEqual(first.status,'completed')
                self.assertEqual(core.parking_moves['R1']['spot'][0],destination)
                lift = core.elevators['E1']
                advance_until(core,lambda: any(r.robot_id=='R1' for r in lift.riders))
                bed = next(obj['id'] for obj in document['floors'][-1]['objects'] if obj['kind']=='service')
                new = core.add_task(bed,robot_id='R1',service='dwell',duration=0)
                core.advance()
                self.assertEqual(new.status,'pending')
                self.assertTrue(any(r.robot_id=='R1' for r in lift.riders))
                advance_until(core,lambda: new.status=='assigned')
                self.assertFalse(any(r.robot_id=='R1' for r in lift.riders))
                self.assertNotIn('R1',core.parking_moves)
            finally:
                core.close()

    def test_charging_starts_below_fifty_and_continues_to_full(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*local_scene(50),output=root,local_sampling=True)
            try:
                robot = core.by_robot['R1']
                core.advance()
                self.assertEqual(robot.status,'parked')
                self.assertEqual(core.available_battery(robot)[0],50)
                task = core.add_task('A',robot_id='R1',service='mqtt')
                advance_until(core,lambda: robot.status=='charging')
                self.assertEqual(task.status,'completed')
                low = core.available_battery(robot)[0]
                self.assertLess(low,50)
                distance = robot.distance
                advance_until(core,lambda: robot.status=='parked')
                self.assertAlmostEqual(core.available_battery(robot)[0],100)
                self.assertEqual(robot.distance,distance)
            finally:
                core.close()

    def test_return_to_vacant_floor_avoids_a_second_coverage_trip(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*setup(),output=root)
            try:
                task = core.add_task('F2-bed-service',robot_id='R1',service='dwell',duration=0)
                advance_until(core,lambda: 'R1' in core.parking_moves)
                self.assertEqual(core.parking_moves['R1']['spot'],('F1','F1-parking'))
                advance_until(core,lambda: core.by_robot['R1'].status=='parked')
                self.assertEqual(task.status,'completed')
                self.assertEqual(core.floor_coverage_snapshot({})['counts'],{'F1':1,'F2':1})
                self.assertFalse(any(e['event']=='coverage_move_started' for e in core.events))
                self.assertEqual(sum(e['event']=='elevator_occupied' for e in core.events),2)
            finally:
                core.close()


if __name__=='__main__':
    unittest.main()
