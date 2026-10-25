"""自适应动态规划：初始化、碰撞闸、动作控制权与真实Q策略验收。"""
import math
import unittest
import numpy as np
from ward_patrol.adaptive.adaptive_patrol_demo import create_sim, load_q, run
from ward_patrol.simulation.complex_ward_demo import DT, RADIUS, MARGIN
from tools.verify_dual_report import verify


class AdaptiveTests(unittest.TestCase):
    def make(self,**kwargs):
        sim = create_sim(**kwargs)
        self.addCleanup(sim.close)
        return sim

    def test_initial_scenes_have_no_overlap_both_layouts(self):
        for scenario in ("corridor","ring"):
            for seed in range(3000,3006):
                sim = self.make(scenario=scenario,seed=seed)
                try:
                    for actor in sim.ward.actors:
                        self.assertTrue(sim.free(actor.xy,False,actor.radius+.05))
                        for robot in sim.robots:
                            self.assertGreater(math.dist(actor.xy,robot.xy),RADIUS+MARGIN+actor.radius)
                    for i,actor in enumerate(sim.ward.actors):
                        for other in sim.ward.actors[i+1:]:
                            self.assertGreater(math.dist(actor.xy,other.xy),actor.radius+other.radius)
                finally:
                    sim.close()

    def test_paired_controllers_share_exact_initial_conditions(self):
        conditions = []
        for controller in ("astar","fixed","adaptive"):
            sim = self.make(scenario="ring",seed=3000,controller=controller)
            conditions.append(sim.initial_conditions)
            sim.close()
        self.assertEqual(conditions[0],conditions[1])
        self.assertEqual(conditions[0],conditions[2])

    def test_smoothed_path_is_continuously_static_safe(self):
        sim = self.make(scenario="corridor",seed=3000,people=False)
        sim.control([1,1])
        for robot in sim.robots:
            self.assertTrue(robot.path)
            self.assertTrue(all(sim.segment(a,b,False) for a,b in zip(robot.path,robot.path[1:])))

    def test_yield_and_pause_really_stop(self):
        sim = self.make(scenario="corridor",seed=3000,people=False)
        before = [r.xy for r in sim.robots]
        sim.control([3,3])
        for _ in range(12):
            sim.tick()
        self.assertEqual(before,[r.xy for r in sim.robots])
        sim.paused = True
        elapsed = sim.elapsed
        sim.tick()
        self.assertEqual(elapsed,sim.elapsed)

    def test_near_corner_cannot_skip_a_required_waypoint(self):
        sim = self.make(scenario="corridor",seed=3000,people=False)
        robot = sim.robots[1]
        robot.xy = (6.51296149,1.467784)
        robot.path = [(6.5,1.5),(6.5,2.75),(7.65,3.6)]
        self.assertFalse(sim.segment(robot.xy,robot.path[1],False))
        target = sim.target(robot,.45)
        np.testing.assert_allclose(target,[6.5,1.5])
        self.assertEqual(robot.path[0],(6.5,1.5))

    def test_head_on_safe_stop_and_speed_bound(self):
        sim = self.make(scenario="corridor",seed=3000,people=False)
        a,b = sim.robots
        a.xy,b.xy = (-5.,0.),(-4.,0.)
        sim.headings = [np.array([1.,0.]),np.array([-1.,0.])]
        sim.local_targets = [np.array([-3.,0.]),np.array([-6.,0.])]
        for _ in range(120):
            for robot in sim.robots:
                before = robot.xy
                sim.advance_robot(robot)
                self.assertLessEqual(math.dist(before,robot.xy),.95*DT+1e-10)
            self.assertGreater(math.dist(a.xy,b.xy),2*RADIUS)
            self.assertLess(a.xy[0],b.xy[0])
        self.assertGreater(sum(sim.rejected_frames),0)

    def test_trained_policy_task_and_collision_audit(self):
        q = load_q("artifacts/adaptive_artifacts_v3/q_policy.json")
        self.assertGreater(np.abs(q).sum(),0)
        report = run("corridor",3000,True,"adaptive",q)
        self.assertTrue(report["completed"],report["robots"])
        self.assertEqual(verify(report),[])
        self.assertEqual(report["static_collision_frames"],0)
        self.assertEqual(report["person_collision_frames"],0)
        self.assertEqual(report["robot_overlap_frames"],0)
        self.assertGreater(report["min_person_clearance_m"],0)

    def test_nearest_dispatch_is_independent_of_navigation(self):
        assignments = []
        for controller in ("balanced","balanced_astar","balanced_short"):
            sim = self.make(scenario="corridor",seed=4001,controller=controller,people=False)
            assignments.append([(r.robot_id,sim.task_for(r).bed_id) for r in sim.robots])
            for robot in sim.robots:
                self.assertGreater(sim.task_for(robot).goal[0]*robot.xy[0],0)
            sim.close()
        self.assertEqual(assignments[0],assignments[1])
        self.assertEqual(assignments[0],assignments[2])

    def test_balanced_policy_preserves_task_history(self):
        q = load_q("artifacts/adaptive_artifacts_v3/q_policy.json")
        report = run("corridor",3000,True,"balanced",q)
        self.assertEqual(verify(report),[])
        self.assertEqual(report["person_collision_frames"]+report["static_collision_frames"]+report["robot_overlap_frames"],0)
        self.assertEqual(report["scheduler"],"nearest")

    def test_nearest_same_bed_stays_serial(self):
        q = load_q("artifacts/adaptive_artifacts_v3/q_policy.json")
        report = run("corridor",3000,False,"balanced",q,beds=["N1-1","N1-1","S3-2","S3-2"])
        self.assertEqual(verify(report),[])
        first,second = [t for t in report["tasks"] if t["bed_id"]=="N1-1"]
        self.assertGreaterEqual(second["assigned_at"],first["completed_at"])


if __name__ == "__main__":
    unittest.main()
