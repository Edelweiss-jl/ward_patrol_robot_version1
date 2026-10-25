# 目录整理验证记录

验证日期：2026-10-25。以下是本次目录整理后的检查，未重新训练或覆盖交付模型。

## 检查结果

- 全套回归：`python -m unittest discover -s tests -t . -v`，Ran 34 tests in 63.540s，全部通过。
- 17 个带命令行参数的入口运行 `--help` 均返回 0，覆盖仿真、演示、训练、评估、绘图与报告校验。早期独立交互脚本 dynamic_ward_demo 不在该项检查内。
- 当前自适应方案无窗口实跑：4/4 任务完成，15.2 仿真秒；随后报告校验通过。
- 111 个模型、原始数据、历史源码及原有输出文件的 SHA256 与移动前一致；实验目录 README 添加说明，原文保留于末尾。
- 当前源码均通过 Python 语法解析。
- 项目目录 README 覆盖与当前文档本地链接已检查。

日志在 `outputs/reorganization_tests.txt`，入口检查在 `outputs/reorganization_cli_checks.json`，实跑报告在 `outputs/reorganization_adaptive_report.json`；这些临时验证输出默认不提交 Git。

## 保留事项

历史报告、JSON 和源码快照中的旧路径没有改写，以便保留实验原貌。当前操作以根目录 README 和 docs/guides 为准。虚拟环境、Git、IDE 配置未移动；个人 IDE 脚本运行配置需按新的模块名调整。GUI 按键与窗口交互本次未人工验证。

文件迁移没有执行 git add、reset 或 commit，因此已有暂存状态保留；Git 可能暂时显示旧路径删除和新目录未跟踪，审阅时请结合 [迁移表](README.md) 查看。
