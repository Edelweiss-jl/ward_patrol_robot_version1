# 双机器人 PPO

在共享双机器人仿真上封装集中式联合 PPO 环境，模型同时输出两台机器人的动作。

## 文件说明

| 文件 | 用途 |
| --- | --- |
| [dual_ppo_env.py](dual_ppo_env.py) | 双机器人 Gym 环境：52 维观测、两台各 9 种动作。 |
| [dual_ppo_demo.py](dual_ppo_demo.py) | 加载联合模型并运行双机器人演示。 |
| [train_dual_ppo.py](train_dual_ppo.py) | 训练集中式联合 PPO 并保存配置与日志。 |
| [evaluate_dual_ppo.py](evaluate_dual_ppo.py) | 对不同场景和控制器进行评估。 |
| [plot_dual_ppo_results.py](plot_dual_ppo_results.py) | 读取训练与评估记录生成图表。 |

`__init__.py` 将目录标记为 Python 包，不是运行入口。

## 使用方法

所有命令从项目根目录执行，解释器使用项目 venv。

```powershell
.\venv\Scripts\python.exe -m ward_patrol.dual_ppo.dual_ppo_demo --headless
```

## 输入与输出

默认读取 `artifacts/dual_ppo_artifacts/` 的策略或模型，演示报告写入 `outputs/demo_outputs/`。训练/评估/绘图脚本集中在本目录；参数以各入口 `--help` 为准。新训练使用新的输出目录，例如：

```powershell
.\venv\Scripts\python.exe -m ward_patrol.dual_ppo.train_dual_ppo --steps 16384 --output artifacts/dual_ppo_new_run
```

不要覆盖已有实验；评估新模型时显式指定 `--policy`（自适应）或 `--model`（PPO），并指定新的 `--output`。绘图用 `--directory` 选择实验目录。

## 依赖、详细手册与扩展

依赖安装见 [requirements](../../requirements/README.md)。完整参数、算法解释和历史结果见 [专题指南](../../docs/guides/README_dual_ppo.md)。所有源码修改后的回归测试放在 `tests/`，按 [测试说明](../../tests/README.md) 运行。

新增同类功能放本目录；多个算法共用的能力放 `common/` 或基础仿真目录。模型和截图不要放到这里。跨目录导入使用 `ward_patrol.目录.模块` 的完整名称。
