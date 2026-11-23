"""Bounded observed wait history, with an explicit cold-start risk interval."""
from collections import defaultdict, deque
import math


class ElevatorRisk:
    def configure_elevator_risk(self):
        self.elevator_wait_history = defaultdict(lambda:deque(maxlen=128))
        self.elevator_risk_revision = 0

    def record_elevator_wait(self, lift, floor, seconds, at=None):
        hour = int((self.elapsed if at is None else at)//3600)%24
        self.elevator_wait_history[lift,floor,hour].append(float(seconds))
        self.elevator_risk_revision += 1
        self.last_dispatch = -math.inf

    def elevator_wait_risk(self, identity, floor):
        policy = self.dispatch_policy
        hour = int(self.elapsed//3600)%24
        samples = sorted(self.elevator_wait_history.get((identity,floor,hour),()))
        learned = len(samples)>=policy.elevator_min_samples
        if learned:
            lower = max(policy.elevator_wait_lower_seconds,samples[(len(samples)-1)//2])
            upper = max(lower,samples[max(0,math.ceil(len(samples)*policy.elevator_wait_quantile)-1)])
        else:
            lower,upper = policy.elevator_wait_lower_seconds,policy.elevator_wait_upper_seconds
        # A measured longer queue can raise the envelope; upper is an estimate,
        # never a bound on future human traffic.
        live_wait = max(0.,self.elevators[identity].external_busy_until-self.elapsed)
        return dict(lower_seconds=max(lower,live_wait),budget_seconds=max(upper,live_wait),
                    samples=len(samples),source='observed_quantile' if learned else 'configured_interval',hour=hour)

    def elevator_wait_budgets(self):
        return {(identity,floor):self.elevator_wait_estimate(identity,floor)
                for identity,lift in self.elevators.items() for floor in lift.landings}

    def elevator_wait_estimate(self, identity, floor):
        lift = self.elevators[identity]
        base = lift.destination or lift.floor or floor
        known = abs(self.floor_levels[base]-self.floor_levels[floor])*2+4*len(lift.queue)+(4 if lift.rider else 0)
        return max(known,self.elevator_wait_risk(identity,floor)['budget_seconds'])

    def route_wait_budget(self, actions):
        return sum(self.elevator_wait_estimate(action.elevator_id,action.origin)
                   for action in actions if hasattr(action,'elevator_id'))

    def set_elevator_traffic(self, command):
        if command.get('run_id',self.run_id)!=self.run_id:
            raise ValueError('巡查运行已切换，请刷新后重试')
        lift = self.elevators.get(command.get('elevator_id'))
        seconds = command.get('busy_for')
        if lift is None or type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<0:
            raise ValueError('请选择电梯并输入非负的共享占用时长')
        lift.external_busy_until = self.elapsed+seconds
        if seconds and lift.phase=='permission':
            lift.permit = None
            lift.phase = 'boarding' if lift.riders else 'idle'
        self.elevator_risk_revision += 1
        self.last_dispatch = -math.inf
        self.emit('elevator_traffic_changed',elevator_id=lift.identity,busy_until=lift.external_busy_until,
                  reason='共享电梯暂不能接入新机器人；已有乘客继续安全运行')
