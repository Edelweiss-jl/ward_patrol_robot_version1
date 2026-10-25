# adaptive_artifacts_v3 实验文件说明

这是一个独立实验目录。模型、日志、评估数据和历史源码在整理时原样移动，未重新训练或修改指标。原来的 README（如有）保留在本文末尾。

## 文件怎么读

| 文件 | 用途 |
| --- | --- |
| [evaluation.csv](evaluation.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [evaluation.json](evaluation.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |
| [evaluation.md](evaluation.md) | 当时的评估/验证结论，包含历史命令。 |
| [evaluation_balanced.csv](evaluation_balanced.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [evaluation_balanced.json](evaluation_balanced.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |
| [evaluation_balanced.md](evaluation_balanced.md) | 当时的评估/验证结论，包含历史命令。 |
| [evaluation_balanced_static.csv](evaluation_balanced_static.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [evaluation_balanced_static.json](evaluation_balanced_static.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |
| [evaluation_balanced_static.md](evaluation_balanced_static.md) | 当时的评估/验证结论，包含历史命令。 |
| [evaluation_static.csv](evaluation_static.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [evaluation_static.json](evaluation_static.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |
| [evaluation_static.md](evaluation_static.md) | 当时的评估/验证结论，包含历史命令。 |
| [q_policy.json](q_policy.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |
| [results.png](results.png) | 结果图或场景图。 |
| [runtime.json](runtime.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |
| [training.json](training.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |
| [validation.md](validation.md) | 当时的评估/验证结论，包含历史命令。 |
| [wall_recheck.json](wall_recheck.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |

## 如何使用及扩展

从项目根目录运行当前程序；模型路径使用 `artifacts/adaptive_artifacts_v3/文件名`。具体入口见 [项目总说明](../../README.md) 和 [实验总览](../README.md)。旧模型不能直接套入新观测空间；源码快照内的旧导入保持原样，需要按当时环境复现。

不要将新实验覆盖到本目录。新建相邻的带版本/日期目录，并记录参数、种子、依赖与评估条件。下方历史说明中的“上一级”和旧根目录路径均指整理前布局；新位置请查 [迁移对照](../../docs/migration/README.md)。

## 原始说明（历史记录）

# 最终动态规划与Q-learning产物

- `q_policy.json`：adaptive-q-v3共享Q表、访问次数、真实训练参数和完成标记。
- `training.json`：60回合实际仿真训练记录，种子1000—1059，包含探索动作。
- `evaluation.json/csv/md`：独立6000系列动态配对评估，含原A*、固定cruise、固定short及学习选择四种控制器。
- `evaluation_balanced.json/csv/md`：最终8000系列配对评估，含原A*、就近分配+原A*、就近分配+固定short、就近分配+学习选择，分别隔离调度和学习贡献。
- `evaluation_static.json/csv/md`：5000系列静态补充对照。
- `results.png`：由上述原始数据生成的汇报图。
- `validation.md`：测试、碰撞审计和结论边界。

使用上一级 `adaptive_patrol_demo.py`。算法、运行、复现及历史场景初始化勘误详见上一级 `README_adaptive_patrol.md`。

首轮模型及退化结果保留在 `../adaptive_artifacts_v1/`，不能与本版策略混用。q_policy包含版本检查，默认入口拒绝旧版本。
