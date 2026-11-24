"""体征服务主流程：订阅到达事件 -> 生成体征 -> 判定 -> 发布状态（异常标红）。"""

from __future__ import annotations

import json
from pathlib import Path

from . import protocol
from .bed_registry import BedRegistry
from .mqtt_bus import MqttBus
from .vitals_analyzer import VitalsAnalyzer
from .vitals_generator import VitalsGenerator


class VitalsService:
    def __init__(self, cfg, record_path=None, verbose=True):
        self.cfg = cfg
        self.verbose = verbose
        self.topics = cfg["topics"]
        self.qos = cfg["qos"]
        self.generator = VitalsGenerator(cfg)
        self.analyzer = VitalsAnalyzer(cfg)
        self.registry = BedRegistry()
        self.records = []
        self._record_path = Path(record_path or cfg.get("record_path", "outputs/vitals_records.jsonl"))
        self._record_file = None
        self.bus = None

    # ---- 核心处理 ----
    def process_arrival(self, bed_id, robot_id=None, seq=0, sim_time=None, profile=None):
        """一次到站采样：生成体征、判定、登记，返回发布用的状态消息。"""
        sample = self.generator.generate(bed_id, seq=seq, robot_id=robot_id, sim_time=sim_time,
                                         profile=profile)
        verdict = self.analyzer.analyze(sample["vitals"], sample["scenario"], profile=profile)
        status_msg = protocol.status_message(bed_id, verdict, robot_id=robot_id,
                                             seq=seq, sim_time=sim_time)
        self.registry.update(bed_id, status_msg)
        self._record(sample, status_msg)
        return sample, status_msg

    def handle_arrival(self, msg):
        bed_id = msg.get("bed_id")
        if not bed_id:
            print(f"[WARN] arrival without bed_id: {msg}")
            return
        sample, status_msg = self.process_arrival(
            bed_id,
            robot_id=msg.get("robot_id"),
            seq=msg.get("seq", 0),
            sim_time=msg.get("sim_time"),
            profile=msg.get("profile"),
        )
        self._publish_status(status_msg, sample)

    def _publish_status(self, status_msg, sample):
        self.bus.publish(self.topics["vitals"], sample, self.qos.get("vitals", 0))
        self.bus.publish(self.topics["status"], status_msg, self.qos.get("status", 1))
        if status_msg["abnormal"]:
            self.bus.publish(self.topics["alert"], status_msg, self.qos.get("alert", 1))

        vitals = status_msg["vitals"]
        flag = "ABNORMAL" if status_msg["abnormal"] else "normal"
        detail = "；".join(status_msg["reasons"]) or "当前项目未触发预警"
        print(f"[BED {status_msg['bed_id']}] {flag} / {status_msg['status']} "
              f"HR={vitals.get('heart_rate')} SpO2={vitals.get('spo2')} "
              f"BP={vitals.get('systolic_bp')}/{vitals.get('diastolic_bp')} "
              f"RR={vitals.get('respiratory_rate')} T={vitals.get('temperature')}")
        print(f"    {detail}")

    def _record(self, sample, status_msg):
        entry = dict(status_msg)
        entry["event"] = "vitals_record"
        entry["scenario"] = sample.get("scenario")
        self.records.append(entry)
        if self._record_file:
            self._record_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._record_file.flush()

    # ---- 启动 ----
    def start(self, block=True):
        self._record_path.parent.mkdir(parents=True, exist_ok=True)
        self._record_file = self._record_path.open("a", encoding="utf-8")
        topics = self.topics
        self.bus = MqttBus(
            self.cfg,
            client_id=self.cfg.get("client", {}).get("service_id", "vitals-service"),
            will={"topic": topics["liveness"], "payload": {"service": "vitals", "state": "offline"},
                  "qos": self.qos.get("liveness", 0)},
        )
        self.bus.subscribe(topics["arrival"], self.qos.get("arrival", 1))
        self.bus.on(topics["arrival"], self.handle_arrival)
        self.bus.on_connected(
            lambda _bus: _bus.publish(topics["liveness"],
                                      {"service": "vitals", "state": "online"},
                                      self.qos.get("liveness", 0), retain=True)
        )
        self.bus.connect()
        print(f"[SERVICE] waiting for bed arrivals on {topics['arrival']}")
        if block:
            self.bus.loop_forever()

    def stop(self):
        if self.bus:
            self.bus.close()
        if self._record_file:
            self._record_file.close()
            self._record_file = None

    def summary(self):
        return self.registry.summary()
