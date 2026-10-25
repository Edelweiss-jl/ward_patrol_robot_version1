# 最终验证记录

日期：2026-10-20；解释器为项目venv，依赖与源码哈希见runtime.json。

- 完整命令：`python -m unittest test_adaptive_patrol test_dual_ppo test_complex_ward_demo test_dual_robot_demo test_ppo_patrol`。最终34项全部通过，包含就近匹配导航独立性、同床串行、初始无重叠、墙角必要折点、安全停车、限速及交付模型。
- 默认`python adaptive_patrol_demo.py --headless`：balanced，4/4完成，15.2仿真秒。原任务报告校验器通过，机器人同时移动13.767秒。
- 最终动态：8000—8019，两地图、四控制器，160条记录。每组20/20完成，最终组合40/40配对均快于原A*，碰撞审计均0。
- 最终静态：9000—9004，两地图、四控制器，40条记录；单独FIFO诊断另有160动态及40静态记录，均保留。
- 训练：60回合，22,180转移，约400.6秒；Q选择模式而非专家动作模仿。Q表在FIFO训练，组合系统冻结复用并独立验证。
- results.png由真实JSON/训练记录生成，已检查图面；GUI交互未人工点击验收。
- 首轮退化结果保留在adaptive_artifacts_v1；旧PPO环形初始化重叠已勘误并统一修复。
- 一次墙钟异常值保留；wall_recheck.json记录同一场景复跑及原始值。任务效率结论只使用固定步长仿真秒，不声称CPU时间优越。

核心结论：大幅收益主要来自减少不必要跨区分配，动态导航在同调度下仍有收益。Q-learning相对固定short的额外均值收益仅约0.24%/1.42%，没有证明其普遍或统计显著地优于规则。
