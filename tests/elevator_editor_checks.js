'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),crypto=require('crypto'),path=require('path');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'ward_patrol_web/static/elevators.js'),'utf8');
const context=vm.createContext({console,uid:()=>crypto.randomUUID().replaceAll('-',''),clone:value=>JSON.parse(JSON.stringify(value)),
  mapDisplayName:map=>map.name,clearCopiedPatient:()=>{}});
vm.runInContext(source,context);
const old=JSON.parse(fs.readFileSync(0,'utf8'));
context.old=old;
const normalized=vm.runInContext('normalizeElevatorMap(clone(old))',context);
context.map=JSON.parse(JSON.stringify(normalized));
vm.runInContext(`
  const lift=map.elevators[0],level=map.floors[1],previous=lift.landings.F2;
  const newId=attachLiftLanding(map,'F2',previous.entrance_id,'');
  if(newId==='E1'||lift.landings.F2.entrance_id) throw Error('Rebinding must release the old landing');
  if(map.elevators.length!==2) throw Error('Creating a lift should create exactly one resource');
  attachLiftLanding(map,'F2',previous.entrance_id,'E1');
  if(!lift.landings.F2.entrance_id||map.elevators[1].landings.F2.entrance_id) throw Error('Rebinding failed');
`,context);
const rebound=JSON.parse(JSON.stringify(context.map));
const editor=fs.readFileSync(path.join(root,'ward_patrol_web/static/editor.js'),'utf8');
vm.runInContext(editor.slice(editor.indexOf('function draftFromTemplate('),editor.indexOf("action('useMapTemplate'")),context);
const template=vm.runInContext('draftFromTemplate(old)',context);
assert.notStrictEqual(template.elevators[0].id,normalized.elevators[0].id);
assert(!template.floors.some(level=>old.floors.some(other=>level.id===other.id)));
assert(Object.keys(template.elevators[0].landings).every(fid=>template.floors.some(level=>level.id===fid)));
async function checkPlacementRequests() {
  context.configuration={models:[]};
  for(const status of ['ready','proposed','invalid']) {
    const copiedMap={elevators:[{id:'E1'}]};
    const calls=[];
    context.api=async (path,request)=>{
      assert.strictEqual(path,'/api/maps/elevators');
      calls.push(request);
      if(request.action==='copy') {
        assert.strictEqual(request.source_floor,'F2');
        assert.strictEqual(request.lift_id,'E1');
        assert.strictEqual(request.confirm_source,true);
        return {map:copiedMap,reports:{E1:[
          {floor_id:'F1',status:'proposed'},{floor_id:'F2',status},
          {floor_id:'F3',status:'invalid',issues:['净空不足']},{floor_id:'F4',status:'missing',issues:[]}
        ]}};
      }
      assert.strictEqual(request.action,'confirm');
      assert.strictEqual(request.map,copiedMap);
      assert.strictEqual(JSON.stringify(request.floor_ids),status==='ready'?'["F1"]':'["F1","F2"]');
      return {map:copiedMap,reports:{E1:[{floor_id:'F2',status:'ready'}]}};
    };
    const result=await vm.runInContext("placeLiftLanding(map,'E1','F2')",context);
    assert.strictEqual(calls.length,status==='invalid'?1:2);
    assert.strictEqual(result.map,copiedMap);
    assert.strictEqual(result.reports.E1.find(row=>row.floor_id==='F2').status,status==='proposed'?'ready':status);
  }
}
async function checkLegacyWallRecovery() {
  const sourceFloor={id:'F1',objects:[
    {id:'wall-1',kind:'wall',x:-9,y:0,width:.16,height:14,rotation:0},
    {id:'entry',kind:'elevator',lift_id:'E1',wall_id:'wall-1',waiting_id:'wait',exit_id:'exit',x:-9,y:.5,width:1.8,rotation:90},
    {id:'wait',kind:'waiting',elevator_id:'entry',x:-8,y:0},{id:'exit',kind:'exit',elevator_id:'entry',x:-8,y:1}
  ]};
  const targetFloors=['F2','F3','F4'].map((id,index)=>({id,objects:[{
    ...sourceFloor.objects[0],id:'wall-'+id,x:index===2?-7:-9
  }]}));
  const issue='此层没有匹配墙体，请逐层重新定位';
  const oldMap={floors:[sourceFloor,...targetFloors],elevators:[{
    id:'E1',served_floors:['F1','F2','F3','F4'],
    landings:{F1:{entrance_id:'entry',waiting_id:'wait',exit_id:'exit',confirmed:true},
      ...Object.fromEntries(targetFloors.map(level=>[level.id,{confirmed:false,placement_issue:issue}]))}
  }]};
  const reports={E1:[{floor_id:'F1',status:'ready',issues:[]},...targetFloors.map(level=>({
    floor_id:level.id,status:'missing',issues:[issue]
  }))]};
  context.oldMap=oldMap;
  context.api=async (path,request)=>{
    if(path==='/api/maps/validate') {
      // Simulate an existing fixture obstructing the F3 opening.
      return {valid:!request.elevators[0].landings.F3.entrance_id};
    }
    assert.strictEqual(path,'/api/maps/elevators');
    if(request.action==='copy') {
      assert.strictEqual(request.confirm_source,false);
      return {map:oldMap,reports};
    }
    assert.strictEqual(request.action,'inspect');
    return {map:request.map,reports};
  };
  const result=await vm.runInContext("placeLiftLanding(oldMap,'E1','F1',false)",context);
  const landings=result.map.elevators[0].landings;
  const target=result.map.floors[1].objects;
  const entrance=target.find(object=>object.id===landings.F2.entrance_id);
  assert.strictEqual(entrance.wall_id,'wall-F2');
  assert.strictEqual(entrance.rotation,90);
  assert.strictEqual(entrance.x,-9);
  assert.notStrictEqual(entrance.id,'entry');
  assert.strictEqual(target.find(object=>object.id===entrance.waiting_id).elevator_id,entrance.id);
  assert.strictEqual(landings.F2.confirmed,false);
  assert.strictEqual(landings.F1.confirmed,true);
  assert.strictEqual(landings.F3.entrance_id,undefined);
  assert(landings.F3.placement_issue.includes('几何冲突'));
  assert.strictEqual(landings.F4.entrance_id,undefined);
  assert.strictEqual(oldMap.floors[1].objects.length,1);
}
checkPlacementRequests().then(checkLegacyWallRecovery).then(()=>{
  process.stdout.write(JSON.stringify({normalized,rebound,template}));
}).catch(error=>{
  console.error(error);
  process.exitCode=1;
});
