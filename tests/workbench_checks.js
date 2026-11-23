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
process.stdout.write('Workbench readiness and mode guards passed.');
