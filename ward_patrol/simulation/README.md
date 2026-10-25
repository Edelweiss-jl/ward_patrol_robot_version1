# 基础病区仿真

负责病房建模、障碍物、A* 路径规划、机器人运动和基础演示。先理解这里，再阅读学习算法。

## 文件说明

| 文件 | 用途 |
| --- | --- |
| [complex_ward_demo.py](complex_ward_demo.py) | 共享病区、障碍物和单机器人仿真；提供 corridor/ring 两种布局。 |
| [dual_robot_demo.py](dual_robot_demo.py) | 双机器人仿真与共享任务队列，也是后续算法复用的基类。 |
| [multi_room_ward_demo.py](multi_room_ward_demo.py) | 多病房走廊演示入口，调用共享仿真。 |
| [ring_ward_demo.py](ring_ward_demo.py) | 环形病区演示入口，调用共享仿真。 |
| [dynamic_ward_demo.py](dynamic_ward_demo.py) | 早期独立动态病区演示；直接运行会启动交互仿真，不是公共库。 |

`__init__.py` 将目录标记为 Python 包，不是运行入口。

## 使用方法

所有命令从项目根目录执行，解释器使用项目 venv。

```powershell
.\venv\Scripts\python.exe -m ward_patrol.simulation.multi_room_ward_demo --headless --seconds 240
```

## 依赖、详细手册与扩展

依赖安装见 [requirements](../../requirements/README.md)。完整参数、算法解释和历史结果见 [专题指南](../../docs/guides/README_complex_demos.md)。所有源码修改后的回归测试放在 `tests/`，按 [测试说明](../../tests/README.md) 运行。

新增同类功能放本目录；多个算法共用的能力放 `common/` 或基础仿真目录。模型和截图不要放到这里。跨目录导入使用 `ward_patrol.目录.模块` 的完整名称。
