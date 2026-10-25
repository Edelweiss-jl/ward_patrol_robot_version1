# ppo_artifacts 实验文件说明

这是一个独立实验目录。模型、日志、评估数据和历史源码在整理时原样移动，未重新训练或修改指标。原来的 README（如有）保留在本文末尾。

## 文件怎么读

| 文件 | 用途 |
| --- | --- |
| [dynamic_monitor.csv](dynamic_monitor.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [environment_freeze.txt](environment_freeze.txt) | 当时的依赖或环境记录。 |
| [evaluation.csv](evaluation.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [evaluation.json](evaluation.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |
| [evaluation.md](evaluation.md) | 当时的评估/验证结论，包含历史命令。 |
| [ppo_patrol.zip](ppo_patrol.zip) | 训练得到的 PPO 模型，需匹配对应环境版本。 |
| [ppo_static.zip](ppo_static.zip) | 训练得到的 PPO 模型，需匹配对应环境版本。 |
| [progress.csv](progress.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [results.png](results.png) | 结果图或场景图。 |
| [static_monitor.csv](static_monitor.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [training_config.json](training_config.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |

## 如何使用及扩展

从项目根目录运行当前程序；模型路径使用 `artifacts/ppo_artifacts/文件名`。具体入口见 [项目总说明](../../README.md) 和 [实验总览](../README.md)。旧模型不能直接套入新观测空间；源码快照内的旧导入保持原样，需要按当时环境复现。

不要将新实验覆盖到本目录。新建相邻的带版本/日期目录，并记录参数、种子、依赖与评估条件。下方历史说明中的“上一级”和旧根目录路径均指整理前布局；新位置请查 [迁移对照](../../docs/migration/README.md)。
