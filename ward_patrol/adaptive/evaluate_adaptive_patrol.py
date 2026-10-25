"""同场景配对评估：原A*、固定新规划器、Q-learning规划器。"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import time
from ward_patrol.adaptive.adaptive_patrol_demo import load_q, run
from ward_patrol.adaptive.dynamic_route_planner import DynamicRouteSimulation as AdaptiveSimulation


def summarize(rows,seconds):
    groups = []
    for scenario,people,controller in dict.fromkeys((r["scenario"],r["people"],r["controller"]) for r in rows):
        sample = [r for r in rows if (r["scenario"],r["people"],r["controller"]) == (scenario,people,controller)]
        successful = [r for r in sample if r["success"]]
        baseline = {r["seed"]:r for r in rows if r["scenario"]==scenario and r["people"]==people and r["controller"]=="astar"}
        pairs = [(r,baseline[r["seed"]]) for r in successful if r["seed"] in baseline and baseline[r["seed"]]["success"]]
        ratio = statistics.mean((b["seconds"]-r["seconds"])/b["seconds"]*100 for r,b in pairs) if pairs else None
        groups.append(dict(scenario=scenario,people=people,controller=controller,episodes=len(sample),
                           successes=len(successful),success_rate=len(successful)/len(sample),
                           mean_success_seconds=statistics.mean(r["seconds"] for r in successful) if successful else None,
                           mean_par2_seconds=statistics.mean(r["seconds"] if r["success"] else seconds*2 for r in sample),
                           mean_wall_seconds=statistics.mean(r["wall_seconds"] for r in sample),
                           mean_distance_m=statistics.mean(r["distance_m"] for r in sample),
                           mean_wait_seconds=statistics.mean(r["wait_seconds"] for r in sample),
                           paired_successes=len(pairs),paired_mean_time_reduction_percent=ratio,
                           paired_total_time_reduction_percent=(1-sum(r["seconds"] for r,b in pairs)/sum(b["seconds"] for r,b in pairs))*100 if pairs else None,
                           paired_faster=sum(r["seconds"]<b["seconds"]-1e-4 for r,b in pairs),
                           collision_frames=sum(r["collision_frames"] for r in sample)))
    return groups


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes",type=int,default=20)
    parser.add_argument("--seed",type=int,default=8000)
    parser.add_argument("--seconds",type=float,default=180)
    parser.add_argument("--policy",default="artifacts/adaptive_artifacts_v3/q_policy.json")
    parser.add_argument("--output",default="artifacts/adaptive_artifacts_v3/evaluation_balanced.json")
    parser.add_argument("--scenarios",nargs="+",choices=["corridor","ring"],default=["corridor","ring"])
    parser.add_argument("--controllers",nargs="+",choices=["astar","fixed","short","adaptive","balanced","balanced_short","balanced_astar"],default=["astar","balanced_astar","balanced_short","balanced"])
    parser.add_argument("--static",action="store_true",help="No people; default evaluates dynamic scenes")
    args = parser.parse_args()
    if args.episodes<1 or not math.isfinite(args.seconds) or args.seconds<=0:
        parser.error("episodes and seconds must be positive")
    q = load_q(args.policy)
    output = Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    rows = []
    try:
        for scenario in args.scenarios:
            for seed in range(args.seed,args.seed+args.episodes):
                # 交替顺序以减小CPU热状态和系统负载偏差；每个控制器都重新建世界。
                order = args.controllers if seed%2==0 else list(reversed(args.controllers))
                condition = None
                for controller in order:
                    report = run(scenario,seed,not args.static,controller,q,args.seconds,capture=False)
                    digest = hashlib.sha256(json.dumps(report["initial_conditions"],sort_keys=True).encode()).hexdigest()
                    if condition is not None and digest!=condition:
                        raise RuntimeError("Initial condition mismatch")
                    condition = digest
                    row = dict(scenario=scenario,people=not args.static,seed=seed,controller=controller,
                               initial_conditions_sha256=digest,initial_conditions=report["initial_conditions"],
                               success=report["completed"],completed_tasks=report["completed_tasks"],
                               seconds=report["simulated_seconds"],wall_seconds=report["wall_seconds"],
                               distance_m=sum(r["distance_m"] for r in report["robots"]),
                               wait_seconds=sum(r["wait_seconds"] for r in report["robots"]),
                               replans=sum(r["replans"] for r in report["robots"]),
                               collision_frames=report["robot_overlap_frames"]+report["static_collision_frames"]+report["person_collision_frames"],
                               min_person_clearance_m=report["min_person_clearance_m"],
                               mode_counts=report.get("mode_counts"))
                    rows.append(row)
                    print(f"{scenario} {seed} {controller}: {report['outcome']} {row['seconds']}s",flush=True)
    finally:
        summary = summarize(rows,args.seconds)
        data = dict(version=AdaptiveSimulation.VERSION,policy_sha256=hashlib.sha256(Path(args.policy).read_bytes()).hexdigest(),
                    seed_start=args.seed,requested_episodes=args.episodes,max_seconds=args.seconds,
                    generated_at_unix=time.time(),summary=summary,episodes=rows,
                    initial_scene_generator="collision-free-v2; invalid initial overlaps rejected")
        output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        if rows:
            with output.with_suffix(".csv").open("w",newline="",encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle,fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        lines = ["# 动态路径规划配对评估", "", "| 地图 | 人员 | 控制器 | 完成 | 成功平均秒 | PAR2秒 | 配对均值提速% | 配对总时下降% | 更快/配对成功 | 碰撞帧 |",
                 "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for s in summary:
            mean,ratio,total = s["mean_success_seconds"],s["paired_mean_time_reduction_percent"],s["paired_total_time_reduction_percent"]
            lines.append(f"| {s['scenario']} | {s['people']} | {s['controller']} | {s['successes']}/{s['episodes']} | "
                         f"{f'{mean:.2f}' if mean is not None else '-'} | {s['mean_par2_seconds']:.2f} | "
                         f"{f'{ratio:.2f}' if ratio is not None else '-'} | {f'{total:.2f}' if total is not None else '-'} | {s['paired_faster']}/{s['paired_successes']} | {s['collision_frames']} |")
        lines += ["", "PAR2：成功使用实际仿真时间，超时使用两倍上限；越低越好。配对提速仅比较两控制器均成功的同种子回合。",
                  "balanced_astar与balanced使用同样就近调度以隔离导航贡献；balanced_short禁用Q选择以隔离学习贡献。fixed/short/adaptive则保留FIFO做导航诊断。不能把调度或平滑路线的收益全部归因于强化学习。"]
        output.with_suffix(".md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()
