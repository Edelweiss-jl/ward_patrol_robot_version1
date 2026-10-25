# 正式 Python 源码

这里是 `ward_patrol` Python 包，集中保存当前使用的程序，不存模型、实验数据和历史源码快照。

| 子目录 | 负责什么 |
| --- | --- |
| [simulation](simulation/README.md) | 病区建模、基础导航和基础演示 |
| [common](common/README.md) | 共享场景初始化与任务分配 |
| [adaptive](adaptive/README.md) | 自适应规划、Q-learning 完整流程 |
| [ppo](ppo/README.md) | 单机器人 PPO 完整流程 |
| [dual_ppo](dual_ppo/README.md) | 双机器人 PPO 完整流程 |

从项目根目录通过 `python -m ward_patrol.目录.模块` 运行。不要在本目录或功能子目录直接运行脚本路径，否则完整包导入可能失败。`__init__.py` 是包标识，不需要运行。

依赖方向：基础仿真 → 共享逻辑/算法调用；自适应和双机器人 PPO 复用双机器人仿真；单机器人 PPO 自有环境。新增算法独立建包并写 README；公用功能需确有复用再抽到 common。详细安装、模型位置和扩展规范见 [总说明](../README.md)。
