# 正式实验产物与历史归档

本目录保存模型、训练配置、原始日志、评估表、图像和与实验绑定的历史源码。每个实验独立保留，不将不同版本的模型/环境混用。

| 目录 | 用途 |
| --- | --- |
| [adaptive_artifacts](adaptive_artifacts/README.md) | 自适应首轮工作副本 |
| [adaptive_artifacts_v1](adaptive_artifacts_v1/README.md) | 自适应首轮模型与源码归档 |
| [adaptive_artifacts_v3](adaptive_artifacts_v3/README.md) | 当前自适应演示默认 Q 表及对照实验 |
| [ppo_artifacts](ppo_artifacts/README.md) | 当前单机器人 PPO 模型与评估 |
| [ppo_artifacts_v1](ppo_artifacts_v1/README.md) | 19 维旧环境和旧模型，不能用于现有 28 维环境 |
| [dual_ppo_artifacts](dual_ppo_artifacts/README.md) | 双机器人联合 PPO 模型与评估 |

`.zip` 是模型，`.json` 保存配置/逐回合结果，`.csv` 便于统计，`.md` 解释结果，`.png` 用于展示。归档中的 `.py` 只用于复现当时版本，不是正式运行入口。

新实验用独立目录，例如 `artifacts/adaptive_v4/`，并添加 README，写清用途、代码/环境版本、随机种子、训练命令、评估条件和局限。临时试跑输出放 outputs。当前训练、评估命令见对应源码目录及 docs/guides；历史报告中的旧路径仅用于记录当时环境。
