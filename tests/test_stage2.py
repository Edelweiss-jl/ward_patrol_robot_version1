"""Stage 2 geometry, version, fleet and task acceptance."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pybullet as bullet
from ward_patrol.maps.geometry import blank_map, DEFAULT_MODELS, Planner, MapStore, validate, compile_floor, copy_floor, legacy_map
from ward_patrol.runtime.editable import EditableRuntime
from ward_patrol_web.workspace import TaskBedConflict, Workspace


def scene(door=1.):
    document=blank_map('门宽验收')
    floor=document['floors'][0]
    floor.update(width=12,height=12)
    floor['objects']=[dict(id='W',kind='wall',x=0,y=0,width=12,height=.2,rotation=0),
                      dict(id='D',kind='door',wall_id='W',x=0,y=0,width=door,height=.2,rotation=0),
                      dict(id='B',kind='bed',x=0,y=4.5,width=1,height=2,rotation=0)]
    for index,x in enumerate((-4,-2,2,4)):
        floor['objects'] += [dict(id=f'P{index}',kind='parking',x=x,y=-3,width=.2,height=.2,rotation=0),
                             dict(id=f'S{index}',kind='service',bed_id='B',x=x,y=3,width=.2,height=.2,rotation=0)]
    document['version']=1
    return document


def instances(count,model='small'):
    return [dict(id=f'R{i+1}',model_id=model,floor_id='F1',pose=[x,-3,90],parking_id=f'P{i}',enabled=True)
            for i,x in enumerate((-4,-2,2,4)[:count])]


class Stage2Tests(unittest.TestCase):
    def test_door_models_and_geometry(self):
        document=scene()
        self.assertTrue(validate(document)['valid'])
        small=Planner(document['floors'][0],DEFAULT_MODELS[0])
        large=Planner(document['floors'][0],DEFAULT_MODELS[1])
        self.assertTrue(small.route((-2,-3),(-2,3))['path'])
        failure=large.route((-2,-3),(-2,3))
        self.assertFalse(failure['path'])
        self.assertIn('门洞',failure['reason'])
        document['floors'][0]['objects'][1]['width']=2
        self.assertTrue(Planner(document['floors'][0],DEFAULT_MODELS[1]).route((-2,-3),(-2,3))['path'])
        self.assertEqual(len(compile_floor(document['floors'][0])),3)

    def test_versions_and_floor_references(self):
        with tempfile.TemporaryDirectory() as root:
            store=MapStore(root)
            old=store.save(scene())
            changed=deepcopy(old)
            changed['floors'][0]['objects'][1]['width']=2
            new=store.save(changed)
            self.assertEqual((old['version'],new['version']),(1,2))
            self.assertEqual(store.list()[0]['floors'][0]['objects'][1]['width'],1.)
            copied=copy_floor(new,'F1')
            self.assertTrue(validate(copied)['valid'])
            original_ids={o['id'] for o in copied['floors'][0]['objects']}
            new_ids={o['id'] for o in copied['floors'][1]['objects']}
            self.assertFalse(original_ids & new_ids)
            for obj in copied['floors'][1]['objects']:
                for key in ('wall_id','bed_id'):
                    if key in obj:self.assertIn(obj[key],new_ids)

    def test_one_two_four_robots_and_physics(self):
        for count in (1,2,4):
            with self.subTest(count=count),tempfile.TemporaryDirectory() as root:
                document=scene(3.)
                core=EditableRuntime(document,DEFAULT_MODELS,instances(count),output=root)
                try:
                    # Ray passes through the real opening and hits solid wall off-center.
                    ray=bullet.rayTest([0,-1,.4],[0,1,.4],physicsClientId=core.client)[0]
                    self.assertEqual(ray[0],-1)
                    ray=bullet.rayTest([4,-1,.4],[4,1,.4],physicsClientId=core.client)[0]
                    self.assertNotEqual(ray[0],-1)
                    for index in range(count):
                        core.submit(dict(action='create_task',bed=f'S{index}',task=dict(service='dwell',duration=.1,robot_id=f'R{index+1}')))
                    for _ in range(15000):
                        core.advance()
                        if core.tasks and all(t.status=='completed' for t in core.tasks):break
                    self.assertEqual(len(core.robots),count)
                    self.assertTrue(all(t.status=='completed' for t in core.tasks),[(r.robot_id,r.xy,r.status) for r in core.robots])
                finally:core.close()
                snapshots=Path(root,core.run_id,'snapshots.jsonl')
                self.assertTrue(snapshots.stat().st_size>0)
                self.assertEqual(json.loads(Path(root,core.run_id,'map.json').read_text(encoding='utf-8'))['version'],1)

    def test_manual_release_and_batch(self):
        with tempfile.TemporaryDirectory() as root:
            core=EditableRuntime(scene(3),DEFAULT_MODELS,instances(1),output=root)
            try:
                core.submit(dict(action='create_batch',tasks=[dict(bed='S0',task=dict(service='manual',release=2,priority=3))]))
                for _ in range(100):core.advance()
                self.assertEqual(core.tasks[0].status,'pending')
                for _ in range(5000):
                    core.advance()
                    if core.service_started:break
                self.assertEqual(core.tasks[0].status,'assigned')
                core.submit(dict(action='confirm_service',task_id='T001'))
                core.submit(dict(action='confirm_service',task_id='T001'))
                core.advance()
                self.assertEqual(sum(e['event']=='task_completed' for e in core.events),1)
            finally:core.close()

    def test_dispatch_prefers_priority_then_earliest_deadline(self):
        with tempfile.TemporaryDirectory() as root:
            core = EditableRuntime(scene(3), DEFAULT_MODELS, instances(1), output=root)
            try:
                unlimited = core.add_task('S0', priority=2)
                later = core.add_task('S1', priority=2, deadline=90)
                sooner = core.add_task('S2', priority=2, deadline=60)
                lower_priority = core.add_task('S3', priority=1, deadline=30)
                for expected in (sooner, later, unlimited, lower_priority):
                    core.dispatch()
                    self.assertEqual(core.robots[0].task_id, expected.task_id)
                    core.finish(expected, core.robots[0], 'test')
            finally:
                core.close()

    def test_samples_are_versionable(self):
        for kind in ('corridor','ring'):
            document=legacy_map(kind)
            self.assertTrue(validate(document)['valid'])
            self.assertTrue(any(o['kind']=='door' for o in document['floors'][0]['objects']))
            self.assertTrue(any(o['kind']=='bed' for o in document['floors'][0]['objects']))

    def test_dispatch_wait_reasons_distinguish_busy_and_unreachable_for_each_bed(self):
        with tempfile.TemporaryDirectory() as root:
            core = EditableRuntime(scene(3), DEFAULT_MODELS, instances(1), output=root)
            try:
                first = core.add_task('S0', service='dwell')
                second = core.add_task('S1', service='dwell')
                later = core.add_task('S2', service='dwell', release=10)
                core.dispatch()
                self.assertEqual(first.status, 'assigned')
                self.assertIn('车辆暂时繁忙', core.snapshot()['wait_reasons'][second.task_id])
                self.assertIn('等待发布时间', core.snapshot()['wait_reasons'][later.task_id])
                core.finish(first, core.robots[0], 'test')
                with patch.object(core.planners['R1'], 'route', return_value={'path':[], 'reason':'通道受阻'}):
                    core.dispatch()
                self.assertIn('本轮路径规划失败（R1：通道受阻）', core.snapshot()['wait_reasons'][second.task_id])
                self.assertEqual(core.events[-1]['bed_id'], 'S1')
            finally:
                core.close()

    def test_saved_task_queue_batch_publication_and_recovery(self):
        document = scene(3)
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            core = EditableRuntime(document, DEFAULT_MODELS, instances(1), output=Path(root)/'runs')
            try:
                core.started = False
                records = [dict(id='TASK-'+digit*32, map_id=document['id'], beds=[bed],
                                bed_labels=[bed], count=1, period=0, task=dict(service='dwell'))
                           for digit, bed in [('1','S0'),('2','S1'),('3','missing')]]
                records[0]['created_at'] = '2026-11-16T16:00:00+00:00'
                records[1]['created_at'] = '2026-11-17T07:00:00+00:00'
                workspace._write_json(workspace.task_queue_path,
                                      {record['id']: dict(record, status='saved') for record in records})
                self.assertFalse(core.started)
                workspace = Workspace(root)
                queue = lambda: workspace.editor_tasks(document['id'], core)
                self.assertEqual([item['status'] for item in queue()], ['saved']*3)
                aliases = ['PATROL-20261117-L0001', 'PATROL-20261117-L0002', 'PATROL-LEGACY-L0001']
                self.assertEqual([item['display_number'] for item in queue()], aliases)
                request = dict(run_id=core.run_id, map_id=document['id'], map_version=document['version'])
                ids = [record['id'] for record in records]
                result = workspace.publish_editor_tasks(dict(request, ids=[ids[0],ids[2]]), core)
                self.assertEqual(result['submitted'], 2)
                core.advance()
                self.assertFalse(core.tasks)
                self.assertTrue(queue()[0]['error'])

                batch = dict(request, ids=ids[:2])
                self.assertEqual(workspace.publish_editor_tasks(batch, core)['submitted'], 2)
                self.assertEqual(workspace.publish_editor_tasks(batch, core)['submitted'], 0)
                self.assertEqual([item['status'] for item in queue()][:2], ['publishing']*2)
                with self.assertRaisesRegex(ValueError, '无法删除'):
                    workspace.delete_editor_task(records[0], core)
                core.advance()
                self.assertTrue(core.started)
                self.assertEqual([spec['patrol_id'] for spec in core.task_specs.values()], ids[:2])

                # After an interruption, the event log lets a new run recover unfinished tasks.
                class NewRun:
                    def snapshot(self):
                        return {'run_id':'new-run'}

                restored = Workspace(root).editor_tasks(document['id'], NewRun())
                self.assertEqual([item['status'] for item in restored], ['queued','queued','saved'])
                self.assertEqual([item['display_number'] for item in restored], aliases)
                self.assertEqual([item['id'] for item in restored], ids)
                self.assertEqual(len(core.tasks), 2)
            finally:
                core.close()

    def test_new_task_saves_pending_without_starting_and_enters_a_running_core(self):
        document = scene(3)
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            core = EditableRuntime(document, DEFAULT_MODELS, instances(1), output=Path(root)/'runs')
            try:
                core.started = False
                data = dict(id='user-supplied-id', request_id='a'*32, map_id=document['id'], beds=['S0'],
                            notes='  夜间巡查  ', count=1, period=0,
                            task=dict(service='dwell', priority=3, release=1, deadline=20))
                record = workspace.save_editor_task(data)
                self.assertRegex(record['id'], r'^PATROL-[0-9]{8}-0001$')
                self.assertTrue(record['created_at'].endswith('+00:00'))
                self.assertEqual(record['notes'], '夜间巡查')
                self.assertEqual(record['status'], 'queued')
                self.assertEqual(workspace.save_editor_task(data), record)
                workspace.submit_queued_editor_tasks(core.snapshot(), core.submit)
                core.advance()
                self.assertFalse(core.started)
                self.assertEqual(core.tasks, [])
                core.submit({'action': 'resume'})
                core.advance()
                workspace = Workspace(root)
                workspace.submit_queued_editor_tasks(core.snapshot(), core.submit)
                workspace.submit_queued_editor_tasks(core.snapshot(), core.submit)
                core.advance()
                self.assertEqual(len(core.tasks), 1)
                self.assertEqual(core.tasks[0].status, 'pending')
                spec = core.task_specs[core.tasks[0].task_id]
                self.assertEqual((spec['patrol_id'], spec['priority'], spec['deadline']), (record['id'], 3, 20))
                self.assertEqual(workspace.editor_tasks(document['id'], core)[0]['created_at'], record['created_at'])
                for _ in range(6000):
                    core.advance()
                    if core.tasks[0].status == 'completed':
                        break
                self.assertEqual(core.tasks[0].status, 'completed')
                self.assertEqual(workspace.delete_editor_task(record, core), {'deleted': True, 'archived': True})
                self.assertTrue(Workspace(root).editor_tasks(document['id'], core)[0]['archived'])
                self.assertEqual(workspace.delete_editor_task(record, core), {'deleted': False, 'archived': True})
                self.assertEqual(core.tasks[0].status, 'completed')
                replacement = workspace.save_editor_task(dict(data, request_id='b'*32), core)
                self.assertNotEqual(replacement['id'], record['id'])
            finally:
                core.close()

    def test_new_run_continues_only_unfinished_visits_with_original_task_number(self):
        document = scene(3)
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            stored = workspace.save_editor_task(dict(map_id=document['id'], request_id='e'*32,
                beds=['S0','S1'], count=1, period=0, task=dict(service='dwell')))
            old = EditableRuntime(document,DEFAULT_MODELS,instances(1),output=Path(root)/'runs')
            try:
                workspace.submit_queued_editor_tasks(old.snapshot(),old.submit)
                old.advance()
                for _ in range(5000):
                    if old.tasks[0].status == 'completed':
                        break
                    old.advance()
                self.assertEqual([task.status for task in old.tasks], ['completed','pending'])
            finally:
                old.close()
            new = EditableRuntime(document,DEFAULT_MODELS,instances(1),output=Path(root)/'runs')
            try:
                workspace = Workspace(root)
                restored = workspace.editor_tasks(document['id'],new)[0]
                self.assertEqual((restored['id'],restored['status'],restored['visit_states']),
                                 (stored['id'],'queued',['completed']))
                for _ in range(2):
                    workspace.submit_queued_editor_tasks(new.snapshot(),new.submit)
                new.advance()
                self.assertEqual([task.bed_id for task in new.tasks], ['S1'])
                self.assertEqual(new.task_specs[new.tasks[0].task_id]['visit_index'], 1)
                for _ in range(5000):
                    if new.tasks[0].status == 'completed':
                        break
                    new.advance()
                restored = workspace.editor_tasks(document['id'],new)[0]
                self.assertEqual(restored['visit_states'], ['completed','completed'])
                self.assertTrue(restored['completed'])
            finally:
                new.close()

    def test_task_number_continues_after_reload_and_resets_on_local_date_change(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            data = dict(request_id='a'*32, map_id='corridor', beds=['N1-1'], count=1, period=0)
            with patch('ward_patrol_web.workspace.datetime') as clock:
                clock.now.return_value = datetime(2026, 11, 17, 15, 59, tzinfo=timezone.utc)
                first = workspace.save_editor_task(data)
                workspace = Workspace(root)
                second = workspace.save_editor_task(dict(data, request_id='b'*32, map_id='ring'))
                self.assertEqual((first['id'], second['id']), ('PATROL-20261117-0001', 'PATROL-20261117-0002'))
                clock.now.return_value = datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)
                self.assertEqual(workspace.save_editor_task(data), first)
                third = workspace.save_editor_task(dict(data, request_id='c'*32, beds=['S3-2']))
                self.assertEqual(third['id'], 'PATROL-20261118-0001')

    def test_deleted_task_number_can_be_reused_without_accepting_stale_delete(self):
        class IdleRunner:
            def snapshot(self):
                return {}

        runner = IdleRunner()
        with tempfile.TemporaryDirectory() as root, patch('ward_patrol_web.workspace.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc)
            workspace = Workspace(root)
            data = dict(request_id='a'*32, map_id='corridor', beds=['N1-1'], count=1, period=0)
            first = workspace.save_editor_task(data)
            second = workspace.save_editor_task(dict(data, request_id='b'*32, beds=['S3-2']))
            self.assertEqual(workspace.delete_editor_task(first, runner), {'deleted': True})
            self.assertEqual(workspace.delete_editor_task(first, runner), {'deleted': False})
            workspace = Workspace(root)
            self.assertEqual([task['id'] for task in workspace.editor_tasks('corridor', runner)], [second['id']])
            replacement = workspace.save_editor_task(dict(data, request_id='c'*32))
            self.assertEqual(replacement['id'], first['id'])
            with self.assertRaisesRegex(ValueError, '任务记录已变化'):
                workspace.delete_editor_task(first, runner)
            self.assertEqual([task['id'] for task in workspace.editor_tasks('corridor', runner)],
                             [second['id'], replacement['id']])

    def test_save_rejects_beds_in_unfinished_tasks_until_whole_task_ends(self):
        document = copy_floor(scene(3), 'F1')
        second_floor = document['floors'][1]
        second_bed = next(obj for obj in second_floor['objects'] if obj['kind'] == 'service')
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            workspace.maps.save(document)
            base = dict(map_id=document['id'], count=1, period=0)
            first = workspace.save_editor_task(dict(base, request_id='a'*32, beds=['S0','S1']))
            duplicate = dict(base, request_id='b'*32, beds=['S0'], bed_labels=['一楼 / B03'])
            with self.assertRaises(TaskBedConflict) as raised:
                workspace.save_editor_task(duplicate)
            self.assertEqual(raised.exception.conflicts, [dict(bed_id='S0', label='一楼 / B03', task_number=first['id'])])
            workspace.save_editor_task(dict(base, request_id='c'*32, beds=[second_bed['id']], bed_labels=['二楼 / B03']))

            run_id = 'd'*32
            stored = workspace._task_records()
            stored[first['id']].update(status='published', run_id=run_id)
            workspace._write_json(workspace.task_queue_path, stored)
            visits = [dict(task_id='T001', bed_id='S0', status='completed'),
                      dict(task_id='T002', bed_id='S1', status='assigned')]
            state = dict(run_id=run_id, map_id=document['id'], tasks=visits,
                         task_specs={item['task_id']: {'patrol_id': first['id']} for item in visits})
            runner = type('Runner', (), {'snapshot': lambda self: state})()
            with self.assertRaises(TaskBedConflict):
                workspace.save_editor_task(duplicate, runner)
            visits[1]['status'] = 'cancelled'
            folder = Path(root)/'runs'/run_id
            folder.mkdir(parents=True)
            (folder/'snapshot.json').write_text(json.dumps(state), encoding='utf-8')
            with self.assertRaises(TaskBedConflict):
                Workspace(root).save_editor_task(duplicate)
            visits[1]['status'] = 'completed'
            (folder/'snapshot.json').write_text(json.dumps(state), encoding='utf-8')
            self.assertEqual(Workspace(root).save_editor_task(duplicate)['status'], 'queued')

    def test_archive_published_task_when_all_visits_have_ended(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            data = dict(map_id=scene(3)['id'], request_id='a'*32, beds=['S0', 'S1', 'S2'], count=1, period=0)
            record = workspace.save_editor_task(data)
            run_id = 'd'*32
            stored = workspace._task_records()
            stored[record['id']].update(status='published', run_id=run_id)
            workspace._write_json(workspace.task_queue_path, stored)
            visits = [dict(task_id=f'T{i}', bed_id=bed, status=status)
                      for i, (bed, status) in enumerate(zip(data['beds'], ('completed', 'cancelled', 'assigned')))]
            state = dict(run_id=run_id, map_id=data['map_id'], tasks=visits,
                         task_specs={visit['task_id']: {'patrol_id': record['id']} for visit in visits})
            runner = type('Runner', (), {'snapshot': lambda self: state})()
            self.assertEqual(workspace.get('/api/archives/tasks'), [])
            with self.assertRaisesRegex(ValueError, '无法删除'):
                workspace.delete_editor_task(record, runner)
            state['tasks'] = visits[:2]
            with self.assertRaisesRegex(ValueError, '无法删除'):
                workspace.delete_editor_task(record, runner)
            visits[-1]['status'] = 'expired'
            state['tasks'] = visits
            self.assertEqual(workspace.delete_editor_task(record, runner), {'deleted': True, 'archived': True})
            workspace = Workspace(root)
            self.assertEqual(workspace.delete_editor_task(record, runner), {'deleted': False, 'archived': True})
            archived = workspace.editor_tasks(data['map_id'], runner)[0]
            self.assertTrue(archived['archived'])
            self.assertTrue(archived['archived_at'])
            self.assertFalse(archived['completed'])
            self.assertEqual([visit['status'] for visit in runner.snapshot()['tasks']],
                             ['completed', 'cancelled', 'expired'])
            replacement = workspace.save_editor_task(dict(data, request_id='b'*32), runner)
            self.assertNotEqual(replacement['id'], record['id'])
            other = workspace.save_editor_task(dict(data, map_id='another-map', request_id='c'*32), runner)
            stored = workspace._task_records()
            stored[other['id']]['archived'] = True
            workspace._write_json(workspace.task_queue_path, stored)
            archives = {task['id']: task for task in workspace.get('/api/archives/tasks')}
            self.assertEqual(set(archives), {record['id'], other['id']})
            self.assertEqual(archives[record['id']]['run_id'], run_id)
            self.assertEqual(archives[record['id']]['archived_at'], archived['archived_at'])
            self.assertIsNone(archives[other['id']]['archived_at'])

    def test_permanent_delete_removes_finished_task_from_saved_and_archive_lists(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            data = dict(map_id='corridor',request_id='a'*32,beds=['N1-1'],notes='remove this',
                        count=1,period=0)
            record = workspace.save_editor_task(data)
            run_id = 'd'*32
            stored = workspace._task_records()
            stored[record['id']].update(status='published',run_id=run_id)
            workspace._write_json(workspace.task_queue_path,stored)
            visit = dict(task_id='T1',bed_id='N1-1',status='assigned')
            state = dict(run_id=run_id,map_id=data['map_id'],tasks=[visit],
                         task_specs={'T1':{'patrol_id':record['id']}})
            runner = type('Runner',(),{'snapshot':lambda self:state})()
            with self.assertRaisesRegex(ValueError,'无法删除'):
                workspace.delete_editor_task(record,runner,permanent=True)
            visit['status'] = 'completed'
            self.assertEqual(workspace.delete_editor_task(record,runner,permanent=True),{'deleted':True})

            workspace = Workspace(root)
            self.assertEqual(workspace.editor_tasks(data['map_id'],runner),[])
            self.assertEqual(workspace.archived_tasks(),[])
            self.assertEqual(workspace.delete_editor_task(record,runner,permanent=True),{'deleted':False})
            self.assertNotIn('remove this',workspace.task_queue_path.read_text(encoding='utf-8'))
            replacement = workspace.save_editor_task(dict(data,request_id='b'*32),runner)
            self.assertNotEqual(replacement['id'],record['id'])
            self.assertEqual(replacement['display_number'],record['id'])

    def test_reuses_both_deleted_display_numbers_without_reusing_published_ids(self):
        with tempfile.TemporaryDirectory() as root, patch('ward_patrol_web.workspace.datetime') as clock:
            clock.now.return_value = datetime(2026,11,23,2,0,tzinfo=timezone.utc)
            workspace = Workspace(root)
            document = workspace.maps.save(scene(3))
            data = dict(map_id=document['id'],beds=['S0'],count=1,period=0)
            records = workspace._task_records()
            for number in (1,2):
                task_id = f'PATROL-20261123-{number:04d}'
                records[task_id] = dict(id=task_id,map_id='corridor',status='deleted')
            workspace._write_json(workspace.task_queue_path,records)
            first = workspace.save_editor_task(dict(data,request_id='a'*32))
            second = workspace.save_editor_task(dict(data,request_id='b'*32,map_id='ring',beds=['N1-2']))
            self.assertEqual([first['display_number'],second['display_number']],
                             ['PATROL-20261123-0001','PATROL-20261123-0002'])
            self.assertEqual([first['id'],second['id']],['PATROL-20261123-0003','PATROL-20261123-0004'])
            core = EditableRuntime(document,DEFAULT_MODELS,instances(1),output=Path(root)/'runs')
            try:
                workspace.submit_queued_editor_tasks(dict(core.snapshot(),started=True),core.submit)
                core.advance()
                spec = next(iter(core.task_specs.values()))
                self.assertEqual(spec['patrol_id'],first['id'])
                self.assertEqual(spec['display_number'],first['display_number'])
            finally:
                core.close()

    def test_conflicting_legacy_queue_records_are_flagged_and_not_submitted_together(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Workspace(root)
            data = dict(request_id='a'*32, map_id='corridor', beds=['N1-1'],
                        bed_labels=['一楼 / N1-1'], count=1, period=0)
            first = workspace.save_editor_task(data)
            later = dict(first, id=first['id'][:-4]+'0002', request_id='b'*32)
            workspace._write_json(workspace.task_queue_path, {first['id']:first,later['id']:later})
            state = {'run_id':'f'*32,'map_id':'corridor','started':True,'tasks':[]}
            runner = type('Runner', (), {'snapshot': lambda self: state})()
            self.assertEqual(workspace.editor_tasks('corridor', runner)[1]['bed_conflicts'][0]['task_number'], first['id'])
            commands = []
            workspace.submit_queued_editor_tasks(state, commands.append)
            self.assertEqual([task['id'] for cmd in commands for task in cmd['records']], [first['id']])
            state['events'] = [dict(event='command_applied', command_id=commands[0]['command_id'])]
            state['tasks'] = [dict(task_id='T001', bed_id='N1-1', status='completed')]
            state['task_specs'] = {'T001':{'patrol_id':first['id']}}
            workspace.submit_queued_editor_tasks(state, commands.append)
            self.assertEqual(commands[1]['records'][0]['id'], later['id'])

    def test_multi_floor_patrol_groups_and_rejects_invalid_targets_atomically(self):
        document = copy_floor(scene(3), 'F1')
        second = document['floors'][1]
        parking = next(obj for obj in second['objects'] if obj['kind'] == 'parking')
        service = next(obj for obj in second['objects'] if obj['kind'] == 'service')
        fleet = [instances(1)[0], dict(instances(1)[0], id='R2', floor_id=second['id'], parking_id=parking['id'])]
        with tempfile.TemporaryDirectory() as root:
            core = EditableRuntime(document, DEFAULT_MODELS, fleet, output=root)
            try:
                core.started = False
                patrol = dict(action='create_patrols', run_id=core.run_id, beds=['S0', service['id']],
                              count=2, period=3, task=dict(service='dwell', duration=.1))
                for invalid in (dict(patrol, beds=['S0', 'missing']),
                                dict(patrol, task=dict(patrol['task'], robot_id='R1')),
                                dict(patrol, run_id='stale-run')):
                    core.submit(invalid)
                    core.advance()
                    self.assertEqual(core.events[-1]['event'], 'command_rejected')
                    self.assertEqual(core.tasks, [])
                    self.assertFalse(core.started)
                core.submit(patrol)
                core.advance()
                self.assertTrue(core.started)
                specs = list(core.snapshot()['task_specs'].values())
                self.assertEqual([spec['patrol_id'] for spec in specs], ['T001','T001','T003','T003'])
                self.assertEqual([spec['release'] for spec in specs], [0,0,3,3])
                for _ in range(6000):
                    core.advance()
                    if all(task.status == 'completed' for task in core.tasks):
                        break
                self.assertEqual([(task.status, task.robot_id) for task in core.tasks],
                                 [('completed','R1'),('completed','R2')]*2)
                groups = [event['visit_task_ids'] for event in core.events if event['event'] == 'patrol_created']
                self.assertEqual(groups, [['T001','T002'],['T003','T004']])
            finally:
                core.close()

if __name__=='__main__':unittest.main()
