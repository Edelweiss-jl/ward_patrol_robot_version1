# 辅助校验工具

`verify_dual_report.py` 检查已生成的双机器人 JSON 报告：整批任务是否完成、分配/到达/完成事件是否唯一、时间顺序是否合理、两台机器人是否参与，以及报告中的安全指标。

从根目录运行：

```powershell
.\venv\Scripts\python.exe -m tools.verify_dual_report outputs/demo_outputs/adaptive_report.json
```

不传路径时检查 `outputs/demo_outputs/dual_robot_report.json`。成功返回 0，报告不合格或无法读取返回 1。超时/提前退出的报告无法通过“整批完成”验收属于正常现象。此工具只读取报告，不能代替逐帧仿真测试。

工具本身仅使用 Python 标准库。新增独立报告检查、数据转换等脚本放这里；算法训练/评估脚本应继续放相应算法目录。`__init__.py` 是包标识。
