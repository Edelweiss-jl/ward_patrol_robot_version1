# 自适应动态规划与 Q-learning

在双机器人仿真上增加规划模式选择、动态重规划与任务分配。Q-learning 学习选择规划模式，底层仍包含路径规划与安全检查。

## 文件说明

| 文件 | 用途 |
| --- | --- |
| [adaptive_patrol.py](adaptive_patrol.py) | 自适应仿真基础与规划模式。 |
| [dynamic_route_planner.py](dynamic_route_planner.py) | 当前动态路线规划实现，继承自适应仿真。 |
| [adaptive_patrol_demo.py](adaptive_patrol_demo.py) | 加载 Q 表并运行演示，支持多种对照控制器。 |
| [train_adaptive_patrol.py](train_adaptive_patrol.py) | 实际仿真中的 Q-learning 训练，生成 Q 表和训练记录。 |
| [evaluate_adaptive_patrol.py](evaluate_adaptive_patrol.py) | 同种子配对评估并导出 JSON/CSV/Markdown。 |
| [plot_adaptive_results.py](plot_adaptive_results.py) | 读取训练和评估记录生成汇报图。 |

`__init__.py` 将目录标记为 Python 包，不是运行入口。

## 使用方法

所有命令从项目根目录执行，解释器使用项目 venv。

```powershell
.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo --headless
```

## 输入与输出

默认读取 `artifacts/adaptive_artifacts_v3/` 的策略或模型，演示报告写入 `outputs/demo_outputs/`。训练/评估/绘图脚本集中在本目录；参数以各入口 `--help` 为准。新训练使用新的输出目录，例如：

```powershell
.\venv\Scripts\python.exe -m ward_patrol.adaptive.train_adaptive_patrol --episodes 60 --output artifacts/adaptive_new_run
```

不要覆盖已有实验；评估新模型时显式指定 `--policy`（自适应）或 `--model`（PPO），并指定新的 `--output`。绘图用 `--directory` 选择实验目录。

## 依赖、详细手册与扩展

依赖安装见 [requirements](../../requirements/README.md)。完整参数、算法解释和历史结果见 [专题指南](../../docs/guides/README_adaptive_patrol.md)。所有源码修改后的回归测试放在 `tests/`，按 [测试说明](../../tests/README.md) 运行。

新增同类功能放本目录；多个算法共用的能力放 `common/` 或基础仿真目录。模型和截图不要放到这里。跨目录导入使用 `ward_patrol.目录.模块` 的完整名称。
