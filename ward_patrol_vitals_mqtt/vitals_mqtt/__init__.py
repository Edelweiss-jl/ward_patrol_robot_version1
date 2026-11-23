"""病区巡查体征 MQTT 服务。

到达事件 -> 生成模拟体征 -> 判定是否异常 -> 发布床位状态（异常标红）。
"""

from .config import load_config
from .protocol import TOPIC_ARRIVAL, TOPIC_STATUS, TOPIC_VITALS, TOPIC_ALERT, TOPIC_LIVENESS
from .vitals_generator import VitalsGenerator
from .vitals_analyzer import VitalsAnalyzer
from .bed_registry import BedRegistry
from .mqtt_bus import MqttBus
from .service import VitalsService

__all__ = [
    "load_config",
    "TOPIC_ARRIVAL",
    "TOPIC_VITALS",
    "TOPIC_STATUS",
    "TOPIC_ALERT",
    "TOPIC_LIVENESS",
    "VitalsGenerator",
    "VitalsAnalyzer",
    "BedRegistry",
    "MqttBus",
    "VitalsService",
]
