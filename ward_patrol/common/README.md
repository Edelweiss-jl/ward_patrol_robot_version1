# 共享场景与调度

放置多个算法共同使用的逻辑。这里没有独立演示入口，应由仿真或算法模块导入。

## 文件说明

| 文件 | 用途 |
| --- | --- |
| [patrol_scenarios.py](patrol_scenarios.py) | 统一生成回合初始场景，处理随机种子及初始碰撞检查。 |
| [patrol_dispatch.py](patrol_dispatch.py) | 就近任务分配，供自适应方案调用。 |

`__init__.py` 将目录标记为 Python 包，不是运行入口。

## 使用方法

所有命令从项目根目录执行，解释器使用项目 venv。

例如在代码中使用 `from ward_patrol.common.patrol_scenarios import initialize_episode`，参数与调用示例参考自适应演示和双机器人 PPO 环境。

## 依赖、详细手册与扩展

依赖安装见 [requirements](../../requirements/README.md)。完整参数、算法解释和历史结果见 [专题指南](../../docs/guides/README_adaptive_patrol.md)。所有源码修改后的回归测试放在 `tests/`，按 [测试说明](../../tests/README.md) 运行。

新增同类功能放本目录；多个算法共用的能力放 `common/` 或基础仿真目录。模型和截图不要放到这里。跨目录导入使用 `ward_patrol.目录.模块` 的完整名称。
