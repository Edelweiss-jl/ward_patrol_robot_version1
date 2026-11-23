'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const context=vm.createContext({console});
const source=fs.readFileSync(path.join(__dirname,'../ward_patrol_web/static/workbench.js'),'utf8').replace(/initializeWorkspace\(\);\s*$/,'');
vm.runInContext(source,context);
const map={id:'ward',version:2,floors:[{id:'F1',objects:[{id:'P1',kind:'parking'}]}]};
const config={models:[{id:'small'}],instances:[{id:'R1',model_id:'small',floor_id:'F1',parking_id:'P1'}]};
const snapshot={map_id:'ward',map_version:2,started:false,tasks:[]};
const facts=(document=map,fleet=config,state=snapshot)=>context.workspaceFacts(document,fleet,state,[],true);
assert.strictEqual(context.workspaceSuggestion(facts({...map,version:0})),'map');
assert.strictEqual(context.workspaceSuggestion(facts(map,{...config,instances:[]})),'fleet');
assert.strictEqual(context.workspaceSuggestion(facts()),'tasks');
assert.strictEqual(facts(map,config,{...snapshot,map_version:1}).current,false);
assert.strictEqual(facts(map,config,{...snapshot,ended:true}).ended,true);
assert.strictEqual(facts(map,config,{...snapshot,ended:true}).current,false);
assert.strictEqual(facts(map,config,null).current,false);
assert.strictEqual(context.workspaceSuggestion({...facts(),geometry:false}),'map');
assert.strictEqual(facts(map,{...config,instances:[...config.instances,{...config.instances[0],id:'R2'}]}).invalid,1);
assert.strictEqual(facts(map,{...config,instances:[{...config.instances[0],floor_id:'other'}]}).fleetReady,false);
assert.strictEqual(facts(map,{...config,instances:[{...config.instances[0],model_id:'unknown'}]}).fleetReady,false);
assert.strictEqual(facts(map,{...config,instances:[...config.instances,{id:'off',enabled:false}]}).fleetReady,true);
const active=facts(map,config,{...snapshot,started:true,tasks:[{status:'assigned'},{status:'pending'},{status:'completed'}]});
assert.strictEqual(context.workspaceSuggestion(active),'monitor');
assert.strictEqual(active.active,1);assert.strictEqual(active.waiting,1);assert.strictEqual(active.completed,1);
assert.strictEqual(facts(map,config,{...snapshot,map_id:'other',tasks:[{status:'assigned'}]}).total,0);
vm.runInContext("workspaceInitialized=true;workspaceView='monitor'",context);
assert.strictEqual(context.workspaceAllowsEditing(),false);assert.strictEqual(context.workspaceAllowsPerceptionView(),true);
vm.runInContext("workspaceView='tasks'",context);
assert.strictEqual(context.workspaceAllowsEditing(),false);assert.strictEqual(context.workspaceAllowsPerceptionView(),false);
context.$ = ()=>({open:false});
vm.runInContext("workspaceView='map'",context);assert.strictEqual(context.workspaceAllowsEditing(),true);
context.$ = ()=>({open:true});
assert.strictEqual(context.workspaceAllowsEditing(),false);
vm.runInContext("workspaceView='archive'",context);
assert.strictEqual(context.workspaceAllowsEditing(),false);assert.strictEqual(context.workspaceAllowsPerceptionView(),false);
const archiveControls = {};
const archiveButtons = ['maps','tasks'].map(category=>({dataset:{archiveCategory:category},setAttribute(key,value){this[key]=value;}}));
const archiveLoads = [];
Object.assign(context,{
  $: id=>archiveControls[id]??=(Object.create(null)),
  document:{querySelectorAll:()=>archiveButtons},
  archivedMapManager:{refresh:()=>archiveLoads.push('maps')}
});
vm.runInContext('refreshArchivedTasks=()=>archiveLoads.push("tasks")',Object.assign(context,{archiveLoads}));
context.showArchiveCategory('tasks');
assert.equal(archiveControls.mapManager.hidden,true);
assert.equal(archiveControls.archivedTasks.hidden,false);
assert.equal(archiveButtons[1]['aria-pressed'],'true');
context.showArchiveCategory('maps');
assert.equal(archiveControls.mapManager.hidden,false);
assert.equal(archiveControls.archivedTasks.hidden,true);
assert.deepEqual(archiveLoads,['tasks','maps']);
const editorSource=fs.readFileSync(path.join(__dirname,'../ward_patrol_web/static/editor.js'),'utf8');
const mapControls=vm.createContext({assert});
vm.runInContext(`
  const fields=new Map();
  const $=id=>{if(!fields.has(id))fields.set(id,{options:[]});return fields.get(id);};
  function options(id,entries){$(id).options=entries.map(([value,textContent])=>({value,textContent}));}
  const template={id:'corridor',version:1,name:'corridor',template:true};
  const versions=[template,{id:'corridor',version:2,name:'corridor',template:false},
    {id:'corridor',version:14,name:'corridor',template:false}];
  let documentMap=template,replay=null;
`,mapControls);
vm.runInContext(editorSource.slice(editorSource.indexOf('function mapVersionKey('),editorSource.indexOf('async function loadSavedMaps(')),mapControls);
vm.runInContext(`
  mapOptions();
  assert.equal($('mapTemplateList').value,'corridor@1');
  assert.deepEqual($('mapTemplateList').options.slice(1).map(option=>option.value),['corridor@1']);
  assert.deepEqual($('mapList').options.slice(1).map(option=>option.value),['corridor@14','corridor@2']);
  assert.equal($('mapList').value,'');
  assert.equal($('useMapTemplate').disabled,false);
  assert.equal($('saveMap').textContent,'保存为地图');
  documentMap=versions[2];
  syncMapOption();
  assert.equal($('mapTemplateList').value,'');
  assert.equal($('mapList').value,'corridor@14');
  assert.equal($('useMapTemplate').disabled,true);
  assert.equal($('saveMap').textContent,'保存新版本');
  versions[2].display_name='test2';
  mapOptions();
  assert.equal($('mapList').value,'corridor@14');
  assert.equal($('mapList').options.find(option=>option.value==='corridor@14').textContent,mapDisplayName(documentMap));
  assert.equal($('mapList').options.find(option=>option.value==='corridor@14').textContent,'test2');
  assert.equal($('mapList').options.find(option=>option.value==='corridor@2').textContent,'corridor');
`,mapControls);
const roomControls=vm.createContext({assert});
vm.runInContext(`
  let compileRevision=0;
  const wall=(x,y,width,height)=>({kind:'wall',x,y,width,height});
  const door=(id,x)=>({kind:'door',id,x,y:0,width:1.1,height:.2});
  const bed=(id,x)=>({kind:'bed',id,x,y:2});
  const service=(bed_id,name)=>({kind:'service',id:'service-'+bed_id,bed_id,name});
  const first={id:'F1',name:'一层',width:12,height:10,objects:[
    wall(0,0,10,.2),wall(0,4,10,.2),wall(-5,2,.2,4),wall(0,2,.2,4),wall(5,2,.2,4),
    door('left',-2.5),door('right',2.5),bed('a',-4),bed('b',-1.5),bed('c',2),
    service('a','N1-1'),service('b','N1-2'),service('c','N2-1')
  ]};
  const documentMap={floors:[first,{...first,id:'F2',name:'二层'}]};
`,roomControls);
vm.runInContext(editorSource.slice(editorSource.indexOf('function taskDestinations('),editorSource.indexOf('function taskFeedback(')),roomControls);
vm.runInContext(`
  assert.deepEqual(taskRoomsOn(first).map(room=>room.beds.map(bed=>bed.id)),[['a','b'],['c']]);
  assert.equal(resolveTaskChoice('一层／N1','room').id,'left');
  assert.throws(()=>resolveTaskChoice('N1','room'),/重复/);
  assert.equal(resolveTaskChoice('二层','floor').id,'F2');
  first.objects.find(object=>object.id==='left').room_number='101';
  first.objects.find(object=>object.id==='a').room_name='101';
  compileRevision++;
  assert.deepEqual(resolveTaskChoice('一层 / 101','room').beds.map(bed=>bed.id),['a','b']);
`,roomControls);
const vitalsSource=fs.readFileSync(path.join(__dirname,'../ward_patrol_web/static/vitals.js'),'utf8');
const furnishingSource=fs.readFileSync(path.join(__dirname,'../ward_patrol_web/static/furnishing.js'),'utf8');
const tooltipContext=vm.createContext({assert});
vm.runInContext(vitalsSource,tooltipContext);
vm.runInContext(furnishingSource.slice(furnishingSource.indexOf('function refreshCanvasTooltip('),
  furnishingSource.indexOf("canvas.addEventListener('pointerleave'")),tooltipContext);
vm.runInContext(`
  const bed={id:'bed1',name:'01 床',kind:'bed'};
  const level={objects:[bed,{id:'S1',kind:'service',bed_id:'bed1'},{id:'S2',kind:'service',bed_id:'bed1'}]};
  const floor=()=>level, bedAtPointer=()=>bed, bedDisplayName=object=>object.name;
  const modelTitle={}, modelSize={}, modelGuide={}, modelControls={};
  const positionModelTooltip=()=>{};
  const hoveredCanvasPointer={clientX:10,clientY:10}, raisedView=true, taskPicking=false;
  const showTaskRouteTooltip=()=>{throw Error('已巡检的床位应优先显示巡检结果');};
  const sample=(bed_id,seq,result,accepted=true)=>({request:{bed_id,seq,sim_time:seq},accepted,result});
  const occupied={bed_status:'occupied',verdict:{status:'warning',reasons:['血氧偏低']},vitals:{spo2:93}};
  const vacant={bed_status:'vacant',verdict:{status:'vacant'}};
  const samples={newer:sample('S2',2,vacant),older:sample('S1',1,occupied),pending:sample('S2',3,occupied,false)};
  refreshCanvasTooltip(bedVitalsOnFloor(level,latestVitals(samples)));
  assert.equal(modelTitle.textContent,'01 床');
  assert.equal(modelSize.textContent,'空床位 · 巡检于仿真 2.0 秒');
  assert.equal(modelGuide.textContent,'');
  refreshCanvasTooltip(bedVitalsOnFloor(level,latestVitals({older:samples.older})));
  assert.equal(modelSize.textContent,'已有入住 · 预警 · 巡检于仿真 1.0 秒');
  assert.equal(modelGuide.textContent,'血氧 93%');
  assert.equal(modelControls.textContent,'血氧偏低');
`,tooltipContext);
const elevatorContext=vm.createContext({assert});
vm.runInContext(furnishingSource.slice(furnishingSource.indexOf('function drawElevatorEntrances('),
  furnishingSource.indexOf('function wallElevatorAt(')),elevatorContext);
vm.runInContext(`
  const elevatorAccent='#a96a3a', selected=null, painted=[];
  const ctx={save(){},restore(){this.shadowBlur=0;}};
  const corners3=(object,height)=>[object.id,height];
  const polygon=([id,height],color)=>painted.push({id,height,glowing:!!ctx.shadowBlur,color});
  const objectHeight=wall=>wall.z;
  const $=()=>({value:'0'});
  let replay=null, matching=true;
  const matchesCurrentMapRun=()=>matching;
  const state={elevators:[{id:'E1',floor_id:'F1'},{id:'E2',floor_id:'F2'}]};
  const first={id:'F1',objects:[{id:'wall',kind:'wall',z:1.5},
    {id:'east-first',kind:'elevator',lift_id:'E1',wall_id:'wall',height:.2}]};
  const second={id:'F2',objects:[{id:'east-second',kind:'elevator',lift_id:'E1'},
    {id:'west-second',kind:'elevator',shaft_id:' E2 '}]};
  const highlighted=()=>painted.splice(0).filter(entry=>entry.glowing).map(entry=>entry.id);

  drawElevatorEntrances(first,true);
  assert.equal(painted[0].height,1.5);
  assert.notEqual(painted[0].color,elevatorAccent);
  drawElevatorEntrances(second,true);
  assert.deepEqual(highlighted(),['east-first','west-second']);

  state.elevators[0]= {id:'E1',floor_id:null,destination_floor_id:'F2'};
  drawElevatorEntrances(first,false);
  drawElevatorEntrances(second,false);
  assert.deepEqual(highlighted(),['west-second']);

  state.elevators[0].floor_id='F2';
  drawElevatorEntrances(first,false);
  drawElevatorEntrances(second,false);
  assert.deepEqual(highlighted(),['east-second','west-second']);

  matching=false;
  drawElevatorEntrances(second,false);
  assert.deepEqual(highlighted(),[]);
  replay={snapshots:[{elevators:[{id:'E1',floor_id:'F1'}]}]};
  drawElevatorEntrances(first,true);
  drawElevatorEntrances(second,true);
  assert.deepEqual(highlighted(),['east-first']);
`,elevatorContext);
process.stdout.write('Workbench readiness, mode guards, bed inspections, and elevator highlights passed.');
