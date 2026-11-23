"""Building-wide lift editing, conservative migration, and runtime integration."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from ward_patrol.maps.elevators import (catalog_errors, elevator_action, landing_reports,
                                       normalize_elevators, remove_landing)
from ward_patrol.maps.geometry import DEFAULT_MODELS, MapStore, copy_floor, validate
from ward_patrol.maps.templates import elevator_demo_map
from ward_patrol.runtime.editable import EditableRuntime
from ward_patrol.runtime.elevator import build_elevators
from ward_patrol_web.workspace import Workspace
from tests.test_stage4 import advance_until, setup


def edit(document, action='inspect', **fields):
    return elevator_action(dict(map=document,action=action,lift_id='E1',**fields),DEFAULT_MODELS)


class ElevatorCatalogTests(unittest.TestCase):
    def test_legacy_migration_keeps_identity_and_does_not_mutate_input(self):
        old=elevator_demo_map()
        old['schema']=2
        original=deepcopy(old)
        document=normalize_elevators(old)
        self.assertEqual(old,original)
        self.assertEqual(document['schema'],3)
        self.assertEqual(len(document['elevators']),1)
        lift=document['elevators'][0]
        self.assertEqual((lift['id'],lift['name']),('E1','E1'))
        self.assertEqual(set(lift['served_floors']),{'F1','F2'})
        self.assertNotIn('legacy_connections',lift)
        self.assertTrue(validate(document)['valid'])
        self.assertEqual(normalize_elevators(document),document)
        for floor in document['floors']:
            entry=next(o for o in floor['objects'] if o['kind']=='elevator')
            self.assertEqual(entry['lift_id'],'E1')
            self.assertNotIn('service_floors',entry)
            self.assertNotIn('shaft_id',entry)

    def test_inconsistent_legacy_stops_preserve_restrictions_until_explicit_update(self):
        old=elevator_demo_map()
        entry=next(o for o in old['floors'][1]['objects'] if o['kind']=='elevator')
        entry['service_floors']=['F2']
        document=normalize_elevators(old)
        lift=document['elevators'][0]
        self.assertIn('migration_warning',lift)
        self.assertEqual(lift['legacy_connections'],{'F1':[],'F2':[]})
        floors={f['id']:f for f in document['floors']}
        self.assertEqual(build_elevators(floors,document['elevators'])['E1'].landings['F1'].entrance['service_floors'],[])
        result=edit(document,'update',name='住院梯',served_floors=['F1','F2'],default_width=1.8)['map']
        self.assertNotIn('legacy_connections',result['elevators'][0])
        self.assertEqual(result['elevators'][0]['id'],'E1')

    def test_unlinked_legacy_entrances_are_not_guessed_to_be_the_same_lift(self):
        old=elevator_demo_map()
        for floor in old['floors']:
            next(o for o in floor['objects'] if o['kind']=='elevator').pop('shaft_id')
        result=normalize_elevators(old)
        self.assertEqual(len(result['elevators']),2)
        self.assertEqual(len({lift['name'] for lift in result['elevators']}),2)
        self.assertTrue(all(len(lift['landings'])==1 for lift in result['elevators']))
        legacy=build_elevators({floor['id']:floor for floor in old['floors']})
        self.assertEqual({key:lift.name for key,lift in legacy.items()},
                         {lift['id']:lift['name'] for lift in result['elevators']})

    def test_pending_stops_do_not_create_phantom_runtime_landings(self):
        document=normalize_elevators(elevator_demo_map())
        remove_landing(document,document['elevators'][0],'F2')
        result=edit(document)
        self.assertEqual(result['reports']['E1'][1]['status'],'missing')
        lifts=build_elevators({f['id']:f for f in document['floors']},document['elevators'])
        self.assertEqual(set(lifts['E1'].landings),{'F1'})

    def test_copy_uses_new_local_ids_and_needs_confirmation(self):
        document=normalize_elevators(elevator_demo_map())
        remove_landing(document,document['elevators'][0],'F2')
        result=edit(document,'copy',source_floor='F1')
        document=result['map']
        lift=document['elevators'][0]
        self.assertEqual(result['reports']['E1'][1]['status'],'proposed')
        source,target=lift['landings']['F1'],lift['landings']['F2']
        for key in ('entrance_id','waiting_id','exit_id'):
            self.assertNotEqual(source[key],target[key])
        entry=next(o for o in document['floors'][1]['objects'] if o['id']==target['entrance_id'])
        self.assertEqual(entry['wall_id'],'F2-south')
        self.assertFalse(target['confirmed'])
        self.assertEqual(set(build_elevators({f['id']:f for f in document['floors']},document['elevators'])['E1'].landings),{'F1'})
        confirmed=edit(document,'confirm',floor_ids=['F2'])
        self.assertEqual(confirmed['reports']['E1'][1]['status'],'ready')
        self.assertTrue(confirmed['map']['elevators'][0]['landings']['F2']['confirmed'])

    def test_copy_does_not_overwrite_existing_placement(self):
        document=normalize_elevators(elevator_demo_map())
        previous=deepcopy(document['elevators'][0]['landings']['F2'])
        result=edit(document,'copy',source_floor='F1')['map']
        self.assertEqual(result['elevators'][0]['landings']['F2'],previous)

    def test_placing_on_any_stop_generates_only_missing_served_landings(self):
        document=normalize_elevators(elevator_demo_map())
        document=copy_floor(copy_floor(document,'F1'),'F1')
        lift=document['elevators'][0]
        for fid in lift['served_floors']:
            if fid!='F2':
                remove_landing(document,lift,fid)
        lift['landings']['F2']['confirmed']=False
        other=deepcopy(document['floors'][0])
        other.update(id='F3',objects=[])
        document['floors'].append(other)
        # The same wall can be drawn as a tall rectangle with a different rotation.
        wall=next(obj for obj in document['floors'][0]['objects'] if obj['id']=='F1-south')
        wall.update(width=wall['height'],height=wall['width'],rotation=90)
        with TemporaryDirectory() as root:
            result=Workspace(root).post('/api/maps/elevators',dict(
                map=document,action='copy',confirm_source=True,lift_id='E1',
                source_floor='F2',models=DEFAULT_MODELS))
        updated=result['map']
        lift=updated['elevators'][0]
        self.assertEqual([row['status'] for row in result['reports']['E1']],['ready']*4)
        self.assertEqual(set(lift['landings']),set(lift['served_floors']))
        self.assertTrue(all(landing['confirmed'] for landing in lift['landings'].values()))
        self.assertFalse(updated['floors'][-1]['objects'])
        for key in ('entrance_id','waiting_id','exit_id'):
            source=next(obj for obj in updated['floors'][1]['objects'] if obj['id']==lift['landings']['F2'][key])
            target=next(obj for obj in updated['floors'][0]['objects'] if obj['id']==lift['landings']['F1'][key])
            self.assertNotEqual(target['id'],source['id'])
            self.assertEqual((target['x'],target['y'],target['width'],target['rotation']),
                             (source['x'],source['y'],source['width'],source.get('rotation',0)))
        self.assertTrue(validate(updated)['valid'])

    def test_adding_a_stop_uses_existing_entrance_as_reference(self):
        document=normalize_elevators(elevator_demo_map())
        lift=document['elevators'][0]
        remove_landing(document,lift,'F2')
        lift['served_floors']=['F1']
        result=edit(document,'update',name='住院梯',served_floors=['F1','F2'],default_width=1.6)
        self.assertEqual([row['status'] for row in result['reports']['E1']],['ready','ready'])
        self.assertEqual(result['map']['elevators'][0]['landings']['F1'],lift['landings']['F1'])

    def test_one_confirmation_skips_blocked_landings(self):
        document=normalize_elevators(elevator_demo_map())
        lift=document['elevators'][0]
        for landing in lift['landings'].values():
            landing['confirmed']=False
        document['floors'][1]['objects'].append(dict(id='blocked',kind='furniture',x=-2,y=-2,width=2,height=2))
        result=edit(document,'copy',source_floor='F1',confirm_source=True)
        self.assertEqual([row['status'] for row in result['reports']['E1']],['ready','invalid'])
        landings=result['map']['elevators'][0]['landings']
        self.assertTrue(landings['F1']['confirmed'])
        self.assertFalse(landings['F2']['confirmed'])

    def test_nonmatching_floor_remains_pending_and_cannot_be_confirmed(self):
        document=normalize_elevators(elevator_demo_map())
        remove_landing(document,document['elevators'][0],'F2')
        next(o for o in document['floors'][1]['objects'] if o['id']=='F2-south')['y']=-4
        result=edit(document,'copy',source_floor='F1')
        self.assertEqual(result['reports']['E1'][1]['status'],'missing')
        self.assertTrue(result['reports']['E1'][1]['issues'])
        with self.assertRaises(ValueError):
            edit(result['map'],'confirm',floor_ids=['F2'])

    def test_blocked_waiting_point_cannot_be_confirmed(self):
        document=normalize_elevators(elevator_demo_map())
        document['elevators'][0]['landings']['F2']['confirmed']=False
        document['floors'][1]['objects'].append(dict(id='blocked',kind='furniture',x=-2,y=-2,width=2,height=2))
        self.assertEqual(landing_reports(document,DEFAULT_MODELS)['E1'][1]['status'],'invalid')
        with self.assertRaises(ValueError):
            edit(document,'confirm',floor_ids=['F2'])

    def test_update_stops_and_delete_remove_only_the_linked_floor_markers(self):
        document=normalize_elevators(elevator_demo_map())
        result=edit(document,'update',name='病区电梯',served_floors=['F1'],default_width=1.6)['map']
        self.assertFalse(any(o['kind'] in ('elevator','waiting','exit') for o in result['floors'][1]['objects']))
        self.assertTrue(any(o['kind']=='parking' for o in result['floors'][1]['objects']))
        self.assertEqual(result['elevators'][0]['id'],'E1')
        result=edit(result,'delete')['map']
        self.assertFalse(result['elevators'])
        self.assertFalse(any(o['kind']=='elevator' for f in result['floors'] for o in f['objects']))

    def test_copied_floor_retains_lift_binding_but_requires_confirmation(self):
        document=copy_floor(normalize_elevators(elevator_demo_map()),'F1')
        new=document['floors'][-1]
        lift=document['elevators'][0]
        self.assertIn(new['id'],lift['served_floors'])
        self.assertFalse(lift['landings'][new['id']]['confirmed'])
        self.assertTrue(validate(document)['valid'])

    def test_duplicate_and_unknown_bindings_are_rejected(self):
        document=normalize_elevators(elevator_demo_map())
        lift=document['elevators'][0]
        document['elevators'].append(dict(deepcopy(lift),id='other',name='另一部梯'))
        self.assertTrue(catalog_errors(document))
        document=normalize_elevators(elevator_demo_map())
        entry=next(o for o in document['floors'][0]['objects'] if o['kind']=='elevator')
        entry['lift_id']=['bad']
        self.assertTrue(catalog_errors(document))

    def test_incomplete_import_returns_validation_errors(self):
        document=normalize_elevators(elevator_demo_map())
        entry=next(o for o in document['floors'][0]['objects'] if o['kind']=='elevator')
        entry.pop('kind')
        self.assertFalse(validate(document)['valid'])

    def test_save_writes_schema3_as_a_new_version_without_rewriting_history(self):
        with TemporaryDirectory() as root:
            store=MapStore(root)
            old=elevator_demo_map();old.update(schema=2,version=1)
            path=Path(root)/old['id']/'1.json';path.parent.mkdir()
            path.write_text(json.dumps(old),encoding='utf-8');before=path.read_bytes()
            saved=store.save(old)
            self.assertEqual((saved['version'],saved['schema']),(2,3))
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(len(saved['elevators']),1)

    def test_workspace_api_creates_stops_without_repeated_local_configuration(self):
        with TemporaryDirectory() as root:
            workspace=Workspace(root)
            document=normalize_elevators(elevator_demo_map())
            result=workspace.post('/api/maps/elevators',dict(map=document,action='create',name='后勤梯',
                served_floors=['F1','F2'],default_width=1.8,capacity=3,models=DEFAULT_MODELS))
            lift=result['map']['elevators'][-1]
            self.assertEqual(lift['served_floors'],['F1','F2'])
            self.assertEqual(lift['capacity'],3)
            self.assertTrue(all(row['status']=='missing' for row in result['reports'][lift['id']]))
            update=dict(map=result['map'],action='update',lift_id=lift['id'],name=lift['name'],
                        served_floors=lift['served_floors'],default_width=1.8,models=DEFAULT_MODELS)
            self.assertEqual(workspace.post('/api/maps/elevators',update)['map']['elevators'][-1]['capacity'],3)
            revised=workspace.post('/api/maps/elevators',dict(update,capacity=1))['map']
            saved=workspace.post('/api/maps/save',revised)
            reloaded=next(item for item in workspace.get('/api/maps') if item['id']==saved['id'])
            self.assertEqual(reloaded['elevators'][-1]['capacity'],1)
            for invalid in (0,-1,1.5,True,'3',None):
                with self.subTest(capacity=invalid), self.assertRaisesRegex(ValueError,'搭载车辆数'):
                    workspace.post('/api/maps/elevators',dict(update,capacity=invalid))

    def test_canonical_catalog_executes_a_cross_floor_task_after_renaming(self):
        document,models,instances=setup()
        document=edit(document,'update',name='住院楼东梯',served_floors=['F1','F2'],default_width=1.8)['map']
        with TemporaryDirectory() as root:
            core=EditableRuntime(document,models,instances,output=root)
            try:
                self.assertEqual(core.elevators['E1'].snapshot()['name'],'住院楼东梯')
                core.submit(dict(action='create_task',bed='F2-bed-service',task=dict(robot_id='R1',service='dwell',duration=0)))
                advance_until(core,lambda: bool(core.tasks) and core.tasks[0].status=='completed')
                self.assertEqual(core.robot_floors['R1'],'F2')
            finally:
                core.close()

    @unittest.skipUnless(shutil.which('node'),'Node is needed for the editor data contract checks')
    def test_editor_migration_attachment_and_template_copy_match_backend(self):
        result=subprocess.run(['node',str(Path(__file__).with_name('elevator_editor_checks.js'))],
            input=json.dumps(elevator_demo_map()),text=True,encoding='utf-8',capture_output=True,check=True)
        maps=json.loads(result.stdout)
        self.assertEqual(maps['normalized'],normalize_elevators(elevator_demo_map()))
        for document in maps.values():
            self.assertTrue(validate(document)['valid'],validate(document))


if __name__=='__main__':
    unittest.main()
