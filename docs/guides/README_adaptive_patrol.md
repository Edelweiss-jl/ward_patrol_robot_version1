> 目录整理说明：本页命令均在项目根目录执行；使用 `python -m 包.模块`。历史指标保留，文件新位置见根目录 README。

# 第三阶段改进：动态路径规划与 Q-learning 自适应选择

目标是在相同安全约束下缩短巡查时间、提高完成率。保留原A*和PPO的源码、模型及历史结果，新增动态规划器、真实训练的Q-learning模式选择器和配对实验。最终成绩以本文实测章节和原始评估数据为准，不保证每个场景都比A*快。

## 1. 运行

```powershell
Set-Location 'E:\python汇报\ward_patrol_robot'
.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo
```

默认两台机器人、动态走廊、四个任务、种子4000，加载 `artifacts/adaptive_artifacts_v3/q_policy.json`，无需重训。空格同时暂停/继续人员和机器人，ESC退出；完成或超时自动关闭窗口并保存报告。PyCharm选本文件、项目venv解释器和项目根工作目录。

默认`balanced`组合为：就近任务分配＋动态路线平滑＋Q-learning选择规划模式。Q只选择导航模式，就近分配是独立确定性算法，不把调度收益计为强化学习成果。

```powershell
# 动态环形、无窗口及自定义任务
.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo --scenario ring --seed 4005
.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo --headless --report outputs/demo_outputs/adaptive_report.json
.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo --headless --beds N1-1 S3-2 N2-1 S2-2 --seconds 240

# 相同初始条件的原A*和两种禁用学习的消融对照
.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo --controller astar --headless --report outputs/demo_outputs/adaptive_astar.json
.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo --controller fixed --headless --report outputs/demo_outputs/adaptive_fixed.json
.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo --controller short --headless --report outputs/demo_outputs/adaptive_short.json

# 相同就近调度，分别采用原A*和固定short规划，隔离调度/导航/学习贡献
.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo --controller balanced_astar --headless --report outputs/demo_outputs/balanced_astar.json
.\venv\Scripts\python.exe -m ward_patrol.adaptive.adaptive_patrol_demo --controller balanced_short --headless --report outputs/demo_outputs/balanced_short.json
```

`--no-people`可关闭人员。任务床号同第一阶段，走廊N1-1到S3-2，环形ICU1—4、WARD1—4，名称区分大小写；允许重复任务，同床串行。退出码：全部完成0，超时/ESC中断1，策略或参数错误2。策略缺失、版本错误、训练未完成会明确报错，不静默降级。默认报告覆盖同名文件，保留实验时指定不同路径。`--seconds`默认180，是仿真秒。

## 2. 为什么不只换神经网络算法

上一版PPO确定性测试始终选择前进，仅换成DQN、SAC或增加训练步数不能解决“动态障碍让全局路径变空”和“栅格路线拐折多”。本版拆开职责：A*提供静态全局路线，动态A*根据当前人员和另一台机器人重新选路，局部跟踪执行安全捷径，Q-learning按现场状态选择规划模式。

这是 **Q-learning + 平滑A* + 预测局部规划 + 安全停车** 的混合系统。强化学习没有替代A*；固定模式对照用于辨别规划本身和学习选择各自的收益。

## 3. 动态规划流程与公平约束

1. 默认balanced采用静态A*路长做就近匹配，避免空闲机器人跨区接队首任务而把更近任务留在队列中；保留任务唯一领取和同床串行。astar/fixed/short/adaptive保留原FIFO以隔离导航效果；balanced_astar/balanced_short/balanced共用就近调度。该贪心匹配不保证全局最优。
2. 切换目标或受阻时先规划动态A*路线，绕过当前人员及另一台机器人；无动态路线时保留静态骨架，继续观察和尝试。
3. 用连续几何检查做可见性平滑，只有不穿墙和家具的折点才可跳过。
4. 每0.2秒分别选择两台机器人的局部规划模式。
5. 选取安全的前视目标并稳定跟踪，不自由偏转到路径的另一侧。cruise模式额外检查0.4秒人员相对运动预测。
6. 只有下一段连续安全时才跳过折点；不能仅因距离小于0.12米就丢弃墙角路点。受阻、缺少路径、目标切换时按模式间隔重新规划。
7. 每1/60秒检查实际移动，危险移动只停车；每0.2秒重新观察和选择方向，随动态障碍改变行走路径。

预测速度来自上一0.2秒实际位移，首周期为0，不读取人员未来真实轨迹。人员仍同时礼让两台机器人；机器人顺序提交位置，禁止相互穿过。预测可有误差，安全闸仍需工作。

两方案速度均0.95米/秒、半径0.28米、安全余量0.16米、到达阈值0.025米、床旁停留0.6秒，人员规则相同；调度差异独立列出，并用同调度消融隔离导航贡献。提速不能来自提高速度、减小半径或减少停留。

## 4. 强化学习：状态、动作与更新

使用共享表格Q-learning，而非神经网络；36种状态可完整导出，适合检查学习行为。两台机器人共享Q表，分别选择模式。

| 状态因素 | 分箱 |
| --- | --- |
| 最近人员到机器人表面的间距 | >1.5米、0.6—1.5米、≤0.6米 |
| 另一台机器人中心距离 | >3米、1.2—3米、≤1.2米 |
| 是否超过1秒未移动 | 否/是 |
| 距当前目标是否小于1.2米 | 否/是 |

合计3×3×2×2=36，没有床号、种子、测试标签或未来任务信息。

| 动作 | 模式 | 前视距离 | 行为 |
| --- | --- | --- | --- |
| 0 | short | 0.45米 | 较短前视，受阻最多每0.65秒重规划 |
| 1 | cruise | 1.4米 | 额外0.4秒人员预测，受阻最多每0.8秒重规划 |
| 2 | detour | 2米 | 较长前视，受阻最多每0.4秒重规划 |
| 3 | yield | 停车 | 等待一个0.2秒周期 |

Q-learning决定前视、预测和重规划模式，实际方向来自安全路线。路线或预测不安全时停车，是明确的安全机制，不是假装模型选了等待。

```text
Q(s,a) <- Q(s,a) + 0.12 * [r + 0.97 * max Q(s',a') - Q(s,a)]
回合结束时未来价值为0。
每台每周期 r = 4 × 到当前全局路点的距离减少量 - 0.04 + 15 × 新完成任务数
```

反向运动产生负进展奖励；等待有时间成本。初始Q全0，epsilon-greedy探索，训练时随机打破并列值。没有专家标签、监督模仿或前进价值预置。状态离散化与模式设计属于工程选择，有限训练不构成最优性证明。

评估与演示冻结Q表，使用argmax贪心选择，不探索、不更新参数。未访问状态的Q均为0，推理并列时选最小编号short模式；不能声称这些状态已经学会处理。

## 5. 训练与复现

```powershell
.\venv\Scripts\python.exe -m ward_patrol.adaptive.train_adaptive_patrol --episodes 60 --seed 23 --scenario-seed 1000 --output artifacts/adaptive_artifacts_new
```

输出目录必须为空或不存在，不覆盖交付。每回合重新创建实际PyBullet双机器人病区；走廊/环形交替、有人员、场景种子1000—1059，任务顺序、合法人员位置和速度随机化。上限120仿真秒；探索率0.45线性降至0.05，alpha0.12、gamma0.97。

`q_policy.json`保存完整Q值、访问次数、参数、种子、实际回合/转移数、墙钟时间和完成标记；`training.json`保存逐回合奖励、耗时、成功和探索率。中断仍保存已有数据并标记未完成，演示拒绝加载未完成策略。依赖复用PyBullet和NumPy，无新增框架；完整环境仍可用 `requirements/requirements_ppo.txt` 恢复。

Q表在FIFO环境训练，最终就近调度复用冻结Q表并另做独立验证；没有声称训练了任务分配强化学习模型。

如只运行本版而不使用旧PPO，可安装 `requirements/requirements_adaptive.txt`（仅NumPy、PyBullet）；绘制汇报图另外需要Matplotlib，项目现有venv已包含。

## 6. 配对评估与正确解读

最终组合采用四个对照，避免把不同模块的收益混在一起：

| 控制器 | 调度 | 导航 | 用途 |
| --- | --- | --- | --- |
| astar | 原FIFO | 原A*跟踪 | 原始系统基线 |
| balanced_astar | 就近匹配 | 原A*跟踪 | 隔离调度收益 |
| balanced_short | 就近匹配 | 新动态规划、固定short | 禁用强化学习的消融 |
| balanced | 就近匹配 | 新动态规划、Q选择 | 默认最终组合 |

```powershell
# 最终组合：20种子×2布局×4控制器=160回合
.\venv\Scripts\python.exe -m ward_patrol.adaptive.evaluate_adaptive_patrol --episodes 20 --seed 8000 --controllers astar balanced_astar balanced_short balanced

# 单独导航的FIFO诊断，另存
.\venv\Scripts\python.exe -m ward_patrol.adaptive.evaluate_adaptive_patrol --episodes 20 --seed 6000 --controllers astar fixed short adaptive --output artifacts/adaptive_artifacts_v3/evaluation.json

# 静态补充，另存
.\venv\Scripts\python.exe -m ward_patrol.adaptive.evaluate_adaptive_patrol --episodes 5 --seed 5000 --static --controllers astar fixed short adaptive --output artifacts/adaptive_artifacts_v3/evaluation_static.json

# 最终组合的静态补充
.\venv\Scripts\python.exe -m ward_patrol.adaptive.evaluate_adaptive_patrol --episodes 5 --seed 9000 --static --controllers astar balanced_astar balanced_short balanced --output artifacts/adaptive_artifacts_v3/evaluation_balanced_static.json
```

训练1000—1059；首轮开发3000附近，首轮评估4000—4019暴露问题后用于改进；6000系列单独导航评估进一步暴露FIFO跨区任务成本，该轮记录完整保留。最终组合另用8000—8019独立种子。控制器均重新建世界，初始任务队列、人员位置/速度、机器人起点完全相同（实际领取顺序允许因调度算法不同而不同）；初始条件及SHA256写入记录，配对不一致即报错。按种子交替控制器执行顺序，减小系统负载偏差。

| 指标 | 解释 |
| --- | --- |
| 完成率 | 时限内完成整批，部分完成也算失败 |
| 配对提速 | 仅双方都成功的同种子回合，对 `(A*时间-本方法时间)/A*时间` 求平均 |
| 配对总时下降 | 双方都成功的配对中，`1-本方法总时间/A*总时间`，更能体现严重退化的影响 |
| 更快数量 | 严格更快回合数/双方均成功配对数 |
| 成功平均时间 | 仅成功回合，必须结合完成率解释 |
| PAR2 | 成功用实际时间，失败用2×时间上限，对全部回合平均，越低越好 |
| 碰撞帧 | 分别审计墙体、人员、机器人接触，正常应为0 |
| 电脑实际秒数 | 包含建场景、规划、决策和仿真，受机器负载影响 |

任务仿真耗时是主要效率指标，单次墙钟采样不是实时性能上界。人员仍礼让机器人，后续人员轨迹随机器人行为变化，但交互规则相同。`fixed`固定cruise，`short`固定short，均保留新规划器而禁用学习；固定模式也有的收益不能全部写成强化学习收益。

## 7. 上一版评估勘误

旧随机初始化未排除人员与机器人起点重叠。例如旧环形种子3000中R1为(-9.5,0)，人员为(-9.4,0.5144)，中心距离约0.524米，小于半径之和0.54米。因此旧环形动态超时不能全部归因于算法。

现在 `ward_patrol/common/patrol_scenarios.py` 统一拒绝机器人/人员、人员/人员及静态障碍初始冲突，并用于原PPO环境和新评估。旧数据保留且注明勘误；新A*基线全部重新跑，没有把修复场景生成器的收益计成新算法收益。

## 8. 文件、报告与验收

```text
ward_patrol/adaptive/adaptive_patrol.py          共享路线平滑、状态、报告与场景辅助
ward_patrol/adaptive/dynamic_route_planner.py    最终稳定跟踪、动态重规划、预测和安全闸
ward_patrol/adaptive/adaptive_patrol_demo.py     演示、Q表加载、配对初始条件及逐帧审计
ward_patrol/adaptive/train_adaptive_patrol.py    真实共享Q-learning训练
ward_patrol/adaptive/evaluate_adaptive_patrol.py 配对JSON/CSV/Markdown评估
ward_patrol/common/patrol_scenarios.py         共享的无初始冲突场景生成器
ward_patrol/common/patrol_dispatch.py          与导航独立的就近任务匹配，支持原A*消融
tests/test_adaptive_patrol.py     初始化、公平性、安全、停车、限速及实策略验收
artifacts/adaptive_artifacts_v3/     最终策略、训练记录、评估和验证说明
artifacts/adaptive_artifacts_v1/     首轮策略、源码快照及失败/退化结果
```

报告保留任务事件、距离/等待和并行统计，增加 `mode_counts`、状态/模式轨迹、全局规划次数/用时、初始条件、墙体/人员碰撞帧和最小人员表面间距。`navigation_debug`记录结束时路径、目标和人员位置。演示每0.2秒保存轨迹，批评估只存逐回合指标和初始条件。

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_adaptive_patrol
.\venv\Scripts\python.exe -m unittest tests.test_dual_ppo tests.test_complex_ward_demo tests.test_dual_robot_demo tests.test_ppo_patrol
.\venv\Scripts\python.exe -m tools.verify_dual_report outputs/demo_outputs/adaptive_report.json
```

## 9. 局限

36状态共享表尚未覆盖任意多机器人、陌生建筑、真实传感器噪声及在线任务流。预测是常速度近似，仍可能停车、绕远或超时；没有完备通道预约和全局死锁消解。仍是二维运动学仿真，不是临床或真实机器人部署验证。整体均值提升不代表每个回合都更快，必须保留退化和失败记录。

本次训练/评估只覆盖既有两张地图与各自默认四任务集合，随机化任务顺序及人员条件；不是任意床位组合或任意布局的性能保证。

## 10. 最终实测结果与结论

最终Q表版本adaptive-q-v3，实际训练60回合、22,180条机器人状态转移，约400.6秒。所有测试均使用冻结Q表，没有根据8000系列测试结果继续调参。最终动态评估为8000—8019、两张地图、四控制器，共160回合：

| 动态地图 | 原A*＋FIFO | 就近分配＋原A* | 就近＋固定short | 最终就近＋Q动态规划 | 相对原系统平均耗时下降 |
| --- | --- | --- | --- | --- | --- |
| 走廊 | 33.00秒 | 17.54秒 | 15.69秒 | **15.65秒** | **52.56%** |
| 环形 | 40.77秒 | 22.97秒 | 21.60秒 | **21.30秒** | **47.75%** |

以上为整批四任务完成的平均仿真时间；本批所有控制器均20/20成功，因此PAR2与成功平均时间相同。最终组合在40个动态同种子配对中全部比原始A*系统更快；墙体、人员和机器人碰撞审计帧均为0。原基线完成率已为100%，因此本次只能说保持完成率，不能声称成功率进一步提高。

最终两台机器人累计距离（含整批结束前的返航）平均从走廊53.18米降至26.78米、环形72.05米降至37.35米，分别缩短约49.64%、48.17%；平均累计受阻等待从6.33秒降至0.26秒、2.01秒降至0.72秒。速度、半径、安全余量、停留时间均未放宽。

**贡献拆分：**就近分配是大幅提速的主要来源。相同就近调度下，最终导航相对原A*仍减少约10.74%走廊耗时、7.29%环形耗时；但其中包含路线平滑和重规划机制。Q选择相对固定short仅额外改善约0.24%、1.42%；走廊逐回合为3胜16平1负，环形为11胜4平5负。这个额外收益很小，尚未通过多训练种子统计验证，不宣称Q-learning稳定优于固定规则，也不把总提速52%写成强化学习单独的功劳。不希望加载策略时，可直接使用`--controller balanced_short`，同批数据也显著快于原系统。

5000系列静态FIFO诊断、6000系列动态FIFO诊断、首轮4000系列较差结果全部保留；9000系列另有40回合最终组合静态对照。单独导航版本仍存在比原A*慢的回合，说明任务调度和路径规划必须一起分析，不能只展示成功案例。

数据与图片：

- [最终动态配对表](../../artifacts/adaptive_artifacts_v3/evaluation_balanced.md)、[JSON原始记录](../../artifacts/adaptive_artifacts_v3/evaluation_balanced.json)、[CSV](../../artifacts/adaptive_artifacts_v3/evaluation_balanced.csv)。
- [最终静态配对表](../../artifacts/adaptive_artifacts_v3/evaluation_balanced_static.md)。
- [汇报图](../../artifacts/adaptive_artifacts_v3/results.png)，复现命令：`.\venv\Scripts\python.exe -m ward_patrol.adaptive.plot_adaptive_results`。
- [验证记录](../../artifacts/adaptive_artifacts_v3/validation.md)与[操作验收](../acceptance/ACCEPTANCE_adaptive_patrol.md)。

最终34项测试全部通过；默认演示完成4/4任务，15.2仿真秒，任务事件校验通过。GUI键盘交互未做人工点击验收，无窗口执行和图面已检查。

墙钟记录中保留了一次异常长的运行间隔：走廊8019、balanced_short为11,632.72实际秒，而同场景复跑为0.92实际秒、同样15.367仿真秒。原因未确定，未删除该原始值，复跑见`wall_recheck.json`。因此本文**不据单次墙钟用时宣称CPU计算效率优势**；上面的提速均指固定步长仿真的任务完成时间，不是训练速度或真实机器人实测速度。
