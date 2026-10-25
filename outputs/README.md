# 运行输出

这里保存演示报告、截图、调试日志和试验性输出，与正式模型和基准实验分开。

[demo_outputs](demo_outputs/README.md) 保留原根目录 demo_outputs 中的所有文件，也是当前演示的默认输出位置。正式训练成果请放 artifacts。

新增临时任务可创建 `outputs/任务名/`，在相应 CLI 的 `--report`、`--events`、`--screenshot` 或 `--output` 参数中指定路径。需要长期复现时，将完整实验整理到 artifacts 的独立版本目录并补充 README。

生成文件默认不提交 Git；目录 README 参与版本管理。分享截图或报告时请明确复制所需文件，不要假设临时结果已进入仓库。
