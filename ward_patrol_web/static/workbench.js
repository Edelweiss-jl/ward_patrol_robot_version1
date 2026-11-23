'use strict';

const workspaceViews={
  map:{title:'地图建模',step:'步骤 01 / 04',description:'编辑楼层与病区布局，统一设置电梯的停靠关系。'},
  fleet:{title:'车队配置',step:'步骤 02 / 04',description:'配置车型，为每台机器人安排所属楼层和停车点。'},
  tasks:{title:'任务调度',step:'步骤 03 / 04',description:'选择巡查床位，保存任务后统一发布，由系统分配机器人与路线。'},
  monitor:{title:'运行监控',step:'步骤 04 / 04',description:'查看机器人位置、执行路线和楼层驻留，必要时暂停或调整运行。'},
  archive:{title:'归档管理',step:'',description:'管理已归档地图，查询已归档的巡查任务。'},
  replay:{title:'历史回放',step:'运行记录',description:'选择一次历史运行，按时间轴查看当时的任务和机器人状态。'}
};
let workspaceView='map',workspaceInitialized=false,workspaceSwitching=false,workspaceRunStamp='';
let workspaceFleetSaved=null,workspaceRenderStamp='';
let workspaceReplaySeen=null;
let workspaceConnected=null;
const archiveSections = {
  maps: {panel:'mapManager', refresh:()=>archivedMapManager.refresh()},
  tasks: {panel:'archivedTasks', refresh:()=>refreshArchivedTasks()}
};
let archiveCategory='maps', archivedTasks=[], archivedTasksLoading=false;
const workspaceGuideSteps=[
  ['map','准备地图','选择已有版本，或从模板、空白地图开始。设置楼层、床位、服务点、停车点和电梯后，保存新版本。'],
  ['fleet','配置车队','选择车型，为车辆分配独立停车点，保存车队配置。先做车型通行预览，再准备巡查。'],
  ['tasks','保存并发布任务','创建任务，按床位、病房或楼层选择巡检范围。保存后打开任务队列，勾选任务并点击发布。'],
  ['monitor','查看执行过程','下发任务后自动分配车辆和路线。在这里查看执行进度、楼层覆盖、电梯状态及事件记录。']
];
function workspaceAllowsEditing() { return !workspaceInitialized||(workspaceView==='map'&&!$('mapBatchManager').open); }
function workspaceAllowsPerceptionView() { return !workspaceInitialized||['monitor','replay'].includes(workspaceView); }
function workspaceSetConnection(connected) {workspaceConnected=connected;renderWorkbench();}
function workspaceStorage(key,value) {
  try {if(value===undefined)return localStorage.getItem(key);localStorage.setItem(key,value);} catch (_) {return null;}
}
function workspaceFleetStamp(config) { return JSON.stringify([config.models,config.instances]); }
function workspaceEventCsv(events) {
  const keys=[...new Set(events.flatMap(event=>Object.keys(event)))];
  if(!keys.length)keys.push('event_id','step','event');
  const quote=value=>'"'+String(value??'').replaceAll('"','""')+'"';
  const rows=[keys,...events.map(event=>keys.map(key=>typeof event[key]==='object'?JSON.stringify(event[key]):event[key]))];
  return '\ufeff'+rows.map(row=>row.map(quote).join(',')).join('\r\n');
}
function workspaceFacts(map,config,snapshot,records=[],geometry=null) {
  const models=new Set(config.models.map(model=>model.id));
  const enabled=config.instances.filter(vehicle=>vehicle.enabled!==false);
  const occupied=new Set();
  const invalidIds=[];
  for(const vehicle of enabled) {
    const level=map.floors.find(item=>item.id===vehicle.floor_id);
    const key=vehicle.floor_id+':'+vehicle.parking_id;
    if(!models.has(vehicle.model_id)||!level?.objects.some(item=>item.kind==='parking'&&item.id===vehicle.parking_id)||occupied.has(key)) invalidIds.push(vehicle.id);
    occupied.add(key);
  }
  const matches=!!map.version&&!!snapshot&&snapshot.map_id===map.id&&snapshot.map_version===map.version;
  const ended=matches&&!!snapshot.ended;
  const current=matches&&!ended;
  const visits=current?snapshot.tasks||[]:[];
  return {saved:!!map.version,ended,floors:map.floors.length,vehicles:enabled.length,invalid:invalidIds.length,invalidIds,
    fleetReady:enabled.length>0&&!invalidIds.length,current,geometry,
    records:records.filter(record=>!record.archived).length,
    completed:visits.filter(task=>task.status==='completed').length,
    waiting:visits.filter(task=>['pending','queued','blocked'].includes(task.status)).length,
    active:visits.filter(task=>task.status==='assigned').length,
    total:visits.length,started:current&&!!snapshot.started,paused:current&&!!snapshot.paused};
}
function workspaceSuggestion(facts) {
  if(!facts.saved||facts.geometry===false)return 'map';
  if(!facts.fleetReady)return 'fleet';
  if(!facts.current||!facts.total)return 'tasks';
  return 'monitor';
}
function workspaceElement(tag,className,text) {
  const element=document.createElement(tag);if(className)element.className=className;
  if(text!==undefined)element.textContent=text;return element;
}
function workspaceScope(element,views) {
  element.dataset.workspace=views;return element;
}
function showArchiveCategory(category) {
  archiveCategory = category;
  for (const [name, section] of Object.entries(archiveSections)) $(section.panel).hidden = name!==category;
  for (const button of document.querySelectorAll('[data-archive-category]')) {
    button.setAttribute('aria-pressed',String(button.dataset.archiveCategory===category));
  }
  return archiveSections[category].refresh();
}

async function openArchivedTaskRun(runId) {
  if (!documentMap) throw Error('地图工作区仍在加载，请稍后重试。');
  await switchWorkspace('replay');
  if (workspaceView!=='replay') return;
  const runs = $('runs');
  if (![...runs.options].some(option=>option.value===runId)) await $('refreshRuns').onclick();
  if (workspaceView!=='replay') return;
  if (![...runs.options].some(option=>option.value===runId)) throw Error('这项任务关联的运行暂无可用回放。');
  runs.value = runId;
  await $('loadReplay').onclick();
}

function renderArchivedTasks() {
  const query = $('archivedTaskSearch').value.trim().toLowerCase();
  const matches = archivedTasks.filter(task=>[task.number, task.id, task.map_id, ...task.beds]
    .join(' ').toLowerCase().includes(query));
  const rows = matches.map(task=>{
    const row = document.createElement('tr');
    row.insertCell().append(workspaceElement('strong','',task.number),workspaceElement('div','muted',task.map_id));
    row.insertCell().textContent = task.beds.join('、') || '—';
    row.insertCell().textContent = formatTaskCreation(task.archived_at) || '—';
    const playback = row.insertCell();
    if (task.run_id) {
      const button = workspaceElement('button','','查看回放');
      button.type = 'button';
      button.onclick = ()=>openArchivedTaskRun(task.run_id).catch(error=>notice(error.message));
      playback.append(button);
    } else playback.textContent = '—';
    return row;
  });
  $('archivedTaskRows').replaceChildren(...rows);
  $('archivedTaskStatus').textContent = matches.length ? '共 '+matches.length+' 项已归档任务。' :
    query ? '没有匹配的归档任务。' : '暂无已归档任务。';
}

async function refreshArchivedTasks() {
  if (archivedTasksLoading) return;
  archivedTasksLoading = true;
  $('archivedTaskStatus').textContent = '正在读取已归档任务…';
  $('archivedTaskSearch').disabled = true;
  try {
    archivedTasks = await api('/api/archives/tasks');
    renderArchivedTasks();
  } catch (error) {
    $('archivedTaskStatus').textContent = '读取失败。'+error.message;
  } finally {
    archivedTasksLoading = false;
    $('archivedTaskSearch').disabled = false;
  }
}

function arrangeWorkspace() {
  const fileActions=workspaceElement('details');fileActions.id='mapFileActions';
  fileActions.append(workspaceElement('summary','','版本与导入导出'));
  const files=workspaceElement('div','bar');files.append($('renameMap'),$('exportMap'),$('importMap').closest('label'));
  fileActions.append(files,$('mapNameForm'));$('mapToolsPanel').append(fileActions);
  const newMapButtons=workspaceElement('div','bar');newMapButtons.append($('blank'));$('structureTools').before(newMapButtons);
  const widthRow=$('floorWidth').closest('.bar'),fineRow=$('tool').closest('.bar');
  $('mapAdvancedSlot').append(widthRow,fineRow);
  const structure=$('drawFloor').closest('.build-tools');
  $('cameraControls').append(viewButton);
  $('mapDocumentBar').after($('floorArea'));
  $('structureTools').append(structure);
  const catalog=$('catalog'),catalogHint=catalog.nextElementSibling;
  $('catalogSlot').append(catalog,catalogHint);
  const background=$('background').closest('div');
  const backgroundDetails=workspaceElement('details');backgroundDetails.append(workspaceElement('summary','','底图与比例标定'),background);
  $('mapAdvancedSlot').append(backgroundDetails);
  for(const id of ['templateMapControls','openMapManager','renameMap','blank','saveMap','exportMap','mapNameForm','addFloor','copyFloor','renameFloor','deleteFloor','floorNameForm','wallStatus'])
    workspaceScope($(id),'map');
  workspaceScope($('importMap').closest('label'),'map');
  for(const id of ['mapToolsPanel','liftPanel','inspectorPanel'])workspaceScope($(id),'map');
  for(const id of ['modelsPanel','fleetPanel'])workspaceScope($(id),'fleet');
  workspaceScope($('tasksPanel'),'tasks replay');
  workspaceScope($('newTask'),'tasks');workspaceScope($('taskEditor'),'tasks');
  workspaceScope($('replayPanel'),'replay');
  $('workspaceAside').prepend($('replayPanel'));
  const runtimeActions=$('runtimeActions');$('mapDocumentBar').after(runtimeActions);
  runtimeActions.after(workspaceScope($('runtime'),'tasks monitor replay'));
  workspaceScope($('runtimePanel'),'monitor replay');$('runtimePanel').querySelector('h2').textContent='楼层覆盖与事件';
  workspaceScope($('runtimeActions'),'tasks monitor');
  for(const id of ['pause','resume','endRun'])workspaceScope($(id),'monitor');
  workspaceScope($('speed').closest('label'),'monitor');
  workspaceScope($('eventDetails'),'monitor replay');
  workspaceScope($('start'),'tasks');
  // A single set of controls is moved, preserving all event handlers and drafts.
  const preparation=workspaceScope(workspaceElement('section'),'fleet');preparation.id='fleetPreparation';
  preparation.append(workspaceElement('h2','','通行检查与巡查准备'));
  const checks=workspaceElement('ul','readiness-list');checks.id='fleetReadiness';preparation.append(checks);
  const buttons=workspaceElement('div','bar');
  const prepare=workspaceElement('button','primary','准备当前地图');prepare.type='button';prepare.id='fleetPrepare';
  prepare.onclick=()=>prepareWorkspaceRun();buttons.append($('preview'),prepare);
  preparation.append(buttons,$('previewResult'));$('workspaceAside').append(preparation);
  const policy=workspaceScope(workspaceElement('section'),'tasks monitor');
  const details=workspaceElement('details');details.append(workspaceElement('summary','','调度偏好（可选）'),$('dispatchPolicyPanel'));policy.append(details);$('workspaceAside').append(policy);
  const diagnostics=workspaceScope(workspaceElement('section','workspace-diagnostics'),'monitor replay');
  diagnostics.id='workspaceDiagnostics';
  const statusDetails=workspaceElement('details');statusDetails.open=true;
  statusDetails.append(workspaceElement('summary','','电梯与通道状态'));
  for(const [panelId,controlsId] of [['elevatorMonitor','elevatorControls'],['passageMonitor','passageControls']]) {
    const panel=$(panelId),controls=$(controlsId),debug=workspaceElement('details');
    workspaceScope(debug,'monitor');debug.append(workspaceElement('summary','','仿真测试工具'),controls);panel.append(debug);statusDetails.append(panel);
  }
  diagnostics.append(statusDetails);
  const perceptionDetails=workspaceElement('details');perceptionDetails.append(workspaceElement('summary','','测距、障碍与仿真测试'),$('perceptionMonitor'));diagnostics.append(perceptionDetails);$('workspaceAside').append(diagnostics);
  const robots=workspaceScope(workspaceElement('section'),'monitor');robots.id='workspaceRobots';
  robots.append(workspaceElement('h2','','车辆状态'),workspaceElement('div'));robots.lastChild.id='workspaceRobotRows';
  $('workspaceAside').prepend(robots);
  const overview=workspaceScope(workspaceElement('div','run-overview'),'tasks monitor replay');overview.id='workspaceRunOverview';
  for(const [id,label] of [['wbWaiting','等待分配的床位'],['wbActive','正在执行的床位'],['wbCompleted','已完成的床位']]) {
    const cell=workspaceElement('div');cell.append(workspaceElement('span','',label));const count=workspaceElement('strong','','0');count.id=id;cell.append(count);overview.append(cell);
  }
  $('canvasColumn').prepend(overview);
  const replayEmpty=workspaceScope(workspaceElement('section','replay-empty'),'replay');replayEmpty.id='replayEmpty';
  replayEmpty.append(workspaceElement('span','empty-illustration','↶'),workspaceElement('h2','','选择一次巡查，回看执行过程'),workspaceElement('p','muted','在右侧选择历史运行并加载，可查看对应地图、床位任务和车辆轨迹。'));
  $('canvasColumn').prepend(replayEmpty);
  const hint=workspaceElement('p');hint.id='canvasModeHint';$('mapCanvasPanel').append(hint);
  $('eventDetails').querySelector('a').onclick=event=>{
    if(!replay)return;
    event.preventDefault();
    const url=URL.createObjectURL(new Blob([workspaceEventCsv(replay.events||[])],{type:'text/csv;charset=utf-8'}));
    const download=document.createElement('a');download.href=url;download.download='replay-events.csv';document.body.append(download);download.click();download.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  for(const [index,[view,title,text]] of workspaceGuideSteps.entries()) {
    const row=workspaceElement('li');row.append(workspaceElement('span','guide-index',String(index+1)));
    const content=workspaceElement('div');content.append(workspaceElement('strong','',title),workspaceElement('p','',text));
    const link=workspaceElement('button','','前往'+workspaceViews[view].title+' →');link.type='button';
    link.onclick=()=>{$('workbenchGuide').close();switchWorkspace(view);};content.append(link);row.append(content);$('guideSteps').append(row);
  }
}
function applyWorkspaceScopes() {
  for(const element of document.querySelectorAll('[data-workspace]'))
    element.classList.toggle('workspace-hidden',!element.dataset.workspace.split(' ').includes(workspaceView));
}
async function switchWorkspace(view,{hash=true,focus=true}={}) {
  if(!workspaceViews[view]||workspaceSwitching)return;
  if(dragging||buildingGesture||catalogDrag||cameraDrag){notice('请先完成当前拖动，再切换分区。');return;}
  workspaceSwitching=true;
  try {
    if(view!=='map'&&$('mapBatchManager').open)$('mapBatchManager').close();
    if(view!=='fleet'&&$('instanceEditor').open)closeVehicleEditor();
    if(view!=='replay')cancelReplayLoad();
    if(replay&&view!=='replay')await $('exitReplay').onclick();
    if(taskPicking&&view!=='tasks')setTaskPicking(false);
    if(view!=='tasks'&&$('taskFloorPicker').open)$('taskFloorPicker').close();
    pickingObstaclePosition=false;$('pickObstaclePosition').setAttribute('aria-pressed','false');
    calibration=null;groupSelection.clear();hideModelTooltip();setBuildMode('select');
    workspaceView=view;document.body.dataset.workspaceView=view;
    workspaceStorage('ward-workspace-view',view);
    if(hash&&location.hash!=='#'+view)window.history.pushState(null,'','#'+view);
    for(const button of document.querySelectorAll('[data-view]')) {
      if(button.dataset.view===view)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
    }
    const info=workspaceViews[view];$('workspaceTitle').textContent=info.title;$('workspaceEyebrow').textContent=info.step;
    $('workspaceDescription').textContent=info.description;document.title=info.title+' · 病区巡查工作台';
    applyWorkspaceScopes();workspaceRenderStamp='';renderWorkbench();
    if(view==='archive') {
      $('workspaceNext').textContent='刷新归档列表';$('workspaceNext').disabled=false;
      showArchiveCategory(archiveCategory);
    }
    if(view==='fleet'){setFleetQueueOpen(true);renderFleetQueue();}
    if(view==='replay'&&!$('runs').options.length)await $('refreshRuns').onclick();
    if(view==='tasks'&&$('taskEditor').hidden) {showTaskPanel('savedTaskQueue',true);if(documentMap&&configuration)renderTaskQueues(viewingCurrentRun());}
    if(view==='replay'&&replay){showTaskPanel('savedTaskQueue',true);renderTaskQueues(true);}
    updateViewportHelp();
    if(documentMap&&configuration)draw();
    if(focus){$('workspaceTitle').focus({preventScroll:true});$('workspaceTitle').scrollIntoView({block:'start'});}
  } catch(error){notice(error.message);}
  finally{workspaceSwitching=false;}
}
function prepareWorkspaceRun() {
  if(replay)return;
  return Promise.resolve($('start').onclick()).then(()=>renderWorkbench()).catch(error=>notice(error.message));
}
async function workspaceNextAction() {
  if(workspaceView==='archive')return archiveSections[archiveCategory].refresh();
  if(!documentMap||!configuration)return;
  const facts=workspaceFacts(documentMap,configuration,state,taskRecords,checkedGeometry?.map===documentMap?checkedGeometry.valid:null);
  const available=isAvailableMapVersion(documentMap);
  if (!available && !facts.current && ['fleet','tasks','monitor'].includes(workspaceView)) return switchWorkspace('map');
  if(workspaceView==='map') {
    if(facts.geometry===false){notice('请先修正地图检查提示的问题，再继续配置车队。');return;}
    if(!available)await $('saveMap').onclick();
    if(isAvailableMapVersion(documentMap))await switchWorkspace('fleet');
  } else if(workspaceView==='fleet') {
    if(!facts.saved)return switchWorkspace('map');
    if(!facts.fleetReady){if(facts.invalidIds.length){setFleetQueueOpen(true);renderFleetQueue();openVehicle(facts.invalidIds[0]);}else if(!$('instanceEditor').open)$('newInstance').click();return;}
    if(workspaceFleetSaved!==workspaceFleetStamp(configuration)) {
      await api('/api/editor/config',configuration);workspaceFleetSaved=workspaceFleetStamp(configuration);
      notice('车队配置已保存。先准备巡查，再发布任务。');
    }
    await switchWorkspace('tasks');
  } else if(workspaceView==='tasks') {
    if(!facts.saved)return switchWorkspace('map');
    if(!facts.fleetReady)return switchWorkspace('fleet');
    if(!facts.current)return prepareWorkspaceRun();
    if($('taskEditor').hidden)await $('newTask').onclick();else $('taskBedNumber').focus();
  } else if(workspaceView==='monitor') {
    if(!facts.current)return facts.saved&&facts.fleetReady?prepareWorkspaceRun():switchWorkspace(workspaceSuggestion(facts));
    await switchWorkspace('tasks');openTaskPanel('savedTaskQueue');renderTaskQueues(true);
  } else {await $('refreshRuns').onclick();notice('历史运行记录已刷新，选择记录后点击加载回放。');}
}
function renderWorkbench() {
  if(!workspaceInitialized||!documentMap||!configuration)return;
  if(workspaceFleetSaved===null)workspaceFleetSaved=workspaceFleetStamp(configuration);
  const facts=workspaceFacts(documentMap,configuration,state,taskRecords,checkedGeometry?.map===documentMap?checkedGeometry.valid:null);
  const available=isAvailableMapVersion(documentMap);
  const needsMap=!available&&!facts.current;
  const inReplay=!!replay;
  $('eventDetails').querySelector('a').textContent=inReplay?'下载本次回放全部事件 CSV':'下载当前运行事件 CSV';
  if(inReplay&&workspaceReplaySeen!==replay) {
    workspaceReplaySeen=replay;showTaskPanel('savedTaskQueue',true);renderTaskQueues(true);
  }
  for(const id of ['mapCanvasPanel','tasksPanel','runtimePanel','workspaceRunOverview','workspaceDiagnostics'])
    $(id).classList.toggle('replay-awaiting',workspaceView==='replay'&&!inReplay);
  $('replayEmpty').classList.toggle('replay-awaiting',inReplay);
  $('replaySlider').disabled=!inReplay||!replay.snapshots.length;$('exitReplay').disabled=!inReplay;
  $('loadReplay').disabled=replayLoading||!$('runs').options.length;
  $('loadReplay').textContent=replayLoading?'正在加载…':'加载回放';
  const connected=workspaceConnected!==false&&!!state?.robots&&!state?.error;
  $('workspaceConnectionDot').dataset.connected=String(connected);
  const connection=state?.error?'服务异常':connected?'本地服务已连接':workspaceConnected===false?'连接中断，正在重连':'正在连接服务';
  if($('workspaceConnection').textContent!==connection)$('workspaceConnection').textContent=connection;
  const tasks=inReplay?state?.tasks||[]:facts.current?state.tasks||[]:[];
  const counts=[tasks.filter(t=>['pending','queued','blocked'].includes(t.status)).length,tasks.filter(t=>t.status==='assigned').length,tasks.filter(t=>t.status==='completed').length];
  for(const [i,id] of ['wbWaiting','wbActive','wbCompleted'].entries())if($(id).textContent!==String(counts[i]))$(id).textContent=String(counts[i]);
  const texts={
    map:available?'下一步：配置车队 →':'保存地图并配置车队 →',
    fleet:needsMap?'先保存地图 →':!facts.fleetReady?(facts.invalid?'调整车辆与停车点':'配置车辆与停车点'):workspaceFleetSaved!==workspaceFleetStamp(configuration)?'保存车队并进入任务 →':'下一步：任务调度 →',
    tasks:needsMap?'先保存地图 →':!facts.fleetReady?'先配置车队 →':!facts.current?'准备当前地图':'创建巡查任务',
    monitor:facts.current?'前往任务队列 →':needsMap?'先保存地图 →':'准备当前地图',replay:'刷新历史记录',archive:'刷新归档列表'};
  const changingRun=!!pendingRun||!!pendingEndRun;
  $('workspaceNext').textContent=texts[workspaceView];$('workspaceNext').disabled=workspaceView!=='archive'&&changingRun;
  $('notice').classList.toggle('workspace-hidden',workspaceView!=='map'&&$('notice').textContent==='选择已有版本或从空白地图开始。保存地图后配置车辆并预览。');
  $('fleetPrepare').disabled=!!replay||!available||!facts.fleetReady||changingRun;
  $('start').disabled=!!replay||!available||!facts.fleetReady||changingRun;
  $('start').hidden=facts.current&&editedFleetRunId!==state?.run_id;
  const progress=[['map','地图',available?'已保存 · '+facts.floors+' 层':facts.saved?'版本已移出列表':'草稿待保存',available],
    ['fleet','车队',facts.invalid?facts.invalid+' 台需调整':facts.vehicles+' 台已配置',facts.fleetReady],
    ['tasks','任务',facts.records+' 项在队列',facts.records>0],
    ['monitor','巡查',inReplay?'正在回放':facts.ended?'已结束':facts.started?(facts.paused?'已暂停':'执行中'):facts.current?'已准备':'待准备',facts.current]];
  const stamp=JSON.stringify([progress,facts.saved,facts.fleetReady,facts.invalid,facts.geometry,workspaceView,inReplay]);
  if(stamp!==workspaceRenderStamp) {
    $('workflowProgress').replaceChildren();
    for(const [view,label,status,complete] of progress) {
      const button=workspaceElement('button');button.type='button';button.dataset.complete=String(complete);
      button.append(workspaceElement('span','step-dot'),workspaceElement('strong','',label),workspaceElement('small','',status));
      button.onclick=()=>switchWorkspace(view);$('workflowProgress').append(button);
    }
    $('fleetReadiness').replaceChildren();
    for(const [complete,label] of [[facts.saved,'地图已保存为版本'],[facts.fleetReady,facts.invalid?facts.invalid+' 台车辆的车型或停车点需要调整':'已配置车辆和独立停车点'],[facts.geometry===true,'地图几何检查通过']]) {
      const item=workspaceElement('li','',(complete?'✓ ':'○ ')+label);item.dataset.complete=String(complete);$('fleetReadiness').append(item);
    }
    $('canvasModeHint').textContent=workspaceView==='map'?'编辑模式 · 在右侧选择工具，点选物件查看属性。':workspaceView==='tasks'?'任务模式 · 点击「创建任务」后，可按床位、病房或楼层选择巡检范围。':workspaceView==='fleet'?'车队模式 · 地图仅供查看，车辆位置由所属楼层和停车点决定。':inReplay?'历史回放 · 地图与车辆为该次运行的记录。':'运行模式 · 浏览路线和车辆状态，编辑布局请切换「地图建模」。';
    workspaceRenderStamp=stamp;
  }
  const robots=(facts.current||inReplay)?state?.robots||[]:[];
  const robotStamp=JSON.stringify([documentMap.floors.map(level=>[level.id,level.name]),robots.map(robot=>[robot.id,robot.floor_id,robot.status,robot.battery_percent])]);
  if(robotStamp!==workspaceRunStamp) {
    const rows=$('workspaceRobotRows');rows.replaceChildren();
    const statuses={idle:'空闲',moving:'行驶中',servicing:'服务中',waiting:'等待',blocked:'受阻',assigned:'执行中',completed:'已完成'};
    for(const robot of robots) {
      const row=workspaceElement('div','robot-state'),left=workspaceElement('div','',robot.id);
      left.append(workspaceElement('small','',documentMap.floors.find(level=>level.id===robot.floor_id)?.name||'跨层运行'));
      row.append(left,workspaceElement('span','',(statuses[robot.status]||robot.status||'—')+' · '+(robot.battery_percent??'—')+'%'));rows.append(row);
    }
    if(!robots.length)rows.append(workspaceElement('p','muted','准备当前地图的巡查后，在这里查看车辆状态。'));
    workspaceRunStamp=robotStamp;
  }
}
function initializeWorkspace() {
  arrangeWorkspace();workspaceInitialized=true;
  const previousRender=renderState;renderState=function(){previousRender();renderWorkbench();};
  const previousConfig=configOptions;configOptions=function(...args){previousConfig(...args);renderWorkbench();};
  const previousDirty=dirty;dirty=function(){previousDirty();renderWorkbench();};
  $('workspaceNext').onclick=()=>workspaceNextAction().catch(error=>notice(error.message));
  for(const button of document.querySelectorAll('[data-view]'))button.onclick=()=>switchWorkspace(button.dataset.view);
  for(const button of document.querySelectorAll('[data-archive-category]'))button.onclick=()=>showArchiveCategory(button.dataset.archiveCategory);
  $('archivedTaskSearch').oninput=renderArchivedTasks;
  $('openMapManager').onclick=()=>{
    $('openMapManager').focus();
    $('mapBatchManager').showModal();
    return savedMapManager.refresh({resetSearch:true});
  };
  $('closeMapManager').onclick=()=>$('mapBatchManager').close();
  const showGuide=()=>{$('workbenchGuide').showModal();};
  $('openGuide').onclick=showGuide;$('welcomeGuide').onclick=showGuide;
  $('closeGuide').onclick=()=>$('workbenchGuide').close();
  $('guideContinue').onclick=()=>{
    $('workbenchGuide').close();if(documentMap&&configuration)switchWorkspace(workspaceSuggestion(workspaceFacts(documentMap,configuration,state,taskRecords,checkedGeometry?.valid)));
  };
  $('welcomeBanner').hidden=workspaceStorage('ward-workspace-welcome-v1')==='dismissed';
  $('dismissWelcome').onclick=()=>{$('welcomeBanner').hidden=true;workspaceStorage('ward-workspace-welcome-v1','dismissed');};
  action('saveConfig',async()=>{await api('/api/editor/config',configuration);workspaceFleetSaved=workspaceFleetStamp(configuration);notice('车队配置已保存，可以进行通行预览并准备巡查。');renderWorkbench();});
  action('refreshRuns',async()=>{
    const chosen=$('runs').value,all=await api('/api/runs/summary');
    const entries=all.filter(record=>record.has_snapshots||$('replayIncludeEmpty').checked);
    options('runs',entries.map(record=>[record.id,record.name+' v'+record.version+' · '+new Date(record.created_at*1000).toLocaleString('zh-CN',{hour12:false})+(record.has_snapshots?'':' · 未开始')]),chosen);
    if(!$('runs').value&&entries.length)$('runs').selectedIndex=0;
    $('replayRecordsStatus').textContent=entries.length?'共 '+entries.length+' 条记录，选择后加载。':'暂无可回放的运行。巡查开始并生成记录后，会显示在这里。';
    renderWorkbench();
  });
  $('replayIncludeEmpty').onchange=()=>$('refreshRuns').click();
  window.addEventListener('hashchange',()=>switchWorkspace(location.hash.slice(1),{hash:false}));
  const requested=location.hash.slice(1)||workspaceStorage('ward-workspace-view');
  switchWorkspace(workspaceViews[requested]?requested:'map',{hash:false,focus:false});
}
initializeWorkspace();
