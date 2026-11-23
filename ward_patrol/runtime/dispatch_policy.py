"""Validated simulation-time policy knobs; no training or external data required."""
from dataclasses import asdict, dataclass, fields
import math


@dataclass(frozen=True)
class DispatchPolicy:
    response_seconds: float = 60.
    urgent_response_seconds: float = 20.
    emergency_priority: int = 1
    coverage_ready_seconds: float = 30.
    vacancy_grace_seconds: float = 20.
    rebalance_delay_seconds: float = 15.
    relocation_cooldown_seconds: float = 90.
    support_gain_seconds: float = 20.
    demand_horizon_seconds: float = 120.
    replan_interval_seconds: float = 15.
    manual_service_seconds: float = 60.
    mqtt_service_seconds: float = 15.
    elevator_wait_lower_seconds: float = 30.
    elevator_wait_upper_seconds: float = 120.
    elevator_wait_quantile: float = .9
    elevator_min_samples: int = 8
    spatial_radius_m: float = 6.
    spatial_batch_size: int = 4
    spatial_candidates: int = 12
    group_switch_seconds: float = 5.
    improvement_trials: int = 4
    improvement_budget_ms: float = 12.

    @classmethod
    def read(cls, values=None):
        if values is None:
            return cls()
        known = {field.name for field in fields(cls)}
        if not isinstance(values,dict) or set(values)-known:
            raise ValueError('调度策略包含未知字段')
        result = cls(**values)
        integers = {'emergency_priority','elevator_min_samples','spatial_batch_size','spatial_candidates','improvement_trials'}
        for key,value in asdict(result).items():
            if (type(value) not in (int,float) or not math.isfinite(value) or
                key in integers and type(value) is not int):
                raise ValueError('调度策略 '+key+' 数值无效')
            if key!='emergency_priority' and value<0:
                raise ValueError('调度策略 '+key+' 不可为负数')
        if (result.response_seconds<=0 or result.urgent_response_seconds<=0 or
            result.replan_interval_seconds<=0 or result.coverage_ready_seconds<=0 or
            result.spatial_batch_size<1 or result.spatial_candidates<1 or result.elevator_min_samples<1 or
            not 0<result.elevator_wait_quantile<=1 or
            result.elevator_wait_lower_seconds>result.elevator_wait_upper_seconds):
            raise ValueError('调度策略的响应阈值、分组数量或电梯等待区间无效')
        return result

    def snapshot(self):
        return asdict(self)
