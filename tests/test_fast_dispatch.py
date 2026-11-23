"""Look-ahead allocation, cache invalidation and continuous path safety."""
from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ward_patrol.maps.geometry import DEFAULT_MODELS, Planner, blank_map
from ward_patrol.runtime.editable import EditableRuntime
from tests.test_stage2 import scene, instances
from tests.test_stage4 import setup as elevator_setup


def plan_until_ready(core, limit=500):
    for _ in range(limit):
        core.advance_planning()
        if core.planning_metrics['status']=='ready':
            return core.planning_snapshot()
    raise AssertionError(core.planning_metrics)


class FastDispatchTests(unittest.TestCase):
    def test_legacy_retry_caps_are_ignored_and_attempt_ids_keep_advancing(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(scene(3),DEFAULT_MODELS,instances(1),output=root)
            try:
                core.paused = True
                task = core.add_task('S0',retry={'max_attempts':1})
                self.assertNotIn('retry',core.task_specs[task.task_id])
                for expected in range(2,22):
                    core.submit(dict(action='retry_task',task_id=task.task_id))
                    core.advance()
                    self.assertEqual(core.attempts[task.task_id],expected)
                    self.assertEqual(task.status,'pending')
                self.assertFalse(any(event['event']=='command_rejected' for event in core.events))
            finally:
                core.close()

    def test_all_pending_beds_have_unique_robot_queue_and_safe_paths(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(scene(3),DEFAULT_MODELS,instances(2),output=root)
            try:
                tasks = [core.add_task('S'+str(i%4),service='dwell',duration=1) for i in range(20)]
                state = plan_until_ready(core)
                self.assertEqual(set(state['dispatch_plan']),{t.task_id for t in tasks})
                queued = [key for queue in state['robot_queues'].values() for key in queue]
                self.assertEqual(len(queued),len(set(queued)))
                self.assertEqual(set(queued),{t.task_id for t in tasks})
                self.assertTrue(all(state['robot_queues'].values()))
                for queue in state['robot_queues'].values():
                    finish = 0.
                    for key in queue:
                        visit = state['dispatch_plan'][key]
                        self.assertGreaterEqual(visit['estimated_start']+.001,finish)
                        finish = visit['estimated_finish']
                        planner = core.planner_on('F1',DEFAULT_MODELS[0])
                        for leg in visit['legs']:
                            self.assertTrue(all(planner.segment(a,b) for a,b in zip(leg['path'],leg['path'][1:])))
                # Estimates do not falsely claim execution has already begun.
                self.assertTrue(all(t.status=='pending' and t.robot_id is None for t in tasks))
            finally:
                core.close()

    def test_queue_executed_immediately_after_previous_service(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(scene(3),DEFAULT_MODELS,instances(1),output=root)
            try:
                tasks = [core.add_task('S'+str(i),service='dwell',duration=0) for i in range(4)]
                state = plan_until_ready(core)
                expected = state['robot_queues']['R1']
                for _ in range(15000):
                    core.advance()
                    if all(t.status=='completed' for t in tasks):
                        break
                self.assertTrue(all(t.status=='completed' for t in tasks))
                assigned = [e for e in core.events if e['event']=='task_assigned']
                self.assertEqual([e['task_id'] for e in assigned],expected)
                completed = {e['task_id']:e['step'] for e in core.events if e['event']=='task_completed'}
                for previous,next_event in zip(expected,assigned[1:]):
                    self.assertLessEqual(next_event['step']-completed[previous],1)
            finally:
                core.close()

    def test_cumulative_battery_and_capabilities_are_enforced_in_plan(self):
        document = blank_map()
        document['version'] = 1
        floor = document['floors'][0]
        floor['objects'] = [dict(id=key,kind=kind,x=x,y=0,width=.2,height=.2)
                            for key,kind,x in [('P','parking',-4),('A','service',0),('B','service',4)]]
        fleet = [dict(id='R1',model_id='small',floor_id='F1',pose=[-4,0,0],parking_id='P',
                      battery_percent=21.,safety_battery_percent=20)]
        with TemporaryDirectory() as root:
            core = EditableRuntime(document,DEFAULT_MODELS,fleet,output=root)
            try:
                first = core.add_task('A')
                second = core.add_task('B')
                incompatible = core.add_task('A',capabilities=['unavailable'])
                plan = plan_until_ready(core)['dispatch_plan']
                self.assertIn(first.task_id,plan)
                self.assertNotIn(second.task_id,plan)
                self.assertNotIn(incompatible.task_id,plan)
            finally:
                core.close()

    def test_cancel_retry_and_new_priority_invalidate_queue(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(scene(3),DEFAULT_MODELS,instances(1),output=root)
            try:
                first = core.add_task('S0',retry={'max_attempts':2})
                second = core.add_task('S1')
                state = plan_until_ready(core)
                old_revision = state['planning']['revision']
                core.paused = True
                core.submit(dict(action='cancel_task',task_id=first.task_id))
                core.advance()
                self.assertFalse(core.planning_snapshot()['dispatch_plan'])
                state = plan_until_ready(core)
                self.assertNotIn(first.task_id,state['dispatch_plan'])
                self.assertIn(second.task_id,state['dispatch_plan'])
                core.submit(dict(action='retry_task',task_id=first.task_id))
                core.advance()
                urgent = core.add_task('S2',priority=9)
                state = plan_until_ready(core)
                self.assertEqual(state['robot_queues']['R1'][0],urgent.task_id)
                self.assertIn(first.task_id,state['dispatch_plan'])
                self.assertGreater(state['planning']['revision'],old_revision)
            finally:
                core.close()

    def test_closure_rebuilds_paths_and_cached_failure_recovers(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(scene(3),DEFAULT_MODELS,instances(1),output=root)
            try:
                task = core.add_task('S0')
                state = plan_until_ready(core)
                revision = state['planning']['revision']
                core.perception_command(dict(action='set_road_closure',id='door-closed',floor_id='F1',
                                             x=0,y=0,width=3,height=.3))
                state = plan_until_ready(core)
                self.assertNotIn(task.task_id,state['dispatch_plan'])
                self.assertGreater(state['planning']['revision'],revision)
                core.perception_command(dict(action='clear_road_closure',id='door-closed'))
                self.assertIn(task.task_id,plan_until_ready(core)['dispatch_plan'])
            finally:
                core.close()

    def test_cross_floor_queues_include_every_floor_leg(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*elevator_setup(),output=root)
            try:
                first = core.add_task('F2-bed-service',robot_id='R1')
                second = core.add_task('F1-bed-service',robot_id='R1')
                state = plan_until_ready(core)
                self.assertEqual(state['robot_queues']['R1'],[first.task_id,second.task_id])
                for task in (first,second):
                    visit = state['dispatch_plan'][task.task_id]
                    self.assertEqual({leg['floor_id'] for leg in visit['legs']},{'F1','F2'})
                core.elevator_command(dict(action='set_elevator_state',elevator_id='E1',mode='out_of_service'))
                state = plan_until_ready(core)
                self.assertNotIn(first.task_id,state['dispatch_plan'])
                self.assertIn(second.task_id,state['dispatch_plan'])
            finally:
                core.close()

    def test_future_release_and_same_bed_exclusion_remain_effective(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(scene(3),DEFAULT_MODELS,instances(2),output=root)
            try:
                first = core.add_task('S0',service='manual')
                second = core.add_task('S0',service='manual')
                future = core.add_task('S1',release=100,priority=10)
                plan_until_ready(core)
                core.dispatch()
                self.assertEqual(first.status,'assigned')
                self.assertEqual(second.status,'pending')
                self.assertEqual(future.status,'pending')
            finally:
                core.close()

    def test_newly_released_priority_precedes_preplanned_low_priority_beds(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(scene(3),DEFAULT_MODELS,instances(1),output=root)
            try:
                lower = core.add_task('S0')
                urgent = core.add_task('S1',release=10,priority=9)
                state = plan_until_ready(core)
                self.assertEqual(state['robot_queues']['R1'][0],lower.task_id)
                core.elapsed = 10
                self.assertFalse(core.planning_snapshot()['dispatch_plan'])
                core.dispatch()
                self.assertEqual(core.robots[0].task_id,urgent.task_id)
            finally:
                core.close()

    def test_cooperative_budget_and_plan_reuse(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(scene(3),DEFAULT_MODELS,instances(1),output=root)
            try:
                for i in range(20):
                    core.add_task('S'+str(i%4))
                # A search may cross the time budget, but the next candidate is
                # deferred instead of evaluating the whole batch in one frame.
                with patch('ward_patrol.runtime.planning.time.perf_counter',side_effect=[0.,0.,.02,.02]):
                    core.advance_planning()
                self.assertEqual(core.planning_metrics['status'],'planning')
                state = plan_until_ready(core)
                revision = state['planning']['revision']
                with patch.object(core,'find_robot_route',side_effect=AssertionError('queue recalculated')):
                    core.advance_planning()
                self.assertEqual(core.planning_metrics['revision'],revision)
            finally:
                core.close()


class PlannerCacheTests(unittest.TestCase):
    def test_cached_paths_are_independent_and_one_way_is_directional(self):
        floor = blank_map()['floors'][0]
        floor['objects'] = [dict(id='east',kind='one_way',x=0,y=0,width=20,height=16,rotation=0)]
        planner = Planner(floor,DEFAULT_MODELS[0])
        result = planner.route((-1,0),(1,0))
        self.assertTrue(result['path'])
        result['path'][0][0] = 999
        with patch.object(planner,'_route',side_effect=AssertionError('cached route recomputed')):
            self.assertEqual(planner.route((-1,0),(1,0))['path'][0][0],-1)
        self.assertFalse(planner.route((1,0),(-1,0))['path'])

    def test_continuous_collision_checks_thin_rotated_obstacles_and_corners(self):
        floor = blank_map()['floors'][0]
        floor['objects'] = [dict(id='thin',kind='wall',x=.02,y=0,width=.001,height=1,rotation=30)]
        model = deepcopy(DEFAULT_MODELS[0])
        model.update(width=.0001,length=.0001,margin=0)
        planner = Planner(floor,model)
        self.assertFalse(planner.segment((0,0),(.04,0)))
        rectangle = dict(x=0,y=0,width=2,height=2,rotation=0)
        self.assertFalse(Planner._touches((1.8,1.8),(2,2),rectangle,1))
        self.assertTrue(Planner._touches((1.6,1.6),(2,2),rectangle,1))


if __name__=='__main__':
    unittest.main()
