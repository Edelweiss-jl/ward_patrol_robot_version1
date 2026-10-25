# 演示与调试输出

这里集中保存原 demo_outputs 的截图、JSON 报告、JSONL 事件和终端日志。已有文件全部保留，不代表本次整理重新生成。

- `adaptive_*`、`balanced_*`：自适应规划及调度试验。
- `dual_ppo_*`、`stage3_*`：双机器人 PPO 或该阶段对照/超时检查。
- 其他 `dual_*`：基础双机器人巡查、阻塞和超时验收。
- `ppo_*`：单机器人 PPO 演示、复测及验收日志。
- `multi_room*`、`ring_ward*`：基础病区演示与截图。

JSON 是完整报告，JSONL 每行是一条事件，PNG 是截图，TXT 是运行日志。历史报告中的文件路径保留原样。当前报告用 `python -m tools.verify_dual_report outputs/demo_outputs/文件.json` 检查（在根目录执行）。

反复使用同一 `--report` 路径可能覆盖演示报告；需要保留对比时使用含日期/方案的新文件名。不要在这里放当前源码或唯一的正式模型。
