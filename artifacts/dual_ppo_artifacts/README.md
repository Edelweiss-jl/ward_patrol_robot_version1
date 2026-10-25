# dual_ppo_artifacts 实验文件说明

这是一个独立实验目录。模型、日志、评估数据和历史源码在整理时原样移动，未重新训练或修改指标。原来的 README（如有）保留在本文末尾。

## 文件怎么读

| 文件 | 用途 |
| --- | --- |
| [evaluation.csv](evaluation.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [evaluation.json](evaluation.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |
| [evaluation.md](evaluation.md) | 当时的评估/验证结论，包含历史命令。 |
| [monitor.csv](monitor.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [ppo_dual.zip](ppo_dual.zip) | 训练得到的 PPO 模型，需匹配对应环境版本。 |
| [progress.csv](progress.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [results.png](results.png) | 结果图或场景图。 |
| [scene.png](scene.png) | 结果图或场景图。 |
| [training_config.json](training_config.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |
| [validation.md](validation.md) | 当时的评估/验证结论，包含历史命令。 |

## 如何使用及扩展

从项目根目录运行当前程序；模型路径使用 `artifacts/dual_ppo_artifacts/文件名`。具体入口见 [项目总说明](../../README.md) 和 [实验总览](../README.md)。旧模型不能直接套入新观测空间；源码快照内的旧导入保持原样，需要按当时环境复现。

不要将新实验覆盖到本目录。新建相邻的带版本/日期目录，并记录参数、种子、依赖与评估条件。下方历史说明中的“上一级”和旧根目录路径均指整理前布局；新位置请查 [迁移对照](../../docs/migration/README.md)。

## 原始说明（历史记录）

# 第三阶段交付产物

- `ppo_dual.zip`：由 `train_dual_ppo.py` 真实训练的集中式联合 PPO，52维输入、两台各9动作。
- `training_config.json`：准确训练配置、依赖版本、实际步数、墙钟用时、完成标志。
- `monitor.csv` / `progress.csv`：训练回合与优化过程原始日志。
- `evaluation.json` / `.csv` / `.md`：独立种子下PPO和A*的真实对照，JSON包含模型SHA256和动作统计。
- `results.png`：根据上述日志生成的汇报图。
- `scene.png`：本阶段复用的静态复杂走廊初始场景，红蓝各一台机器人。
- `validation.md`：本次自动验证记录及结果解释。

完整操作、算法和局限见上一级 `README_dual_ppo.md`。不要使用第二阶段单机器人入口加载本模型。
