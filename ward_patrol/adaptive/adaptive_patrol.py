"""自适应动态导航：Q-learning选择局部规划模式，连续几何安全闸。"""
from __future__ import annotations
import math
import time
import numpy as np
import pybullet as p
from ward_patrol.simulation.dual_robot_demo import DualRobotSimulation, RADIUS


class AdaptiveSimulation(DualRobotSimulation):
    VERSION = "adaptive-base"
    MODES = ("short", "cruise", "detour", "yield")
    LOOKAHEAD = (.45, 1.4, 2.0, .45)

    def __init__(self, *args, **kwargs):
        self.modes = [1, 1]
        self.local_targets = [None, None]
        self.headings = [None, None]
        self.last_motion = [0., 0.]
        self.last_goals = [None, None]
        self.last_plans = [-100., -100.]
        self.plan_calls = 0
        self.planning_wall_seconds = 0.
        self.rejected_frames = [0, 0]
        self.mode_counts = np.zeros((2,4), dtype=int)
        self.last_actor_xy = None
        self.actor_velocity = []
        self.trajectory = []
        super().__init__(*args, **kwargs)

    def route(self, robot, goal, dynamic=True):
        start = time.perf_counter()
        result = super().route(robot, goal, dynamic)
        self.planning_wall_seconds += time.perf_counter()-start
        self.plan_calls += 1
        return result

    def smooth(self, points, robot=None):
        if not points:
            return []
        output, index = [points[0]], 0
        while index < len(points)-1:
            nxt = len(points)-1
            while nxt > index+1 and not (self.safe_segment(robot,points[index],points[nxt]) if robot
                                         else self.segment(points[index],points[nxt],False)):
                nxt -= 1
            output.append(points[nxt])
            index = nxt
        return output

    def make_plan(self, robot, goal):
        i = self.robots.index(robot)
        # 动态A*先给出绕人/绕另一台机器人的拓扑路线；无动态路线才保留静态骨架。
        points = self.route(robot, goal, dynamic=True)
        dynamic = bool(points)
        if not points:
            points = self.route(robot,goal,dynamic=False)
        robot.path = self.smooth(points,robot if dynamic else None)
        robot.replans += 1
        self.last_goals[i] = goal
        self.last_plans[i] = self.elapsed
        self.emit("path_planned", robot, self.task_for(robot), reachable=bool(robot.path),
                  waypoint_count=len(robot.path), planner="dynamic A* + visibility smoothing" if dynamic else "static skeleton")
        self.draw_path(robot)

    def target(self, robot, lookahead):
        points = [np.asarray(robot.xy)] + [np.asarray(x) for x in robot.path]
        # 不能用宽松到点阈值丢弃墙角折点；毫米级偏差也可能使下一段穿过膨胀墙。
        while len(robot.path) > 1 and math.dist(robot.xy, robot.path[0]) < 1e-8:
            robot.path.pop(0)
        points = [np.asarray(robot.xy)] + [np.asarray(x) for x in robot.path]
        if len(points) < 2:
            return np.asarray(robot.xy)
        # 先跳过可直视的旧折点；再在当前线段取前视目标。
        while len(robot.path) > 1 and self.safe_segment(robot,robot.xy,robot.path[1]):
            robot.path.pop(0)
        delta = np.asarray(robot.path[0])-robot.xy
        length = np.linalg.norm(delta)
        return np.asarray(robot.xy)+delta*min(1.,lookahead/max(length,1e-9))

    def state(self, robot):
        i = self.robots.index(robot)
        task = self.task_for(robot)
        goal = task.goal if task else robot.home
        nearby = min([math.dist(robot.xy,a.xy)-RADIUS-a.radius for a in self.ward.actors]+[10.])
        other = math.dist(robot.xy,self.robots[1-i].xy)
        # 3x3x2x2=36种离散状态，无床号、种子或测试结果泄漏。
        obstacle_bin = 0 if nearby > 1.5 else 1 if nearby > .6 else 2
        peer_bin = 0 if other > 3 else 1 if other > 1.2 else 2
        stuck = int(self.elapsed-self.last_motion[i] > 1.)
        near_goal = int(math.dist(robot.xy, goal) < 1.2)
        return ((obstacle_bin*3+peer_bin)*2+stuck)*2+near_goal

    def decide(self, robot, mode):
        raise NotImplementedError("Use DynamicRouteSimulation")

    def advance_robot(self, robot):
        raise NotImplementedError("Use DynamicRouteSimulation")

    def control(self, modes):
        now = [np.asarray(a.xy) for a in self.ward.actors]
        self.actor_velocity = ([np.zeros(2) for _ in now] if self.last_actor_xy is None else
                               [(a-b)/.2 for a,b in zip(now,self.last_actor_xy)])
        self.last_actor_xy = now
        self.modes = list(modes)
        for robot, mode in zip(self.robots,modes):
            self.decide(robot,int(mode))

    def refresh_ui(self):
        super().refresh_ui()
        count = sum(t.status == "completed" for t in self.tasks)
        self.status_id = p.addUserDebugText(
            f"ADAPTIVE Q | DONE {count}/{len(self.tasks)} | MODES {self.modes} | SPACE pause  ESC exit",
            [-self.ward.hx,-self.ward.hy-.7,.1],[.1,.2,.3],1.1,replaceItemUniqueId=self.status_id)

    def report(self):
        report = super().report()
        report.update(planner=self.VERSION, mode_counts=self.mode_counts.tolist(),
                      global_plan_calls=self.plan_calls, global_planning_wall_seconds=self.planning_wall_seconds,
                      rejected_frames=self.rejected_frames, trajectory=self.trajectory)
        report["navigation_debug"] = dict(paths=[r.path for r in self.robots],
            local_targets=[x.tolist() if x is not None else None for x in self.local_targets],
            headings=[x.tolist() if x is not None else None for x in self.headings],
            actors=[a.xy for a in self.ward.actors])
        return report
