"""稳定的动态路线跟踪：动态A*拓扑重规划、连续可见性捷径和学习模式。"""
import math
import numpy as np
import pybullet as p
from ward_patrol.adaptive.adaptive_patrol import AdaptiveSimulation
from ward_patrol.simulation.dual_robot_demo import DualRobotSimulation, DT, RADIUS, MARGIN


class DynamicRouteSimulation(AdaptiveSimulation):
    VERSION = "adaptive-q-v3"

    def __init__(self,*args,**kwargs):
        self.last_rejection = [False,False]
        super().__init__(*args,**kwargs)

    def decide(self,robot,mode):
        i = self.robots.index(robot)
        task = self.task_for(robot)
        goal = task.goal if task else robot.home
        self.mode_counts[i,mode] += 1
        if math.dist(robot.xy,goal)<.025:
            self.headings[i] = None
            return
        interval = (.65, .8, .4, .8)[mode]
        needs_plan = (goal!=self.last_goals[i] or not robot.path or self.last_rejection[i]
                      or (robot.path and not self.safe_segment(robot,robot.xy,robot.path[0])))
        if needs_plan and (goal!=self.last_goals[i] or self.elapsed-self.last_plans[i]>=interval):
            self.make_plan(robot,goal)
            self.last_rejection[i] = False
        self.headings[i] = None
        if mode==3 or not robot.path:
            return
        target = self.target(robot,self.LOOKAHEAD[mode])
        if np.linalg.norm(target-robot.xy)<1e-8:
            return
        self.local_targets[i] = target
        # 仅模式1预测短时相对运动；模式0优先跟踪，模式2更频繁拓扑重规划。
        if mode==1:
            horizon = .4
            vector = target-robot.xy
            end = np.asarray(robot.xy)+vector/max(np.linalg.norm(vector),1e-9)*min(.95*horizon,np.linalg.norm(vector))
            for actor,velocity in zip(self.ward.actors,self.actor_velocity):
                relative = np.asarray(robot.xy)-actor.xy
                delta = end-robot.xy-velocity*horizon
                fraction = np.clip(-np.dot(relative,delta)/max(np.dot(delta,delta),1e-9),0,1)
                if np.linalg.norm(relative+fraction*delta)<RADIUS+actor.radius+MARGIN:
                    self.last_rejection[i] = True
                    return
        self.headings[i] = target-robot.xy

    def advance_robot(self,robot):
        i = self.robots.index(robot)
        task = self.task_for(robot)
        goal = task.goal if task else robot.home
        if math.dist(robot.xy,goal)<.025:
            return DualRobotSimulation.advance_robot(self,robot)
        if self.headings[i] is None:
            self.begin_wait(robot,"dynamic_route_wait")
            return False
        vector = np.asarray(self.local_targets[i])-robot.xy
        distance = float(np.linalg.norm(vector))
        if distance<1e-8:
            return False
        step = min(.95*DT,distance)
        end = np.asarray(robot.xy)+vector/distance*step
        if not self.safe_segment(robot,robot.xy,end):
            self.last_rejection[i] = True
            self.rejected_frames[i] += 1
            self.begin_wait(robot,"dynamic_route_safety_stop")
            return False
        self.end_wait(robot)
        robot.xy = tuple(float(x) for x in end)
        robot.distance += step
        self.last_motion[i] = self.elapsed
        robot.status = "moving" if task else "returning"
        yaw = math.atan2(vector[1],vector[0])
        p.resetBasePositionAndOrientation(robot.body,[*end,.245],p.getQuaternionFromEuler([0,0,yaw]))
        p.resetBasePositionAndOrientation(robot.marker,[end[0]+.22*math.cos(yaw),end[1]+.22*math.sin(yaw),.48],[0,0,0,1])
        return True
