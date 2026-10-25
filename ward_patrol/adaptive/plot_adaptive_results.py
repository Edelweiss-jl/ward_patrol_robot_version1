"""根据真实训练和配对评估记录生成汇报图。"""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory",default="artifacts/adaptive_artifacts_v3")
    parser.add_argument("--evaluation",default="evaluation_balanced.json")
    parser.add_argument("--controller",default="balanced")
    args = parser.parse_args()
    root = Path(args.directory)
    data = json.loads((root/args.evaluation).read_text(encoding="utf-8"))
    training = json.loads((root/"training.json").read_text(encoding="utf-8"))
    fig,axes = plt.subplots(2,3,figsize=(16,8))
    controllers = list(dict.fromkeys(s["controller"] for s in data["summary"]))
    colors = ["#777777","#ff7f00","#4daf4a","#377eb8"]
    for index,controller in enumerate(controllers):
        group = [next(s for s in data["summary"] if s["scenario"]==scenario and s["controller"]==controller)
                 for scenario in ("corridor","ring")]
        width = .8/len(controllers)
        axes[0,0].bar(np.arange(2)+(index-(len(controllers)-1)/2)*width,
                      [s["mean_par2_seconds"] for s in group],width,label=controller,color=colors[index])
        axes[0,1].bar(np.arange(2)+(index-(len(controllers)-1)/2)*width,
                      [s["success_rate"]*100 for s in group],width,color=colors[index])
    axes[0,0].set(title="PAR2 task time (lower is better)",ylabel="Simulation seconds",xticks=[0,1],xticklabels=["corridor","ring"])
    axes[0,0].legend(fontsize=8)
    axes[0,1].set(title="Batch completion rate",ylabel="Percent",ylim=(0,110),xticks=[0,1],xticklabels=["corridor","ring"])
    limits = []
    for scenario,color in (("corridor","#377eb8"),("ring","#e41a1c")):
        baseline = {r["seed"]:r for r in data["episodes"] if r["scenario"]==scenario and r["controller"]=="astar"}
        pairs = [(r,baseline[r["seed"]]) for r in data["episodes"] if r["scenario"]==scenario and r["controller"]==args.controller and r["success"] and baseline[r["seed"]]["success"]]
        axes[0,2].scatter([b["seconds"] for r,b in pairs],[r["seconds"] for r,b in pairs],label=scenario,color=color,alpha=.8)
        limits.extend([max(r["seconds"],b["seconds"]) for r,b in pairs])
    upper = max(limits,default=1)*1.1
    axes[0,2].plot([0,upper],[0,upper],"k--",alpha=.5)
    axes[0,2].set(title="Matched episodes: below line is faster",xlabel="Original A* seconds",ylabel="Combined planner seconds")
    axes[0,2].legend(fontsize=8)
    axes[1,0].plot([r["episode"] for r in training],[r["reward"] for r in training],color="#377eb8")
    axes[1,0].set(title="Actual training returns",xlabel="Episode",ylabel="Team return")
    axes[1,1].plot([r["episode"] for r in training],[r["seconds"] for r in training],color="#4daf4a")
    axes[1,1].set(title="Training task time (includes exploration)",xlabel="Episode",ylabel="Simulation seconds")
    hist = np.sum([r["mode_counts"] for r in data["episodes"] if r["controller"]==args.controller],axis=0)
    for i,color in ((0,"#e41a1c"),(1,"#377eb8")):
        axes[1,2].bar(np.arange(4)+(i-.5)*.35,hist[i],.35,label=f"R{i+1}",color=color)
    axes[1,2].set(title="Learned mode counts (including idle time)",xticks=range(4),xticklabels=["short","cruise","detour","yield"])
    axes[1,2].legend(fontsize=8)
    for ax in axes.flat:
        ax.grid(axis="y",alpha=.2)
    fig.suptitle("Dynamic route planning | matched initial scenes | equal speed and safety margin")
    fig.tight_layout()
    fig.savefig(root/"results.png",dpi=150)
    plt.close(fig)


if __name__=="__main__":
    main()
