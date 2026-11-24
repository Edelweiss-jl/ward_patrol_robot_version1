"""Charging placement and runtime regressions through the editable simulation."""
from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest

from ward_patrol.maps.geometry import DEFAULT_MODELS, blank_map, validate
from ward_patrol.maps.templates import elevator_demo_map
from ward_patrol.runtime.editable import EditableRuntime, validate_setup


def point(identity, kind, x, y, **settings):
    return dict(id=identity, kind=kind, x=x, y=y, rotation=0, width=.25, height=.25, **settings)


def dock(identity, x, y):
    return point(identity, 'parking', x, y, charger={'number': identity, 'rate': 100})


def robot(identity, floor, parking, x, y, charge=24):
    return dict(id=identity, model_id='small', floor_id=floor, parking_id=parking,
                pose=[x, y, 0], battery_percent=charge, safety_battery_percent=20)


class ChargingTests(unittest.TestCase):
    def test_charger_requires_parking_and_clear_elevator_space(self):
        document = elevator_demo_map()
        floor = document['floors'][0]
        invalid = dock('C1', 0, -4.)
        floor['objects'].append(invalid)
        self.assertTrue(any('电梯门口' in item for item in validate(document)['geometry']))
        invalid.update(x=4, y=-3.5, kind='service')
        self.assertTrue(any('必须绑定停车点' in item for item in validate(document)['structure']))
        invalid['kind'] = 'parking'
        self.assertTrue(validate(document)['valid'])
        with self.assertRaisesRegex(ValueError, '固定停车点'):
            validate_setup(document, DEFAULT_MODELS, [robot('R1', 'F1', 'C1', 4, -3.5)])

    def test_single_dock_is_reserved_then_freed_and_patrol_resumes(self):
        document = blank_map()
        document['version'] = 1
        document['floors'][0]['objects'] = [
            point('P1', 'parking', -4, -2), point('P2', 'parking', -4, 2),
            dock('C', 3, 0), point('S', 'service', 4, 3),
        ]
        fleet = [robot('R1', 'F1', 'P1', -4, -2), robot('R2', 'F1', 'P2', -4, 2, 24.5)]
        with TemporaryDirectory() as directory:
            core = EditableRuntime(document, DEFAULT_MODELS, fleet, output=directory, local_sampling=True)
            try:
                visit = core.add_task('S', service='dwell', duration=.1)
                core.advance()
                self.assertEqual(core.charge_reservations, {('F1', 'C'): 'R1'})
                self.assertEqual(visit.status, 'pending')
                self.assertEqual(core.by_robot['R2'].status, 'waiting_charge')
                for _ in range(5500):
                    core.advance()
                    if visit.status == 'completed' and core.charge_reservations.get(('F1', 'C')) == 'R2':
                        break
                self.assertEqual(visit.status, 'completed')
                self.assertEqual(core.charge_reservations, {('F1', 'C'): 'R2'})
                completed = next(event for event in core.events if event['event'] == 'charging_completed')
                self.assertEqual(completed['battery_percent'], 80)
                self.assertEqual(completed['robot_id'], 'R1')
            finally:
                core.close()

    def test_cross_floor_charging_uses_elevator_and_rejects_unaffordable_trip(self):
        document = elevator_demo_map()
        document['version'] = 1
        document['floors'][1]['objects'].extend([dock('C2', 4, -3.5), point('P3', 'parking', 5, 0)])
        fleet = [robot('R1', 'F1', 'F1-parking', -4, -2)]
        for charge in (0.5, 24):
            with self.subTest(charge=charge), TemporaryDirectory() as directory:
                configured = deepcopy(fleet)
                configured[0]['battery_percent'] = charge
                core = EditableRuntime(document, DEFAULT_MODELS, configured, output=directory)
                try:
                    core.advance()
                    if charge < 1:
                        self.assertEqual(core.charge_reservations, {})
                        self.assertEqual(core.robots[0].status, 'waiting_charge')
                        self.assertEqual(core.robots[0].distance, 0)
                        continue
                    self.assertEqual(core.charge_reservations, {('F2', 'C2'): 'R1'})
                    for _ in range(3000):
                        core.advance()
                        if core.robots[0].status == 'charging':
                            break
                    self.assertEqual(core.robots[0].status, 'charging')
                    self.assertEqual(core.robot_floors['R1'], 'F2')
                    self.assertTrue(any(event['event'] == 'elevator_occupied' for event in core.events))
                finally:
                    core.close()

    def test_second_robot_can_reserve_remote_dock_while_local_dock_is_reserved(self):
        document = elevator_demo_map()
        document['version'] = 1
        document['floors'][0]['objects'].extend([dock('C1', 4, -3.5), point('P2', 'parking', -4, 1)])
        document['floors'][1]['objects'].append(dock('C2', 4, -3.5))
        fleet = [robot('R1', 'F1', 'F1-parking', -4, -2), robot('R2', 'F1', 'P2', -4, 1, 24.5)]
        with TemporaryDirectory() as directory:
            core = EditableRuntime(document, DEFAULT_MODELS, fleet, output=directory)
            try:
                core.advance()
                self.assertEqual(core.charge_reservations, {('F1', 'C1'): 'R1', ('F2', 'C2'): 'R2'})
            finally:
                core.close()
