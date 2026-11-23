"""床位状态登记：保存每个床位最近一次判定结果，供监控端与收尾汇总使用。"""

from __future__ import annotations

import threading


class BedRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._beds = {}
        self._listeners = []

    def add_listener(self, callback):
        """状态发生变化时回调 callback(record)；用于监控端打印或写文件。"""
        with self._lock:
            self._listeners.append(callback)

    def update(self, bed_id, record):
        """写入一条判定记录，返回是否较上一次发生了变化。"""
        with self._lock:
            previous = self._beds.get(bed_id)
            changed = previous is None or previous.get("status") != record.get("status")
            self._beds[bed_id] = record
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(record)
            except Exception as exc:  # 监听者出错不应影响主流程
                print(f"[WARN] listener failed: {exc}")
        return changed

    def get(self, bed_id):
        with self._lock:
            return self._beds.get(bed_id)

    def snapshot(self):
        with self._lock:
            return dict(self._beds)

    def abnormal_beds(self):
        with self._lock:
            return {k: v for k, v in self._beds.items() if v.get("abnormal")}

    def summary(self):
        with self._lock:
            beds = dict(self._beds)
        counts = {"normal": 0, "warning": 0, "critical": 0}
        for record in beds.values():
            status = record.get("status", "normal")
            counts[status] = counts.get(status, 0) + 1
        return {"total": len(beds), "counts": counts,
                "abnormal": counts["warning"] + counts["critical"],
                "beds": beds}
