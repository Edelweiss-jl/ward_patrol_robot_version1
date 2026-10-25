# ppo_artifacts_v1 实验文件说明

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
| [ppo_patrol_env.py](ppo_patrol_env.py) | 历史源码快照，保留原始导入，不作为当前入口。 |
| [ppo_static.zip](ppo_static.zip) | 训练得到的 PPO 模型，需匹配对应环境版本。 |
| [progress.csv](progress.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [static_monitor.csv](static_monitor.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [training_config.json](training_config.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |
| [warmup_validation.csv](warmup_validation.csv) | 训练日志或逐回合评估表，可用表格软件查看。 |
| [warmup_validation.json](warmup_validation.json) | 训练配置、Q 表或机器可读实验结果，具体含义见文件名及下方历史说明。 |
| [warmup_validation.md](warmup_validation.md) | 当时的评估/验证结论，包含历史命令。 |

## 如何使用及扩展

从项目根目录运行当前程序；模型路径使用 `artifacts/ppo_artifacts_v1/文件名`。具体入口见 [项目总说明](../../README.md) 和 [实验总览](../README.md)。旧模型不能直接套入新观测空间；源码快照内的旧导入保持原样，需要按当时环境复现。

不要将新实验覆盖到本目录。新建相邻的带版本/日期目录，并记录参数、种子、依赖与评估条件。下方历史说明中的“上一级”和旧根目录路径均指整理前布局；新位置请查 [迁移对照](../../docs/migration/README.md)。

## 原始说明（历史记录）

# 首轮实验归档

此处为 ward-local-v1（19 维观测）模型和原始评估，不是默认交付模型。
80,384 步训练后，静态 20/20 成功，动态 10/20 成功；动态评估所有动作都是向前，尚未学会避障。
因此补充短时风险观测并重新训练 v2，最终结果在 ../ppo_artifacts。
此目录保留当时环境源码，v1 模型不能直接用于现有 28 维 v2 环境。
首轮种子 1000—1019 已用于诊断，最终 v2 评估改用 2000—2019。
