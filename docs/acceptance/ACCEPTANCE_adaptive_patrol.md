> 目录整理说明：本页命令均在项目根目录执行；使用 `python -m 包.模块`。历史指标保留，文件新位置见根目录 README。

# 动态路径规划改进验收

全部命令在项目根目录，用现有venv解释器运行；详细算法与指标见 [README_adaptive_patrol.md](../guides/README_adaptive_patrol.md)。

1. `.\venv\Scripts\python.exe -m unittest tests.test_adaptive_patrol`：应检查两种布局初始无冲突、三控制器初始条件相同、平滑路径连续安全、等待/暂停、对向安全闸和限速、墙角必要折点不能提前丢弃、真实策略完成任务。
2. `.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo --headless`：保存任务、轨迹和碰撞报告；整批成功返回0。`static_collision_frames`、`person_collision_frames`、`robot_overlap_frames`均应为0。
3. `.\venv\Scripts\python.exe -m tools.verify_dual_report outputs/demo_outputs/adaptive_report.json`：检查完成任务的唯一分配、唯一完成和时间关系。超时报告不应通过整批完成校验。
4. `.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo`：查看双机器人和动态人员；空格冻结两者，继续恢复；ESC提前关闭并保存中断报告。GUI交互需人工检查，不能仅凭无窗口测试宣称已验证。
5. 使用相同`--seed`分别运行`--controller astar`、`--controller fixed`、`--controller short`、`--controller adaptive`，指定不同`--report`，对比`initial_conditions`必须完全相同。
6. `.\venv\Scripts\python.exe -m ward_patrol.adaptive.evaluate_adaptive_patrol --episodes 20 --seed 8000 --controllers astar balanced_astar balanced_short balanced`：最终组合生成160条逐回合记录，不丢弃退化/超时样本。6000系列FIFO导航诊断另存 `evaluation.json`；配对均值提速与配对总时下降分别报告。
7. `.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo --headless --seconds 0.2 --report outputs/demo_outputs/adaptive_timeout.json`：应记录未完成并返回1，而非成功。
8. 在新输出目录重新训练：`.\venv\Scripts\python.exe -m ward_patrol.adaptive.train_adaptive_patrol --episodes 4 --output outputs/demo_outputs/adaptive_training_smoke`。应产生真实Q值与访问次数、训练记录；再次使用相同非空目录应拒绝覆盖。4回合只验收流程，不验收性能。
9. 回归前两阶段及PPO：`.\venv\Scripts\python.exe -m unittest tests.test_dual_ppo tests.test_complex_ward_demo tests.test_dual_robot_demo tests.test_ppo_patrol`。

性能验收不能只看演示，也不能只看成功平均时间。至少同时核对完成率、全部样本PAR2、配对退化回合、碰撞审计和消融；模型更换本身不等于提升。4000系列暴露跟踪问题、6000系列暴露FIFO分配成本，均保留；最终组合用8000—8019。balanced_astar控制调度因素，balanced_short控制学习因素，不能把就近分配收益写成强化学习收益。
