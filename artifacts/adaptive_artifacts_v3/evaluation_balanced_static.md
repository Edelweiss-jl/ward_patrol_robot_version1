# 动态路径规划配对评估

| 地图 | 人员 | 控制器 | 完成 | 成功平均秒 | PAR2秒 | 配对均值提速% | 配对总时下降% | 更快/配对成功 | 碰撞帧 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| corridor | False | astar | 5/5 | 20.99 | 20.99 | 0.00 | 0.00 | 0/5 | 0 |
| corridor | False | balanced_astar | 5/5 | 16.10 | 16.10 | 12.06 | 23.28 | 1/5 | 0 |
| corridor | False | balanced_short | 5/5 | 15.20 | 15.20 | 16.97 | 27.57 | 5/5 | 0 |
| corridor | False | balanced | 5/5 | 15.20 | 15.20 | 16.97 | 27.57 | 5/5 | 0 |
| ring | False | astar | 5/5 | 31.85 | 31.85 | 0.00 | 0.00 | 0/5 | 0 |
| ring | False | balanced_astar | 5/5 | 21.52 | 21.52 | 24.72 | 32.44 | 3/5 | 0 |
| ring | False | balanced_short | 5/5 | 20.60 | 20.60 | 27.93 | 35.32 | 5/5 | 0 |
| ring | False | balanced | 5/5 | 20.60 | 20.60 | 27.93 | 35.32 | 5/5 | 0 |

PAR2：成功使用实际仿真时间，超时使用两倍上限；越低越好。配对提速仅比较两控制器均成功的同种子回合。
balanced_astar控制调度因素，balanced_short控制学习因素；fixed/short/adaptive保留FIFO进行单独导航诊断。不能把调度、平滑或重规划的收益全部归因于强化学习。
