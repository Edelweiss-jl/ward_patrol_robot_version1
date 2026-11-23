# 病区巡查机器人项目

这是一个基于 PyBullet 的病区巡查仿真项目：从病房建模和 A* 路径规划开始，逐步加入双机器人协作、PPO 强化学习，以及动态路径规划与 Q-learning。它用于算法实验和演示；目前不是连接真实机器人、传感器或医院业务系统的应用。

## 先从哪里看

- 只想看演示：按下面“运行演示”操作。
- 想理解程序：先读 [基础仿真](ward_patrol/simulation/README.md)，再读 [自适应规划](ward_patrol/adaptive/README.md)。
- 想看算法与实验细节：读 [完整使用指南](docs/guides/README.md)。
- 想找原来的文件：读 [旧位置与新位置对照](docs/migration/README.md)。文件名基本保留，只改变归属目录。
- 想查看运行中的重要画面：读 [截图及其意义](image/README.md)。

## 整体目录与职责

```text
ward_patrol_robot/
├── README.md                 项目总入口（本文）
├── ward_patrol/              正式 Python 代码
│   ├── simulation/           病区、基础导航、单/双机器人演示
│   ├── common/               场景初始化、共享任务分配
│   ├── adaptive/             动态规划、Q-learning、训练/评估/绘图
│   ├── ppo/                  单机器人 PPO 完整流程
│   └── dual_ppo/             双机器人 PPO 完整流程
├── tests/                    自动化回归测试
├── tools/                    已生成报告的校验工具
├── requirements/             不同用途的依赖清单
├── docs/
│   ├── guides/               原有详细 README，作为专题使用手册
│   ├── acceptance/           各阶段验收步骤与历史说明
│   └── migration/            文件迁移表和移动前哈希
├── artifacts/                模型、训练日志、评估结果、历史源码快照
│   ├── adaptive_artifacts/   自适应首轮工作副本
│   ├── adaptive_artifacts_v1/ 自适应首轮归档
│   ├── adaptive_artifacts_v3/ 当前自适应演示默认策略
│   ├── ppo_artifacts/        当前单机器人 PPO 默认模型
│   ├── ppo_artifacts_v1/     单机器人旧模型及旧环境
│   └── dual_ppo_artifacts/   双机器人 PPO 默认模型
├── image/                   重要运行截图及逐张意义说明
├── outputs/demo_outputs/    演示截图、临时报告、调试输出
├── venv/                    本机虚拟环境（保持原位）
├── .git/                    Git 元数据（保持原位）
├── .idea/                   本机 IDE 配置（保持原位）
└── __pycache__/             Python 自动缓存（旧缓存可保留，无需编辑）
```

业务目录及其子目录均有 README。`venv`、`.git`、`.idea`、`__pycache__` 属于工具维护的目录，不按业务分类，也不要手动移动内部文件；虚拟环境中可能包含原安装路径，移动会损坏环境。

## 代码之间怎样配合

`simulation/complex_ward_demo.py` 提供病区与基础仿真；`simulation/dual_robot_demo.py` 在其基础上提供双机器人任务与运动流程。`common/` 提供共享场景初始化、任务分配。`adaptive/` 和 `dual_ppo/` 复用双机器人仿真，分别用动态规划/Q-learning 或 PPO 做决策。单机器人 `ppo/` 有自己的 Gym 环境。

每种学习方案尽量把环境/算法、演示、训练、评估、绘图放在同一功能目录。流程是：训练生成模型 → 演示加载模型 → 评估生成 JSON/CSV/Markdown → 绘图读取评估与日志。输出放 `artifacts/` 或 `outputs/`，测试放 `tests/`，不混进源码目录。

## 环境准备

在本项目根目录打开 PowerShell。已有 `venv` 时直接使用它：

```powershell
.\venv\Scripts\python.exe --version
.\venv\Scripts\python.exe -m pip check
```

新机器可使用 Python 3.10 建立环境，再按 [依赖说明](requirements/README.md) 安装自适应或 PPO 所需依赖。绘图需要额外安装绘图依赖。不要复制别的电脑的 `venv`。

## 运行演示

查看地图编辑、车辆配置和巡检任务，可从项目根目录启动 Web 演示：

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements/requirements_web.txt
.\venv\Scripts\python.exe -m ward_patrol_web.server --no-mqtt
```

打开[巡查工作台](http://127.0.0.1:8000/)配置场景并查看床位状态，或打开[简易监控](http://127.0.0.1:8000/monitor)查看内置病区。车辆到达床旁时，空床和入住未登记的床位只记录状态，已入住的床位结合年龄和诊断生成模拟体征。悬浮在已巡检的床位上可查看最近一次结果。`--no-mqtt` 使用本地模拟采样。要通过 MQTT 收发采样请求和结果，请按 [MQTT 服务说明](ward_patrol_vitals_mqtt/README.md)启动服务，并在启动 Web 时去掉 `--no-mqtt`。

任务下发后，运行器先派车，再预排后续床位及路线。同层相邻床位按真实路程分组，完整方案生成后限时尝试少量换序和换车。默认保留楼层基本接单能力，按剩余工作量支援，持续缺车时延迟补位并设置调动稳定期。等梯采用保守预算和实际排队历史分位数，运行页可模拟共享占用、修改调度偏好，并查看接单能力、服务空窗及后续虚线路线。规则、参数及复测说明见[快速床位调度](docs/fast-dispatch.md)。

地图编辑器支持[电梯统一建模](docs/elevator-modeling.md)：整部电梯一次选择停靠层，各层入口用下拉框关联；支持参考位置批量复制、逐层检查确认和旧地图兼容读取。

首页现在是[病区巡查工作台](docs/workbench.md)，按地图建模、车队配置、任务调度、运行监控和历史回放分区，并提供使用引导和准备状态提示。`/editor` 保留兼容，原简易监控位于 `/monitor`。

所有命令均从根目录执行，不要先进入子目录。`-m` 后是带点号的模块名，不带 `.py`。

```powershell
# 当前自适应方案：双机器人 + 动态人员 + 学习选择规划模式
.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo
# 无窗口运行，适合快速验证
.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo --headless
# 基础场景与双机器人 A*
.\venv\Scripts\python.exe -m ward_patrol.simulation.multi_room_ward_demo
.\venv\Scripts\python.exe -m ward_patrol.simulation.ring_ward_demo
.\venv\Scripts\python.exe -m ward_patrol.simulation.dual_robot_demo
# 单机器人 / 双机器人 PPO
.\venv\Scripts\python.exe -m ward_patrol.ppo.ppo_patrol_demo
.\venv\Scripts\python.exe -m ward_patrol.dual_ppo.dual_ppo_demo
```

命令中的相对模型路径和输出路径都相对于项目根目录。默认模型已随目录调整到 `artifacts/`，默认演示报告到 `outputs/demo_outputs/`。可通过 `--model`、`--policy`、`--report`、`--output` 等参数指定其他位置，各模块具体参数用 `--help` 查看。旧版 `dynamic_ward_demo` 是独立交互脚本，没有统一命令行接口。

PyCharm：解释器选择 `venv\Scripts\python.exe`；运行配置选择“模块名称”，如 `ward_patrol.adaptive.adaptive_patrol_demo`；工作目录设为本项目根目录。原来按根目录脚本路径保存的个人运行配置需要更新。

## 测试和报告校验

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -t . -v
.\venv\Scripts\python.exe -m tools.verify_dual_report outputs/demo_outputs/adaptive_report.json
```

完整测试需要 PPO 依赖和已有模型。图形窗口的键盘交互还需人工查看；无窗口测试不能代替 GUI 验收。整理后的验证情况见 [整理验证记录](docs/migration/validation.md)。

## 以后新增内容放哪里

| 新内容 | 放置位置 | 例子 |
| --- | --- | --- |
| 病区布局、通用运动仿真、基础演示 | `ward_patrol/simulation/` | `new_ward_demo.py` |
| 多个方案都要用的场景或任务逻辑 | `ward_patrol/common/` | `task_priority.py` |
| 某种现有算法的改动、训练或评估脚本 | 相应算法目录 | `ward_patrol/adaptive/evaluate_new_scene.py` |
| 一套全新的算法 | `ward_patrol/算法英文名/` | `ward_patrol/dqn/` |
| 自动测试 | `tests/` | `test_task_priority.py` |
| 独立数据检查、格式转换工具 | `tools/` | `export_report.py` |
| 详细使用手册 | `docs/guides/` | `dqn_guide.md` |
| 验收标准或步骤 | `docs/acceptance/` | `ACCEPTANCE_dqn.md` |
| 模型、训练与评估的正式成果 | `artifacts/方案_版本或日期/` | `artifacts/adaptive_v4/` |
| 临时截图、调试报告、试运行日志 | `outputs/实验名/` | `outputs/navigation_smoke/` |
| 运行过程中需长期保留的重要截图 | `image/`，并在其中的 README 逐张说明意义 | `image/20261025_adaptive_corridor_01_obstacle_wait.png` |
| 额外依赖清单 | `requirements/` | `requirements_dqn.txt` |

新增功能目录时，先创建 `__init__.py` 和 `README.md`。代码导入使用完整路径，例如 `from ward_patrol.common.patrol_dispatch import nearest_dispatch`，不要往 `sys.path` 塞目录。README 至少说明用途、逐文件职责、从根目录可复制的命令、输入输出、依赖、注意事项和扩展方式，并在本页增加入口。

新增实验使用新的输出目录，保留已有模型和失败结果，记录算法/环境版本、种子、训练配置及评估条件。历史目录中的 `.py` 是当时的源码快照，不是当前程序入口；不同观测维度、版本的模型不能混用。历史 JSON 和报告中的旧路径保留作证据，当前操作以新使用指南为准。

根目录只保留总说明、必要项目配置和工具环境。不要再把业务脚本、新 README 或训练产物散放到根目录。
