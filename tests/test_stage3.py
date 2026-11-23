"""Fixed-step perception tests using the same runtime as the editor."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ward_patrol.maps.geometry import DEFAULT_MODELS, blank_map
from ward_patrol.runtime.editable import EditableRuntime


def box(identity, kind, x, y, width, height):
    return dict(id=identity,kind=kind,x=x,y=y,width=width,height=height)


def scenario(obstacles=(), start=(-4,0), goal=(4,0), sensors=None):
    document = blank_map()
    document['version'] = 1
    document['floors'][0]['objects'] = [box('P','parking',*start,.3,.3),box('S','service',*goal,.3,.3),*obstacles]
    model = deepcopy(DEFAULT_MODELS[0])
    model['sensors'].update(sensors or {})
    instances = [dict(id='R1',floor_id='F1',model_id='small',pose=[*start,0],parking_id='P')]
    return document,[model],instances


def start(core):
    core.submit(dict(action='create_task',bed='S',task=dict(service='dwell',duration=0)))


def cart(core, x, y):
    core.submit(dict(action='upsert_obstacle',floor_id='F1',id='cart',kind='cart',x=x,y=y))


def until(core, predicate, steps=2400):
    for _ in range(steps):
        core.advance()
        if predicate():
            return
    raise AssertionError((core.robots[0].xy,core.lidars['R1'].decision,core.wait_reasons))


class PerceptionTests(unittest.TestCase):
    def test_wall_occludes_dynamic_obstacle_without_changing_hidden_prefix(self):
        data = scenario([box('wall','wall',-1.5,0,3,.2)],start=(-4,-1.6),goal=(5,-1.6))
        with TemporaryDirectory() as root:
            control = EditableRuntime(*data,output=Path(root)/'control')
            trial = EditableRuntime(*data,output=Path(root)/'trial')
            try:
                cart(trial,.35,.7)
                start(control)
                start(trial)
                hidden = 0
                for _ in range(800):
                    control.advance()
                    trial.advance()
                    if trial.lidars['R1'].first_hit_step is not None:
                        break
                    self.assertEqual(trial.robots[0].xy,control.robots[0].xy)
                    self.assertEqual(trial.velocities['R1'],control.velocities['R1'])
                    self.assertEqual(trial.robots[0].path,control.robots[0].path)
                    hidden += 1
                self.assertGreater(hidden,100)
                self.assertIsNotNone(trial.lidars['R1'].first_hit_step)
                self.assertEqual(trial.perception_metrics['R1']['truth_interventions'],0)
            finally:
                control.close()
                trial.close()

    def test_measured_cart_blocks_then_resumes_after_observed_clearance(self):
        walls = [box('W1','wall',0,1.15,18,1.2),box('W2','wall',0,-1.15,18,1.2),
                 box('W3','wall',-9,0,.4,2.6),box('W4','wall',9,0,.4,2.6)]
        with TemporaryDirectory() as root:
            core = EditableRuntime(*scenario(walls),output=root)
            try:
                cart(core,0,0)
                start(core)
                until(core,lambda: 'R1' in core.observed_blockages)
                events = {event['event']:event['step'] for event in core.events}
                self.assertLess(events['obstacle_detected'],events['obstacle_stopped'])
                self.assertLessEqual(events['obstacle_stopped'],events['blockage_reported'])
                self.assertIn('等待',core.wait_reasons[core.tasks[0].task_id])
                core.submit(dict(action='remove_obstacle',id='cart'))
                until(core,lambda: core.tasks[0].status=='completed')
                self.assertFalse(core.observed_blockages)
                self.assertEqual(core.perception_metrics['R1']['contact_steps'],0)
                self.assertEqual(core.perception_metrics['R1']['truth_interventions'],0)
            finally:
                core.close()

    def test_open_floor_detour_uses_observed_cells(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*scenario(),output=root)
            try:
                cart(core,0,0)
                start(core)
                until(core,lambda: core.tasks and core.tasks[0].status=='completed', steps=3600)
                self.assertTrue(any(event['event']=='route_replanned' for event in core.events))
                self.assertEqual(core.perception_metrics['R1']['truth_interventions'],0)
            finally:
                core.close()

    def test_scan_delay_and_loss_are_deterministic(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*scenario(sensors={'delay':.25,'noise':.01,'dropout':.4}),output=root)
            try:
                start(core)
                for _ in range(15):
                    core.advance()
                self.assertIsNone(core.lidars['R1'].frame)
                self.assertEqual(core.robots[0].xy,(-4,0))
                core.advance()
                frame = core.lidars['R1'].frame
                self.assertEqual(frame['step'],1)
                self.assertGreater(len(frame['beams']),0)
                self.assertLess(len(frame['beams']),core.lidars['R1'].config['rays'])
            finally:
                core.close()

    def test_unobserved_cells_expire_without_reading_scene_truth(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*scenario(sensors={'ttl':.25}),output=root)
            try:
                cart(core, -1.8,0)
                start(core)
                until(core,lambda: bool(core._observed_cells(core.lidars['R1'])))
                core.lidars['R1'].config['dropout'] = 1
                until(core,lambda: not core._observed_cells(core.lidars['R1']))
                self.assertIn('cart',core.scene_obstacles)
                self.assertEqual(core.perception_metrics['R1']['contact_steps'],0)
            finally:
                core.close()

    def test_moving_person_crosses_using_fixed_steps(self):
        with TemporaryDirectory() as root:
            core = EditableRuntime(*scenario(),output=root)
            try:
                core.submit(dict(action='upsert_obstacle',floor_id='F1',id='walker',kind='person',
                                 x=-.5,y=-1.6,target=[-.5,1.6]))
                start(core)
                until(core,lambda: core.tasks and core.tasks[0].status=='completed',steps=3600)
                self.assertEqual(core.scene_obstacles['walker']['xy'],(-.5,1.6))
                self.assertIsNotNone(core.lidars['R1'].first_hit_step)
                self.assertEqual(core.perception_metrics['R1']['contact_steps'],0)
            finally:
                core.close()

    def test_published_closure_changes_planner_before_scanning(self):
        walls = [box('W1','wall',0,1.15,18,1.2),box('W2','wall',0,-1.15,18,1.2),
                 box('W3','wall',-9,0,.4,2.6),box('W4','wall',9,0,.4,2.6)]
        with TemporaryDirectory() as root:
            core = EditableRuntime(*scenario(walls),output=root)
            try:
                core.started = False
                core.submit(dict(action='set_road_closure',id='closed',floor_id='F1',x=0,y=0,width=.5,height=1.1))
                core.advance()
                self.assertEqual(core.step,0)
                self.assertFalse(core.planners['R1'].free((0,0)))
                self.assertIsNone(core.lidars['R1'].frame)
                core.submit(dict(action='clear_road_closure',id='closed'))
                core.advance()
                self.assertTrue(core.planners['R1'].free((0,0)))
            finally:
                core.close()
