'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../ward_patrol_web/static/editor.js'),'utf8');
const controls={runs:{value:'run'},taskNotes:{value:'unsaved note'},taskEditor:{hidden:false},savedTaskQueue:{hidden:true},
  inspector:{querySelectorAll:()=>[]},replaySlider:{value:0,max:0}};
const pending=[],handlers={};
const context=vm.createContext({console,encodeURIComponent,documentMap:{id:'live',version:14,floors:[{id:'F1'}]},
  replayRequest:0,replayLoading:false,replay:null,runningMap:null,replayDraft:null,selected:'bed1',
  taskBeds:new Set(['service1']),taskMapId:'live',taskRequestId:'request1',
  $:id=>controls[id],floor:()=>({id:'F1'}),clone:value=>JSON.parse(JSON.stringify(value)),
  action:(id,callback)=>{handlers[id]=callback;},api:()=>new Promise(resolve=>pending.push(resolve)),
  refresh:()=>{},compile:async()=>{},renderWorkbench:()=>{},showReplay:()=>{},refreshTaskBeds:()=>{},
  showTaskPanel:(id,show)=>{controls[id].hidden=!show;}});
vm.runInContext(source.slice(source.indexOf('function cancelReplayLoad()'),source.indexOf('function showReplay()')),context);
vm.runInContext(source.slice(source.indexOf("action('exitReplay'"),source.indexOf('async function initialize()')),context);
const archive=version=>({map:{id:'archive',version,floors:[{id:'old'}]},snapshots:[]});
(async()=>{
  const late=handlers.loadReplay();assert.strictEqual(context.replayLoading,true);
  context.cancelReplayLoad();pending.shift()(archive(1));await late;
  assert.strictEqual(context.documentMap.version,14);assert.strictEqual(context.replay,null);
  const first=handlers.loadReplay(),newest=handlers.loadReplay();
  const oldResolve=pending.shift(),newResolve=pending.shift();
  newResolve(archive(7));await newest;oldResolve(archive(3));await first;
  assert.strictEqual(context.documentMap.version,7);assert.strictEqual(context.runningMap.version,14);
  const another=handlers.loadReplay();pending.shift()(archive(6));await another;
  assert.strictEqual(context.runningMap.version,14);
  controls.taskNotes.value='';context.taskBeds.clear();
  await handlers.exitReplay();
  assert.strictEqual(context.documentMap.version,14);
  assert.strictEqual(controls.taskNotes.value,'unsaved note');
  assert(context.taskBeds.has('service1'));assert.strictEqual(context.selected,'bed1');
  assert.strictEqual(controls.taskEditor.hidden,false);
  process.stdout.write('Replay cancellation, original map, and task draft checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
