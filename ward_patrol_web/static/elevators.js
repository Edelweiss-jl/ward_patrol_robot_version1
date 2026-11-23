'use strict';
// The catalog owns stops; floor objects only own placement and local references.
let managedLiftId = null, pendingLiftPlacement = '', liftReports = null, liftRequestPending = false;
const liftPlacementSignatures = new Map();
function nextLiftName(map) {
  const names=new Set((map.elevators||[]).map(lift=>lift.name.toLowerCase()));
  let number=1;while(names.has('e'+number)) number++;
  return 'E'+number;
}
function normalizeElevatorMap(map) {
  map.schema=Math.max(3,map.schema||2);map.elevators ||= [];
  const groups=new Map(),floorIds=new Set(map.floors.map(level=>level.id));
  for(const level of map.floors) for(const object of level.objects) {
    if(object.kind!=='elevator'||object.lift_id) continue;
    const key=object.shaft_id?.trim()||object.id;
    if(!groups.has(key)) groups.set(key,[]);
    groups.get(key).push([level.id,object]);
  }
  // Reserve explicitly named legacy lifts before assigning names to unlinked ones.
  const names=new Set(map.elevators.map(lift=>lift.name.toLowerCase()));
  for(const [key,items] of groups) if(items[0][1].shaft_id?.trim()) names.add(key.toLowerCase());
  for(const [key,items] of groups) {
    if(map.elevators.some(lift=>lift.id===key)) throw Error('旧电梯编号与现有电梯冲突，请重新关联入口');
    if(new Set(items.map(([fid])=>fid)).size!==items.length) throw Error('同一电梯在一层存在多个入口');
    let number=1;while(names.has('e'+number)) number++;
    const name=items[0][1].shaft_id?.trim()?key:'E'+number;names.add(name.toLowerCase());
    const lift={id:key,name,served_floors:[],default_width:items[0][1].width,landings:{}};
    if(!(lift.default_width>=.4&&lift.default_width<=5)) lift.default_width=1.8;
    const connections={};
    for(const [fid,object] of items) {
      for(const id of [fid,...(object.service_floors||[])])
        if(floorIds.has(id)&&!lift.served_floors.includes(id)) lift.served_floors.push(id);
      lift.landings[fid]={entrance_id:object.id,waiting_id:object.waiting_id,exit_id:object.exit_id,confirmed:true};
      connections[fid]=items.filter(([other,target])=>other!==fid&&(object.service_floors||[]).includes(other)&&
        (target.service_floors||[]).includes(fid)).map(([other])=>other);
      object.lift_id=key;
    }
    if(items.length>1&&Object.values(connections).some(others=>others.length!==items.length-1)) {
      lift.legacy_connections=connections;
      lift.migration_warning='旧入口的停靠设置不一致，已保留原通行关系；请在统一面板确认停靠楼层。';
    }
    for(const [,object] of items) {delete object.shaft_id;delete object.service_floors;}
    map.elevators.push(lift);
  }
  return map;
}
function ensureElevatorCatalog() {
  normalizeElevatorMap(documentMap);
  const floorIds=new Set(documentMap.floors.map(level=>level.id));
  for(const lift of documentMap.elevators) {
    lift.served_floors=lift.served_floors.filter(id=>floorIds.has(id));
    for(const fid of Object.keys(lift.landings)) {
      if(!lift.served_floors.includes(fid)) {delete lift.landings[fid];continue;}
      const level=documentMap.floors.find(item=>item.id===fid),landing=lift.landings[fid];
      const entry=level.objects.find(item=>item.id===landing.entrance_id);
      if(!entry) {
        if(landing.entrance_id) lift.landings[fid]={confirmed:false};
        continue;
      }
      if(entry.waiting_id!==landing.waiting_id||entry.exit_id!==landing.exit_id) landing.confirmed=false;
      landing.waiting_id=entry.waiting_id;landing.exit_id=entry.exit_id;
    }
    if(lift.legacy_connections) {
      for(const fid of Object.keys(lift.legacy_connections)) {
        if(!floorIds.has(fid)) delete lift.legacy_connections[fid];
        else lift.legacy_connections[fid]=lift.legacy_connections[fid].filter(id=>floorIds.has(id));
      }
    }
  }
  documentMap.elevators=documentMap.elevators.filter(lift=>lift.served_floors.length);
  rememberLiftPlacements(false);
}
function rememberLiftPlacements(invalidate) {
  if(!documentMap) return;
  for(const lift of documentMap.elevators||[]) for(const [fid,landing] of Object.entries(lift.landings)) {
    const level=documentMap.floors.find(item=>item.id===fid);
    const entry=level?.objects.find(item=>item.id===landing.entrance_id);
    const signature=JSON.stringify([entry,...['waiting_id','exit_id'].map(key=>
      level?.objects.find(item=>item.id===entry?.[key])),level?.objects.filter(item=>['wall','door','furniture','forbidden','one_way'].includes(item.kind))]);
    const key=documentMap.id+':'+lift.id+':'+fid;
    if(invalidate&&liftPlacementSignatures.has(key)&&liftPlacementSignatures.get(key)!==signature) landing.confirmed=false;
    liftPlacementSignatures.set(key,signature);
  }
}
function attachLiftLanding(map,fid,entryId,liftId='') {
  map.elevators ||= [];
  const level=map.floors.find(item=>item.id===fid),entry=level.objects.find(item=>item.id===entryId);
  let lift=map.elevators.find(item=>item.id===liftId);
  if(liftId&&!lift) throw Error('所选电梯不存在');
  if(lift?.landings[fid]?.entrance_id&&lift.landings[fid].entrance_id!==entryId)
    throw Error('此电梯在本层已有入口，请选择另一部电梯');
  const old=map.elevators.find(item=>item.id===entry.lift_id);
  if(old&&old.id!==lift?.id&&old.landings[fid]?.entrance_id===entryId) old.landings[fid]={confirmed:false};
  if(!lift) {
    lift={id:uid(),name:nextLiftName(map),served_floors:[fid],default_width:entry.width,landings:{}};
    map.elevators.push(lift);
  }
  if(!lift.served_floors.includes(fid)) lift.served_floors.push(fid);
  entry.lift_id=lift.id;delete entry.shaft_id;delete entry.service_floors;
  lift.landings[fid]={entrance_id:entry.id,waiting_id:entry.waiting_id,exit_id:entry.exit_id,confirmed:false};
  return lift.id;
}
function liftChoices(fid,entryId) {
  return documentMap.elevators.filter(lift=>entryId
    ? !lift.landings[fid]?.entrance_id||lift.landings[fid].entrance_id===entryId
    : lift.served_floors.includes(fid)&&!lift.landings[fid]?.entrance_id)
    .map(lift=>[lift.id,lift.name]);
}
const legacyWallMismatch = '此层没有匹配墙体，请逐层重新定位';
const recoveredWallConflict = '相应墙体上的入口位置存在几何冲突，请在该层调整';

function matchingLiftWall(level, entry) {
  return level.objects.find(wall=>{
    if(wall.kind!=='wall') return false;
    const vertical=wall.height>wall.width;
    const angle=(wall.rotation||0)+(vertical?90:0);
    const radians=angle*Math.PI/180;
    const dx=entry.x-wall.x,dy=entry.y-wall.y;
    const along=dx*Math.cos(radians)+dy*Math.sin(radians);
    const across=-dx*Math.sin(radians)+dy*Math.cos(radians);
    return Math.abs(Math.sin((angle-(entry.rotation||0))*Math.PI/180))<=.001 &&
      Math.abs(across)<=Math.min(wall.width,wall.height)/2+.01 &&
      Math.abs(along)+entry.width/2<=Math.max(wall.width,wall.height)/2+.001;
  });
}

async function recoverLegacyLiftLandings(result, liftId, sourceFloorId) {
  const missing = result.reports[liftId].filter(row=>row.status==='missing'&&row.issues.includes(legacyWallMismatch));
  if(!missing.length) return result.map;
  let map = result.map;
  const source = map.elevators.find(lift=>lift.id===liftId).landings[sourceFloorId];
  const sourceLevel = map.floors.find(level=>level.id===sourceFloorId);
  const pieces = ['entrance_id','waiting_id','exit_id'].map(key=>sourceLevel.objects.find(object=>object.id===source[key]));
  for(const row of missing) {
    const level = map.floors.find(level=>level.id===row.floor_id);
    const wall = matchingLiftWall(level,pieces[0]);
    if(!wall) continue;
    const candidate = clone(map);
    const target = candidate.floors.find(level=>level.id===row.floor_id);
    const [entry,waiting,exit] = pieces.map(piece=>({...piece,id:uid()}));
    Object.assign(entry,{wall_id:wall.id,waiting_id:waiting.id,exit_id:exit.id});
    waiting.elevator_id=exit.elevator_id=entry.id;
    target.objects.push(entry,waiting,exit);
    attachLiftLanding(candidate,target.id,entry.id,liftId);
    const validation = await api('/api/maps/validate',candidate);
    if(validation.valid) {
      map=candidate;
    } else {
      map=clone(map);
      map.elevators.find(lift=>lift.id===liftId).landings[target.id].placement_issue=recoveredWallConflict;
    }
  }
  return map;
}

async function placeLiftLanding(map, liftId, floorId, confirmSource=true) {
  const request = {map,models:configuration.models,lift_id:liftId};
  // Older servers may leave generated entrances pending and compare the rectangle's raw rotation.
  let result = await api('/api/maps/elevators',{
    ...request,action:'copy',source_floor:floorId,confirm_source:confirmSource
  });
  const recovered = await recoverLegacyLiftLandings(result,liftId,floorId);
  if (recovered!==result.map) result=await api('/api/maps/elevators',{...request,map:recovered,action:'inspect'});
  const source = result.reports[liftId].find(row=>row.floor_id===floorId);
  if (confirmSource&&['ready','proposed'].includes(source.status)) return confirmLiftStops(result,liftId,floorId);
  return result;
}
function confirmLiftStops(result,liftId,sourceFloorId) {
  const rows = result.reports[liftId];
  const source = rows.find(row=>row.floor_id===sourceFloorId);
  if (!source || !['ready','proposed'].includes(source.status)) {
    throw Error('本层入口检查未通过：'+(source?.issues.join('；')||'尚未定位'));
  }
  const floorIds = rows.filter(row=>row.status==='proposed').map(row=>row.floor_id);
  if (!floorIds.length) return result;
  return api('/api/maps/elevators',{
    map:result.map,models:configuration.models,action:'confirm',lift_id:liftId,floor_ids:floorIds
  });
}
function liftLandingNotice(rows) {
  const ready = rows.filter(row=>row.status==='ready').length;
  const invalid = rows.filter(row=>row.status==='invalid').length;
  const missing = rows.filter(row=>row.status==='missing').length;
  return ready+' 层电梯入口已确认。'+(invalid?'有 '+invalid+' 层需要调整。':'')+
    (missing?'有 '+missing+' 层需要定位入口。':'');
}
function canConfirmLiftLanding(lift,floorId) {
  const landing = lift?.landings[floorId];
  return Boolean(landing?.entrance_id)&&(!landing.confirmed||Object.entries(lift.landings).some(([id,other])=>{
    const report = liftReports?.[lift.id]?.find(row=>row.floor_id===id);
    return other.entrance_id&&!other.confirmed&&(!report||report.status==='proposed');
  }));
}
function remapTemplateLifts(draft,floorIds,objectIds) {
  const liftIds=new Map((draft.elevators||[]).map(lift=>[lift.id,uid()]));
  for(const level of draft.floors) for(const entry of level.objects)
    if(liftIds.has(entry.lift_id)) entry.lift_id=liftIds.get(entry.lift_id);
  for(const lift of draft.elevators||[]) {
    lift.id=liftIds.get(lift.id);lift.served_floors=lift.served_floors.map(id=>floorIds.get(id));
    lift.landings=Object.fromEntries(Object.entries(lift.landings).map(([fid,landing])=>[floorIds.get(fid),
      {...landing,...Object.fromEntries(['entrance_id','waiting_id','exit_id'].map(key=>[key,objectIds.get(fid).get(landing[key])]))}]));
    if(lift.legacy_connections) lift.legacy_connections=Object.fromEntries(Object.entries(lift.legacy_connections)
      .map(([fid,targets])=>[floorIds.get(fid),targets.map(id=>floorIds.get(id))]));
  }
}
function liftButton(text,callback) {
  const button=document.createElement('button');button.type='button';button.textContent=text;
  button.onclick=()=>Promise.resolve().then(callback).catch(error=>notice(error.message));
  button.disabled=!!replay||liftRequestPending;return button;
}
function openElevatorManager(id) {
  managedLiftId=id||managedLiftId;$('liftManager').open=true;renderElevatorManager();
  $('liftManager').scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function liftOperation(action,extra={}) {
  if(replay||liftRequestPending) return;
  const original=documentMap,revision=compileRevision;
  liftRequestPending=true;renderElevatorManager();
  try {
    let result=await api('/api/maps/elevators',{map:original,models:configuration.models,action,lift_id:managedLiftId,...extra});
    if(action==='update') {
      const rows = result.reports[result.lift_id];
      const source = rows.find(row=>row.status==='ready')||rows.find(row=>row.status!=='missing');
      if(source&&rows.some(row=>row.status==='missing'&&
        (!row.issues.length||row.issues.includes(legacyWallMismatch)||row.issues.includes(recoveredWallConflict)))) {
        result=await placeLiftLanding(result.map,result.lift_id,source.floor_id,false);
      }
      if(source?.status==='ready') result=await confirmLiftStops(result,result.lift_id,source.floor_id);
    }
    if(original!==documentMap||revision!==compileRevision) {notice('地图已变化，请重新检查电梯。');return;}
    if(action!=='inspect') {checkpoint();documentMap=result.map;rememberLiftPlacements(false);dirty();}
    managedLiftId=result.lift_id||managedLiftId;liftReports=result.reports;
    refresh();if(action!=='inspect') await compile();
    notice('电梯设置已更新，保存新版本后用于巡查。');
  } finally {liftRequestPending=false;renderElevatorManager();}
}
function renderElevatorManager() {
  const container=$('liftManagerBody');if(!container||!documentMap||!configuration) return;
  const catalog=documentMap.elevators||[];
  if(managedLiftId===null||(managedLiftId&&!catalog.some(lift=>lift.id===managedLiftId))) managedLiftId=catalog[0]?.id||'';
  const lift=catalog.find(item=>item.id===managedLiftId);
  container.replaceChildren();
  const select=document.createElement('select');select.id='managedLift';select.setAttribute('aria-label','整部电梯');
  select.add(new Option('新增电梯',''));
  for(const item of catalog) select.add(new Option(item.name,item.id));
  select.value=managedLiftId;select.onchange=()=>{managedLiftId=select.value;renderElevatorManager();};
  // Empty selection remains a deliberate new-lift draft.
  const bar=document.createElement('div');bar.className='bar';bar.append(select,liftButton('新增电梯',()=>renderLiftDraft()));container.append(bar);
  renderLiftFields(container,lift);
}
function renderLiftDraft() {
  managedLiftId='';$('managedLift').value='';const container=$('liftManagerBody');
  while(container.children.length>1) container.lastChild.remove();renderLiftFields(container,null);
}
function renderLiftFields(container,lift) {
  const form=document.createElement('form');form.id='liftSettings';
  const name=field(form,'电梯名称','liftName',lift?.name||nextLiftName(documentMap));name.required=true;name.maxLength=60;
  const width=field(form,'默认入口宽度（米）','liftWidth',lift?.default_width||1.8,'number');width.min=.4;width.max=5;width.step=.1;
  const capacity=field(form,'每趟最多搭载车辆数','liftCapacity',lift?.capacity??2,'number');
  capacity.required=true;capacity.min=1;capacity.step=1;
  const stops=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent='停靠楼层（整部电梯统一设置）';stops.append(legend);
  const choices=documentMap.floors.map((level,index)=>{
    const input=field(stops,level.name,'liftStop'+index,'','checkbox');
    input.checked=lift?lift.served_floors.includes(level.id):level.id===floor().id;return [level.id,input];
  });form.append(stops);
  const save=liftButton(lift?'保存电梯设置':'创建电梯',()=>{
    if(!form.reportValidity()) return;
    return liftOperation(lift?'update':'create',{
      name:name.value,default_width:Number(width.value),capacity:Number(capacity.value),
      served_floors:choices.filter(([,input])=>input.checked).map(([id])=>id)
    });
  });form.append(save);form.onsubmit=event=>{event.preventDefault();save.click();};container.append(form);
  if(!lift) {
    if(replay||liftRequestPending) for(const input of container.querySelectorAll('input,select,button')) input.disabled=true;
    return;
  }
  if(lift.migration_warning) {const warning=document.createElement('p');warning.className='lift-warning';warning.textContent=lift.migration_warning;container.append(warning);}
  const help=document.createElement('p');help.className='muted';help.textContent='在任一停靠层定位并确认一次，其余停靠层会自动生成入口并确认通过检查的入口。';container.append(help);
  const table=document.createElement('table');table.setAttribute('aria-label','电梯各层入口');
  const heading=table.createTHead().insertRow();for(const text of ['楼层','入口状态','操作']) {const th=document.createElement('th');th.textContent=text;heading.append(th);}
  const body=table.createTBody();
  for(const fid of lift.served_floors) {
    const landing=lift.landings[fid],report=liftReports?.[lift.id]?.find(row=>row.floor_id===fid),row=body.insertRow();
    row.insertCell().textContent=documentMap.floors.find(f=>f.id===fid).name;
    const cell=row.insertCell();cell.textContent=report?({missing:'待定位',invalid:'需调整',proposed:'待确认',ready:'已确认'}[report.status]):landing?.entrance_id?(landing.confirmed?'已确认':'待检查确认'):'待定位';
    const issue=report?.issues.join('；')||landing?.placement_issue;if(issue) {const detail=document.createElement('small');detail.textContent=issue;cell.append(document.createElement('br'),detail);}
    const actions=row.insertCell();actions.append(liftButton(landing?.entrance_id?'查看 / 调整':'定位入口',()=>{
      selected=landing?.entrance_id||null;pendingLiftPlacement=selected?'':lift.id;
      if(typeof setBuildMode==='function') setBuildMode('select');refresh(fid);
      if(!selected) {$('tool').value='elevator';notice('为「'+lift.name+'」在本层墙体上放置入口，候梯点和出梯区域会自动生成。');}
      draw();canvas.scrollIntoView({behavior:'smooth',block:'center'});
      if(selected&&canConfirmLiftLanding(lift,fid)) showLiftLandingPrompt(selected);
    }));
  }
  container.append(table,liftButton('删除整部电梯',()=>liftOperation('delete')));
  if(replay||liftRequestPending) for(const input of container.querySelectorAll('input,select,button')) input.disabled=true;
}
