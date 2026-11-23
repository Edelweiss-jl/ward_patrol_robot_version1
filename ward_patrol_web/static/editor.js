'use strict';
const $ = id => document.getElementById(id);
const canvas = $('canvas'), ctx = canvas.getContext('2d');
let documentMap, configuration, versions = [], selected = null, history = [], compiled = [], preview = [], state = null;
let dragging = null, calibration = null, replay = null, backgroundImage = null, backgroundUrl = null;
let runningMap = null, pendingRun = null, pendingEndRun = null;
let replayRequest = 0, replayLoading = false, replayDraft = null;
const elevatorAccent = '#a96a3a';
const vehicleColors = {red:['红色','#da4651'],yellow:['黄色','#ecb629'],blue:['蓝色','#3279cf'],
  green:['绿色','#36a269'],purple:['紫色','#894fbc']};
let vehicleDraft = null, editedFleetRunId = null;
let modelDraft = null, modelDraftCollapsed = false, modelChangePending = false;
let taskPicking = false, taskMapId = null, taskRequestId = null, taskSubmitting = false;
let taskRecords = [], taskQueueRequest = 0, taskQueueTimer;
const selectedSavedTasks = new Set();
const taskBeds = new Set();
let pickingObstaclePosition = false, pendingSceneCommand = null;
const labels = {wall:'墙',door:'门',bed:'床',furniture:'家具',parking:'停车点',service:'服务点',elevator:'电梯入口',waiting:'候梯点',exit:'出梯区域',forbidden:'禁行区',one_way:'单向区域',single_lane:'单车窄通道'};
const clone = value => JSON.parse(JSON.stringify(value));
const uid = () => crypto.randomUUID().replaceAll('-','');
const list = value => value.split(',').map(v=>v.trim()).filter(Boolean);
const floor = () => documentMap.floors.find(f=>f.id===$('floor').value) || documentMap.floors[0];
const notice = value => {$('notice').textContent = typeof value==='string'?value:JSON.stringify(value,null,2);};
async function api(path, data, readOptions) {
  const response = await fetch(path, data===undefined?readOptions:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) {
    const error=Error(result.error || JSON.stringify(result));
    error.status=response.status;
    if (Array.isArray(result.conflicts)) error.conflicts=result.conflicts;
    throw error;
  }
  return result;
}
function action(id, callback, showError=notice) {$(id).onclick=()=>Promise.resolve().then(callback).catch(e=>showError(e.message));}
function options(id, values, chosen) {
  const element=$(id); element.replaceChildren();
  for (const [value,text] of values) {const option=new Option(text,value);element.add(option);}
  if (chosen!==undefined) element.value=chosen;
}
function checkpoint() {history.push(clone(documentMap));if(history.length>80)history.shift();}
let checkedGeometry = null;
let compileRevision = 0;
function dirty() {rememberLiftPlacements(true);liftReports=null;checkedGeometry=null;compileRevision++;documentMap.version=0;delete documentMap.digest;preview=[];syncMapOption();}
async function compile() {
  const revision=++compileRevision;
  const map=documentMap;
  const result=await api('/api/maps/compile',map);
  if (revision!==compileRevision || map!==documentMap) return;
  compiled=result.floors;
  checkedGeometry={...result.validation,map};
  if (!checkedGeometry.valid) notice([...checkedGeometry.structure,...checkedGeometry.geometry].join('\n'));
  draw();
  return checkedGeometry;
}
function refresh(previous=$('floor').value) {
  ensureElevatorCatalog();
  syncMapOption();
  if (!replay && documentMap.version) localStorage.setItem('ward-editor-map-version',mapVersionKey(documentMap));
  options('floor',documentMap.floors.map(f=>[f.id,f.name]),documentMap.floors.some(f=>f.id===previous)?previous:documentMap.floors[0].id);
  renderFloorTabs();
  renderModelQueue();
  renderFleetQueue();
  $('floorWidth').value=floor().width;$('floorHeight').value=floor().height;
  if (taskMapId!==documentMap.id || replay) {
    taskBeds.clear();
    taskRequestId=null;
    $('taskNotes').value='';
    $('taskBedNumber').value='';
    showTaskPanel('taskEditor',false);
    if (taskPicking) setTaskPicking(false);
    taskMapId=replay?null:documentMap.id;
    taskRecords=[];
    selectedSavedTasks.clear();
    clearTimeout(taskQueueTimer);
    taskQueueTimer=undefined;
    if (!replay) loadTaskRecords().catch(error=>taskFeedback(error.message));
  }
  $('newTask').disabled=!!replay;
  if (replay) showTaskPanel('taskEditor',false);
  if (!$('taskEditor').hidden) refreshTaskSuggestions();
  refreshTaskBeds();
  const parkingChoice=$('instance-parking_id');
  const vehicleFloor=documentMap.floors.find(level=>level.id===$('instance-floor_id')?.value);
  if (parkingChoice && vehicleFloor) {
    const numbers=parkingNumbers(vehicleFloor);
    for (const option of parkingChoice.options) {
      if (numbers.has(option.value)) option.text=numbers.get(option.value);
    }
  }
  inspector();renderState();renderElevatorManager();
}
function transform() {const f=floor(), scale=Math.min((canvas.width-48)/f.width,(canvas.height-80)/f.height);return {scale,x:canvas.width/2,y:canvas.height/2+10};}
function point(x,y) {const t=transform();return [t.x+x*t.scale,t.y-y*t.scale];}
function world(event) {const b=canvas.getBoundingClientRect(),t=transform();return [((event.clientX-b.left)*canvas.width/b.width-t.x)/t.scale, (t.y-(event.clientY-b.top)*canvas.height/b.height)/t.scale];}
function snap(value) {const step=Math.max(.01,Number($('snap').value)||.1);return Math.round(value/step)*step;}
function rectangle(o,color,outline=false) {
  const [x,y]=point(o.x,o.y),t=transform();ctx.save();ctx.translate(x,y);ctx.rotate(-(o.rotation||0)*Math.PI/180);
  ctx.fillStyle=color;ctx.strokeStyle=color;ctx.lineWidth=2;
  if(outline)ctx.strokeRect(-o.width*t.scale/2,-o.height*t.scale/2,o.width*t.scale,o.height*t.scale);
  else ctx.fillRect(-o.width*t.scale/2,-o.height*t.scale/2,o.width*t.scale,o.height*t.scale);
  ctx.restore();
}
function draw() {
  if(!documentMap)return;ctx.clearRect(0,0,canvas.width,canvas.height);
  const f=floor(),t=transform();
  if(f.background) {
    if(backgroundUrl!==f.background.data){backgroundUrl=f.background.data;backgroundImage=new Image();backgroundImage.onload=draw;backgroundImage.src=backgroundUrl;}
    if(backgroundImage?.complete){const [x,y]=point(f.background.x,f.background.y);const width=f.background.width_m*t.scale;ctx.globalAlpha=.45;ctx.drawImage(backgroundImage,x,y,width,width*backgroundImage.height/backgroundImage.width);ctx.globalAlpha=1;}
  }
  ctx.strokeStyle='#e4ebee';ctx.lineWidth=1;
  for(let x=-f.width/2;x<=f.width/2;x+=1){ctx.beginPath();ctx.moveTo(...point(x,-f.height/2));ctx.lineTo(...point(x,f.height/2));ctx.stroke();}
  for(let y=-f.height/2;y<=f.height/2;y+=1){ctx.beginPath();ctx.moveTo(...point(-f.width/2,y));ctx.lineTo(...point(f.width/2,y));ctx.stroke();}
  const rectangles=compiled.find(c=>c.id===f.id)?.rectangles||f.objects.filter(o=>['wall','bed','furniture'].includes(o.kind));
  for(const o of rectangles)rectangle(o,o.kind==='wall'?'#596e7b':o.kind==='bed'?'#4a9a9c':'#b39b75');
  const namedBeds = bedsWithServiceNames(f);
  for(const o of f.objects){
    if(o.kind==='wall'||o.kind==='bed'||o.kind==='furniture'){
      if(o.id===selected) rectangle(o,'#e34d43',true);
      if(o.kind==='bed' && !namedBeds.has(o.id)) {
        const [x,y]=point(o.x,o.y);
        ctx.font='13px sans-serif';ctx.fillStyle='#143849';ctx.fillText(o.name||'病床',x+5,y-8);
      }
      continue;
    }
    if (o.kind==='elevator') continue;
    const color={door:'#20a088',parking:'#677cc1',service:'#187d62',forbidden:'#e37e7e',one_way:'#d9b751',single_lane:'#9aa9d888',waiting:'#d4a640',exit:'#69a6b5'}[o.kind];
    rectangle(o,color,o.kind==='door');
    if (o.kind==='parking') {
      if(o.id===selected) rectangle(o,'#e34d43',true);
      continue;
    }
    const [x,y]=point(o.x,o.y);ctx.font='13px sans-serif';ctx.fillStyle='#143849';ctx.fillText(o.name||labels[o.kind],x+5,y-8);
    if(o.kind==='one_way'){ctx.save();ctx.translate(x,y);ctx.rotate(-(o.rotation||0)*Math.PI/180);ctx.fillText('→',0,4);ctx.restore();}
    if(o.id===selected)rectangle(o,'#e34d43',true);
  }
  drawElevatorEntrances(f,false);
  for(const route of preview.filter(r=>r.floor_id===f.id&&r.path.length)){ctx.beginPath();ctx.strokeStyle='#187d62';ctx.lineWidth=2;route.path.forEach((p,i)=>i?ctx.lineTo(...point(...p)):ctx.moveTo(...point(...p)));ctx.stroke();}
  drawFleet(f);
}
function field(parent,label,key,value,type='text') {const line=document.createElement('label');line.append(document.createTextNode(label));const input=document.createElement('input');input.id=key;input.type=type;input.value=value??'';line.append(input);parent.append(line);return input;}
function inspectorInfo(parent,label,value) {
  const row = document.createElement('div');
  row.className = 'inspector-info';
  const name = document.createElement('span');
  name.textContent = label;
  const content = document.createElement('strong');
  content.textContent = value;
  row.append(name,content);
  parent.append(row);
}
function inspectorChoice(parent,label,choices,current) {
  const row = document.createElement('label');
  row.append(document.createTextNode(label));
  const select = document.createElement('select');
  for (const [value,text] of choices) select.add(new Option(text,value));
  select.value = current ?? '';
  row.append(select);
  parent.append(row);
  return select;
}
function inspectorName(parent,label,id,object) {
  const input = field(parent,label,id,object.name||labels[object.kind]);
  input.required = true;
  return input;
}
function roomNumberError(level,value,exceptId) {
  if (value.length>24) return '病房编号最多 24 个字符。';
  if (value && level.objects.some(object=>object.kind==='door' && object.id!==exceptId &&
      object.room_number?.trim().toLowerCase()===value.toLowerCase())) {
    return '本楼层已有编号「'+value+'」的病房门洞。';
  }
  return '';
}
const bedStatuses = [['','未记录'],['vacant','空床位'],['occupied','已有入住']];
function bedsWithServiceNames(level) {
  return new Set(level.objects.filter(object=>object.kind==='service' && object.bed_id).map(object=>object.bed_id));
}
function bedDisplayName(bed,level) {
  const service = level.objects.find(object=>object.kind==='service' && object.bed_id===bed.id);
  return service ? service.name||'床旁服务点' : bed.name||'病床';
}
function addPatientFields(form,status,patient) {
  const section = document.createElement('fieldset');
  section.className = 'patient-fields';
  const title = document.createElement('legend');
  title.textContent = '入住患者资料';
  section.append(title);
  const name = field(section,'姓名','patient-name',patient.name);
  const age = field(section,'年龄（岁）','patient-age',patient.age,'number');
  age.min = '0';
  age.max = '130';
  age.step = '1';
  const patientId = field(section,'患者编号','patient-id',patient.id);
  const sex = inspectorChoice(section,'性别',[
    ['','请选择'],['female','女'],['male','男'],['other','其他'],['unknown','未说明']
  ],patient.sex);
  const diagnosis = field(section,'疾病或诊断','patient-diagnosis',patient.diagnosis);
  const notes = field(section,'备注（选填）','patient-notes',patient.notes);
  for (const [input,length] of [[name,80],[patientId,80],[diagnosis,200],[notes,500]]) {
    input.maxLength=length;
  }
  const required=[name,age,patientId,sex,diagnosis];
  const update = () => {
    const occupied=status.value==='occupied';
    section.hidden=!occupied;
    for (const input of [...required,notes]) {
      input.disabled=!occupied;
      input.required=occupied && input!==notes;
    }
  };
  status.onchange=update;
  form.append(section);
  update();
  return () => {
    if (status.value!=='occupied') return null;
    const years=Number(age.value);
    if (!String(age.value).trim() || !Number.isInteger(years) || years<0 || years>130) {
      throw Error('年龄须为 0 至 130 之间的整数。');
    }
    const record={name:name.value.trim(),age:years,id:patientId.value.trim(),sex:sex.value,
      diagnosis:diagnosis.value.trim()};
    if (!record.name || !record.id || !record.sex || !record.diagnosis) {
      throw Error('请填写姓名、患者编号、性别和疾病或诊断。');
    }
    if (notes.value.trim()) record.notes=notes.value.trim();
    return record;
  };
}
function clearCopiedPatient(object) {
  if (object.kind!=='bed') return;
  delete object.patient;
  if (object.bed_status==='occupied') object.bed_status='';
}
function addBedProperties(form,level,bed,services) {
  const room = field(form,'所属病房','obj-room',bed.room_name);
  room.placeholder = '如 203';
  const suggested = level.objects.filter(object=>object.kind==='door' && object.room_number);
  if (suggested.length) {
    const list = document.createElement('datalist');
    list.id = 'ward-room-numbers';
    for (const door of suggested) {
      const option = document.createElement('option');
      option.value = door.room_number;
      list.append(option);
    }
    room.setAttribute('list',list.id);
    form.append(list);
  }
  const status = inspectorChoice(form,'床位状态',bedStatuses,bed.bed_status);
  if (!status.value) status.value='';
  const patient = addPatientFields(form,status,bed.patient||{});
  if (!services.length) inspectorInfo(form,'床旁服务点','未关联');
  const names = services.map((service,index)=>inspectorName(form,
    services.length===1?'床旁服务点名称':'床旁服务点 '+(index+1)+' 名称','obj-service-'+index,service));
  return () => {
    const record = patient();
    if (services.length) delete bed.name;
    bed.room_name = room.value.trim();
    bed.bed_status = status.value;
    if (record) bed.patient = record;
    else delete bed.patient;
    services.forEach((service,index)=>{service.name=names[index].value.trim();});
  };
}
function addGeometryFields(form,object) {
  const fields = object.kind==='door' ? {width:'门宽（米）'}
    : object.kind==='elevator' && object.wall_id ? {width:'入口宽度（米）'}
    : {x:'X（米）',y:'Y（米）',width:'宽（米）',height:'深（米）',rotation:'旋转角度'};
  const inputs = Object.entries(fields).map(([key,label])=>{
      const input = field(form,label,'obj-'+key,object[key] ?? (key==='rotation'?0:null),'number');
      input.step = 'any';
      input.required = true;
      if (key==='width' || key==='height') input.min = '0.01';
      return [key,input];
    });
  return () => Object.fromEntries(inputs.map(([key,input])=>[key,Number(input.value)]));
}
function parkingNumbers(level) {
  const points=level.objects.filter(item=>item.kind==='parking');
  const numbers=new Map(points.filter(item=>item.parking_number).map(item=>[item.id,item.parking_number.trim()]));
  const used=new Set([...numbers.values()].map(number=>number.toLowerCase()));
  let sequence=1;
  for (const point of points) {
    if (numbers.has(point.id)) continue;
    while (used.has('p'+sequence)) sequence++;
    numbers.set(point.id,'P'+sequence);
    used.add('p'+sequence);
  }
  return numbers;
}
function addOtherProperties(form,level,object) {
  const service = object.kind==='service';
  const parkingNumber = object.kind==='parking'
    ? field(form,'停车点编号','obj-parking-number',parkingNumbers(level).get(object.id)) : null;
  if (parkingNumber) {parkingNumber.required=true;parkingNumber.maxLength=24;}
  const name = inspectorName(form,service?'服务点名称':'名称','obj-name',object);
  if (service) {
    const bed = level.objects.find(item=>item.kind==='bed' && item.id===object.bed_id);
    if (bed) {
      inspectorInfo(form,'床旁关联','已关联病床');
      inspectorInfo(form,'所属病房',bed.room_name||'未记录');
      inspectorInfo(form,'床位状态',bedStatuses.find(([key])=>key===bed.bed_status)?.[1]||'未记录');
    }
  }
  const room = object.kind==='door' ? field(form,'病房编号','obj-room-number',object.room_number) : null;
  if (room) {
    room.maxLength = 24;
    room.placeholder = '如 203，可留空';
  }
  const geometry = addGeometryFields(form,object);
  if (object.kind==='door' || (object.kind==='elevator' && object.wall_id)) {
    const wall = level.objects.find(item=>item.id===object.wall_id);
    inspectorInfo(form,'所属墙体',wall?.name||(wall?'墙体':'未关联'));
  }
  const refs = [];
  let liftChoice;
  if (object.kind==='elevator') {
    const settings=document.createElement('details');
    const summary=document.createElement('summary');
    summary.textContent='入口关联';
    settings.append(summary);
    form.append(settings);
    liftChoice=inspectorChoice(settings,'所属电梯',[...liftChoices(level.id,object.id),['','新建一部电梯']],object.lift_id);
    const manage=liftButton('管理整部电梯',()=>openElevatorManager(object.lift_id));settings.append(manage);
    for (const [key,kind] of [['waiting_id','waiting'],['exit_id','exit']]) {
      const choices = level.objects.filter(item=>item.kind===kind)
        .map((item,index)=>[item.id,(item.name||labels[kind])+'（'+(index+1)+'）']);
      const input = inspectorChoice(settings,labels[kind],[['','请选择'],...choices],object[key]);
      input.required = true;
      refs.push([key,input]);
    }
  }
  const models = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = '车型通行限制';
  models.append(summary);
  const modelChoices = configuration.models.map((model,index)=>{
    const input = field(models,model.name||'车型 '+(index+1),'obj-model-'+index,'','checkbox');
    input.checked = (object.models||[]).includes(model.id);
    return [model.id,input];
  });
  form.append(models);
  return () => {
    const roomNumber = room?.value.trim();
    const number = parkingNumber?.value.trim();
    if (parkingNumber) {
      if (!number || number.length>24) throw Error('停车点编号须为 1 至 24 个字符');
      if ([...parkingNumbers(level)].some(([id,value])=>id!==object.id && value.toLowerCase()===number.toLowerCase())) {
        throw Error('本楼层已存在这个停车点编号');
      }
    }
    if (room) {
      const error = roomNumberError(level,roomNumber,object.id);
      if (error) throw Error(error);
    }
    const original = clone(object);
    Object.assign(object,geometry(),{name:name.value.trim()});
    if (number) object.parking_number = number;
    if (roomNumber) object.room_number = roomNumber;
    else if (room) delete object.room_number;
    for (const [key,input] of refs) object[key]=input.value;
    if (object.kind==='elevator') {
      managedLiftId=attachLiftLanding(documentMap,level.id,object.id,liftChoice.value);
    }
    const known = new Set(modelChoices.map(([id])=>id));
    object.models = [...(object.models||[]).filter(id=>!known.has(id)),
      ...modelChoices.filter(([,input])=>input.checked).map(([id])=>id)];
    if (typeof attachedMove==='function') attachedMove(original,object);
    else moveDoors(original,object);
  };
}
function inspector() {
  const target = $('inspector');
  target.replaceChildren();
  const level = floor();
  const object = level.objects.find(item=>item.id===selected);
  if (!object) {
    target.textContent='选择画布对象';
    return;
  }
  const title = document.createElement('p');
  title.textContent = object.kind==='bed'?'病床资料':object.kind==='service'?'服务点资料':labels[object.kind];
  const form = document.createElement('form');
  inspectorInfo(form,'楼层',level.name);
  const apply = object.kind==='bed'
    ? addBedProperties(form,level,object,level.objects.filter(item=>item.kind==='service' && item.bed_id===object.id))
    : addOtherProperties(form,level,object);
  const save = document.createElement('button');
  save.type = 'submit';
  save.textContent = '应用属性';
  save.disabled = !!replay;
  form.append(save);
  if (!replay && object.kind==='elevator') {
    const lift = documentMap.elevators.find(item=>item.id===object.lift_id);
    if (canConfirmLiftLanding(lift,level.id)) {
      form.append(liftButton('在地图上查看入口',()=>showLiftLandingPrompt(object.id)));
    }
  }
  form.onsubmit = async event => {
    event.preventDefault();
    if (replay || floor()!==level || selected!==object.id) return;
    if ([...form.querySelectorAll('input[required]')].some(input=>!input.disabled && !String(input.value).trim())) {
      notice('请填写必填属性');
      return;
    }
    try {
      checkpoint();
      apply();
      dirty();
      refresh();
      await compile();
    } catch (error) {notice(error.message);}
  };
  target.append(title,form);
}
function moveDoors(before,after) {
  if(before.kind!=='wall')return;
  const old=(before.rotation||0)*Math.PI/180,newAngle=(after.rotation||0)*Math.PI/180;
  for(const door of floor().objects.filter(o=>o.wall_id===before.id && ['door','elevator'].includes(o.kind))){
    const entranceBefore=door.kind==='elevator' ? clone(door) : null;
    const dx=door.x-before.x,dy=door.y-before.y;
    const x=dx*Math.cos(old)+dy*Math.sin(old),y=-dx*Math.sin(old)+dy*Math.cos(old);
    door.x=after.x+x*Math.cos(newAngle)-y*Math.sin(newAngle);door.y=after.y+x*Math.sin(newAngle)+y*Math.cos(newAngle);
    door.rotation=after.rotation+(entranceBefore && after.height>after.width?90:0);
    if (entranceBefore) attachedMove(entranceBefore,door);
  }
}
function containsPoint(object,pos) {
  const angle=(object.rotation||0)*Math.PI/180;
  const dx=pos[0]-object.x, dy=pos[1]-object.y;
  const sin=Math.sin(angle), cos=Math.cos(angle);
  return Math.abs(dx*cos+dy*sin)<=Math.max(.15,object.width/2) &&
    Math.abs(-dx*sin+dy*cos)<=Math.max(.15,object.height/2);
}
function hit(pos,filter=()=>true) {
  return floor().objects.findLast(object=>filter(object) && containsPoint(object,pos));
}
canvas.onpointerdown=event=>{
  if(replay)return;const pos=world(event);
  if(calibration){calibration.push(pos);if(calibration.length===2){const measured=Math.hypot(calibration[1][0]-calibration[0][0],calibration[1][1]-calibration[0][1]);if(measured>.001){checkpoint();floor().background.width_m*=Number($('calibrationDistance').value)/measured;dirty();draw();notice('底图比例已标定');}calibration=null;}return;}
  const kind=$('tool').value;
  if(kind==='select'){const obj=hit(pos);selected=obj?.id;inspector();if(obj){checkpoint();dragging={object:obj,position:pos,original:clone(obj)};canvas.setPointerCapture(event.pointerId);}draw();return;}
  const parent=floor().objects.find(o=>o.id===selected);
  if(kind==='door'&&parent?.kind!=='wall'){notice('先选择墙，再选择门工具');return;}
  checkpoint();const sizes={wall:[4,.2],door:[1,.2],bed:[1,2],furniture:[1,1],parking:[.25,.25],service:[.25,.25],elevator:[1.5,1.5],waiting:[.3,.3],exit:[1.5,1.5],forbidden:[2,2],one_way:[3,1.5]};
  const obj={id:uid(),kind,x:snap(pos[0]),y:snap(pos[1]),width:sizes[kind][0],height:sizes[kind][1],rotation:0,name:labels[kind]};
  if(kind==='door'){Object.assign(obj,{wall_id:parent.id,x:parent.x,y:parent.y,rotation:parent.rotation,height:parent.height});}
  if(kind==='service'&&parent?.kind==='bed')obj.bed_id=parent.id;
  if(kind==='elevator')obj.service_floors=[floor().id];
  floor().objects.push(obj);selected=obj.id;$('tool').value='select';dirty();refresh();compile().catch(e=>notice(e.message));
};
canvas.onpointermove=event=>{if(!dragging)return;const pos=world(event),obj=dragging.object,before=clone(obj);obj.x=snap(dragging.original.x+pos[0]-dragging.position[0]);obj.y=snap(dragging.original.y+pos[1]-dragging.position[1]);moveDoors(before,obj);dirty();draw();};
canvas.onpointerup=()=>{if(dragging){dragging=null;inspector();compile().catch(e=>notice(e.message));}};
function closeFloorNameForm() {
  $('floorNameForm').hidden = true;
  $('renameFloor').setAttribute('aria-expanded','false');
}
function renderFloorTabs() {
  const active = floor();
  const deletion = $('deleteFloor');
  deletion.disabled = !!replay || documentMap.floors.length<=1;
  deletion.title = replay ? '回放模式下无法编辑楼层' : deletion.disabled
    ? '地图至少保留一个楼层' : '删除当前楼层：'+active.name;
  const activeFloor = documentMap.id+'@'+active.id;
  if ($('floorTabs').dataset.active !== activeFloor) {
    closeFloorNameForm();
    $('floorTabs').dataset.active = activeFloor;
  }
  const activeLabel = buildingOverview ? '整栋楼 · '+documentMap.floors.length+' 层' : '当前楼层 · '+active.name;
  if ($('canvasFloor').textContent!==activeLabel) $('canvasFloor').textContent = activeLabel;
  const tabs = $('floorTabs');
  const signature = JSON.stringify(documentMap.floors.map(f=>[f.id,f.name]));
  if (tabs.dataset.floors!==signature) {
    tabs.replaceChildren();
    for (const level of documentMap.floors) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.floor = level.id;
      button.textContent = level.name;
      button.title = level.name;
      button.onclick = () => {
        if ($('floor').value===level.id && !buildingOverview) return;
        $('floor').value = level.id;
        $('floor').onchange();
      };
      tabs.append(button);
    }
    tabs.dataset.floors = signature;
  }
  for (const button of tabs.children) {
    const current = button.dataset.floor===active.id;
    button.setAttribute('aria-pressed',String(current));
    if (current && (button.offsetLeft<tabs.scrollLeft ||
        button.offsetLeft+button.offsetWidth>tabs.scrollLeft+tabs.clientWidth)) {
      tabs.scrollLeft = button.offsetLeft;
    }
  }
}
$('floor').onchange=()=>{
  if (buildingOverview) setBuildingOverview(false);
  selected = null;
  closeFloorNameForm();
  refresh();
};
$('renameFloor').onclick=()=>{
  if (!documentMap || replay) return;
  $('floorNameForm').hidden = false;
  $('renameFloor').setAttribute('aria-expanded','true');
  $('floorName').value = floor().name;
  $('floorName').focus();
  $('floorName').select();
};
$('cancelFloorRename').onclick=closeFloorNameForm;
$('floorNameForm').onsubmit=event=>{
  event.preventDefault();
  if (!documentMap || replay) return;
  const name = $('floorName').value.trim();
  if (!name) {
    notice('请输入楼层名称');
    return;
  }
  if (name!==floor().name) {
    checkpoint();
    floor().name = name;
    dirty();
    refresh();
  }
  closeFloorNameForm();
};

action('blank',async()=>{checkpoint();documentMap=await api('/api/maps/blank',{name:'自定义病区'});selected=null;compiled=[];refresh();});
action('saveMap',async()=>{documentMap=await api('/api/maps/save',documentMap);versions=await api('/api/maps');mapOptions();refresh();notice('已保存版本 '+documentMap.version+'，历史运行继续使用原版本');});
function mapVersionKey(map) {
  return map.id+'@'+map.version;
}
function isAvailableMapVersion(map) {
  return !!map.version && versions.some(version=>mapVersionKey(version)===mapVersionKey(map));
}
function isHospitalTemplate(map) {
  return map.template===true;
}
function mapDisplayName(map) {
  return (map.version && versions.find(item=>mapVersionKey(item)===mapVersionKey(map))?.display_name)
    || map.display_name || map.name;
}
let mapNameTarget = null;
function closeMapNameForm() {
  mapNameTarget = null;
  $('mapNameForm').hidden = true;
  $('renameMap').setAttribute('aria-expanded','false');
}
function syncMapOption() {
  const saved = $('mapList');
  const templates = $('mapTemplateList');
  const key = documentMap.version ? mapVersionKey(documentMap) : '';
  const available = isAvailableMapVersion(documentMap);
  const unavailable = !!key && !available;
  const template = isHospitalTemplate(documentMap);
  if (mapNameTarget && (mapNameTarget.map!==documentMap || mapNameTarget.version!==documentMap.version || replay || unavailable)) {
    closeMapNameForm();
  }
  $('renameMap').disabled = !!replay || unavailable;
  $('openMapManager').disabled = !!replay;
  saved.value = available && !template ? key : '';
  templates.value = available && template ? key : '';
  if (saved.options[0]) {
    let label = saved.options.length>1 ? '选择已保存地图' : '暂无已保存地图';
    if (replay) label = '回放中的地图';
    else if (!key) label = '当前为未保存草稿';
    else if (unavailable && !template) label = '当前版本已移出列表';
    saved.options[0].textContent = label;
  }
  if (templates.options[0]) {
    templates.options[0].textContent = unavailable && template ? '当前模板已移出列表' :
      templates.options.length>1 ? '选择地图模板' : '暂无地图模板';
  }
  saved.disabled = !!replay || saved.options.length<=1;
  templates.disabled = !!replay || templates.options.length<=1;
  $('useMapTemplate').disabled = !!replay || !template || !available;
  $('saveMap').textContent = template ? '保存为地图' : '保存新版本';
}
function mapOptions() {
  const idsByName = new Map();
  for (const map of versions) {
    const name=map.display_name||map.name;
    if (!idsByName.has(name)) idsByName.set(name,new Set());
    idsByName.get(name).add(map.id);
  }
  const templates = [], saved = [];
  const sorted = [...versions].sort((a,b)=>a.id.localeCompare(b.id) || b.version-a.version);
  for (const map of sorted) {
    const name=map.display_name||map.name;
    const suffix = idsByName.get(name).size>1 ? ' · '+map.id.slice(0,8) : '';
    if (isHospitalTemplate(map)) templates.push([mapVersionKey(map),name+suffix]);
    else saved.push([mapVersionKey(map),name]);
  }
  options('mapList',[['','选择已保存地图'],...saved]);
  options('mapTemplateList',[['','选择地图模板'],...templates]);
  for (const id of ['mapList','mapTemplateList']) $(id).options[0].disabled = true;
  syncMapOption();
}

let archivedMapCatalog = [], mapManagerBusy = false;

async function loadSavedMaps() {
  versions = await api('/api/maps');
  if (documentMap) {
    mapOptions();
    if (typeof renderWorkbench==='function') renderWorkbench();
  }
}

async function loadArchivedMaps() {
  const catalog = await api('/api/maps/manage');
  archivedMapCatalog = catalog.filter(map=>map.status==='archived');
}

function createMapManager(panel, status) {
  const search = panel.querySelector('[data-map-search]');
  const selectAll = panel.querySelector('[data-map-select-all]');
  const count = panel.querySelector('[data-map-count]');
  const feedback = panel.querySelector('[data-map-feedback]');
  const empty = panel.querySelector('[data-map-empty]');
  const rows = panel.querySelector('tbody');
  const buttons = [...panel.querySelectorAll('[data-map-operation]')];
  const selected = new Set();
  const saved = status==='active';
  let loaded = false;

  function visibleMaps() {
    const query = search.value.trim().toLowerCase();
    const catalog = saved
      ? versions.filter(map=>!isHospitalTemplate(map)).map(map=>({...map,name:map.display_name||map.name}))
      : archivedMapCatalog;
    return catalog.filter(map=>`${map.name} ${map.id} v${map.version}`.toLowerCase().includes(query))
      .sort((a,b)=>a.name.localeCompare(b.name,'zh-CN') || a.id.localeCompare(b.id) || b.version-a.version);
  }

  function updateControls(visible) {
    selectAll.disabled = mapManagerBusy || !visible.length;
    selectAll.checked = !!visible.length && selected.size===visible.length;
    selectAll.indeterminate = selected.size>0 && selected.size<visible.length;
    count.textContent = `已选 ${selected.size} / ${visible.length} 个版本`;
    search.disabled = mapManagerBusy;
    for (const button of buttons) button.disabled = mapManagerBusy || !selected.size;
  }

  function render() {
    const visible = visibleMaps();
    rows.replaceChildren(...visible.map(map=>{
      const row = document.createElement('tr');
      const key = mapVersionKey(map);
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.id = panel.id+'-'+key;
      checkbox.checked = selected.has(key);
      checkbox.disabled = mapManagerBusy;
      checkbox.setAttribute('aria-label', `${map.name} · ${map.id} · v${map.version}`);
      checkbox.onchange = ()=>{
        if (checkbox.checked) selected.add(key);
        else selected.delete(key);
        updateControls(visible);
      };
      row.insertCell().append(checkbox);
      const label = document.createElement('label');
      label.htmlFor = checkbox.id;
      label.textContent = map.name;
      const identity = document.createElement('div');
      identity.className = 'muted';
      identity.textContent = map.id;
      row.insertCell().append(label, identity);
      row.insertCell().textContent = 'v'+map.version;
      return row;
    }));
    empty.hidden = !!visible.length || mapManagerBusy || !loaded;
    empty.textContent = search.value.trim() ? '没有匹配的地图版本。' :
      status==='active' ? '暂无已保存地图。' : '暂无已归档地图。';
    updateControls(visible);
  }

  async function refresh({resetSearch=false}={}) {
    if (mapManagerBusy) return;
    if (resetSearch) search.value = '';
    clearMapManagerSelections();
    loaded = false;
    feedback.textContent = '正在读取地图版本…';
    mapManagerBusy = true;
    renderMapManagers();
    try {
      await (saved ? loadSavedMaps() : loadArchivedMaps());
      loaded = true;
      feedback.textContent = '';
    } catch (error) {
      feedback.textContent = error.status===404 && !saved
        ? '当前服务缺少地图归档接口。请重启工作台服务后重试。'
        : '读取失败。'+error.message;
    } finally {
      mapManagerBusy = false;
      renderMapManagers();
    }
  }

  async function manage(operation) {
    const maps = visibleMaps().filter(map=>selected.has(mapVersionKey(map)));
    if (mapManagerBusy || !maps.length) return;
    if (operation==='delete' && !confirm(`永久删除选中的 ${maps.length} 个地图版本？删除后无法恢复。`)) return;
    const label = {archive:'归档',restore:'恢复',delete:'永久删除'}[operation];
    mapManagerBusy = true;
    feedback.textContent = '正在'+label+'…';
    renderMapManagers();
    let result;
    try {
      result = await api('/api/maps/manage',{
        action:operation,versions:maps.map(map=>({map_id:map.id,version:map.version}))
      });
      clearMapManagerSelections();
      await Promise.all([loadSavedMaps(),loadArchivedMaps()]);
      feedback.textContent = result.changed ? `已${label} ${result.changed} 个地图版本。` : '选中的版本状态已经更新。';
      if (result.cleanup_pending) feedback.textContent += '部分文件暂时无法清理，服务重启时会重试。';
    } catch (error) {
      feedback.textContent = !result && error.status===404
        ? '当前服务缺少地图批量操作接口。请重启工作台服务后重试。'
        : (result ? '操作已提交，刷新列表失败。' : '操作失败。')+error.message;
    } finally {
      mapManagerBusy = false;
      renderMapManagers();
    }
  }

  search.oninput = ()=>{
    selected.clear();
    feedback.textContent = '';
    render();
  };
  selectAll.onchange = ()=>{
    selected.clear();
    const visible = visibleMaps();
    if (selectAll.checked) for (const map of visible) selected.add(mapVersionKey(map));
    render();
  };
  for (const button of buttons) button.onclick = ()=>manage(button.dataset.mapOperation);
  return {refresh,render,clearSelection:()=>selected.clear()};
}

const savedMapManager = createMapManager($('mapBatchManager'),'active');
const archivedMapManager = createMapManager($('mapManager'),'archived');

function clearMapManagerSelections() {
  savedMapManager.clearSelection();
  archivedMapManager.clearSelection();
}

function renderMapManagers() {
  savedMapManager.render();
  archivedMapManager.render();
}

async function openMapVersion(event) {
  const version = versions.find(map=>mapVersionKey(map)===event.target.value);
  if (!version || replay) return;
  checkpoint();
  documentMap = clone(version);
  delete documentMap.display_name;
  selected = null;
  preview = [];
  compiled = [];
  setBuildMode('select');
  refresh();
  notice('已切换至 '+mapDisplayName(version)+' v'+version.version+'。'+(version.description || '')+
    (isHospitalTemplate(version) ? '点击「从此模板建图」创建独立草稿。' : ''));
  try {
    await compile();
  } catch (error) {
    notice('地图已切换，几何加载失败：'+error.message);
  }
}
$('mapList').onchange = openMapVersion;
$('mapTemplateList').onchange = openMapVersion;
$('renameMap').onclick = () => {
  if (!documentMap || replay) return;
  mapNameTarget = {map:documentMap,version:documentMap.version};
  $('mapName').value = mapDisplayName(documentMap);
  $('mapNameForm').hidden = false;
  $('renameMap').setAttribute('aria-expanded','true');
  $('mapName').focus();
  $('mapName').select();
};
$('cancelMapName').onclick = closeMapNameForm;
$('mapNameForm').onsubmit = async event => {
  event.preventDefault();
  const target = mapNameTarget;
  if (!target || $('confirmMapName').disabled) return;
  const name = $('mapName').value.trim();
  if (!name || name.length>60) {notice('名称应为 1 至 60 个字符');return;}
  if (!target.version) {
    checkpoint();
    documentMap.name = name;
    delete documentMap.display_name;
    closeMapNameForm();
    syncMapOption();
    notice('草稿已改名。点击「保存新版本」保留名称。');
    return;
  }
  $('confirmMapName').disabled = true;
  try {
    const renamed = await api('/api/maps/rename',{map_id:target.map.id,version:target.version,name});
    const version = versions.find(item=>item.id===renamed.map_id && item.version===renamed.version);
    if (version) version.display_name = renamed.display_name;
    if (mapNameTarget===target) closeMapNameForm();
    mapOptions();
    notice('版本名称已保存为「'+renamed.display_name+'」。');
  } catch (error) {notice(error.message);}
  finally {$('confirmMapName').disabled = false;}
};
function draftFromTemplate(template) {
  const draft = normalizeElevatorMap(clone(template));
  draft.id = uid();
  draft.name = mapDisplayName(template)+'（自定义）';
  delete draft.display_name;
  draft.version = 0;
  delete draft.template;
  delete draft.digest;
  const floorIds = new Map(draft.floors.map(level=>[level.id,uid()]));
  const allObjectIds=new Map(draft.floors.map(level=>[level.id,new Map(level.objects.map(object=>[object.id,uid()]))]));
  for (const level of draft.floors) {
    const objectIds = allObjectIds.get(level.id);
    level.id = floorIds.get(level.id);
    for (const object of level.objects) {
      clearCopiedPatient(object);
      object.id = objectIds.get(object.id);
      for (const key of ['wall_id','bed_id','waiting_id','exit_id','elevator_id']) {
        if (objectIds.has(object[key])) object[key] = objectIds.get(object[key]);
      }
      if (Array.isArray(object.service_floors)) {
        object.service_floors = object.service_floors.map(id=>floorIds.get(id) || id);
      }
    }
  }
  remapTemplateLifts(draft,floorIds,allObjectIds);
  return draft;
}
action('useMapTemplate',async()=>{
  if (replay || !isAvailableMapVersion(documentMap) || !isHospitalTemplate(documentMap)) return;
  checkpoint();
  documentMap = draftFromTemplate(documentMap);
  selected = null;
  compiled = [];
  setBuildMode('select');
  dirty();
  refresh();
  const result = await compile();
  if (result?.valid) notice('已从模板创建独立草稿。调整布局后点「保存新版本」。');
});
action('exportMap',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(documentMap,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=documentMap.id+'.json';link.click();URL.revokeObjectURL(url);});
$('importMap').onchange=async event=>{try{const data=JSON.parse(await event.target.files[0].text());const check=await api('/api/maps/validate',data);if(!check.valid){notice(check);return;}checkpoint();documentMap=data;dirty();refresh();await compile();}catch(error){notice(error.message);}};
action('addFloor',()=>{checkpoint();const f={id:'F-'+uid().slice(0,8),name:'楼层 '+(documentMap.floors.length+1),width:20,height:16,objects:[],background:null};documentMap.floors.push(f);dirty();refresh();$('floor').value=f.id;refresh();});
action('copyFloor',async()=>{checkpoint();documentMap=await api('/api/maps/copy-floor',{map:documentMap,floor_id:floor().id});dirty();refresh();$('floor').value=documentMap.floors.at(-1).id;refresh();await compile();});
action('resizeFloor',async()=>{checkpoint();floor().width=Number($('floorWidth').value);floor().height=Number($('floorHeight').value);dirty();await compile();});
action('undo',async()=>{if(history.length){documentMap=history.pop();selected=null;refresh();await compile();}});
action('deleteObject',async()=>{checkpoint();floor().objects=floor().objects.filter(o=>o.id!==selected);selected=null;dirty();refresh();await compile();});
action('rotate',async()=>{const obj=floor().objects.find(o=>o.id===selected);if(obj){checkpoint();const before=clone(obj);obj.rotation=(obj.rotation+15)%360;moveDoors(before,obj);dirty();refresh();await compile();}});
$('background').onchange=event=>{const file=event.target.files[0];if(!file)return;const reader=new FileReader();reader.onload=()=>{checkpoint();floor().background={data:reader.result,width_m:floor().width,x:-floor().width/2,y:floor().height/2};dirty();draw();};reader.readAsDataURL(file);};
action('calibrate',()=>{if(!floor().background)throw Error('请先上传底图');calibration=[];notice('依次点击底图上已知距离的两个点');});
action('clearBackground',()=>{checkpoint();floor().background=null;dirty();draw();});
action('preview',async()=>{
  const result=await api('/api/preview',{map:documentMap,...configuration});
  preview=result.results.flatMap(row=>row.segments||[row]);
  $('previewResult').textContent=result.results.map(row=>
    `${row.robot_id} / ${row.model_id} → ${row.service_id}：${row.reason}`).join('\n');
  notice(result.validation);
  draw();
});
function configOptions(focusVehicleId) {
  const vehicle = $('instance').value;
  refreshModelOptions();
  options('instance',[['',''],...configuration.instances.map(i=>[i.id,i.id])],vehicle);
  options('assignedRobot',[['','自动分配'],...configuration.instances.filter(i=>i.enabled!==false && i.parking_id).map(i=>[i.id,i.id])]);
  options('template',configuration.templates.map((t,i)=>[String(i),t.name]));
  instanceForm();
  renderFleetQueue(focusVehicleId);
}

const capabilityNames = {patrol:'病区巡查',vitals:'体征采样'};
const modelBasics = {width:'车宽（米）',length:'车长（米）',speed:'最高速度（米/秒）',margin:'车身额外留距（米）'};
const modelMotion = {acceleration:'起步加速度（米/秒²）',deceleration:'刹车减速度（米/秒²）',angular_speed:'转向速度（弧度/秒）'};
function numericSetting(parent,label,id,value,min,max) {
  const input=field(parent,label,id,value,'number');
  input.step='any';
  input.min=String(min);
  if (max!==undefined) input.max=String(max);
  return input;
}
function setModelEditorVisible(visible) {
  $('modelEditor').hidden=!visible;
  $('newModel').setAttribute('aria-expanded',String(visible && !!modelDraft));
}
const sensorFields={range:['测距范围（米）',.5,20],frequency:['测距更新（次/秒）',1,30],
  fov:['测距视野（度）',45,360],rays:['射线数量',9,181],noise:['测距噪声（米）',0,.5],
  dropout:['丢测概率',0,1],delay:['测距延迟（秒）',0,3],ttl:['观测有效期（秒）',.25,10]};
function modelForm() {
  const model=modelDraft || configuration.models.find(item=>item.id===$('model').value);
  const form=$('modelForm');
  form.replaceChildren();
  setModelEditorVisible(!!model && (!modelDraft || !modelDraftCollapsed));
  $('cancelModel').hidden=!modelDraft;
  $('deleteModel').hidden=!!modelDraft;
  $('saveModel').textContent=modelDraft?'确认创建车型':'保存车型';
  if (!model) return;
  field(form,'车型名称','model-name',model.name);
  for (const [key,label] of Object.entries(modelBasics)) {
    numericSetting(form,label,'model-'+key,model[key],0);
  }
  const turning=inspectorChoice(form,'行驶方式',[
    ['differential','先转向再行驶'],['holonomic','可横移']
  ],model.turning);
  turning.id='model-turning';
  const capabilities=document.createElement('fieldset');
  const legend=document.createElement('legend');
  legend.textContent='可执行的任务';
  capabilities.append(legend);
  for (const key of Object.keys(capabilityNames)) {
    const checkbox=field(capabilities,capabilityNames[key],'model-capability-'+key,'','checkbox');
    checkbox.checked=(model.capabilities||[]).includes(key);
  }
  form.append(capabilities);

  const advanced=document.createElement('details');
  const summary=document.createElement('summary');
  summary.textContent='运动与测距设置';
  advanced.append(summary);
  for (const [key,label] of Object.entries(modelMotion)) {
    numericSetting(advanced,label,'model-'+key,model[key],0);
  }
  for (const [key,[label,min,max]] of Object.entries(sensorFields)) {
    numericSetting(advanced,label,'model-sensor-'+key,model.sensors?.[key],min,max);
  }
  form.append(advanced);
}
function refreshModelOptions(id=$('model').value) {
  options('model',[['',''],...configuration.models.map(model=>[model.id,model.name||model.id])],id);
  modelForm();
  renderModelQueue();
}
function renderModelQueue(focusId) {
  if (!configuration) return;
  const queue=$('modelQueue');
  $('modelQueueButton').textContent='车型队列（'+configuration.models.length+' 种）';
  $('newModel').disabled=!!replay;
  $('saveModel').disabled=!!replay;
  $('deleteModel').disabled=!!replay;
  if (queue.hidden) return;
  queue.replaceChildren();
  if (!configuration.models.length) queue.textContent='还没有车型。';
  for (const model of configuration.models) {
    const button=document.createElement('button');
    button.type='button';
    button.textContent=model.name||model.id;
    const expanded=$('model').value===model.id;
    button.setAttribute('aria-expanded',String(expanded));
    button.setAttribute('aria-controls','modelEditor');
    button.onclick=()=>{
      if (modelChangePending) return;
      openModel(expanded?'':model.id,model.id);
      $('modelFeedback').textContent='';
    };
    queue.append(button);
    if (focusId===model.id) button.focus({preventScroll:true});
  }
}
function openModel(id, focusId) {
  modelDraft=null;
  $('model').value=id;
  modelForm();
  renderModelQueue(focusId);
}
function setModelQueueOpen(open) {
  $('modelQueue').hidden=!open;
  $('modelQueueButton').setAttribute('aria-expanded',String(open));
}
function modelAction(id, callback) {
  $(id).onclick=async()=>{
    if (modelChangePending || !configuration) return;
    modelChangePending=true;
    $('modelFeedback').textContent='';
    try {await callback();}
    catch (error) {$('modelFeedback').textContent=error.message;}
    finally {modelChangePending=false;}
  };
}
modelAction('modelQueueButton',()=>{
  setModelQueueOpen($('modelQueue').hidden);
  openModel('');
});
modelAction('newModel',async()=>{
  if (replay) return;
  if (modelDraft) {
    modelDraftCollapsed=!modelDraftCollapsed;
    setModelEditorVisible(!modelDraftCollapsed);
    return;
  }
  const defaults=configuration.models[0] || await api('/api/editor/models');
  modelDraft={...clone(defaults),id:'model-'+uid(),name:'新车型'};
  modelDraftCollapsed=false;
  setModelQueueOpen(false);
  $('model').value='';
  modelForm();
});
modelAction('cancelModel',()=>openModel(''));
function applyModelList(models, selectedId) {
  configuration.models=models;
  modelDraft=null;
  refreshModelOptions(selectedId);
  const instanceModel=$('instance-model_id');
  if (instanceModel) {
    options('instance-model_id',models.map(item=>[item.id,item.name||item.id]),instanceModel.value);
  }
  renderFleetQueue();
  draw();
}
modelAction('saveModel',async()=>{
  if (replay) return;
  const current=modelDraft || configuration.models.find(item=>item.id===$('model').value);
  if (!current) return;
  const creating=!!modelDraft;
  const model=clone(current);
  model.name=$('model-name').value.trim();
  if (!model.name) throw Error('请填写车型名称');
  for (const [key,label] of Object.entries({...modelBasics,...modelMotion})) {
    const input=$('model-'+key);
    const value=Number(input.value);
    if (!input.value.trim() || !Number.isFinite(value) || value<0 || (key!=='margin' && value===0)) {
      throw Error('请填写有效的'+label);
    }
    model[key]=value;
  }
  model.turning=$('model-turning').value;
  model.capabilities=(model.capabilities||[]).filter(key=>!Object.hasOwn(capabilityNames,key));
  for (const key of Object.keys(capabilityNames)) {
    if ($('model-capability-'+key).checked) model.capabilities.push(key);
  }
  model.sensors ??= {};
  for (const [key,[label,min,max]] of Object.entries(sensorFields)) {
    const raw=$('model-sensor-'+key).value.trim();
    if (!raw) {delete model.sensors[key];continue;}
    const value=Number(raw);
    if (!Number.isFinite(value) || value<min || value>max || (key==='rays' && !Number.isInteger(value))) {
      throw Error(label+'须在 '+min+' 至 '+max+' 之间，射线数量须为整数');
    }
    model.sensors[key]=value;
  }
  const models=await api('/api/editor/models',{action:'save',model});
  applyModelList(models,creating?'':model.id);
  $('modelFeedback').textContent='车型已保存。';
});
modelAction('deleteModel',async()=>{
  if (replay || modelDraft) return;
  const id=$('model').value;
  const model=configuration.models.find(item=>item.id===id);
  if (!model) return;
  const used=configuration.instances.filter(item=>item.model_id===id);
  if (used.length) throw Error('车辆 '+used.map(item=>item.id).join('、')+' 正在使用该车型，请先为这些车辆更换车型。');
  if (documentMap.floors.some(level=>level.objects.some(object=>object.models?.includes(id)))) {
    throw Error('当前地图的通行限制使用了该车型，请先修改相关物件的允许车型。');
  }
  if (!confirm('删除车型「'+(model.name||id)+'」？')) return;
  const models=await api('/api/editor/models',{action:'delete',id});
  applyModelList(models,'');
  $('modelFeedback').textContent='车型已删除。';
});
function closeVehicleEditor() {
  vehicleDraft=null;
  $('instance').value='';
  $('instanceEditor').close();
}
function instanceForm() {
  const instance=vehicleDraft || configuration.instances.find(item=>item.id===$('instance').value);
  const form=$('instanceForm');
  form.replaceChildren();
  if (!instance) {
    if ($('instanceEditor').open) closeVehicleEditor();
    return;
  }
  $('instanceEditorTitle').textContent=vehicleDraft?'新增车辆实例':'编辑车辆 '+instance.id;
  $('instanceFeedback').textContent='';
  $('deleteInstance').hidden = !!vehicleDraft;
  $('deleteInstance').disabled = !!replay;
  $('saveInstance').disabled = !!replay;
  $('saveInstance').textContent = vehicleDraft?'确认创建车辆':'保存车辆实例';
  field(form,'车辆编号','instance-id',instance.id).autofocus=true;
  const model=inspectorChoice(form,'车型',configuration.models.map(item=>[item.id,item.name]),instance.model_id);
  model.id='instance-model_id';
  const color=inspectorChoice(form,'车身颜色',Object.entries(vehicleColors).map(([key,[label]])=>[key,label]),instance.color||'blue');
  color.id='instance-color';
  const floorChoice=inspectorChoice(form,'初始楼层',[
    ['','请选择楼层'],...documentMap.floors.map(level=>[level.id,level.name])
  ],instance.floor_id);
  floorChoice.id='instance-floor_id';
  const parkingChoice=inspectorChoice(form,'停车点',[],'');
  parkingChoice.id='instance-parking_id';
  const hintParking=document.createElement('p');
  hintParking.className='muted';
  hintParking.textContent='停车点由地图编辑器创建，每个停车点只能分配给一台车。';
  form.append(hintParking);
  const pose=field(form,'起点 x,y,角度','instance-pose',instance.pose.join(','));
  const updateParking=chosen=>{
    const level=documentMap.floors.find(item=>item.id===floorChoice.value);
    const candidates=level ? freeParkingPoints(level,configuration.instances.filter(item=>item!==instance)) : [];
    const numbers=level?parkingNumbers(level):new Map();
    const names=candidates.map(item=>[item.id,numbers.get(item.id)]);
    options('instance-parking_id',[['','待分配停车点'],...names],chosen);
    if (!parkingChoice.value) parkingChoice.value='';
  };
  updateParking(instance.parking_id);
  floorChoice.onchange=()=>updateParking('');
  parkingChoice.onchange=()=>{
    const location=documentMap.floors.find(level=>level.id===floorChoice.value)?.objects
      .find(object=>object.id===parkingChoice.value);
    if (location) pose.value=[location.x,location.y,0].join(',');
  };
  numericSetting(form,'初始电量（%）','instance-battery_percent',instance.battery_percent??100,0,100);
  numericSetting(form,'最低安全电量（%）','instance-safety_battery_percent',instance.safety_battery_percent??20,0,100);
  const hint=document.createElement('p');
  hint.className='muted';
  hint.textContent='电量不足以到站并保留安全电量时，车辆会暂缓接单。';
  form.append(hint);
  const enabled=field(form,'启用','instance-enabled','','checkbox');
  enabled.checked=instance.enabled!==false;
}
$('instanceEditor').addEventListener('cancel',event=>{
  event.preventDefault();
  closeVehicleEditor();
});
function freeParkingPoints(level,instances) {
  const reserved = new Set(instances.filter(item=>item.floor_id===level.id).map(item=>item.parking_id));
  return level.objects.filter(item=>item.kind==='parking' && !reserved.has(item.id));
}
function openVehicle(id) {
  if (replay) return;
  vehicleDraft=null;
  $('instance').value=id;
  if (!$('instance').value) return;
  instanceForm();
  $('instanceEditor').showModal();
}
function renderFleetQueue(focusId) {
  if (!documentMap || !configuration) return;
  const queue=$('fleetQueue');
  const button=$('fleetQueueButton');
  button.textContent='车辆队列（'+configuration.instances.length+' 台）';
  $('newInstance').disabled=!!replay;
  if (queue.hidden) return;
  const rows=$('fleetQueueList');
  rows.replaceChildren();
  if (!configuration.instances.length) {
    rows.textContent='还没有车辆。';
    return;
  }
  for (const instance of configuration.instances) {
    const level=documentMap.floors.find(item=>item.id===instance.floor_id);
    const parking=level?.objects.find(item=>item.kind==='parking' && item.id===instance.parking_id);
    const model=configuration.models.find(item=>item.id===instance.model_id);
    const entry=document.createElement('button');
    entry.type='button';
    entry.textContent=[instance.id,model?.name||'未选车型',level?.name||'未分配楼层',
      parking?parkingNumbers(level).get(parking.id):'待分配停车点',
      vehicleColors[instance.color||'blue']?.[0]||'蓝色',instance.enabled===false?'停用':'已启用'].join(' · ');
    entry.disabled=!!replay;
    entry.setAttribute('aria-haspopup','dialog');
    entry.setAttribute('aria-controls','instanceEditor');
    entry.onclick=()=>openVehicle(instance.id);
    rows.append(entry);
    if (instance.id===focusId) entry.focus({preventScroll:true});
  }
}
function setFleetQueueOpen(open) {
  $('fleetQueue').hidden=!open;
  $('fleetQueueButton').setAttribute('aria-expanded',String(open));
}
action('fleetQueueButton',()=>{
  setFleetQueueOpen($('fleetQueue').hidden);
  renderFleetQueue();
});
action('newInstance',()=>{
  if (!documentMap || replay) return;
  const level=floor();
  const parking=freeParkingPoints(level,configuration.instances)[0];
  const model=configuration.models.find(item=>item.id===$('model').value) || configuration.models[0];
  if (!model) throw Error('请先添加车型');
  const ids=new Set(configuration.instances.map(item=>item.id));
  let index=1;
  while (ids.has('R'+index)) index++;
  vehicleDraft={id:'R'+index,model_id:model.id,floor_id:level.id,
    pose:parking?[parking.x,parking.y,0]:[0,0,0],parking_id:parking?.id||'',
    enabled:true,battery_percent:100,safety_battery_percent:20,color:'blue'};
  $('instance').value='';
  instanceForm();
  $('instanceEditor').showModal();
});
action('cancelInstance',closeVehicleEditor);
action('saveInstance',()=>{
  if (replay) return;
  const creating=!!vehicleDraft;
  const index=configuration.instances.findIndex(item=>item.id===$('instance').value);
  if (!creating && index<0) return;
  const instance={...(vehicleDraft||configuration.instances[index])};
  for (const key of ['id','model_id','floor_id','parking_id','color']) instance[key]=$('instance-'+key).value.trim();
  instance.pose=$('instance-pose').value.split(',').map(Number);
  instance.enabled=$('instance-enabled').checked;
  if (!instance.id || !instance.model_id) throw Error('请填写车辆编号并选择车型');
  if ((creating || instance.enabled) && !instance.parking_id) throw Error('请先选择初始楼层和停车点');
  if (instance.parking_id && !documentMap.floors.some(level=>level.id===instance.floor_id &&
      level.objects.some(point=>point.kind==='parking' && point.id===instance.parking_id))) {
    throw Error('请选择该楼层的停车点');
  }
  if (instance.parking_id && configuration.instances.some((item,i)=>i!==index &&
      item.floor_id===instance.floor_id && item.parking_id===instance.parking_id)) {
    throw Error('这个停车点已分配给另一台车，每个停车点只能停一台车。');
  }
  if (configuration.instances.some((item,i)=>item.id===instance.id && i!==index)) throw Error('车辆编号重复');
  for (const key of ['battery_percent','safety_battery_percent']) {
    const raw=$('instance-'+key).value.trim(), value=Number(raw);
    if (!raw || !Number.isFinite(value) || value<0 || value>100) throw Error('初始电量和最低安全电量须在 0 至 100% 之间');
    instance[key]=value;
  }
  if (!Object.hasOwn(vehicleColors,instance.color)) throw Error('请选择车身颜色');
  checkpoint();
  editedFleetRunId=state?.run_id;
  if (creating) configuration.instances.push(instance);
  else configuration.instances[index]=instance;
  closeVehicleEditor();
  configOptions(instance.id);
  draw();
  notice((creating?'车辆已创建。':'车辆配置已更新。')+'点「保存车队配置」后保留设置。');
},message=>{$('instanceFeedback').textContent=message;});
action('deleteInstance',()=>{
  if (!documentMap || replay) return;
  if (vehicleDraft) return;
  const id = $('instance').value;
  const index = configuration.instances.findIndex(instance=>instance.id===id);
  if (index<0) return;
  checkpoint();
  editedFleetRunId=state?.run_id;
  configuration.instances.splice(index,1);
  let updatedTemplates=0;
  for (const template of configuration.templates) {
    if (template.task?.robot_id!==id) continue;
    template.task.robot_id=null;
    updatedTemplates++;
  }
  closeVehicleEditor();
  configOptions();
  $('fleetQueueButton').focus({preventScroll:true});
  draw();
  const detail = updatedTemplates ? '。'+updatedTemplates+' 个关联任务模板已改为自动分配' : '';
  notice('已删除车辆 '+id+detail+'。点击「保存车队配置」保留变更。');
});
action('saveConfig',async()=>notice(await api('/api/editor/config',configuration)));
action('start',async()=>{
  if (!documentMap.version) throw Error('请先保存地图版本');
  if (!isAvailableMapVersion(documentMap)) throw Error('当前版本已移出列表。请恢复此版本、选择可用版本或保存新版本。');
  const request = {id:documentMap.id,version:documentMap.version,previousRun:state?.run_id};
  pendingRun = request;
  try {
    await api('/api/run',{map_id:request.id,version:request.version,models:configuration.models,instances:configuration.instances});
    notice('正在准备当前地图的巡查。');
  } catch (error) {
    if (pendingRun===request) pendingRun = null;
    throw error;
  }
});
const command=data=>api('/api/cmd',data);
action('pause',()=>command({action:'pause'}));action('resume',()=>command({action:'resume'}));$('speed').onchange=()=>command({action:'set_speed',speed:Number($('speed').value)}).catch(e=>notice(e.message));
action('endRun',async()=>{
  if (replay || pendingRun || pendingEndRun || !viewingCurrentRun() || !state.started) return;
  if (!confirm('结束本次巡查？巡查记录将保存，未完成的床位可在下次巡查继续。')) return;
  const request={runId:state.run_id};
  pendingEndRun=request;
  renderState();
  try {
    const result=await command({action:'end_run',run_id:request.runId});
    request.commandId=result.command_id;
  } catch (error) {
    if (pendingEndRun===request) pendingEndRun=null;
    renderState();
    throw error;
  }
});
const taskPriorityLabels={1:'高',0:'中','-1':'低'};
function taskPriorityLevel(priority) {
  return Math.sign(Number(priority)) || 0;
}
function taskFields(){return {content:$('content').value,service:$('serviceType').value,duration:Number($('duration').value),release:Number($('release').value),priority:Number($('priority').value),deadline:$('deadline').value===''?null:Number($('deadline').value),capabilities:list($('capabilities').value),robot_id:$('assignedRobot').value||null};}
action('saveTemplate',async()=>{configuration.templates.push({name:$('templateName').value||'任务模板',task:taskFields()});await api('/api/editor/config',configuration);configOptions();});
action('useTemplate',()=>{const task=configuration.templates[Number($('template').value)]?.task;if(!task)return;for(const key of ['content','duration','release','deadline'])$(key).value=task[key]??'';$('priority').value=String(taskPriorityLevel(task.priority));$('serviceType').value=task.service;$('capabilities').value=task.capabilities.join(',');$('assignedRobot').value=task.robot_id||'';});
function taskDestinations() {
  return documentMap.floors.flatMap(level=>level.objects.filter(object=>object.kind==='service')
    .map(service=>{
      const name=service.name||service.id;
      return {id:service.id, floorId:level.id, bedId:service.bed_id||service.id,
        name, label:level.name+' / '+name};
    }));
}

const taskRoomCache=new WeakMap();
const normalizeTaskName=text=>text.trim().toLowerCase().replace(/\s*[/／]\s*/g,' / ');
const taskBedKey=(floorId,bedId)=>JSON.stringify([floorId,bedId]);

function taskRoomRegions(level) {
  // Keep door openings closed in the wall raster so adjacent rooms stay separate.
  if (![level.width,level.height].every(size=>Number.isFinite(size) && size>=1 && size<=100)) return ()=>0;
  const step=.16, columns=Math.max(1,Math.ceil(level.width/step)), rows=Math.max(1,Math.ceil(level.height/step));
  const x0=-level.width/2, y0=-level.height/2, padding=step/Math.sqrt(2);
  const regions=new Int32Array(columns*rows);
  for (const wall of level.objects.filter(object=>object.kind==='wall')) {
    const angle=(wall.rotation||0)*Math.PI/180, cos=Math.cos(angle), sin=Math.sin(angle);
    const halfWidth=wall.width/2+padding, halfHeight=wall.height/2+padding;
    const dx=Math.abs(cos)*halfWidth+Math.abs(sin)*halfHeight;
    const dy=Math.abs(sin)*halfWidth+Math.abs(cos)*halfHeight;
    const right=Math.min(columns-1,Math.floor((wall.x+dx-x0)/step));
    const top=Math.min(rows-1,Math.floor((wall.y+dy-y0)/step));
    for (let row=Math.max(0,Math.floor((wall.y-dy-y0)/step));row<=top;row++) {
      for (let col=Math.max(0,Math.floor((wall.x-dx-x0)/step));col<=right;col++) {
        const x=x0+(col+.5)*step-wall.x, y=y0+(row+.5)*step-wall.y;
        if (Math.abs(x*cos+y*sin)<=halfWidth && Math.abs(-x*sin+y*cos)<=halfHeight) {
          regions[row*columns+col]=-1;
        }
      }
    }
  }
  const queue=new Int32Array(regions.length);
  let regionCount=0;
  return (x,y)=>{
    const col=Math.floor((x-x0)/step), row=Math.floor((y-y0)/step);
    if (col<0 || col>=columns || row<0 || row>=rows) return 0;
    const start=row*columns+col;
    if (regions[start]) return Math.max(0,regions[start]);
    const region=++regionCount;
    let tail=1;
    queue[0]=start;
    regions[start]=region;
    for (let head=0;head<tail;head++) {
      const index=queue[head], column=index%columns;
      for (const next of [index-columns,index+columns,column>0?index-1:-1,column<columns-1?index+1:-1]) {
        if (regions[next]!==0) continue;
        regions[next]=region;
        queue[tail++]=next;
      }
    }
    return region;
  };
}

function taskRoomsOn(level) {
  const cached=taskRoomCache.get(level);
  if (cached?.revision===compileRevision) return cached.rooms;
  const beds=level.objects.filter(object=>object.kind==='bed');
  const doors=level.objects.filter(object=>object.kind==='door');
  const regionAt=doors.length && beds.length ? taskRoomRegions(level) : ()=>0;
  const regionByBed=new Map(beds.map(bed=>[bed,regionAt(bed.x,bed.y)]));
  const rooms=doors.map((door,index)=>{
    const number=door.room_number?.trim();
    const explicit=number?beds.filter(bed=>normalizeTaskName(bed.room_name||'')===normalizeTaskName(number)):[];
    const angle=(door.rotation||0)*Math.PI/180;
    const sideRegions=[-1,1].map(side=>{
      // Probe both sides beyond the thickness of the wall.
      for (const offset of [.25,.4,.55,.7]) {
        const distance=side*(door.height/2+offset);
        const region=regionAt(door.x-distance*Math.sin(angle),door.y+distance*Math.cos(angle));
        if (region) return region;
      }
      return 0;
    });
    let roomBeds=explicit;
    if (sideRegions.every(Boolean) && sideRegions[0]!==sideRegions[1]) {
      const candidates=sideRegions.map(region=>beds.filter(bed=>regionByBed.get(bed)===region));
      const matches=explicit.length ? candidates.filter(group=>explicit.every(bed=>group.includes(bed))) :
        candidates.filter(group=>group.length);
      if (matches.length===1) {
        roomBeds=explicit.length ? matches[0].filter(bed=>explicit.includes(bed) || !bed.room_name?.trim()) : matches[0];
      }
    }
    const bedPrefixes=new Set(roomBeds.map(bed=>{
      const service=level.objects.find(object=>object.kind==='service' && object.bed_id===bed.id);
      return (service?.name||bed.name||'').match(/^(.+)[-－]\d+$/)?.[1];
    }));
    const name=number || (bedPrefixes.size===1 && [...bedPrefixes][0]) || '门 '+(index+1);
    return {id:door.id,floorId:level.id,name,label:level.name+' / '+name,beds:roomBeds};
  });
  taskRoomCache.set(level,{revision:compileRevision,rooms});
  return rooms;
}

const taskInputLabels={bed:'床位或服务点',room:'病房',floor:'楼层'};
function taskInputChoices(type) {
  if (type==='floor') return documentMap.floors.map(level=>({id:level.id,name:level.name,label:level.name}));
  if (type==='room') return documentMap.floors.flatMap(taskRoomsOn).filter(room=>room.beds.length);
  return taskDestinations();
}

function resolveTaskChoice(value,type) {
  const query=normalizeTaskName(value);
  const matches=taskInputChoices(type).filter(item=>
    [item.name,item.label,item.id].some(text=>normalizeTaskName(text)===query));
  const label=taskInputLabels[type];
  if (!matches.length) throw Error('未找到'+label+'「'+value+'」。');
  if (matches.length>1) throw Error(label+'「'+value+'」有重复。请加上楼层，或使用选择按钮。');
  return matches[0];
}

function taskFeedback(message='', warning=false) {
  const feedback=$('taskFeedback');
  feedback.textContent=message;
  feedback.classList.toggle('task-feedback-warning',warning);
}

function refreshTaskSuggestions() {
  const type=$('taskInputType').value;
  const input=$('taskBedNumber');
  input.placeholder={bed:'如 二层 / N2-1',room:'如 二层 / N2',floor:'如 二层'}[type];
  input.setAttribute('aria-label','手动输入'+taskInputLabels[type]);
  const suggestions=[...new Set(taskInputChoices(type).map(item=>item.label))];
  $('taskBedOptions').replaceChildren(...suggestions.map(label=>new Option(label,label)));
}

function refreshTaskBeds() {
  const byId=new Map(taskDestinations().map(bed=>[bed.id,bed]));
  const items=$('taskBeds');
  items.replaceChildren();
  for (const id of taskBeds) {
    const bed=byId.get(id);
    if (!bed) {taskBeds.delete(id);continue;}
    const item=document.createElement('li');
    item.dataset.serviceId=id;
    const remove=document.createElement('button');
    remove.type='button';
    remove.textContent='移除';
    remove.setAttribute('aria-label','移除 '+bed.label);
    remove.onclick=()=>{
      taskBeds.delete(id);
      updateTaskBedSelection();
    };
    item.append(bed.label,remove);
    items.append(item);
  }
}

function selectTaskBeds(ids,missing=0) {
  const destinations=taskDestinations();
  const byId=new Map(destinations.map(bed=>[bed.id,bed]));
  const key=bed=>taskBedKey(bed.floorId,bed.bedId);
  const selected=new Map(destinations.filter(bed=>taskBeds.has(bed.id)).map(bed=>[key(bed),bed]));
  const visitsByTask=groupTaskVisits(viewingCurrentRun());
  const occupied=new Map();
  for (const record of taskRecords) {
    if (record.archived) continue;
    const visits=visitsByTask.get(record.id)||[];
    const states=taskVisitStates(record,visits);
    const completed=states.length===record.beds.length*(record.count||1) && states.every(status=>status==='completed');
    if (completed) continue;
    for (const id of record.beds) {
      const bed=byId.get(id);
      if (bed && !occupied.has(key(bed))) occupied.set(key(bed),record.display_number||record.id);
    }
  }
  const seen=new Set(), duplicates=[], warnings=[];
  for (const id of ids) {
    const bed=byId.get(id);
    if (!bed || seen.has(key(bed))) continue;
    const bedKey=key(bed);
    seen.add(bedKey);
    if (selected.has(bedKey)) {
      const existing=selected.get(bedKey);
      duplicates.push(existing.id);
      warnings.push(existing.label+' 重复选择');
    } else if (occupied.has(bedKey)) {
      warnings.push(bed.label+' 重复选择（未完成任务 '+occupied.get(bedKey)+'）');
    } else taskBeds.add(id);
  }
  if (missing) warnings.push(missing+' 个床位尚未关联床旁服务点。');
  updateTaskBedSelection();
  if (warnings.length) {
    highlightTaskBedConflicts(duplicates);
    taskFeedback(['已选 '+taskBeds.size+' 个巡检点。',...warnings].join('\n'),true);
  }
}

function selectWardBeds(beds) {
  if (!beds.length) {taskFeedback('所选范围内没有床位。',true);return;}
  const services=new Map(taskDestinations().map(bed=>[taskBedKey(bed.floorId,bed.bedId),bed.id]));
  const ids=beds.map(({floorId,bed})=>services.get(taskBedKey(floorId,bed.id))).filter(Boolean);
  selectTaskBeds(ids,beds.length-ids.length);
}

function selectTaskRoom(room) {
  selectWardBeds(room.beds.map(bed=>({floorId:room.floorId,bed})));
}

function selectTaskFloors(ids) {
  const beds=documentMap.floors.filter(level=>ids.includes(level.id))
    .flatMap(level=>level.objects.filter(object=>object.kind==='bed').map(bed=>({floorId:level.id,bed})));
  selectWardBeds(beds);
}

function highlightTaskBedConflicts(ids) {
  const conflicts=new Set(ids);
  for (const row of $('taskBeds').children) {
    row.classList.toggle('duplicate-task-bed',conflicts.has(row.dataset.serviceId));
  }
}

function updateTaskBedSelection() {
  refreshTaskBeds();
  taskFeedback('已选 '+taskBeds.size+' 个巡检点。');
  updateViewportHelp();
  draw();
}

function showTaskPanel(id, show) {
  $(id).hidden=!show;
  if (id==='taskEditor' && !show && $('taskFloorPicker').open) $('taskFloorPicker').close();
  $(id==='taskEditor'?'newTask':id+'Button').setAttribute('aria-expanded',String(show));
}

function setTaskPicking(mode) {
  taskPicking=mode;
  if (mode && (buildMode==='pan' || buildingOverview)) setBuildMode('select');
  $('pickTaskBeds').setAttribute('aria-pressed',String(mode==='bed'));
  $('pickTaskRooms').setAttribute('aria-pressed',String(mode==='room'));
  $('taskPickHint').textContent=mode==='room'?'点击画布上的病房门，将该病房的床位加入清单。':
    mode==='bed'?'点击画布上的床位或床旁服务点。':
      '可跨楼层选择。取消选择请在清单中点「移除」。';
  updateCanvasCursor();
  updateViewportHelp();
  draw();
}

function openTaskPanel(panel) {
  for (const id of ['taskEditor','savedTaskQueue']) showTaskPanel(id,id===panel);
  if (panel!=='taskEditor') setTaskPicking(false);
}
action('newTask',async()=>{
  if (replay || taskSubmitting || !documentMap) return;
  const open=$('taskEditor').hidden;
  openTaskPanel(open?'taskEditor':null);
  if (open) {
    taskRequestId ||= uid();
    refreshTaskSuggestions();
    refreshTaskBeds();
  }
  taskFeedback();
  if (open) {
    try {await loadTaskRecords();}
    catch (error) {taskFeedback(error.message);}
  }
});
action('savedTaskQueueButton',async()=>{
  const open=$('savedTaskQueue').hidden;
  openTaskPanel(open?'savedTaskQueue':null);
  renderTaskQueues(viewingCurrentRun()||!!replay);
  if (open && !replay) {
    try {await loadTaskRecords();}
    catch (error) {taskFeedback(error.message);}
  }
});
action('pickTaskBeds',()=>setTaskPicking(taskPicking==='bed'?false:'bed'));
action('pickTaskRooms',()=>setTaskPicking(taskPicking==='room'?false:'room'));
action('pickTaskFloors',()=>{
  setTaskPicking(false);
  const choices=$('taskFloorChoices');
  choices.replaceChildren();
  for (const level of documentMap.floors) {
    const label=document.createElement('label'), input=document.createElement('input');
    input.type='checkbox';
    input.value=level.id;
    label.append(input,level.name);
    choices.append(label);
  }
  $('addTaskFloors').disabled=true;
  $('taskFloorPicker').showModal();
});
$('taskFloorChoices').onchange=()=>{
  $('addTaskFloors').disabled=!$('taskFloorChoices').querySelector('input:checked');
};
$('cancelTaskFloors').onclick=()=>$('taskFloorPicker').close();
$('taskFloorForm').onsubmit=event=>{
  event.preventDefault();
  const ids=[...$('taskFloorChoices').querySelectorAll('input:checked')].map(input=>input.value);
  if (!ids.length) return;
  $('taskFloorPicker').close();
  selectTaskFloors(ids);
};
$('taskInputType').onchange=()=>{
  $('taskBedNumber').value='';
  refreshTaskSuggestions();
};
$('addTaskBed').onsubmit=event=>{
  event.preventDefault();
  try {
    const input=$('taskBedNumber');
    const type=$('taskInputType').value;
    const value=input.value.trim();
    if (!value) throw Error('请输入'+taskInputLabels[type]+'。');
    const item=resolveTaskChoice(value,type);
    if (type==='floor') selectTaskFloors([item.id]);
    else if (type==='room') selectTaskRoom(item);
    else selectTaskBeds([item.id]);
    input.value='';
  } catch(error) {taskFeedback(error.message);}
};

function readEditorTask() {
  if ($('taskBedNumber').value.trim()) throw Error('请先点「添加」将手动输入的巡检范围加入清单。');
  const beds=[...taskBeds];
  if (!beds.length) throw Error('请至少选择一个床位。');
  const count=Number($('count').value), period=Number($('period').value);
  if (!Number.isInteger(count) || count<1 || count*beds.length>1000 || !Number.isFinite(period) || period<0) {
    throw Error('每项任务最多包含 1000 个床位巡检项，发布间隔须为非负数。');
  }
  const labels=new Map(taskDestinations().map(bed=>[bed.id,bed.label]));
  return {request_id:taskRequestId,map_id:documentMap.id,beds,bed_labels:beds.map(id=>labels.get(id)),
    notes:$('taskNotes').value,
    count,period,task:taskFields()};
}

function updateTaskActions() {
  $('saveTask').disabled=taskSubmitting||!!replay;
  $('publishSelectedTasks').hidden=!taskRecords.some(record=>record.status==='saved')||!!replay;
  $('publishSelectedTasks').disabled=taskSubmitting||!!replay||!selectedSavedTasks.size;
}

async function loadTaskRecords() {
  const mapId=documentMap.id, request=++taskQueueRequest;
  clearTimeout(taskQueueTimer);
  taskQueueTimer=undefined;
  try {
    const records=await api('/api/editor/tasks?map_id='+encodeURIComponent(mapId),undefined,{cache:'no-store'});
    if (replay || documentMap.id!==mapId || request!==taskQueueRequest) return;
    const previous=new Map(taskRecords.map(record=>[record.id,record.status]));
    taskRecords=records;
    const saved=new Set(records.filter(record=>record.status==='saved').map(record=>record.id));
    for (const id of selectedSavedTasks) if (!saved.has(id)) selectedSavedTasks.delete(id);
    const resolved=records.filter(record=>
      previous.get(record.id)==='publishing' && record.status!=='publishing' ||
      previous.get(record.id)==='queued' && record.status==='published');
    const rejected=resolved.filter(record=>record.error);
    if (rejected.length) taskFeedback('发布失败，任务仍保存在队列中。'+rejected[0].error);
    else if (resolved.some(record=>!record.request_id)) taskFeedback(resolved.length+' 项任务已发布。');
    renderTaskQueues(viewingCurrentRun());
    scheduleTaskQueueRefresh();
  } catch(error) {
    if (documentMap.id===mapId && request===taskQueueRequest) scheduleTaskQueueRefresh();
    throw error;
  }
}

function scheduleTaskQueueRefresh() {
  if (replay || taskQueueTimer!==undefined) return;
  const waiting=taskRecords.some(record=>record.status==='publishing' ||
    (record.status==='queued' && viewingCurrentRun() && state.started && !state.paused &&
      record.run_id!==state.run_id));
  if (waiting) taskQueueTimer=setTimeout(()=>loadTaskRecords().catch(error=>taskFeedback(error.message)),750);
}

async function publishEditorTasks(ids, mapId) {
  if (replay || documentMap.id!==mapId || !state?.map_id || !viewingCurrentRun() || pendingRun) {
    throw Error('请先保存地图并点击「准备巡查」，再发布已保存的任务。');
  }
  const result=await api('/api/editor/tasks',{action:'publish',ids,map_id:mapId,
    map_version:documentMap.version,run_id:state.run_id});
  if (documentMap.id!==mapId || replay) return;
  taskFeedback(result.submitted?'已提交，等待仿真确认。':'所选任务已发布或正在发布。');
  await loadTaskRecords();
  const selected=taskRecords.filter(record=>ids.includes(record.id));
  const rejected=selected.find(record=>record.status==='saved' && record.error);
  if (rejected) taskFeedback('发布失败，任务仍保存在队列中。'+rejected.error);
  else if (selected.length && selected.every(record=>record.status==='published')) taskFeedback('任务已发布。');
}

async function handleTaskAction(callback) {
  if (taskSubmitting || replay) return;
  taskSubmitting=true;
  updateTaskActions();
  try {await callback();}
  catch(error) {taskFeedback(error.message,!!error.conflicts?.length);}
  finally {
    taskSubmitting=false;
    updateTaskActions();
  }
}

async function saveEditorTask() {
  const record=readEditorTask();
  let saved;
  try {
    saved=await api('/api/editor/tasks',{action:'save',record});
  } catch (error) {
    if (taskRequestId===record.request_id && error.conflicts) {
      highlightTaskBedConflicts(error.conflicts.map(item=>item.bed_id));
    }
    throw error;
  }
  if (replay || documentMap.id!==record.map_id) return;
  if (taskRequestId===record.request_id) {
    taskRequestId=null;
    $('taskNotes').value='';
    taskBeds.clear();
    refreshTaskBeds();
    openTaskPanel('savedTaskQueue');
  }
  taskRecords=[...taskRecords.filter(item=>item.id!==saved.id),saved];
  renderTaskQueues(viewingCurrentRun());
  taskFeedback('任务 '+(saved.display_number||saved.id)+' 已保存，待分配。创建时间 '+formatTaskCreation(saved.created_at)+'。');
  await loadTaskRecords();
}

$('saveTask').onclick=()=>handleTaskAction(saveEditorTask);
$('publishSelectedTasks').onclick=()=>handleTaskAction(()=>publishEditorTasks([...selectedSavedTasks],documentMap.id));

async function deleteSavedTask(record, permanent=false) {
  const number=record.display_number||record.number||record.id;
  const question=permanent || record.resumed_from ?
    '删除任务 '+number+'？该任务的巡检结果和地图标记会一并移除，删除后无法恢复。':
    record.status==='published'?'归档任务 '+number+'？归档后可在「归档管理」中查询。':
      '删除任务 '+number+' 并释放编号？';
  if (!confirm(question)) return;
  const result=await api('/api/editor/tasks',{action:permanent?'permanent_delete':'delete',id:record.id,
    map_id:record.map_id,request_id:record.request_id}).catch(error=>{
    if (permanent && error.message==='未知任务操作') {
      throw Error('当前工作台服务尚未加载删除功能，请重启服务后重试。');
    }
    throw error;
  });
  if (documentMap.id!==record.map_id || replay) return result;
  ++taskQueueRequest;
  selectedSavedTasks.delete(record.id);
  taskRecords=taskRecords.filter(task=>task.id!==record.id || task.request_id!==record.request_id);
  if (result.archived) taskRecords.push({...record,archived:true});
  else hideModelTooltip();
  renderTaskQueues(viewingCurrentRun());
  taskFeedback(result.archived?'任务 '+number+' 已归档。':
    result.deleted?(permanent?'已删除任务 '+number+'。':'已删除任务 '+number+'，编号已释放。'):
      '任务 '+number+' 已不在队列中。');
  return result;
}

const taskQueueStatus={pending:'待分配',assigned:'执行中',completed:'已完成',cancelled:'已取消',expired:'已超时'};
function setTaskQueueCount(id,label,count) {
  const button=$(id+'Button');
  const title=label+'（'+count+' 项）';
  if (button.textContent!==title) button.textContent=title;
}

function groupTaskVisits(visible) {
  const groups=new Map(), specs=state?.task_specs||{};
  for (const task of visible?state?.tasks||[]:[]) {
    const spec=specs[task.task_id]||{};
    const id=spec.patrol_id||task.task_id;
    if (!groups.has(id)) groups.set(id,[]);
    groups.get(id).push({task,spec});
  }
  return groups;
}

function taskVisitStates(record,visits) {
  return visits.length?[...Object.values(record.retained_visit_states||{}),...visits.map(({task})=>task.status)]:
    record.visit_states||[];
}

function renderTaskQueues(visible) {
  const saved=replay?[]:taskRecords;
  const records=saved.filter(record=>!record.archived);
  const groups=groupTaskVisits(visible);
  const known=new Set(saved.map(record=>record.id));
  for (const [id,visits] of groups) {
    // Published queue records are authoritative. Runtime visits alone cannot recreate a deleted record.
    const editorId=/^(PATROL-\d{8}-\d{4,}|TASK-[a-f0-9]{32})$/.test(id);
    if (!known.has(id) && (replay || !editorId)) {
      const task=visits[0].spec;
      records.push({id,status:'published',task,display_number:task.display_number});
    }
  }
  setTaskQueueCount('savedTaskQueue','任务队列',records.length);
  if (!$('savedTaskQueue').hidden) renderSavedTasks(records,groups);
}

function renderSavedTasks(records,groups) {
  const rows=$('savedTaskRows');
  const statuses={saved:'未发布',queued:'待分配',publishing:'发布中',published:'已发布'};
  const labelsById=new Map(taskDestinations().map(bed=>[bed.id,bed.label]));
  const reasons=state?.wait_reasons||{};
  const waiting=viewingCurrentRun() && state.started
    ? (state.paused?'巡查已暂停':'等待调度检查') : '等待启动巡查';
  const key=JSON.stringify([state?.run_id,!!replay,waiting,records,[...labelsById],[...groups],reasons]);
  if (rows.dataset.renderKey===key) return;
  const opened=new Set([...rows.querySelectorAll('details[open]')].map(item=>item.dataset.task));
  rows.dataset.renderKey=key;
  rows.replaceChildren();
  if (!records.length) rows.textContent='暂无保存的任务。';
  for (const record of records) {
    const row=document.createElement('div');
    const detail=document.createElement('details');
    detail.dataset.task=record.id;
    detail.open=opened.has(record.id);
    const summary=document.createElement('summary');
    const displayNumber=record.display_number||record.id;
    const visits=groups.get(record.id)||[];
    const visitStates=taskVisitStates(record,visits);
    const total=(record.beds?.length||0)*(record.count||1)||visitStates.length;
    const done=visitStates.filter(status=>status==='completed').length;
    const ended=total>0 && visitStates.length===total &&
      visitStates.every(value=>['completed','cancelled','expired'].includes(value));
    let status=record.request_id && record.status!=='published'?'待分配':statuses[record.status];
    if (record.completed || (total && done===total)) status='已完成';
    else if (visitStates.includes('assigned')) status='执行中';
    else if (visitStates.includes('pending')) status='待分配';
    else if (ended && visitStates.every(value=>value==='cancelled')) status='已取消';
    else if (ended && visitStates.every(value=>value==='expired')) status='已超时';
    else if (ended) status='已结束（部分床位未完成）';
    if (record.bed_conflicts?.length && !visits.length) status+=' · 床位冲突';
    const progress=done+' / '+total;
    summary.textContent=[displayNumber,record.task.content||'巡查',status,progress].join(' · ');
    if (record.status==='saved' && !replay) {
      const label=document.createElement('label');
      const checkbox=document.createElement('input');
      checkbox.type='checkbox';
      checkbox.checked=selectedSavedTasks.has(record.id);
      checkbox.onchange=()=>{
        if (checkbox.checked) selectedSavedTasks.add(record.id);
        else selectedSavedTasks.delete(record.id);
        updateTaskActions();
      };
      label.append(checkbox,' 选择发布');
      checkbox.setAttribute('aria-label','选择发布 '+displayNumber);
      row.append(label);
    }
    detail.append(summary);
    appendTaskRecordDetails(detail,record,{displayNumber,status,progress,showBeds:!visits.length,waiting});
    if (visits.length) appendTaskVisitDetails(detail,visits,labelsById,reasons,waiting);
    if (!replay && record.map_id) {
      const remove=document.createElement('button');
      remove.type='button';
      const actionLabel=record.status==='published'?'归档任务':'删除任务';
      remove.textContent=actionLabel;
      remove.setAttribute('aria-label',actionLabel+' '+displayNumber);
      remove.disabled=!['saved','queued'].includes(record.status) && !(record.status==='published' && ended);
      remove.onclick=()=>handleTaskAction(()=>deleteSavedTask(record));
      const actions=document.createElement('div');
      actions.className='bar';
      actions.append(remove);
      if (record.status==='published' && ended) {
        const permanentDelete=document.createElement('button');
        permanentDelete.type='button';
        permanentDelete.className='delete-task';
        permanentDelete.textContent='删除任务';
        permanentDelete.setAttribute('aria-label','删除任务 '+displayNumber);
        permanentDelete.onclick=()=>handleTaskAction(()=>deleteSavedTask(record,true));
        actions.append(permanentDelete);
      }
      detail.append(actions);
      if (remove.disabled) {
        const hint=document.createElement('p');
        hint.className='muted';
        hint.textContent='任务结束后可从队列移除。';
        detail.append(hint);
      }
    }
    row.append(detail);
    rows.append(row);
  }
  updateTaskActions();
}

function formatTaskCreation(timestamp) {
  return timestamp?new Date(timestamp).toLocaleString():'';
}

function appendTaskRecordDetails(parent,record,{displayNumber,status,progress,showBeds,waiting}) {
  const metadata=document.createElement('dl');
  metadata.className='task-detail-fields';
  const fields=[['任务编号',displayNumber],['优先级',taskPriorityLabels[taskPriorityLevel(record.task.priority)]],
    ['截止时间',record.task.deadline==null?'未设置':record.task.deadline+' 仿真秒'],
    ['整单状态',status],['完成床位数',progress]];
  if (record.created_at) fields.push(['创建时间',formatTaskCreation(record.created_at)]);
  for (const [label,value] of fields) {
    const title=document.createElement('dt'), text=document.createElement('dd');
    title.textContent=label;
    text.textContent=value;
    metadata.append(title,text);
  }
  parent.append(metadata);
  if (record.notes) {
    const notes=document.createElement('p');
    notes.textContent='备注 '+record.notes;
    notes.style.whiteSpace='pre-wrap';
    parent.append(notes);
  }
  const items=document.createElement('ul');
  items.className='task-list';
  const conflicts=new Map((record.bed_conflicts||[]).map(item=>[item.bed_id,item.task_number]));
  for (const [index,label] of (showBeds?record.bed_labels||[]:[]).entries()) {
    const item=document.createElement('li');
    const owner=conflicts.get(record.beds[index]);
    const reason=owner?'重复选择（未完成任务 '+owner+'）':
      status.startsWith('待分配')?(record.error||waiting):'';
    item.textContent=[label,reason].filter(Boolean).join(' · ');
    if (owner) item.classList.add('duplicate-task-bed');
    items.append(item);
  }
  if (showBeds) parent.append(items);
  if (record.error) {
    const error=document.createElement('p');
    error.textContent=record.error;
    parent.append(error);
  }
}

function appendTaskVisitDetails(detail,visits,labelsById,reasons,waiting) {
  const items=document.createElement('ul');
  items.className='task-list';
  for (const {task,spec} of visits) {
    const item=document.createElement('li');
    const title=document.createElement('strong');
    title.textContent=labelsById.get(task.bed_id)||task.bed_id;
    const info=document.createElement('p');
    const reason=reasons[task.task_id]||(task.status==='pending'?waiting:'');
    const planned=task.status==='pending'?state?.dispatch_plan?.[task.task_id]:null;
    info.textContent=[task.robot_id||(planned?'预排 '+planned.robot_id+' · 队列第 '+planned.sequence+' 床':'未分配车辆'),
      taskQueueStatus[task.status]||task.status,
      planned?'预计仿真第 '+planned.estimated_finish+' 秒完成（含服务时间估计）':'',
      planned?.elevator_rides!=null?(planned.elevator_rides?'预计乘梯 '+planned.elevator_rides+' 次':'同层执行，无需乘梯'):'',
      planned?.elevator_wait_budget?'等梯预算 '+Math.round(planned.elevator_wait_budget)+' 秒':'',
      planned?.group_id?'床位组 '+planned.group_id:'',
      planned?.deadline_risk?'预计超过截止时间':'',reason].filter(Boolean).join(' · ');
    item.append(title,info);
    if (!replay && task.status!=='completed') {
      const buttons=document.createElement('div');
      buttons.className='bar';
      const actions=[['取消','cancel_task'],['重试','retry_task']];
      if (spec.service==='manual' && task.status==='assigned') actions.unshift(['确认','confirm_service']);
      for (const [label,action] of actions) {
        const button=document.createElement('button');
        button.type='button';
        button.textContent=label;
        button.onclick=()=>command({action,task_id:task.task_id}).catch(error=>taskFeedback(error.message));
        buttons.append(button);
      }
      item.append(buttons);
    }
    items.append(item);
  }
  detail.append(items);
}

function matchesCurrentMapRun() {
  return !!state && !!documentMap?.version &&
    (state.map_id||'corridor')===documentMap.id && (state.map_version||1)===documentMap.version;
}
function viewingCurrentRun() {
  return matchesCurrentMapRun() && !state.ended;
}
function editorRunStatus() {
  if (replay) return '巡查回放 · '+mapDisplayName(documentMap)+' · 仿真时间 '+Math.floor(state?.elapsed||0)+' 秒';
  if (!documentMap.version) return '正在编辑地图。保存新版本后可准备巡查。';
  if (matchesCurrentMapRun() && state.ended) return '巡查已结束 · 已运行 '+Math.floor(state.elapsed)+' 秒 · 可在历史回放中查看';
  if (pendingEndRun && pendingEndRun.runId===state?.run_id) return '正在结束巡查并保存记录…';
  if (!viewingCurrentRun() || !state.started) {
    return state?.map_id && viewingCurrentRun()
      ? '已准备巡查。发布任务后自动开始计时，也可在运行监控中手动启动。'
      : '地图已保存。需要仿真时，点「准备巡查」。';
  }
  const planning=state.planning;
  const planText=planning?.status==='planning'?' · 正在预排剩余床位（已排 '+planning.planned+' 床）':
    planning?.status==='ready' && planning.planned?' · 已预排 '+planning.planned+' 床 · 计算 '+planning.computation_ms+' ms · 虚线为预排路线':'';
  return (state.paused?'巡查已暂停':'巡查进行中')+' · 已运行 '+Math.floor(state.elapsed)+' 秒'+planText;
}
const elevatorModes={enabled:'可用',out_of_service:'停用',fault:'故障'};
const elevatorPhases={idle:'停靠',repositioning:'空梯接车',permission:'已放行',boarding:'等待同乘',riding:'载客运行',at_exit:'等待出梯',exiting:'车辆正在出梯'};
function updateElevatorExitOptions() {
  const lift=state?.elevators?.find(item=>item.id===$('runningElevator').value);
  const choice=$('runningElevatorExit');
  const selected=choice.value;
  options('runningElevatorExit',(lift?.service_floor_ids||[]).map(id=>[id,documentMap.floors.find(f=>f.id===id)?.name||id]));
  if (lift?.service_floor_ids.includes(selected)) choice.value=selected;
}
$('runningElevator').onchange=updateElevatorExitOptions;
function renderElevatorMonitor(visible) {
  const lifts=visible?state?.elevators||[]:[];
  $('elevatorMonitor').hidden=!lifts.length;
  if (!lifts.length) return;
  const floorName=id=>documentMap.floors.find(f=>f.id===id)?.name||id;
  const status=lifts.map(lift=>{
    const location=lift.floor_id?floorName(lift.floor_id):
      floorName(lift.origin_floor_id)+' → '+floorName(lift.destination_floor_id)+'（'+Math.round((lift.progress||0)*100)+'%）';
    const waits=Object.entries(state.elevator_wait_risk?.[lift.id]||{}).map(([floor,risk])=>
      floorName(floor)+' 等梯预算 '+Math.round(risk.budget_seconds)+' 秒（'+
      (risk.source==='observed_quantile'?'历史分位数，'+risk.samples+' 次观测':'配置区间，观测不足')+'）').join('，');
    const riders=lift.occupant_robot_ids || (lift.occupant_robot_id ? [lift.occupant_robot_id] : []);
    return [lift.name||lift.id,location,elevatorModes[lift.mode],elevatorPhases[lift.phase],waits,
      lift.external_busy_until>state.elapsed?'共享占用剩余 '+Math.ceil(lift.external_busy_until-state.elapsed)+' 秒':'',
      lift.service_direction===1?'上行批次':lift.service_direction===-1?'下行批次':'',
      riders.length?'乘车 '+riders.join('、'):'',
      lift.waiting_robot_ids.length?'候梯 '+lift.waiting_robot_ids.join('、'):'',
      lift.blocked_exit_floors.length?'出口堵塞 '+lift.blocked_exit_floors.map(floorName).join('、'):''].filter(Boolean).join(' · ');
  }).join('\n');
  if ($('elevatorStatus').textContent!==status) $('elevatorStatus').textContent=status;
  $('elevatorControls').hidden=!!replay;
  const picker=$('runningElevator');
  const ids=lifts.map(item=>item.id);
  const key=JSON.stringify([state.run_id,ids]);
  if (picker.dataset.lifts!==key) {
    const selected=picker.value;
    options('runningElevator',lifts.map(lift=>[lift.id,lift.name||lift.id]),ids.includes(selected)?selected:ids[0]);
    picker.dataset.lifts=key;
    updateElevatorExitOptions();
  }
  $('elevatorTimeline').href='/api/run-elevators?run_id='+encodeURIComponent(state.run_id);
}
for (const [id,mode] of [['enableElevator','enabled'],['disableElevator','out_of_service'],['faultElevator','fault']]) {
  action(id,()=>command({action:'set_elevator_state',run_id:state.run_id,elevator_id:$('runningElevator').value,mode}));
}
for (const [id,blocked] of [['blockElevatorExit',true],['freeElevatorExit',false]]) {
  action(id,()=>command({action:'set_elevator_exit_blocked',run_id:state.run_id,
    elevator_id:$('runningElevator').value,floor_id:$('runningElevatorExit').value,blocked}));
}
for (const [id,clear] of [['simulateElevatorTraffic',false],['clearElevatorTraffic',true]]) {
  action(id,()=>command({action:'set_elevator_traffic',run_id:state.run_id,elevator_id:$('runningElevator').value,
    busy_for:clear?0:Number($('elevatorTrafficSeconds').value)}));
}
let pendingPolicyCommand=null;
action('applyDispatchPolicy',async()=>{
  if (replay || !viewingCurrentRun()) throw Error('请先准备当前地图的巡查运行');
  const policy={};
  for (const input of $('dispatchPolicyPanel').querySelectorAll('[data-policy-key]')) {
    if (input.value==='' || !input.checkValidity()) throw Error('请填写有效的调度参数');
    policy[input.dataset.policyKey]=Number(input.value);
  }
  const result=await command({action:'set_dispatch_policy',run_id:state.run_id,policy});
  pendingPolicyCommand={id:result.command_id,run_id:state.run_id};
  $('dispatchPolicyFeedback').textContent='已提交，等待运行器复核。';
});
function renderDispatchPolicy(current) {
  const panel=$('dispatchPolicyPanel');
  const prepared=current && !replay && !!state?.map_id;
  const policy=prepared?state.dispatch_policy:null;
  const hint=$('dispatchPolicyUnavailable');
  $('dispatchPolicyForm').hidden=!policy;
  hint.hidden=!!policy;
  if (!policy) {
    let message='请先在「车队配置」中点击「准备当前地图」。准备完成后即可调整调度偏好。';
    if (prepared) message='当前运行未提供调度参数。请确认服务版本后重新准备巡查。';
    else if (!documentMap?.version) message='请先保存地图，再到「车队配置」中点击「准备当前地图」。';
    if (hint.textContent!==message) hint.textContent=message;
    return;
  }
  const stamp=state.run_id+JSON.stringify(policy);
  if (panel.dataset.policy!==stamp && !panel.contains(document.activeElement)) {
    for (const input of panel.querySelectorAll('[data-policy-key]')) input.value=policy[input.dataset.policyKey];
    panel.dataset.policy=stamp;
  }
  $('applyDispatchPolicy').disabled=!!replay;
  for (const input of panel.querySelectorAll('[data-policy-key]')) input.disabled=!!replay;
  if (pendingPolicyCommand?.run_id===state.run_id) {
    const event=state.events?.findLast(item=>item.command_id===pendingPolicyCommand.id &&
      ['command_applied','command_rejected'].includes(item.event));
    if (event) {
      $('dispatchPolicyFeedback').textContent=event.event==='command_applied'?'已应用到当前运行。':event.reason;
      pendingPolicyCommand=null;
    }
  }
}
function renderPassageMonitor(visible) {
  const passages=visible?state?.passages||[]:[];
  $('passageMonitor').hidden=!passages.length;
  if (!passages.length) return;
  const text=passages.map(item=>{
    const floorName=documentMap.floors.find(f=>f.id===item.floor_id)?.name||item.floor_id;
    return [floorName+' / '+item.name,item.exit_blocked?'出口堵塞':'出口可用',
      item.occupant_robot_id?'占用 '+item.occupant_robot_id:'空闲',
      item.waiting_robot_ids.length?'等待 '+item.waiting_robot_ids.join('、'):''].filter(Boolean).join(' · ');
  }).join('\n');
  if ($('passageStatus').textContent!==text) $('passageStatus').textContent=text;
  $('passageControls').hidden=!!replay;
  const picker=$('runningPassage');
  const key=JSON.stringify([state.run_id,passages.map(item=>item.id)]);
  if (picker.dataset.passages!==key) {
    options('runningPassage',passages.map(item=>[item.id,item.name]),
      passages.some(item=>item.id===picker.value)?picker.value:passages[0].id);
    picker.dataset.passages=key;
  }
}
for (const [id,blocked] of [['blockPassageExit',true],['freePassageExit',false]]) {
  action(id,()=>command({action:'set_passage_exit_blocked',run_id:state.run_id,
    passage_id:$('runningPassage').value,blocked}));
}
function robotPerceptionView() {
  return (typeof workspaceAllowsPerceptionView!=='function'||workspaceAllowsPerceptionView()) && !$('perceptionMonitor').hidden && $('perceptionView').value==='robot';
}

function updatePerceptionSelection() {
  if (robotPerceptionView()) {
    const robot=state?.robots?.find(item=>item.id===$('perceptionRobot').value);
    if (robot?.floor_id && robot.floor_id!==floor().id) {
      $('floor').value=robot.floor_id;
      $('floor').onchange();
    }
  }
  renderState();
}
$('perceptionView').onchange=updatePerceptionSelection;
$('perceptionRobot').onchange=updatePerceptionSelection;

function pickObstaclePosition(point) {
  $('sceneObstacleX').value=point[0].toFixed(2);
  $('sceneObstacleY').value=point[1].toFixed(2);
  pickingObstaclePosition=false;
  $('pickObstaclePosition').setAttribute('aria-pressed','false');
  $('sceneObstacleResult').textContent='已选 '+floor().name+' 的位置。';
}
action('pickObstaclePosition',()=>{
  pickingObstaclePosition=!pickingObstaclePosition;
  $('pickObstaclePosition').setAttribute('aria-pressed',String(pickingObstaclePosition));
  $('sceneObstacleResult').textContent=pickingObstaclePosition?'请在当前楼层画布点击位置。':'';
});
$('sceneObstacleKind').onchange=()=>{
  const kind=$('sceneObstacleKind').value;
  $('sceneExtra').hidden=kind==='cart';
  $('sceneExtraXLabel').textContent=kind==='person'?'终点 X（可选）':'封路宽（米）';
  $('sceneExtraYLabel').textContent=kind==='person'?'终点 Y（可选）':'封路深（米）';
};

function sceneNumber(id) {
  const value=$(id).value.trim();
  if (!value || !Number.isFinite(Number(value))) throw Error('请填写有效的米制坐标或尺寸');
  return Number(value);
}
async function sendSceneCommand(remove) {
  if (replay || !viewingCurrentRun() || !state?.perception) throw Error('请先准备当前地图的巡查');
  const id=$('sceneObstacleId').value.trim();
  const kind=$('sceneObstacleKind').value;
  const action=kind==='closure'?(remove?'clear_road_closure':'set_road_closure'):(remove?'remove_obstacle':'upsert_obstacle');
  const input={action,id,run_id:state.run_id};
  if (!remove) {
    Object.assign(input,{kind,floor_id:floor().id,x:sceneNumber('sceneObstacleX'),y:sceneNumber('sceneObstacleY')});
    if (kind==='closure') Object.assign(input,{width:sceneNumber('sceneExtraX'),height:sceneNumber('sceneExtraY')});
    if (kind==='person' && ($('sceneExtraX').value || $('sceneExtraY').value)) {
      input.target=[sceneNumber('sceneExtraX'),sceneNumber('sceneExtraY')];
    }
  }
  const result=await command(input);
  pendingSceneCommand={id:result.command_id,run_id:input.run_id};
  $('sceneObstacleResult').textContent='已提交，等待仿真步生效。';
}
for (const [id,remove] of [['saveSceneObstacle',false],['removeSceneObstacle',true]]) {
  action(id,async()=>{
    try {await sendSceneCommand(remove);}
    catch(error) {$('sceneObstacleResult').textContent=error.message;}
  });
}

function renderPerceptionMonitor(visible) {
  const observations=visible?state?.perception:null;
  $('perceptionMonitor').hidden=!observations;
  if (!observations) return;
  $('obstacleControls').hidden=!!replay;
  const pick=$('perceptionRobot'), ids=Object.keys(observations);
  const key=JSON.stringify(ids);
  if (pick.dataset.robots!==key) {
    options('perceptionRobot',ids.map(id=>[id,id]),ids.includes(pick.value)?pick.value:ids[0]||'');
    pick.dataset.robots=key;
  }
  const local=observations[pick.value], scan=local?.scan;
  const metrics=robotPerceptionView()?null:state.perception_metrics?.[pick.value];
  const text=[pick.value,local?.decision,
    scan?'扫描步 '+scan.step:'等待扫描',
    robotPerceptionView()?'绿格为空闲，橙格为观测到的移动障碍，其余未确认':'全景显示场景障碍与管理封路',
    metrics?.min_clearance!=null?'最小间距 '+metrics.min_clearance+' m':'',
    metrics?'接触步 '+metrics.contact_steps+' · 动态障碍拦截 '+metrics.truth_interventions+' · 多车联锁 '+(metrics.vehicle_guard_steps||0):''].filter(Boolean).join(' · ');
  if ($('perceptionStatus').textContent!==text) $('perceptionStatus').textContent=text;
  if (pendingSceneCommand && pendingSceneCommand.run_id===state.run_id) {
    const event=state.events?.findLast(item=>item.command_id===pendingSceneCommand.id &&
      ['command_applied','command_rejected'].includes(item.event));
    if (event) {
      $('sceneObstacleResult').textContent=event.event==='command_rejected'?event.reason:'已在仿真步 '+event.step+' 生效。';
      pendingSceneCommand=null;
    }
  }
}

function renderState() {
  if (!documentMap) return;
  const current = viewingCurrentRun();
  const status = $('runtime');
  const message = editorRunStatus();
  if (status.textContent!==message) status.textContent = message;
  const controlsLocked=!!replay || !current || !!pendingRun || !!pendingEndRun;
  $('pause').disabled = controlsLocked || !state?.started || !!state.paused;
  $('resume').disabled = controlsLocked || (!state?.map_id && !state?.started) || (!!state?.started && !state.paused);
  $('resume').textContent = state?.started || state?.ended ? '继续' : '启动巡查';
  $('endRun').disabled = controlsLocked || !state?.started;
  $('speed').disabled = controlsLocked;
  const visible = current || !!replay;
  const batteryText = visible ? (state?.robots||[]).filter(robot=>typeof robot.battery_percent==='number')
    .map(robot=>robot.id+' 电量 '+robot.battery_percent+'%（最低 '+robot.safety_battery_percent+'%）').join(' · ') : '';
  const fleet=$('fleetBattery');
  if (fleet.textContent!==batteryText) fleet.textContent=batteryText;
  const coverage=visible?state?.floor_coverage:null;
  const floorName=id=>documentMap.floors.find(item=>item.id===id)?.name||id;
  const coverageText=coverage?[
    '楼层驻留：'+Object.entries(coverage.counts).map(([id,count])=>floorName(id)+' '+count+' 台').join('，'),
    coverage.ready_counts?'可接单：'+Object.entries(coverage.ready_counts).map(([id,count])=>
      floorName(id)+' '+count+' 台 / 目标 '+coverage.target_counts[id]+' 台').join('，'):'',
    coverage.vacancy_seconds?Object.entries(coverage.vacancy_seconds).filter(([,seconds])=>seconds>0)
      .map(([id,seconds])=>floorName(id)+' 服务空窗 '+Math.floor(seconds)+' 秒').join('，'):'',
    coverage.moves.length?'正在补位：'+coverage.moves.map(move=>move.robot_id+' → '+floorName(move.floor_id)).join('，'):'',
    coverage.preparing?'正在计算缺车楼层的补位路线':'',
    coverage.projected_missing_floors.length?'预计缺车楼层：'+coverage.projected_missing_floors.map(floorName).join('、'):'',
    coverage.reason||(coverage.robot_shortage?'机器人少于楼层数，至少 '+coverage.robot_shortage+' 层无法同时驻留':'')].filter(Boolean).join(' · '):'';
  if ($('floorCoverage').textContent!==coverageText) $('floorCoverage').textContent=coverageText;
  renderDispatchPolicy(current);
  renderTaskQueues(visible);
  renderElevatorMonitor(visible);
  renderPassageMonitor(visible);
  renderPerceptionMonitor(visible);
  scheduleTaskQueueRefresh();
  $('events').textContent=visible && (replay || state?.started)
    ? (state.events||[]).slice(-35).map(e=>`${e.event_id} 步${e.step} ${e.event} ${e.task_id||''} ${e.reason||''}`).join('\n') : '';
  draw();
}
action('refreshRuns',async()=>options('runs',(await api('/api/runs')).map(id=>[id,id])));
function cancelReplayLoad() {replayRequest++;replayLoading=false;}
function captureReplayDraft() {
  return {floor:floor().id,selected,beds:[...taskBeds],mapId:taskMapId,requestId:taskRequestId,
    notes:$('taskNotes').value,taskOpen:!$('taskEditor').hidden,queueOpen:!$('savedTaskQueue').hidden,
    inspector:[...$('inspector').querySelectorAll('input[id],select[id],textarea[id]')].map(input=>
      ({id:input.id,value:input.value,checked:input.checked}))};
}
action('loadReplay',async()=>{
  const request=++replayRequest;replayLoading=true;
  if(typeof renderWorkbench==='function')renderWorkbench();
  try {
    const loaded=await api('/api/replay?run_id='+encodeURIComponent($('runs').value));
    if(request!==replayRequest)return;
    if(!replay){runningMap=clone(documentMap);replayDraft=captureReplayDraft();}
    replay=loaded;
    if(replay.map.floors)documentMap=clone(replay.map);
    else {
      const old=replay.map;
      documentMap={id:old.map_id||'corridor',version:old.version||1,name:'历史运行',floors:[{id:'F1',name:'一层',width:22,height:18,
        objects:[...old.boxes.map((b,i)=>({id:'old-'+i,kind:'furniture',x:b.x,y:b.y,width:b.sx,height:b.sy,rotation:0})),
          ...old.stops.map(([id,p])=>({id,kind:'service',x:p[0],y:p[1],width:.2,height:.2,rotation:0}))]}]};
    }
    $('replaySlider').max=Math.max(0,replay.snapshots.length-1);$('replaySlider').value=0;selected=null;
    refresh();await compile();if(request===replayRequest)showReplay();
  } finally {
    if(request===replayRequest){replayLoading=false;if(typeof renderWorkbench==='function')renderWorkbench();}
  }
});
function showReplay(){if(!replay)return;const index=Number($('replaySlider').value);state=clone(replay.snapshots[index]||{});if(!state.robots){notice('该运行没有保存快照');return;}state.events=replay.events.filter(e=>e.step<=state.step);$('replayInfo').textContent=`原地图版本 ${documentMap.version} · 快照 ${index+1}/${replay.snapshots.length}`;renderState();}
$('replaySlider').oninput=showReplay;
action('exitReplay',async()=>{
  cancelReplayLoad();replay=null;if(runningMap)documentMap=runningMap;runningMap=null;
  const draft=replayDraft;replayDraft=null;selected=draft?.selected||null;refresh(draft?.floor);
  if(draft) {
    taskBeds.clear();for(const bed of draft.beds)taskBeds.add(bed);
    taskMapId=draft.mapId;taskRequestId=draft.requestId;$('taskNotes').value=draft.notes;
    showTaskPanel('taskEditor',draft.taskOpen);showTaskPanel('savedTaskQueue',draft.queueOpen);refreshTaskBeds();
    for(const value of draft.inspector){const input=$(value.id);if(input){input.value=value.value;if(input.type==='checkbox')input.checked=value.checked;}}
  }
  await compile();
});
async function initialize(){
  [versions,configuration]=await Promise.all([api('/api/maps'),api('/api/editor/config')]);
  const lastSelected=localStorage.getItem('ward-editor-map-version');
  const corridor=versions.filter(m=>m.id==='corridor').sort((a,b)=>b.version-a.version);
  const initialMap=versions.find(m=>mapVersionKey(m)===lastSelected)||corridor[0]||versions[0];
  documentMap=initialMap ? clone(initialMap) : await api('/api/maps/blank',{name:'自定义病区'});
  delete documentMap.display_name;mapOptions();refresh();configOptions();await compile();
  notice('选择已有版本或从空白地图开始。保存地图后配置车辆并预览。');
  const events=new EventSource('/api/stream');
  events.onopen=()=>{if(typeof workspaceSetConnection==='function')workspaceSetConnection(true);};
  events.onerror=()=>{if(typeof workspaceSetConnection==='function')workspaceSetConnection(false);};
  events.onmessage=event=>{
    if(replay)return;
    const previous=state;
    state=JSON.parse(event.data);
    if(state.error){notice(state.error);return;}
    if(pendingEndRun) {
      const result=pendingEndRun.commandId && state.events?.findLast(item=>
        item.command_id===pendingEndRun.commandId && item.event==='command_rejected');
      if(result || state.ended || state.run_id!==pendingEndRun.runId) pendingEndRun=null;
      if(result) notice(result.reason==='unsupported command'
        ? '当前工作台服务尚未加载结束功能，请重启服务后重试。' : result.reason);
    }
    if(state.ended && matchesCurrentMapRun() && (!previous?.ended || previous.run_id!==state.run_id)) {
      notice('本次巡查已结束，记录已保存。');
      loadTaskRecords().catch(error=>taskFeedback(error.message));
    }
    if(pendingRun&&state.run_id!==pendingRun.previousRun&&state.map_id===pendingRun.id&&state.map_version===pendingRun.version){
      pendingRun=null;notice('已准备巡查。发布任务后，仿真才会开始计时。');
    }
    if(state.robots)renderState();
  };
}
window.addEventListener('DOMContentLoaded',()=>initialize().catch(error=>notice(error.message)),{once:true});
