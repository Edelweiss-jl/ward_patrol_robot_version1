"""普通同优先级任务的就近匹配；与导航算法独立，可单独消融。"""
import math


def nearest_dispatch(sim):
    idle = [r for r in sim.robots if r.task_id is None]
    active_beds = {t.bed_id for t in sim.tasks if t.status=="assigned"}
    while idle:
        candidates = []
        for index,task in enumerate(sim.tasks):
            if task.status!="pending" or task.bed_id in active_beds:
                continue
            for robot in idle:
                path = sim.route(robot,task.goal,dynamic=False)
                if path:
                    candidates.append((sim.path_length(path),index,robot.robot_id,robot,task))
        if not candidates:
            break
        distance,_,_,robot,task = min(candidates,key=lambda item:item[:3])
        task.status,task.robot_id,task.assigned_at = "assigned",robot.robot_id,sim.elapsed
        robot.task_id,robot.dwell = task.task_id,0.
        robot.path = []
        robot.plan_timer = 1.
        robot.status = "moving"
        sim.end_wait(robot)
        idle.remove(robot)
        active_beds.add(task.bed_id)
        sim.emit("task_assigned",robot,task,estimated_distance_m=round(distance,3),scheduler="nearest")
