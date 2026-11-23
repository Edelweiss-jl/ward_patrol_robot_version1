import json
import tempfile
import unittest
from ward_patrol.runtime.core import Runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.core=Runtime(output=self.directory.name)

    def tearDown(self):
        self.core.close()
        self.directory.cleanup()

    def arrive(self):
        self.core.submit(dict(action='create_task',bed='N1-1'))
        for _ in range(3000):
            self.core.advance()
            if self.core.outbox:
                return self.core.outbox.pop(0)
        self.fail('arrival timed out')

    def test_old_attempt_and_duplicate_cancel(self):
        request=self.arrive()
        self.core.submit(dict(action='retry_task',task_id=request['task_id']))
        self.core.submit(dict(action='receipt',payload=dict(request,vitals={'heart_rate':70})))
        self.core.advance()
        self.assertTrue(any(e['event']=='receipt_late' for e in self.core.events))
        self.assertFalse(any(e['event']=='task_completed' for e in self.core.events))
        self.core.submit(dict(action='cancel_task',task_id=request['task_id']))
        self.core.submit(dict(action='cancel_task',task_id=request['task_id']))
        self.core.advance()
        self.assertEqual(sum(e['event']=='task_cancelled' for e in self.core.events),1)
        self.assertTrue(all(r.task_id is None for r in self.core.robots))

    def test_duplicate_command_and_manual_receipt(self):
        command=dict(action='trigger_sample',bed='N1-1',command_id='manual-1')
        self.core.submit(command)
        self.core.submit(command)
        self.core.advance()
        self.assertEqual(len(self.core.samples),1)
        request=self.core.outbox.pop()
        self.assertEqual(request['source'],'manual')
        for _ in range(2):
            self.core.submit(dict(action='receipt',payload=dict(request,vitals={'heart_rate':70})))
        self.core.advance()
        self.assertEqual(sum(e['event']=='vitals_received' for e in self.core.events),1)
        self.assertEqual(sum(e['event']=='task_completed' for e in self.core.events),0)

    def test_ending_paused_run_saves_a_frame_and_cannot_resume(self):
        self.core.advance()
        self.core.submit(dict(action='pause'))
        self.core.advance()
        step = self.core.step
        self.core.submit(dict(action='end_run',run_id='stale'))
        self.core.advance()
        self.assertFalse(self.core.ended)
        self.assertTrue(self.core.paused)

        self.core.submit(dict(action='end_run',run_id=self.core.run_id))
        self.core.submit(dict(action='resume'))
        self.core.advance()
        self.core.advance()
        self.assertTrue(self.core.ended)
        self.assertFalse(self.core.started)
        self.assertEqual(self.core.step,step)
        frames = (self.core.directory/'snapshots.jsonl').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(frames),1)
        self.assertTrue(json.loads(frames[0])['ended'])

if __name__=='__main__':unittest.main()
