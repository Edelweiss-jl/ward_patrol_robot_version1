"""MQTT 主题与消息格式。

仿真端（机器人）与本服务通过下面 5 个主题通信，全部使用 UTF-8 JSON。
主题前缀可在 config/mqtt_config.json 中整体替换；字段名保持一致。

| 主题 | 方向 | 说明 |
| --- | --- | --- |
| ward/patrol/bed/arrival  | 仿真 -> 服务 | 机器人到达床位 |
| ward/patrol/bed/vitals   | 服务 -> 订阅者 | 生成的原始体征 |
| ward/patrol/bed/status   | 服务 -> 仿真 | 判定结果与床位颜色（异常为红） |
| ward/patrol/bed/alert    | 服务 -> 订阅者 | 仅异常时发布 |
| ward/patrol/service/liveness | 服务 -> 订阅者 | online / offline（遗嘱消息） |
"""

from __future__ import annotations

import json
import time

TOPIC_ARRIVAL = "ward/patrol/bed/arrival"
TOPIC_VITALS = "ward/patrol/bed/vitals"
TOPIC_STATUS = "ward/patrol/bed/status"
TOPIC_ALERT = "ward/patrol/bed/alert"
TOPIC_LIVENESS = "ward/patrol/service/liveness"

# 判定等级：正常 / 预警 / 危急。warning 与 critical 都属于异常。
LEVELS = ("normal", "warning", "critical")
LEVEL_ORDER = {level: i for i, level in enumerate(LEVELS)}
ABNORMAL_LEVELS = ("warning", "critical")


def now_iso():
    """本地时间的 ISO 字符串，秒后保留 3 位。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + f".{int(time.time() * 1000) % 1000:03d}"


def arrival_message(bed_id, robot_id="R1", sim_time=None, seq=0, **extra):
    """机器人到达床位时发布的消息。"""
    msg = {
        "event": "bed_arrival",
        "bed_id": str(bed_id),
        "robot_id": str(robot_id),
        "seq": int(seq),
        "sim_time": None if sim_time is None else round(float(sim_time), 3),
        "ts": now_iso(),
    }
    msg.update(extra)
    return msg


def vitals_message(bed_id, vitals, scenario="routine", robot_id=None, seq=0, sim_time=None):
    msg = {
        "event": "vitals_sampled",
        "bed_id": str(bed_id),
        "seq": int(seq),
        "scenario": scenario,
        "vitals": dict(vitals),
        "ts": now_iso(),
    }
    if robot_id is not None:
        msg["robot_id"] = str(robot_id)
    if sim_time is not None:
        msg["sim_time"] = round(float(sim_time), 3)
    return msg


def status_message(bed_id, verdict, robot_id=None, seq=0, sim_time=None):
    """判定结果：status / abnormal / color / reasons，供仿真端给床位换色。"""
    msg = {
        "event": "bed_status",
        "bed_id": str(bed_id),
        "seq": int(seq),
        "status": verdict["status"],
        "abnormal": bool(verdict["abnormal"]),
        "color": list(verdict["color"]),
        "reasons": list(verdict["reasons"]),
        "vitals": dict(verdict["vitals"]),
        "scenario": verdict.get("scenario", "routine"),
        "ts": now_iso(),
    }
    if robot_id is not None:
        msg["robot_id"] = str(robot_id)
    if sim_time is not None:
        msg["sim_time"] = round(float(sim_time), 3)
    return msg


def dumps(msg):
    return json.dumps(msg, ensure_ascii=False)


def loads(payload):
    """把 paho 给的 bytes/str 解析为 dict；解析失败返回 None。"""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None
