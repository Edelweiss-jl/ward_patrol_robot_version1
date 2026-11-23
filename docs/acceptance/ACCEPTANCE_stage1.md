# 阶段 1 验收

阶段 1 提供 corridor、两台机器人、固定 1/60 秒步长和 MQTT 床旁采样闭环。

## 启动

在项目根目录的三个 PowerShell 终端依次执行。每个终端使用同一个 venv。

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements\requirements_web.txt
.\venv\Scripts\python.exe -m ward_patrol.runtime.broker
```

```powershell
.\venv\Scripts\python.exe -m ward_patrol.runtime.mqtt
```

```powershell
.\venv\Scripts\python.exe -m ward_patrol_web.server
```

打开 [简易监控](http://127.0.0.1:8000/monitor)。可给 Web 命令加 `--gui` 打开同一世界的 PyBullet 窗口，空格暂停/继续会提交核心命令。终端 Ctrl+C 停止对应服务。broker 只监听 127.0.0.1:1883。

## 顺序验收

1. 分别选择 N1-1 和 S3-2，将床位状态设为「已有入住」，填写年龄和诊断并保存。为两个床位创建巡查任务。两台车从各自停车点出发，任务表显示派车结果。
2. 观察时间线依次出现 task_arrived、service_started、vitals_received、task_completed。体征事件显示模拟数值。车辆收到匹配回执后释放任务。
3. 点击暂停，仿真秒数和步号冻结。此时 MQTT 回执可以进入队列，继续后在步边界应用。
4. 选择 2 倍或 4 倍，观察相同墙钟时间内推进步数增多，步长仍为 1/60 秒。
5. 点击手动采样。vitals_received 的 source 为 manual，任务完成数保持原值。
6. 下载到站、体征、汇总和事件 CSV，按 task_id、attempt_id、sample_id 和 step 核对。页面显示 run_id，可据此定位记录目录。
7. 重启 Web 后，切换床位检查已保存资料。资料在 outputs/runs/beds.json。

## 自动验证

先停止上面启动的三个服务。验证程序使用 1883 和 8011，测试结束后关闭自己启动的进程。

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests
.\venv\Scripts\python.exe -m tools.verify_stage1
```

实际 MQTT 测试覆盖暂停积压回执、重复请求、重复回执、一次完成、HTTP/SSE、Web 发任务、命令行双床任务和 1 倍/2 倍步数测量。额外核心测试覆盖旧尝试迟到回执、重复取消和手动采样。

只运行命令行时，先启动 broker 和体征服务。命令行默认从 `outputs/runs/beds.json` 读取床位资料，也可用 `--output` 指定资料和运行记录目录。

```powershell
.\venv\Scripts\python.exe -m ward_patrol.runtime.cli --beds N1-1 S3-2
```

## 记录位置

- outputs/runs/<run_id>/input.json 保存固定步长、种子、地图标识和车辆 ID。
- map.json 保存本次几何输入，mqtt_config.json 保存通信及体征配置。
- commands.jsonl 保存成功应用的输入和实际生效步，events.jsonl 保存有序事件及原因。
- snapshots.jsonl 每六步保存一份快照，正常停止另写 snapshot.json。
- outputs/vitals/samples.jsonl 保存 sample_id 对应的采样结果，服务重启继续复用。
- outputs/stage1_acceptance/result.json 保存自动验证结果，broker.log、service.log、web.log、cli.log 保存相关日志。该目录 runs 子目录保存核心联调记录。
- CSV 由浏览器下载到用户选择的目录。

## 实现范围与取舍

运行核心位于 ward_patrol/runtime/core.py，复用 DualRobotSimulation 的场景、派单和运动。服务时序由核心覆盖，原有演示继续使用原先停留完成逻辑。HTTP、CLI、GUI 空格和 MQTT 回执都提交命令队列。

体征配置、生成、分级与 MQTT 封装迁自 E:/python汇报/ygy 的 b7ac967。网页使用 Canvas 和标准库 HTTP/SSE，界面已调整为本阶段任务与事件流程。原组员版的任意点导航、动态增减车辆等控件待后续阶段按统一核心实现。

阶段 1 固定两台车并关闭移动行人，聚焦服务闭环。临时地图版本为 corridor/1，保存完整几何快照，地图编辑与车型配置按阶段 2 实施。运行种子记录在输入中，体征生成器种子记录在 MQTT 配置中。

AMQTT 0.12.2 是实际运行的本地 MQTT broker。Paho 为 2.2.0。无需另装 Mosquitto。本阶段 GUI 键盘和浏览器视觉效果仍需人工验收，自动测试已验证 HTTP/SSE 与真实消息链路。资源预约和跨层执行按后续阶段实施。

重复 sample_id 返回持久化结果。相同 command_id 重投会记录 command_duplicate。cancel_task 和 retry_task 接受 task_id，重试增加 attempt_id，旧尝试回执记录 receipt_late。已入住床位凭匹配任务和执行尝试的有效体征回执完成巡查。空床和入住未登记的床位到站后记录 bed_checked 并完成巡查。断链时请求保留，并周期重发等待回执的请求。

验收通过后回复“阶段 1 验收通过，开始阶段 2”。
