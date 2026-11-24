import json
from http.server import ThreadingHTTPServer
from tempfile import TemporaryDirectory
from threading import Thread
from types import SimpleNamespace
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ward_patrol.maps.geometry import legacy_map
from ward_patrol_web.census import service_beds
from ward_patrol_web.server import Handler, SimRunner
from ward_patrol_web.workspace import Workspace
from ward_patrol_web.workspace import VacantTaskBeds


class QuietHandler(Handler):
    def log_message(self, *_args):
        pass


class BedCensusTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Workspace(directory.name)
        self.runner = SimRunner(mqtt=False, workspace=self.workspace)
        self.runner.start()
        self.addCleanup(self.stop_runner)
        self.assertTrue(self.runner.ready.wait(5))
        self.assertIsNone(self.runner.error)
        server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        server.runner, server.workspace = self.runner, self.workspace
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.origin = f'http://127.0.0.1:{server.server_port}'
        self.bed = service_beds(legacy_map('corridor'))['N1-1']

    def stop_runner(self):
        self.runner.stop_event.set()
        self.runner.join(5)

    def request(self, path, body=None):
        request = Request(self.origin + path)
        if body is not None:
            request.data = json.dumps(body).encode()
            request.add_header('Content-Type', 'application/json')
        return urlopen(request, timeout=5)

    def current_bed(self):
        with self.request('/api/bed-census?map_id=corridor&version=1') as response:
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            return next(bed for bed in json.load(response) if bed['key'] == self.bed)

    def change(self, action, patient=None, revision=None):
        with self.request('/api/bed-census', dict(
            map_id='corridor', version=1, key=self.bed, action=action, patient=patient, revision=revision,
        )) as response:
            return json.load(response)['patient']

    def history(self, patient):
        query = urlencode(dict(key=self.bed, revision=patient['revision']))
        with self.request('/api/bed-census/history?' + query) as response:
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            return json.load(response)

    def sample(self, count):
        with self.request('/api/cmd', dict(action='trigger_sample', bed='N1-1')):
            pass
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            samples = list(self.runner.snapshot().get('samples', {}).values())
            if len(samples) == count and samples[-1]['accepted']:
                return samples[-1]['result']
            time.sleep(.02)
        self.fail('Sample processing timed out')

    def test_full_occupancy_lifecycle_and_sampling(self):
        with self.request('/beds') as response:
            self.assertIn('床位管理', response.read().decode())
        self.assertIsNone(self.current_bed()['patient'])
        self.assertEqual(self.current_bed()['name'], 'N1-1')
        self.assertEqual(self.sample(1)['verdict']['status'], 'vacant')

        fields = dict(name='仿真患者甲', age_months=96, sex='female', diagnosis='随访观察')
        patient = self.change('admit', fields)
        with self.assertRaises(HTTPError) as conflict:
            self.change('admit', fields)
        self.assertEqual(conflict.exception.code, 409)
        conflict.exception.close()
        self.assertEqual(Workspace(self.workspace.root).census.records[self.bed], patient)
        sample = self.sample(2)
        self.assertEqual(set(sample['profile']), {'age_months', 'sex', 'pregnant', 'revision'})
        self.assertEqual(self.current_bed()['assessment']['rule'], 'pediatric_reference')

        edited = self.change('edit', dict(fields, age_months=480), patient['revision'])
        self.assertEqual(edited['admitted_at'], patient['admitted_at'])
        self.assertIsNone(self.current_bed()['assessment'])
        with self.assertRaises(HTTPError) as stale:
            self.change('discharge', revision=patient['revision'])
        self.assertEqual(stale.exception.code, 409)
        stale.exception.close()

        self.assertEqual(self.sample(3)['verdict']['rule'], 'news2')
        self.change('discharge', revision=edited['revision'])
        self.assertIsNone(self.current_bed()['patient'])
        readmitted = self.change('admit', dict(fields, name='仿真患者乙'))
        self.assertNotEqual(readmitted['revision'], edited['revision'])
        self.assertIsNone(self.current_bed()['assessment'])

    def test_registration_and_robot_history_survive_reload_and_profile_edit(self):
        fields = dict(name='仿真患者', age_months=480, sex='female')
        pending = self.change('register', fields)
        self.assertIsNone(pending['admitted_at'])
        self.assertEqual(self.current_bed()['status'], 'pending')
        self.assertTrue(pending['registered_at'])
        self.assertEqual(self.history(pending), [])
        self.assertIn('待入住', self.sample(1)['verdict']['reasons'][0])

        patient = self.change('check_in', revision=pending['revision'])
        self.assertTrue(patient['admitted_at'])
        self.assertEqual(self.current_bed()['status'], 'occupied')
        with self.request('/api/cmd', dict(action='set_speed', speed=8)):
            pass
        with self.request('/api/cmd', dict(action='create_task', bed='N1-1')):
            pass
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            entries = self.history(patient)
            if entries:
                break
            time.sleep(.05)
        else:
            self.fail('Robot patrol did not record vitals')
        record, = entries
        self.assertEqual(record['source'], 'task')
        self.assertTrue(record['robot_id'])
        self.assertTrue(record['sampled_at'])
        self.assertIn('spo2', record['vitals'])

        edited = self.change('edit', dict(fields, diagnosis='观察'), patient['revision'])
        self.assertEqual(self.history(edited), entries)
        restored = Workspace(self.workspace.root)
        self.assertEqual(restored.census.history(self.bed, edited['revision']), entries)
        self.change('discharge', revision=edited['revision'])
        new_patient = self.change('register', fields)
        self.assertEqual(self.history(new_patient), [])
        self.change('cancel_registration', revision=new_patient['revision'])
        self.assertEqual(self.current_bed()['status'], 'vacant')

    def test_task_queue_checks_live_occupancy_and_summary_keeps_basic_fields(self):
        queue = '/api/editor/tasks'
        task = dict(map_id='corridor', map_version=1, beds=['N1-1'], count=1, period=0, request_id='a' * 32)
        command = dict(action='save', record=task)
        with self.assertRaises(HTTPError) as rejected:
            self.request(queue, command)
        with rejected.exception as response:
            self.assertEqual(response.code, 409)
            self.assertEqual(json.load(response)['conflicts'], [dict(bed_id='N1-1', label='N1-1')])
        self.assertEqual(self.workspace._task_records(), {})

        patient = self.change('register', dict(name='仿真患者', age_months=480, sex='female', diagnosis='随访'))
        with self.request('/api/bed-census?map_id=corridor&version=1&summary=1') as response:
            bed = next(bed for bed in json.load(response) if bed['key'] == self.bed)
        self.assertEqual(bed['status'], 'pending')
        self.assertEqual(set(bed['patient']), {'name', 'age_months', 'sex'})
        with self.request(queue, command) as response:
            saved = json.load(response)

        self.change('cancel_registration', revision=patient['revision'])
        state = dict(run_id='x', map_id='corridor', map_version=1, started=True)
        submissions = []
        runner = SimpleNamespace(snapshot=lambda: state, submit=submissions.append)
        self.workspace.submit_queued_editor_tasks(state, runner.submit)
        self.assertFalse(submissions)
        self.assertEqual(self.workspace.editor_tasks('corridor', runner)[0]['vacant_beds'][0]['bed_id'], 'N1-1')
        stored = self.workspace._task_records()
        stored[saved['id']]['status'] = 'saved'
        self.workspace._write_json(self.workspace.task_queue_path, stored)
        with self.assertRaises(VacantTaskBeds):
            self.workspace.publish_editor_tasks(dict(state, ids=[saved['id']]), runner)
        self.assertFalse(submissions)

        self.change('register', dict(name='仿真患者', age_months=480, sex='female'))
        stored[saved['id']]['status'] = 'queued'
        self.workspace._write_json(self.workspace.task_queue_path, stored)
        state['started'] = False
        published = self.workspace.publish_editor_tasks(dict(state, ids=[saved['id']]), runner)
        self.assertEqual(published['submitted'], 1)
        self.assertEqual(submissions[0]['records'][0]['beds'], ['N1-1'])
