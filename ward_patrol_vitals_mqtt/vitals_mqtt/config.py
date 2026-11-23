"""配置加载：broker、主题、体征阈值。

配置只从 JSON 读取，便于仿真端与服务端使用同一份阈值；
缺失字段回落到 DEFAULT，避免改一处配置就跑不起来。
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "mqtt_config.json"

DEFAULT = {
    "broker": {"host": "127.0.0.1", "port": 1883, "keepalive": 60,
               "username": None, "password": None},
    "client": {"sim_id": "ward-sim", "service_id": "vitals-service",
               "monitor_id": "vitals-monitor", "robot_id": "R1"},
    "topics": {
        "arrival": "ward/patrol/bed/arrival",
        "vitals": "ward/patrol/bed/vitals",
        "status": "ward/patrol/bed/status",
        "alert": "ward/patrol/bed/alert",
        "liveness": "ward/patrol/service/liveness",
    },
    "qos": {"arrival": 1, "vitals": 0, "status": 1, "alert": 1, "liveness": 0},
    "bed": {
        "color_normal": [0.16, 0.72, 0.36, 1],
        "color_warning": [1.0, 0.35, 0.20, 1],
        "color_critical": [0.80, 0.02, 0.06, 1],
    },
    "generator": {
        "abnormal_rate": 0.3,
        "critical_ratio": 0.35,
        "seed": 20261026,
        "scenarios": ["hypoxia", "hypertension", "fever", "bradycardia", "hypotension"],
    },
    "metrics": {},
    "record_path": "outputs/vitals_records.jsonl",
}


def _merge(base, override):
    """按字典逐层合并，override 覆盖 base。"""
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path=None):
    """读取配置文件；path 为 None 时使用项目内的默认配置。"""
    target = Path(path) if path else DEFAULT_CONFIG_PATH
    raw = {}
    if target.is_file():
        raw = json.loads(target.read_text(encoding="utf-8"))
    elif path:
        raise FileNotFoundError(f"config not found: {target}")
    cfg = _merge(DEFAULT, raw)
    # 阈值是判定的核心，缺失时给出明确报错，而不是静默放行所有数据。
    if not cfg.get("metrics"):
        raise ValueError(f"no metrics thresholds in config: {target}")
    cfg["_path"] = str(target)
    return cfg


def color_for(cfg, status):
    """按状态返回床位 RGBA 颜色，未知状态回落到正常色。"""
    bed = cfg.get("bed", {})
    return bed.get(f"color_{status}", bed.get("color_normal", [0.16, 0.72, 0.36, 1]))
