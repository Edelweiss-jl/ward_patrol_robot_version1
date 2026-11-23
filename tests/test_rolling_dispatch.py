"""Demand-aware coverage, uncertain elevators, grouped visits and bounded repair."""
from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ward_patrol.maps.geometry import DEFAULT_MODELS, blank_map
from ward_patrol.runtime.dispatch_policy import DispatchPolicy
from ward_patrol.runtime.editable import EditableRuntime
from tests.test_fast_dispatch import plan_until_ready
from tests.test_floor_coverage import local_parking_before_restocking, same_floor_fleet
from tests.test_stage4 import setup, advance_until


def open_scene(robots=1, wall=False):
    document = blank_map()
    document['version'] = 1
    objects = document['floors'][0]['objects']
    for key,x in [('A',-4),('B',4),('C',-3),('D',3)]:
        objects.append(dict(id=key,kind='service',x=x,y=0,width=.2,height=.2))
    fleet = []
    for index,x in enumerate((-6,6)[:robots],1):
        key = f'P{index}'
        objects.append(dict(id=key,kind='parking',x=x,y=0,width=.2,height=.2))
        fleet.append(dict(id=f'R{index}',model_id='small',floor_id='F1',parking_id=key,pose=[x,0,0]))
    if wall:
        objects.append(dict(id='wall',kind='wall',x=0,y=0,width=.2,height=12))
        for obj in objects:
            if obj['id']=='A': obj['x']=-1
            if obj['id']=='B': obj['x']=1
    return document,DEFAULT_MODELS,fleet


def finish_coverage_check(core):
    for _ in range(200):
        core.rebalance_floor_coverage()
        if core._coverage_job is None:
            return
    raise AssertionError('coverage search did not finish')


class RollingCoverageTests(unittest.TestCase):
    def test_busy_and_low_battery_robots_do_not_count_as_ready_and_gap_is_measured(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*setup(),output=root)
            try:
                task = core.add_task('F1-bed-service',robot_id='R1',service='dwell',duration=1000)
                core.dispatch()
                core.robot_instances['R2'].update(battery_percent=20,safety_battery_percent=20)
                core.update_service_coverage()
                self.assertEqual(core.coverage_ready,{'F1':0,'F2':0})
                self.assertEqual(core.snapshot()['floor_coverage']['counts'],{'F1':1,'F2':1})
                core.elapsed = 25
                core.update_service_coverage()
                self.assertEqual(core.snapshot()['floor_coverage']['vacancy_seconds']['F1'],25)
                core.finish(task,core.by_robot['R1'],'test')
                core.update_service_coverage()
                self.assertEqual(core.coverage_ready['F1'],1)
                state = core.snapshot()['floor_coverage']
                self.assertEqual(state['vacancy_seconds']['F1'],0)
                self.assertEqual(state['max_unavailable_seconds']['F1'],25)
                self.assertEqual(state['total_unavailable_seconds']['F1'],25)
            finally: core.close()

    def test_manual_and_mqtt_overruns_remain_unavailable(self):
        for service in ('manual','mqtt'):
            with self.subTest(service=service),TemporaryDirectory() as root:
                core = EditableRuntime(*setup(),output=root)
                try:
                    task = core.add_task('F1-bed-service',robot_id='R1',service=service)
                    core.dispatch()
                    core.by_robot['R1'].xy = task.goal
                    core.by_robot['R1'].path = []
                    core.service_started[task.task_id] = 0.
                    core.elapsed = 1000.
                    core.update_service_coverage()
                    self.assertEqual(core.coverage_ready['F1'],0)
                finally: core.close()

    def test_restocking_waits_for_persistent_gap(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*same_floor_fleet(),output=root)
            try:
                core.add_task('F1-bed-service').status = 'completed'
                core.rebalance_floor_coverage()
                self.assertFalse(core.coverage_moves)
                self.assertEqual(core.coverage_deferred_until['F2'],20)
                core.elapsed = 19
                core.rebalance_floor_coverage()
                self.assertFalse(core.coverage_moves)
                core.elapsed = 20
                finish_coverage_check(core)
                self.assertTrue(core.coverage_moves)
            finally: core.close()

    def test_coverage_can_be_restored_while_another_user_task_is_still_running(self):
        document,models,fleet = same_floor_fleet()
        document['floors'][0]['objects'].append(dict(id='spare3',kind='parking',x=-4,y=2,width=.2,height=.2))
        fleet.append(dict(id='R3',model_id='small',floor_id='F1',pose=[-4,2,0],parking_id='spare3'))
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,models,fleet,output=root)
            try:
                task = core.add_task('F1-bed-service',robot_id='R1',service='manual',duration=1000)
                core.dispatch()
                core.rebalance_floor_coverage()
                core.elapsed = 20
                finish_coverage_check(core)
                self.assertEqual(task.status,'assigned')
                self.assertTrue(core.coverage_moves)
                self.assertNotIn('R1',core.coverage_moves)
            finally: core.close()

    def test_returning_local_robot_prevents_redundant_restocking(self):
        document,models,fleet = deepcopy(setup())
        document['floors'][0]['objects'].append(dict(id='extra',kind='parking',x=-4,y=0,width=.2,height=.2))
        document['floors'][1]['objects'].append(dict(id='free-standby',kind='parking',x=5,y=-3,width=.2,height=.2))
        fleet.append(dict(id='R3',model_id='small',floor_id='F1',pose=[-4,0,0],parking_id='extra'))
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,models,fleet,output=root)
            try:
                core.add_task('F2-bed-service',robot_id='R2',service='dwell',duration=40)
                core.dispatch()
                core.rebalance_floor_coverage()
                core.elapsed = 20
                finish_coverage_check(core)
                self.assertFalse(core.coverage_moves)
                self.assertIn('恢复服务',core.coverage_reason)
            finally: core.close()

    def test_stability_period_prevents_immediate_reverse_transfer(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*same_floor_fleet(),output=root)
            try:
                core.add_task('F1-bed-service').status = 'completed'
                for robot in core.robots: core.note_floor_arrival(robot.robot_id,'F1')
                core.rebalance_floor_coverage()
                core.elapsed = 20
                finish_coverage_check(core)
                self.assertFalse(core.coverage_moves)
                self.assertIn('稳定期',core.coverage_reason)
                core.elapsed = 91
                finish_coverage_check(core)
                self.assertTrue(core.coverage_moves)
            finally: core.close()

    def test_ordinary_arrival_keeps_useful_onboard_relocation(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*local_parking_before_restocking(),output=root)
            try:
                core.add_task('F2-bed-service',robot_id='R1',service='dwell',duration=0)
                lift = core.elevators['E1']
                advance_until(core,lambda: bool(core.coverage_moves) and lift.phase=='riding',limit=10000)
                identity = next(iter(core.coverage_moves))
                request = lift.rider
                core.add_task('F2-bed-service',service='dwell',duration=0)
                self.assertIn(identity,core.coverage_moves)
                self.assertIs(lift.rider,request)
                self.assertFalse(request.cancelled)
            finally: core.close()

    def test_workload_targets_use_service_duration_rather_than_bed_count(self):
        document,models,fleet = same_floor_fleet()
        document['floors'][0]['objects'].append(dict(id='p3',kind='parking',x=-4,y=2,width=.2,height=.2))
        fleet.append(dict(id='R3',model_id='small',floor_id='F1',pose=[-4,2,0],parking_id='p3'))
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,models,fleet,output=root)
            try:
                core.add_task('F1-bed-service',duration=1,service='dwell')
                core.add_task('F2-bed-service',duration=300,service='dwell')
                core.update_service_coverage()
                self.assertEqual(core.coverage_targets,{'F1':1,'F2':2})
                self.assertGreater(core.coverage_workload['F2'],core.coverage_workload['F1'])
            finally: core.close()

    def test_heavy_floor_can_receive_extra_support_while_already_covered(self):
        document,models,fleet = deepcopy(setup())
        document['floors'][0]['objects'].append(dict(id='p3',kind='parking',x=-4,y=0,width=.2,height=.2))
        document['floors'][1]['objects'] += [dict(id='standby',kind='parking',x=5,y=-3,width=.2,height=.2),
            dict(id='extra',kind='service',x=4,y=-.5,width=.2,height=.2)]
        fleet.append(dict(id='R3',model_id='small',floor_id='F1',pose=[-4,0,0],parking_id='p3'))
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,models,fleet,output=root)
            try:
                for bed in ('F2-bed-service','extra'):
                    core.add_task(bed,service='dwell',duration=300,release=30)
                core.rebalance_floor_coverage()
                self.assertEqual(core.coverage_ready['F2'],1)
                core.elapsed = 20
                finish_coverage_check(core)
                self.assertTrue(core.coverage_moves)
                move = next(iter(core.coverage_moves.values()))
                self.assertEqual(move['floor_id'],'F2')
                self.assertEqual(move['point_id'],'standby')
            finally: core.close()


class ElevatorRiskTests(unittest.TestCase):
    def test_boarded_robot_does_not_wait_for_the_elevator_a_second_time(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*setup(),output=root)
            try:
                core.add_task('F2-bed-service',robot_id='R1',service='dwell',duration=0)
                lift = core.elevators['E1']
                advance_until(core,lambda: lift.phase=='riding')
                _,_,_,remaining = core._remaining_work(core.by_robot['R1'])
                self.assertLess(remaining,core.dispatch_policy.coverage_ready_seconds)
                core.elevator_command(dict(action='set_elevator_state',elevator_id='E1',mode='fault'))
                core.update_service_coverage()
                self.assertNotIn('R1', [key for key,(_,seconds) in core._readiness.items()
                                       if seconds<=core.dispatch_policy.coverage_ready_seconds])
            finally: core.close()

    def test_large_response_delay_and_urgent_work_allow_cross_floor_support(self):
        for priority in (0,1):
            document,models,fleet = deepcopy(setup())
            document['floors'][1]['objects'].append(dict(id='extra',kind='service',x=4,y=-.5,width=.2,height=.2))
            with self.subTest(priority=priority),TemporaryDirectory() as root:
                core = EditableRuntime(document,models,fleet,output=root)
                try:
                    core.add_task('F2-bed-service',robot_id='R2',service='manual',duration=1000)
                    core.dispatch()
                    task = core.add_task('extra',service='dwell',duration=0,priority=priority)
                    core.dispatch()
                    self.assertEqual(task.robot_id,'R1')
                    self.assertEqual(core.projected_robot_floors(),{'R1':'F2','R2':'F2'})
                finally: core.close()

    def test_cold_start_interval_and_observed_quantile_are_distinct(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*setup(),output=root)
            try:
                before = core.elevator_wait_risk('E1','F1')
                self.assertEqual(before['source'],'configured_interval')
                for seconds in (5,10,20,30,100,120,160,200):
                    core.record_elevator_wait('E1','F1',seconds)
                after = core.elevator_wait_risk('E1','F1')
                self.assertEqual(after['source'],'observed_quantile')
                self.assertEqual(after['budget_seconds'],200)
                self.assertEqual(after['samples'],8)
                core.elapsed = 3600
                self.assertEqual(core.elevator_wait_risk('E1','F1')['source'],'configured_interval')
            finally: core.close()

    def test_shared_traffic_revokes_unboarded_permission_and_records_actual_wait(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*setup(),output=root)
            try:
                core.add_task('F2-bed-service',robot_id='R1',service='dwell')
                lift = core.elevators['E1']
                advance_until(core,lambda: lift.phase=='permission')
                self.assertFalse(core.elevator_wait_history)
                core.submit(dict(action='set_elevator_traffic',elevator_id='E1',busy_for=.5))
                core.advance()
                self.assertIsNone(lift.permit)
                self.assertIsNone(lift.rider)
                advance_until(core,lambda: lift.phase=='riding')
                waits = list(core.elevator_wait_history['E1','F1',0])
                self.assertEqual(len(waits),1)
                self.assertGreaterEqual(waits[0],.5)
            finally: core.close()

    def test_policy_updates_are_atomic_and_paused_time_does_not_accumulate_gaps(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*setup(),output=root)
            try:
                core.paused = True
                core.submit(dict(action='set_dispatch_policy',policy={'response_seconds':0}))
                core.advance()
                self.assertEqual(core.dispatch_policy.response_seconds,60)
                self.assertEqual(core.events[-1]['event'],'command_rejected')
                core.submit(dict(action='set_dispatch_policy',policy={'response_seconds':45}))
                core.advance()
                self.assertEqual(core.dispatch_policy.response_seconds,45)
                for _ in range(30): core.advance()
                self.assertEqual(core.elapsed,0)
            finally: core.close()


class SpatialPlanningTests(unittest.TestCase):
    def test_nearby_beds_are_contiguous_and_shorten_a_zigzag_queue(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*open_scene(),output=root,policy={'improvement_trials':0,'spatial_radius_m':3})
            try:
                tasks = {bed:core.add_task(bed,service='dwell',duration=0) for bed in ('A','B','C','D')}
                state = plan_until_ready(core)
                queue = state['robot_queues']['R1']
                self.assertLess(queue.index(tasks['C'].task_id),queue.index(tasks['B'].task_id))
                self.assertEqual(state['dispatch_plan'][tasks['C'].task_id]['group_id'],tasks['A'].task_id)
                self.assertLess(sum(visit['estimated_distance'] for visit in state['dispatch_plan'].values()),23)
            finally: core.close()

    def test_group_distance_respects_walls_instead_of_straight_line_distance(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*open_scene(wall=True),output=root,policy={'improvement_trials':0,'spatial_radius_m':3})
            try:
                tasks = {bed:core.add_task(bed,service='dwell',duration=0) for bed in ('A','B','C')}
                queue = plan_until_ready(core)['robot_queues']['R1']
                self.assertEqual(queue[:2],[tasks['A'].task_id,tasks['C'].task_id])
            finally: core.close()

    def _bad_plan(self, core, pinned=False):
        left = core.add_task('A',service='dwell',duration=0,robot_id='R2' if pinned else None)
        right = core.add_task('B',service='dwell',duration=0)
        tasks = {task.task_id:task for task in core.tasks}
        job = core._replay_plan({'R1':[right.task_id],'R2':[left.task_id]},tasks,{'used_ms':0.})
        while True:
            try: next(job)
            except StopIteration as result:
                core.dispatch_plan = result.value
                return left,right

    def test_small_queue_exchange_is_committed_only_after_full_validation(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*open_scene(robots=2),output=root,policy={'improvement_budget_ms':100})
            try:
                left,right = self._bad_plan(core)
                before = sum(item['estimated_distance'] for item in core.dispatch_plan.values())
                list(core._improve_fleet_plan())
                self.assertEqual(core.dispatch_plan[left.task_id]['robot_id'],'R1')
                self.assertEqual(core.dispatch_plan[right.task_id]['robot_id'],'R2')
                self.assertLess(sum(item['estimated_distance'] for item in core.dispatch_plan.values()),before)
            finally: core.close()

    def test_exchange_preserves_pinned_robot_and_budget_abort_keeps_original_plan(self):
        for pinned in (False,True):
            with self.subTest(pinned=pinned),TemporaryDirectory() as root:
                core = EditableRuntime(*open_scene(robots=2),output=root,policy={'improvement_budget_ms':100})
                try:
                    self._bad_plan(core,pinned=pinned)
                    before = deepcopy(core.dispatch_plan)
                    if pinned:
                        list(core._improve_fleet_plan())
                    else:
                        core.dispatch_policy = DispatchPolicy.read({'improvement_budget_ms':1})
                        with patch('ward_patrol.runtime.planning.time.perf_counter',side_effect=[0.,.02,.02]):
                            list(core._improve_fleet_plan())
                    self.assertEqual(core.dispatch_plan,before)
                finally: core.close()


if __name__=='__main__': unittest.main()
