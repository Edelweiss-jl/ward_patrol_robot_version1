# 体征模块迁移来源

生成器、分级器、配置、MQTT 封装及原有单元测试来自 E:/python汇报/ygy 的 b7ac967da88cd56e216ab9971385cc6a4a3e1867。

阶段 1 的采样服务入口为 `python -m ward_patrol.runtime.mqtt`，该入口为每次采样保存 sample_id、任务和执行尝试，并缓存重复请求的结果。旧 service.py 保留来源实现供对照。

启动和验收见 docs/acceptance/ACCEPTANCE_stage1.md。
