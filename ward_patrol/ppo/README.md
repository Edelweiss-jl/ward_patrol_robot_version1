# 单机器人 PPO

封装单机器人 Gymnasium 环境，用 Stable-Baselines3 训练与加载 PPO 策略。

## 文件说明

| 文件 | 用途 |
| --- | --- |
| [ppo_patrol_env.py](ppo_patrol_env.py) | 单机器人环境、观测、动作、奖励和安全检查。 |
| [ppo_patrol_demo.py](ppo_patrol_demo.py) | 加载单机器人模型并运行演示。 |
| [train_ppo_patrol.py](train_ppo_patrol.py) | 先静态预热再动态训练，保存模型与日志。 |
| [evaluate_ppo_patrol.py](evaluate_ppo_patrol.py) | PPO 与 A* 对照评估，保存逐回合结果。 |
| [plot_ppo_results.py](plot_ppo_results.py) | 训练日志与评估结果绘图。 |

`__init__.py` 将目录标记为 Python 包，不是运行入口。

## 使用方法

所有命令从项目根目录执行，解释器使用项目 venv。

```powershell
.\venv\Scripts\python.exe -m ward_patrol.ppo.ppo_patrol_demo --headless
```

## 输入与输出

默认读取 `artifacts/ppo_artifacts/` 的策略或模型，演示报告写入 `outputs/demo_outputs/`。训练/评估/绘图脚本集中在本目录；参数以各入口 `--help` 为准。新训练使用新的输出目录，例如：

`ppo_patrol_demo.py` 也支持在 PyCharm 中直接运行脚本。它的默认模型和报告路径按脚本位置定位到项目根目录，不受运行工作目录影响；显式传入的 `--model`、`--report` 和 `--screenshot` 相对路径仍相对于当前工作目录。

```powershell
.\venv\Scripts\python.exe -m ward_patrol.ppo.train_ppo_patrol --steps 40000 --output artifacts/ppo_new_run
```

不要覆盖已有实验；评估新模型时显式指定 `--policy`（自适应）或 `--model`（PPO），并指定新的 `--output`。绘图用 `--directory` 选择实验目录。

## 依赖、详细手册与扩展

依赖安装见 [requirements](../../requirements/README.md)。完整参数、算法解释和历史结果见 [专题指南](../../docs/guides/README_ppo.md)。所有源码修改后的回归测试放在 `tests/`，按 [测试说明](../../tests/README.md) 运行。

新增同类功能放本目录；多个算法共用的能力放 `common/` 或基础仿真目录。模型和截图不要放到这里。跨目录导入使用 `ward_patrol.目录.模块` 的完整名称。
