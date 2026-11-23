"""paho-mqtt 的薄封装：兼容 1.x / 2.x，统一发布、订阅与遗嘱消息。"""

from __future__ import annotations

import json
import time

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:  # 依赖缺失时给出明确提示，而不是在连接阶段才失败
    raise ImportError("paho-mqtt is required: pip install -r requirements.txt") from exc


def _new_client(client_id):
    """paho 2.x 要求显式指定回调版本，1.x 不接受该参数。"""
    if hasattr(mqtt, "CallbackAPIVersion"):
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    return mqtt.Client(client_id=client_id)


class MqttBus:
    def __init__(self, cfg, client_id="vitals-client", will=None):
        broker = cfg.get("broker", {})
        self.host = broker.get("host", "127.0.0.1")
        self.port = int(broker.get("port", 1883))
        self.keepalive = int(broker.get("keepalive", 60))
        self._auth = (broker.get("username"), broker.get("password"))
        self._subscriptions = []
        self._handlers = {}
        self._on_connect_hook = None

        self.client = _new_client(client_id)
        if self._auth[0]:
            self.client.username_pw_set(self._auth[0], self._auth[1] or None)
        if will:
            self.client.will_set(will["topic"], json.dumps(will["payload"], ensure_ascii=False),
                                 will.get("qos", 0), retain=True)
        self.client.on_connect = self._handle_connect
        self.client.on_disconnect = self._handle_disconnect
        self.client.on_message = self._handle_message

    # ---- 订阅与回调 ----
    def subscribe(self, topic, qos=1):
        self._subscriptions.append((topic, qos))
        return self

    def on(self, topic, handler):
        """注册某个主题的处理函数 handler(payload_dict)。"""
        self._handlers.setdefault(topic, []).append(handler)
        return self

    def on_connected(self, callback):
        self._on_connect_hook = callback
        return self

    def _handle_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", None) is not None:
            failed = reason_code.is_failure
        else:  # paho 1.x 传的是整数返回码
            failed = int(reason_code) != 0
        if failed:
            print(f"[MQTT] connect failed: {reason_code}")
            return
        print(f"[MQTT] connected to {self.host}:{self.port}")
        for topic, qos in self._subscriptions:
            client.subscribe(topic, qos)
            print(f"[MQTT] subscribed {topic} (qos={qos})")
        if self._on_connect_hook:
            self._on_connect_hook(self)

    def _handle_disconnect(self, client, userdata, flags=None, reason_code=None, properties=None):
        print(f"[MQTT] disconnected: {reason_code}")

    def _handle_message(self, client, userdata, msg):
        from . import protocol

        data = protocol.loads(msg.payload)
        if data is None:
            print(f"[MQTT] ignore non-json payload on {msg.topic}")
            return
        for handler in self._handlers.get(msg.topic, []):
            try:
                handler(data)
            except Exception as exc:
                print(f"[ERROR] handler failed on {msg.topic}: {exc}")

    # ---- 生命周期 ----
    def connect(self, timeout=8):
        self.client.connect(self.host, self.port, self.keepalive)
        self.client.loop_start()
        deadline = time.time() + timeout
        while not self.client.is_connected() and time.time() < deadline:
            time.sleep(0.05)
        if not self.client.is_connected():
            raise RuntimeError(f"cannot reach broker at {self.host}:{self.port}")
        return self

    def publish(self, topic, payload, qos=0, retain=False, wait=False):
        """发布消息。

        wait 只在主线程调用时才可为 True：QoS 1 的回执由网络线程处理，
        在回调里等待回执会把自己卡死（每条约 5 秒），导致判定结果延迟送达。
        """
        if not isinstance(payload, (str, bytes)):
            payload = json.dumps(payload, ensure_ascii=False)
        info = self.client.publish(topic, payload, qos=qos, retain=retain)
        if wait and qos > 0:
            info.wait_for_publish(timeout=5)
        return info

    def loop_forever(self):
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[MQTT] stopped by user")
        finally:
            self.close()

    def close(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
