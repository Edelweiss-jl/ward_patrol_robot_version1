# 自动化回归测试

测试验证程序行为，特别是场景安全、任务完成、模型接口和报告一致性。这里不保存正式训练结果。

| 文件 | 检查内容 |
| --- | --- |
| test_complex_ward_demo.py | 基础布局、连通性、障碍与单机器人巡查 |
| test_dual_robot_demo.py | 双机器人任务分配、事件、运动与安全 |
| test_adaptive_patrol.py | 自适应规划、初始化、模式切换及策略运行 |
| test_ppo_patrol.py | 单机器人 Gym 契约、真实模型和评估记录 |
| test_dual_ppo.py | 双机器人环境、联合模型和错误模型拒绝 |

在根目录执行全部测试：

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -t . -v
# 只检查自适应功能
.\venv\Scripts\python.exe -m unittest tests.test_adaptive_patrol -v
```

全套需要 requirements 中的 PPO 依赖，以及 artifacts 内的模型和评估记录。测试按新路径加载现有成果，历史源码快照不参与测试发现。图形交互由人工按 docs/acceptance 的步骤验证。

新增测试命名为 `test_功能.py`，使用 `unittest`，从完整包名导入源码。临时文件优先放临时目录；不要覆盖正式模型。`__init__.py` 支持模块形式调用测试。
