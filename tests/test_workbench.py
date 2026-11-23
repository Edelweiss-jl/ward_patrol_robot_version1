"""Workbench entry routes, isolated history metadata, and guided readiness rules."""
from collections import Counter
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from ward_patrol_web.server import Handler
from ward_patrol_web.workspace import Workspace


class QuietHandler(Handler):
    def log_message(self,*args):
        pass


class IdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=[]

    def handle_starttag(self,tag,attrs):
        self.ids.extend(value for key,value in attrs if key=='id')


class WorkbenchTests(unittest.TestCase):
    def test_templates_are_separate_from_saved_and_legacy_versions(self):
        with TemporaryDirectory() as root:
            workspace = Workspace(root)
            template = next(map for map in workspace.get('/api/maps') if map['id'] == 'corridor')
            self.assertTrue(template['template'])
            historical = workspace.maps.save(dict(template, name='旧走廊地图'))

            direct_copy = workspace.post('/api/maps/save', template)
            edited_copy = workspace.post('/api/maps/save', dict(template, version=0, name='编辑后的走廊地图'))
            self.assertEqual(len({template['id'], direct_copy['id'], edited_copy['id']}), 3)
            self.assertEqual((direct_copy['version'], edited_copy['version']), (1, 1))
            self.assertEqual(workspace.post('/api/maps/save', dict(edited_copy, version=0))['version'], 2)
            self.assertEqual(workspace.post('/api/maps/save', historical)['version'], 3)

            for path in ('/api/maps', '/api/maps/manage'):
                versions = {(map['id'], map['version']): map for map in workspace.get(path)}
                self.assertTrue(versions[('corridor', 1)]['template'])
                self.assertFalse(versions[('corridor', 2)]['template'])
                self.assertFalse(versions[('corridor', 3)]['template'])
                self.assertFalse(versions[(direct_copy['id'], 1)]['template'])
                self.assertFalse(versions[(edited_copy['id'], 1)]['template'])

    def test_batch_map_archive_restore_delete_and_replay(self):
        with TemporaryDirectory() as root:
            workspace = Workspace(root)
            original = next(map for map in workspace.get('/api/maps') if map['id'] == 'corridor')
            newest = workspace.maps.save(original)
            workspace.post('/api/maps/rename', dict(map_id='corridor', version=newest['version'], name='待归档版本'))
            batch = [dict(map_id='corridor', version=map['version']) for map in (original, newest)]

            def manage(action, rows=batch):
                return workspace.post('/api/maps/manage', dict(action=action, versions=rows))

            def active():
                return [map['version'] for map in workspace.get('/api/maps') if map['id'] == 'corridor']

            with self.assertRaises(ValueError):
                manage('archive', batch + [dict(map_id='corridor', version=999)])
            self.assertCountEqual(active(), [1, 2])
            with patch.object(workspace.maps, '_write_statuses', side_effect=OSError):
                with self.assertRaises(OSError):
                    manage('delete')
            self.assertCountEqual(active(), [1, 2])

            self.assertEqual(manage('archive')['changed'], 2)
            self.assertEqual(manage('archive')['changed'], 0)
            workspace = Workspace(root)
            self.assertEqual(active(), [])
            archived = [map for map in workspace.get('/api/maps/manage') if map['id'] == 'corridor']
            self.assertEqual({map['status'] for map in archived}, {'archived'})
            self.assertIn('待归档版本', [map['name'] for map in archived])
            with self.assertRaises(ValueError):
                workspace.setup(batch[-1])
            self.assertEqual(manage('restore')['changed'], 2)
            self.assertCountEqual(active(), [1, 2])

            run_id = 'a'*32
            run = Path(root)/'runs'/run_id
            run.mkdir(parents=True)
            (run/'map.json').write_text(json.dumps(newest), encoding='utf-8')
            (run/'input.json').write_text('{}', encoding='utf-8')
            self.assertEqual(manage('archive', batch[:1])['changed'], 1)
            self.assertEqual(manage('delete'), dict(changed=2, cleanup_pending=0))
            self.assertEqual(manage('delete')['changed'], 0)
            workspace = Workspace(root)
            self.assertEqual(active(), [])
            self.assertFalse(list((Path(root)/'maps'/'corridor').iterdir()))
            self.assertEqual(workspace.get('/api/replay?run_id='+run_id)['map'], newest)
            with self.assertRaises(ValueError):
                manage('restore')
            self.assertEqual(workspace.post('/api/maps/save', newest)['version'], 3)

    def test_home_editor_alias_and_legacy_monitor_are_distinct(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        server.workspace=SimpleNamespace(get=lambda path: [] if path=='/api/archives/tasks' else None)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/') as response:
                home=response.read().decode('utf-8')
            with urlopen(base+'/editor') as response:
                self.assertEqual(response.read().decode('utf-8'),home)
            with urlopen(base+'/?source=bookmark') as response:
                self.assertEqual(response.read().decode('utf-8'),home)
            self.assertIn('病区巡查工作台',home)
            self.assertIn('workbenchGuide',home)
            self.assertIn('openMapManager',home)
            self.assertIn('id="mapTemplateList"',home)
            self.assertIn('id="mapList"',home)
            self.assertIn('data-view="archive"',home)
            self.assertIn('id="archiveWorkspace"',home)
            self.assertIn('id="archivedTasks"',home)
            with urlopen(base+'/api/archives/tasks') as response:
                self.assertEqual(json.load(response), [])
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
            with urlopen(base+'/monitor') as response:
                monitor=response.read().decode('utf-8')
            self.assertIn('返回巡查工作台',monitor)
            self.assertNotIn('workspaceMain',monitor)
            for asset in ('workbench.js','workbench.css'):
                with urlopen(base+'/'+asset+'?v=test') as response:
                    self.assertEqual(response.status,200)
                    self.assertTrue(response.read())
            parser=IdParser();parser.feed(home)
            self.assertFalse([key for key,count in Counter(parser.ids).items() if count>1])
        finally:
            server.shutdown();server.server_close();thread.join(3)

    def test_history_summaries_include_versions_and_do_not_change_run_files(self):
        with TemporaryDirectory() as root:
            workspace=Workspace(root)
            for number,snapshots in ((1,''),(2,'{"step":1}\n')):
                folder=Path(root)/'runs'/str(number);folder.mkdir(parents=True)
                (folder/'map.json').write_text(json.dumps(dict(name='测试病区',version=number)),encoding='utf-8')
                (folder/'snapshots.jsonl').write_text(snapshots,encoding='utf-8')
            broken=Path(root)/'runs'/'broken';broken.mkdir();(broken/'map.json').write_text('{',encoding='utf-8')
            before={str(path):path.read_bytes() for path in (Path(root)/'runs').rglob('*') if path.is_file()}
            records=workspace.get('/api/runs/summary')
            self.assertEqual({record['id'] for record in records},{'1','2'})
            self.assertEqual({record['version']:record['has_snapshots'] for record in records},{1:False,2:True})
            self.assertTrue(all(record['name']=='测试病区' and record['created_at']>0 for record in records))
            self.assertEqual(before,{str(path):path.read_bytes() for path in (Path(root)/'runs').rglob('*') if path.is_file()})

    @unittest.skipUnless(shutil.which('node'),'Node is needed for workbench state checks')
    def test_guidance_readiness_and_map_edit_guards(self):
        for script in ('workbench_checks.js','replay_navigation_checks.js'):
            result=subprocess.run(['node',str(Path(__file__).with_name(script))],
                text=True,encoding='utf-8',capture_output=True,check=True)
            self.assertIn('passed',result.stdout)


if __name__=='__main__':
    unittest.main()
