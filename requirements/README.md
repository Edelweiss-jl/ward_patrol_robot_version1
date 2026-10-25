# 依赖与环境

依赖清单用于重建环境，不是程序入口。现有 venv 保留在根目录，可直接继续使用。原 PPO 清单以 Python 3.10 为基准。

| 文件 | 适用范围 |
| --- | --- |
| requirements_adaptive.txt | 基础仿真、自适应训练/评估：NumPy、PyBullet |
| requirements_ppo.txt | 单/双机器人 PPO：额外包含 Gymnasium、SB3、PyTorch |
| requirements_plotting.txt | 绘图：Matplotlib 和 pandas（单机器人图表使用 pandas） |

新环境在根目录创建，然后按需求选择安装：

```powershell
py -3.10 -m venv venv
# 只使用基础仿真、自适应功能
.\venv\Scripts\python.exe -m pip install -r requirements/requirements_adaptive.txt
# 使用 PPO 或运行全部测试
.\venv\Scripts\python.exe -m pip install -r requirements/requirements_ppo.txt --extra-index-url https://download.pytorch.org/whl/cpu
# 绘图时另外安装
.\venv\Scripts\python.exe -m pip install -r requirements/requirements_plotting.txt
.\venv\Scripts\python.exe -m pip check
```

两个算法清单有共同依赖，无需为了运行演示重复创建环境。绘图清单的版本取自整理时本机已安装版本。新增专属依赖可建 `requirements_功能名.txt`；调整版本后检查兼容性，并记录新实验使用的版本。不要在这里存安装包或虚拟环境。
