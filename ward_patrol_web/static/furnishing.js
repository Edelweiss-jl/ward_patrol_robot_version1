/* Direct manipulation tools for furnishing a ward floor. */
const catalogItems = [
  {key:'bed',kind:'bed',name:'病床',width:1.05,height:2.1,color:'#75b4c1'},
  {key:'nurse_station',kind:'furniture',name:'医护站',width:3,height:1.4,color:'#78a998'},
  {key:'wall',kind:'wall',name:'隔墙',width:3,height:.2,color:'#607984'},
  {key:'door',kind:'door',name:'门',width:1.2,height:.2,color:'#bf935c'},
  {key:'cabinet',kind:'furniture',name:'床头柜',width:.5,height:.5,color:'#c29f78'},
  {key:'medicine',kind:'furniture',name:'药品柜',width:1.2,height:.5,color:'#8db7b1'},
  {key:'desk',kind:'furniture',name:'诊疗桌',width:1.5,height:.8,color:'#c7ac88'},
  {key:'chair',kind:'furniture',name:'座椅',width:.55,height:.55,color:'#85a5c4'},
  {key:'bench',kind:'furniture',name:'候诊长椅',width:1.8,height:.65,color:'#85a5c4'},
  {key:'equipment',kind:'furniture',name:'医疗设备',width:.65,height:.65,color:'#a4bbc3'},
  {key:'sink',kind:'furniture',name:'洗手台',width:.8,height:.6,color:'#c7dce1'},
  {key:'parking',kind:'parking',name:'机器人停车位',width:.6,height:.6,color:'#7795b8'},
  {key:'service',kind:'service',name:'服务点',width:.25,height:.25,color:'#4baf84'},
  {key:'elevator',kind:'elevator',name:'电梯入口',width:1.8,height:1.8,color:elevatorAccent},
  {key:'waiting',kind:'waiting',name:'候梯点',width:.35,height:.35,color:'#c6ad64'},
  {key:'exit',kind:'exit',name:'出梯区域',width:1.8,height:1.8,color:'#7eb2b6'},
  {key:'single_lane',kind:'single_lane',name:'单车窄通道',width:3,height:1.3,color:'#9aa9d8'}
];
let buildMode='select', buildingGesture=null, catalogDrag=null, ghostObject=null, activeCard=null;
const originalDraw=draw, originalPointerDown=canvas.onpointerdown;
const originalPointerMove=canvas.onpointermove, originalPointerUp=canvas.onpointerup;

function symbol(context,item,width,height) {
  const w=width,h=height;
  context.fillStyle=item.color;context.strokeStyle='#385461';context.lineWidth=Math.max(1,Math.min(w,h)*.025);
  context.fillRect(-w/2,-h/2,w,h);context.strokeRect(-w/2,-h/2,w,h);
  if(item.key==='bed') {
    context.fillStyle='#edf6f5';context.fillRect(-w*.4,-h*.4,w*.8,h*.22);
    context.fillStyle='#d8eaec';context.fillRect(-w*.4,-h*.08,w*.8,h*.43);
    context.strokeRect(-w*.4,-h*.08,w*.8,h*.43);
    context.fillStyle='#547f8d';context.fillRect(-w*.5,h*.43,w,h*.07);
  } else if(item.key==='nurse_station'||item.key==='desk') {
    context.fillStyle='#e6efe8';context.fillRect(-w*.4,-h*.36,w*.8,h*.7);
    context.fillStyle='#355b63';context.fillRect(-w*.25,-h*.22,w*.24,h*.28);
    context.fillStyle='#c6e5eb';context.fillRect(-w*.23,-h*.2,w*.2,h*.2);
    context.fillStyle='#f8fbf8';context.fillRect(w*.12,-h*.2,w*.18,h*.3);
  } else if(item.key==='medicine'||item.key==='cabinet') {
    context.beginPath();context.moveTo(0,-h/2);context.lineTo(0,h/2);context.stroke();
    context.fillStyle='#eef7f3';context.fillRect(-w*.15,-h*.06,w*.06,h*.12);context.fillRect(w*.09,-h*.06,w*.06,h*.12);
    if(item.key==='medicine'){context.fillStyle='#eaf7f0';context.fillRect(-w*.31,-h*.23,w*.12,h*.46);context.fillRect(-w*.4,-h*.08,w*.3,h*.16);}
  } else if(item.key==='sink') {
    context.fillStyle='#f9fcfc';context.beginPath();context.ellipse(0,0,w*.32,h*.3,0,0,Math.PI*2);context.fill();context.stroke();
    context.fillStyle='#7b959b';context.fillRect(-w*.04,-h*.42,w*.08,h*.24);
  } else if(item.key==='chair'||item.key==='bench') {
    context.fillStyle='#d4e5f1';context.fillRect(-w*.42,-h*.12,w*.84,h*.48);
    context.fillStyle='#547da3';context.fillRect(-w/2,-h/2,w,h*.22);
    if(item.key==='bench'){context.beginPath();context.moveTo(-w/6,-h*.12);context.lineTo(-w/6,h*.36);context.moveTo(w/6,-h*.12);context.lineTo(w/6,h*.36);context.stroke();}
  } else if(item.key==='equipment') {
    context.fillStyle='#345864';context.fillRect(-w*.33,-h*.3,w*.66,h*.42);
    context.strokeStyle='#80dcc7';context.beginPath();context.moveTo(-w*.25,-h*.08);context.lineTo(-w*.1,-h*.08);context.lineTo(0,-h*.22);context.lineTo(w*.1,h*.02);context.lineTo(w*.25,-h*.08);context.stroke();
  } else {
    context.fillStyle='#234650';context.font=`bold ${Math.max(11,Math.min(w,h)*.55)}px sans-serif`;context.textAlign='center';context.textBaseline='middle';
    context.fillText({parking:'P',service:'＋',elevator:'↕',waiting:'•',exit:'↗',door:'门',wall:''}[item.key]||'',0,0);
  }
}
const modelGuides = {
  bed:'放在病房内。会自动生成床旁服务点，床与通道之间应留出车辆通行空间。',
  nurse_station:'放在走廊或护士工作区，保留两侧通道。站台实体会阻挡车辆。',
  wall:'用作隔墙，可拖动控制点调整长度。点击墙上的位置可预览并开出门洞。',
  door:'拖到墙上自动吸附并开洞。在属性里调整门宽，再用车型通行预览检查。',
  cabinet:'放在床边，避开床旁服务点及门洞。',
  medicine:'放在治疗区或沿墙布置，柜体会阻挡车辆。',
  desk:'放在诊疗区，桌体会阻挡车辆，需给通道留出宽度。',
  chair:'放在诊疗桌旁或候诊区，避开门洞和巡查路线。',
  bench:'沿候诊区墙边摆放，给走廊和出入口留出空间。',
  equipment:'放在床旁或设备区，避开床旁服务点。',
  sink:'沿墙或在洗手区布置，避开门洞及狭窄通道。',
  furniture:'用于表示实体家具。调整尺寸以匹配占地，车辆会绕开它。',
  parking:'放在开阔位置。可在对象属性中修改编号，每个停车点可分配一辆车。',
  service:'放在车辆能抵达的位置。创建巡查任务时，选它作为目标。',
  elevator:'在任一停靠层的墙体上放置入口，其余未定位的停靠层会自动生成入口和关联点。',
  waiting:'放在电梯入口外，给等候车辆和过路车辆留出空间。',
  exit:'设在电梯出口外的开阔处，给离开电梯的车辆留出空间。',
  forbidden:'覆盖不允许车辆进入的区域，规划路线会避开它。',
  single_lane:'标出只允许一台车进入的通道，通道两端应留出避让空间。',
  one_way:'旋转区域以设置允许通行的方向，再用路线预览检查。'
};
const modelTooltip = document.createElement('div');
modelTooltip.id = 'modelTooltip';
modelTooltip.className = 'model-tooltip';
modelTooltip.setAttribute('role','tooltip');
modelTooltip.hidden = true;
const modelTitle = document.createElement('strong');
const modelSize = document.createElement('span');
modelSize.className = 'model-size';
const modelGuide = document.createElement('span');
const modelControls = document.createElement('span');
modelControls.className = 'model-controls';
modelTooltip.append(modelTitle,modelSize,modelGuide,modelControls);
document.body.append(modelTooltip);
let hoveredRoutePointer = null;
function hideModelTooltip() {
  modelTooltip.hidden = true;
  hoveredRoutePointer = null;
}
function showModelTooltip(object, x, y, fromCatalog=false) {
  hoveredRoutePointer = null;
  modelTitle.textContent = object.kind==='bed' && !fromCatalog ? bedDisplayName(object,floor()) : object.name || labels[object.kind];
  const format = value => Number(value.toFixed(2));
  modelSize.textContent = format(object.width)+' × '+format(object.height)+' m';
  modelGuide.textContent = object.boundary_side
    ? '外墙跟随楼层范围。用「拖框创建楼层范围」调整整层面积。'
    : modelGuides[object.key || object.asset] || modelGuides[object.kind];
  if (!fromCatalog && object.kind==='elevator') {
    const lift=documentMap.elevators?.find(item=>item.id===object.lift_id);
    const floors = documentMap.floors.filter(level=>(lift?.served_floors||[]).includes(level.id));
    if(lift) modelTitle.textContent=lift.name+' · 本层入口';
    if (floors.length) modelGuide.textContent += ' 服务楼层：'+floors.map(level=>level.name).join('、')+'。';
  }
  modelControls.textContent = !fromCatalog && typeof workspaceAllowsEditing==='function' && !workspaceAllowsEditing() ? '浏览模式；编辑物件请切换「地图建模」。' : fromCatalog ? '左键拖入画布，也可点卡片后点画布放置。'
    : replay ? '' : object.boundary_side ? '选中后按 Delete 删除。'
    : '左键拖动可移动。选中后拖控制点调整，按 Delete 删除。';
  positionModelTooltip(x,y);
}
function positionModelTooltip(x,y) {
  modelTooltip.hidden = false;
  const left = Math.max(8,Math.min(x+14,window.innerWidth-modelTooltip.offsetWidth-8));
  const below = y+16;
  const top = below+modelTooltip.offsetHeight+8 <= window.innerHeight
    ? below : Math.max(8,y-modelTooltip.offsetHeight-10);
  modelTooltip.style.left = left+'px';
  modelTooltip.style.top = top+'px';
}
for(const item of catalogItems) {
  const button=document.createElement('button');button.className='item-card';button.type='button';button.dataset.item=item.key;
  const thumbnail=document.createElement('canvas');thumbnail.width=128;thumbnail.height=112;
  const context=thumbnail.getContext('2d');context.translate(64,56);
  const scale=Math.min(100/item.width,86/item.height);
  symbol(context,item,Math.max(10,item.width*scale),Math.max(10,item.height*scale));
  const text=document.createElement('span');text.textContent=item.name;
  const dimensions=document.createElement('small');dimensions.textContent=`${item.width} × ${item.height} m`;
  button.append(thumbnail,text,dimensions);$('catalog').append(button);
  button.onpointerenter=event=>{
    if (!catalogDrag && event.pointerType==='mouse') showModelTooltip(item,event.clientX,event.clientY,true);
  };
  button.onpointerleave=hideModelTooltip;
  button.onfocus=()=>{
    const bounds=button.getBoundingClientRect();
    showModelTooltip(item,bounds.left,bounds.bottom,true);
  };
  button.onblur=hideModelTooltip;
  button.onpointerdown=event=>{
    hideModelTooltip();
    if(replay || buildingOverview || event.button!==0)return;
    event.preventDefault();button.setPointerCapture(event.pointerId);
    const ghost=document.createElement('div');ghost.className='drag-card';ghost.textContent=item.name;document.body.append(ghost);
    catalogDrag={item,ghost,start:[event.clientX,event.clientY],moved:false};
    ghost.style.left=event.clientX+'px';ghost.style.top=event.clientY+'px';
  };
  button.onpointermove=event=>{
    if(!catalogDrag)return;
    catalogDrag.moved ||= Math.hypot(event.clientX-catalogDrag.start[0],event.clientY-catalogDrag.start[1])>5;
    catalogDrag.ghost.style.left=event.clientX+'px';catalogDrag.ghost.style.top=event.clientY+'px';
    const bounds=canvas.getBoundingClientRect();
    ghostObject=event.clientX>=bounds.left&&event.clientX<=bounds.right&&event.clientY>=bounds.top&&event.clientY<=bounds.bottom?{item,pos:world(event)}:null;
    draw();
  };
  button.onpointerup=event=>{
    if(!catalogDrag)return;
    const drop=ghostObject,drag=catalogDrag;drag.ghost.remove();catalogDrag=null;ghostObject=null;
    if(drop)placeItem(drop.item,drop.pos);
    else if(!drag.moved){activeCard=item;setBuildMode('place');notice('点击画布放置'+item.name+'，也可以直接从物品栏拖入');}
    draw();
  };
  button.onpointercancel=()=>{catalogDrag?.ghost.remove();catalogDrag=null;ghostObject=null;draw();};
}
let groupSelection = new Set();
let selectionFloor = null;
let groupPlacement = null;
let snapHint = null;
let wallReportCache = null;
let buildingOverview = false;
let hoveredLevel = null;
let overviewTargets = [];
let wallPress = null;
let wallDoorTarget = null;

function wallAxis(wall) {
  const vertical = wall.height>wall.width;
  const angle = ((wall.rotation||0)+(vertical?90:0))*Math.PI/180;
  const half = Math.max(wall.width,wall.height)/2;
  const dx = Math.cos(angle)*half, dy = Math.sin(angle)*half;
  return [[wall.x-dx,wall.y-dy],[wall.x+dx,wall.y+dy]];
}
function pointOnSegment(point,a,b) {
  const dx=b[0]-a[0],dy=b[1]-a[1];
  const fraction=Math.max(0,Math.min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy || 1)));
  return [a[0]+fraction*dx,a[1]+fraction*dy];
}
function wallSnap(position) {
  const tolerance = Math.min(.45,Math.max(.12,14/transform().scale));
  let match = null, distance = tolerance;
  for (const wall of floor().objects.filter(object=>object.kind==='wall')) {
    const ends=wallAxis(wall);
    const joint=pointOnSegment(position,...ends);
    const vertex=ends.find(end=>Math.hypot(end[0]-position[0],end[1]-position[1])<=tolerance);
    const target=vertex || joint;
    const gap=Math.hypot(target[0]-position[0],target[1]-position[1]);
    if (gap<=distance) {match=target;distance=gap;}
  }
  const point=match || position.map(snap);
  snapHint=match;
  return point;
}
function isOuterWall(wall,level) {
  if (wall.boundary_side) return true;
  if (wall.kind!=='wall') return false;
  const axis=wallAxis(wall);
  return [level.width/2,level.height/2].some((limit,index)=>
    [-limit,limit].some(edge=>axis.every(endpoint=>Math.abs(endpoint[index]-edge)<=.06)));
}
function inspectWalls(level) {
  const axes=level.objects.filter(object=>object.kind==='wall').map(wallAxis);
  const tolerance=.06;
  const gaps=[], ends=[];
  const borders=[
    ['南侧',0,-level.height/2,level.width],['北侧',0,level.height/2,level.width],
    ['西侧',1,-level.width/2,level.height],['东侧',1,level.width/2,level.height]
  ];
  for (const [name,along,ordinate,length] of borders) {
    const across=1-along;
    const intervals=[];
    for (const axis of axes) {
      if (!axis.every(point=>Math.abs(point[across]-ordinate)<=tolerance)) continue;
      intervals.push(axis.map(point=>point[along]).sort((a,b)=>a-b));
    }
    intervals.sort((a,b)=>a[0]-b[0]);
    // Merge coverage along each edge and report the uncovered stretches.
    let cursor=-length/2;
    for (const [lo,hi] of [...intervals,[length/2,length/2]]) {
      const next=Math.min(length/2,lo);
      if (next-cursor>tolerance) {
        const at=(cursor+next)/2;
        gaps.push({name,length:next-cursor,point:along===0?[at,ordinate]:[ordinate,at]});
      }
      cursor=Math.min(length/2,Math.max(cursor,hi));
    }
  }
  for (const axis of axes) {
    for (const end of axis) {
      const joined=axes.some(other=>{
        if (other===axis) return false;
        const nearest=pointOnSegment(end,...other);
        return Math.hypot(end[0]-nearest[0],end[1]-nearest[1])<=tolerance;
      });
      if (!joined) ends.push(end);
    }
  }
  return {gaps,ends};
}
function wallReport(level) {
  const signature=JSON.stringify([level.width,level.height,
    level.objects.filter(o=>o.kind==='wall').map(o=>[o.x,o.y,o.width,o.height,o.rotation])]);
  if (wallReportCache?.signature!==signature) wallReportCache={signature,...inspectWalls(level)};
  return wallReportCache;
}
function syncObjectSelection() {
  const identity=documentMap.id+'@'+floor().id;
  if (identity!==selectionFloor) {
    selectionFloor=identity;
    groupSelection.clear();
    groupPlacement=null;
    if (buildMode==='box' || buildMode==='paste') setBuildMode('select');
  }
  $('copyObjects').disabled=!groupSelection.size || !!replay || !!groupPlacement;
}
function footprintCorners(object) {
  const angle=(object.rotation||0)*Math.PI/180;
  return [[-1,-1],[1,-1],[1,1],[-1,1]].map(([x,y])=>{
    const dx=x*object.width/2,dy=y*object.height/2;
    return [object.x+dx*Math.cos(angle)-dy*Math.sin(angle),object.y+dx*Math.sin(angle)+dy*Math.cos(angle)];
  });
}
function selectObjectsInBox(start,end) {
  const low=start.map((value,axis)=>Math.min(value,end[axis]));
  const high=start.map((value,axis)=>Math.max(value,end[axis]));
  groupSelection=new Set(floor().objects.filter(object=>!isOuterWall(object,floor()) &&
    footprintCorners(object).every(point=>point.every((value,axis)=>value>=low[axis]&&value<=high[axis])))
    .map(object=>object.id));
  selected=null;
  notice(groupSelection.size?'已框选 '+groupSelection.size+' 个物件。点「复制所选」后在画布预览并落位。':'未框住完整物件，请重新框选。');
}
function collectCopyGroup(level,selection) {
  const objects=level.objects;
  const included=new Set(selection);
  const references=['wall_id','bed_id','waiting_id','exit_id','elevator_id'];
  let size;
  do {
    size=included.size;
    for (const item of objects) {
      if (isOuterWall(item,level)) continue;
      if (included.has(item.id)) {
        for (const key of ['wall_id','waiting_id','exit_id']) {
          const parent=objects.find(object=>object.id===item[key]);
          if (parent && !isOuterWall(parent,level)) included.add(parent.id);
        }
      }
      if ((item.wall_id && included.has(item.wall_id)) ||
          (item.bed_id && included.has(item.bed_id)) ||
          (item.elevator_id && included.has(item.elevator_id))) included.add(item.id);
    }
  } while (included.size!==size);
  const group=objects.filter(o=>included.has(o.id) && !isOuterWall(o,level) &&
    (o.kind!=='door' || objects.some(w=>w.id===o.wall_id && included.has(w.id) && !isOuterWall(w,level))));
  const idMap=new Map(group.map(item=>[item.id,uid()]));
  const copies = group.map(item=>{
    const copy={...clone(item),id:idMap.get(item.id)};
    clearCopiedPatient(copy);
    // A pasted entrance belongs to a new room on the same floor.
    if (copy.kind==='door') delete copy.room_number;
    if (copy.kind==='parking') delete copy.parking_number;
    for (const key of references) {
      if (!copy[key]) continue;
      if (idMap.has(copy[key])) copy[key]=idMap.get(copy[key]);
      else {delete copy[key];if (key==='bed_id' || key==='elevator_id') delete copy.auto_link;}
    }
    return copy;
  });
  return {objects:copies, outline:copyOutline(level,group)};
}
action('boxSelect',()=>{
  if (replay) return;
  groupSelection.clear();selected=null;
  setBuildMode('box');inspector();draw();
  notice('按住左键框住要复制的物件，外墙不会加入复制。');
});
action('copyObjects',()=>{
  if (replay || !groupSelection.size) return;
  const {objects,outline}=collectCopyGroup(floor(),groupSelection);
  if (!objects.length) {notice('外墙上的门需要复制所属楼层。');return;}
  setBuildMode('paste');
  groupPlacement={objects,outline,anchor:[objects[0].x,objects[0].y],target:null,pending:false};
  notice('移动鼠标预览副本，点左键放置。按 Esc 取消。');
  draw();
});
function copyOutline(level,objects) {
  const solids=compiled.find(entry=>entry.id===level.id)?.rectangles;
  return objects.flatMap(object=>{
    if (object.kind==='door') return [];
    if (object.kind!=='wall') return [object];
    if (solids) return solids.filter(piece=>piece.kind==='wall' && piece.id===object.id);
    return level.objects.some(door=>door.kind==='door' && door.wall_id===object.id) ? [] : [object];
  });
}
function translatedGroup(placement,position,objects=placement.objects) {
  const [dx,dy]=position.map((value,axis)=>snap(value-placement.anchor[axis]));
  return objects.map(object=>({...object,x:object.x+dx,y:object.y+dy}));
}
function overlapsDoorway(door,wall) {
  const a=footprintCorners(door),b=footprintCorners(wall);
  return [door,wall].every(object=>{
    const angle=(object.rotation||0)*Math.PI/180;
    return [angle,angle+Math.PI/2].every(axis=>{
      const project=([x,y])=>x*Math.cos(axis)+y*Math.sin(axis);
      const p=a.map(project),q=b.map(project);
      return Math.min(Math.max(...p),Math.max(...q))-Math.max(Math.min(...p),Math.min(...q))>.001;
    });
  });
}
function blockedCopyDoor(level,copies,rectangles) {
  const ids=new Set(copies.map(object=>object.id));
  const walls=rectangles.filter(object=>object.kind==='wall');
  return level.objects.find(door=>door.kind==='door' && walls.some(wall=>
    wall.id!==door.wall_id && (ids.has(wall.id)||ids.has(door.id)) && overlapsDoorway(door,wall)));
}
async function pasteGroup(position) {
  const placement=groupPlacement;
  if (!placement || placement.pending) return;
  const target=floor(), documentAtStart=documentMap;
  const revision=compileRevision;
  const copies=translatedGroup(placement,position);
  const candidate=clone(documentMap);
  const level=candidate.floors.find(level=>level.id===target.id);
  level.objects.push(...copies);
  for(const entry of copies.filter(item=>item.kind==='elevator')) attachLiftLanding(candidate,level.id,entry.id);
  placement.pending=true;
  try {
    const geometry=await api('/api/maps/compile',candidate);
    if (placement!==groupPlacement || documentAtStart!==documentMap || target!==floor() ||
        revision!==compileRevision) return;
    const result=geometry.validation;
    if (!result.valid) {
      notice('副本暂不能放置：'+[...result.structure,...result.geometry].slice(0,3).join('；'));
      return;
    }
    const rectangles=geometry.floors.find(entry=>entry.id===target.id).rectangles;
    if (blockedCopyDoor(level,copies,rectangles)) {
      notice('此位置的门洞会被另一面墙挡住，请移动副本后再放置。');
      return;
    }
    checkpoint();documentMap=candidate;
    groupSelection.clear();
    selected=null;
    setBuildMode('select');dirty();
    compiled=geometry.floors;
    checkedGeometry={...result,map:documentMap};
    refresh();
    notice('');
  } catch (error) {notice(error.message);}
  finally {placement.pending=false;}
}
window.addEventListener('keydown',event=>{
  if ($('mapBatchManager').open) return;
  if (event.key==='Escape' && wallDoorTarget) {clearWallDoorTarget();draw();}
  if (event.key==='Escape' && (['box','paste','room','pan'].includes(buildMode))) {
    setBuildMode('select');draw();
  }
});

function setBuildMode(mode) {
  if (buildingOverview) setBuildingOverview(false);
  buildMode=mode;buildingGesture=null;dragging=null;snapHint=null;wallPress=null;
  clearWallDoorTarget();
  if (mode!=='paste') groupPlacement=null;
  $('tool').value='select';
  $('boxSelect').classList.toggle('active',mode==='box');
  $('panCamera').setAttribute('aria-pressed',String(mode==='pan'));
  $('panCamera').textContent = mode==='pan' ? '结束移动' : '移动画布';
  updateViewportHelp();
  $('drawRoom').classList.toggle('active',mode==='room');
  $('drawFloor').classList.toggle('active',mode==='floor');$('drawWall').classList.toggle('active',mode==='wall');
  updateCanvasCursor();
}
action('drawFloor',()=>{setBuildMode('floor');notice('按住并拖出一个矩形，松开后创建楼层范围和四周墙体');});
action('drawRoom',()=>{setBuildMode('room');draw();notice('左键拖框确定病房大小，松手生成闭合墙体。点墙上的位置可选是否开门。');});
action('drawWall',()=>{setBuildMode('wall');notice('在画布按住拖动，创建任意方向的隔墙');});
action('selectObject',()=>setBuildMode('select'));
action('panCamera',()=>{
  if (!documentMap || buildingOverview || cameraDrag || dragging || buildingGesture || catalogDrag) return;
  setBuildMode(buildMode==='pan'?'select':'pan');
  hideModelTooltip();
  draw();
});

function nearestWall(pos,useLongAxis=false) {
  let candidate=null,best=.8;
  for(const wall of floor().objects.filter(o=>o.kind==='wall')) {
    const vertical=useLongAxis && wall.height>wall.width;
    const length=vertical?wall.height:wall.width;
    const angle=((wall.rotation||0)+(vertical?90:0))*Math.PI/180,dx=pos[0]-wall.x,dy=pos[1]-wall.y;
    const along=dx*Math.cos(angle)+dy*Math.sin(angle),across=-dx*Math.sin(angle)+dy*Math.cos(angle);
    const distance=Math.hypot(Math.max(0,Math.abs(along)-length/2),across);
    if(distance<best){best=distance;candidate={wall,along};}
  }
  return candidate;
}
function placeItem(item,pos) {
  if (item.kind==='elevator') {
    const attached=nearestWall(pos,true);
    if (!attached) {notice('请把电梯入口放到墙上。');return;}
    const bounds=canvas.getBoundingClientRect();
    const [x,y]=point(...pos);
    showWallDoorPrompt({wall:attached.wall,position:pos,
      x:bounds.left+x*bounds.width/canvas.width,y:bounds.top+y*bounds.height/canvas.height},'elevator');
    draw();
    return;
  }
  let attached=null;
  if(item.kind==='door') {
    attached=nearestWall(pos);
    if(!attached){notice('请把门拖到墙上，靠近墙时会自动吸附');return;}
    if(attached.wall.width<item.width+.1){notice('这段墙比门窄，请先拉长墙体');return;}
  }
  checkpoint();
  const object={id:uid(),kind:item.kind,asset:item.key,name:item.name,x:snap(pos[0]),y:snap(pos[1]),width:item.width,height:item.height,rotation:0};
  if(attached){const {wall}=attached,angle=wall.rotation*Math.PI/180;const offset=Math.max(-wall.width/2+item.width/2,Math.min(wall.width/2-item.width/2,snap(attached.along)));Object.assign(object,{wall_id:wall.id,x:wall.x+offset*Math.cos(angle),y:wall.y+offset*Math.sin(angle),rotation:wall.rotation,height:wall.height});}
  floor().objects.push(object);
  if (item.kind==='bed') {
    delete object.name;
    floor().objects.push({id:uid(),kind:'service',name:'床旁服务点',bed_id:object.id,
      auto_link:true,x:object.x,y:object.y-object.height/2-.65,width:.25,height:.25,rotation:0});
  }
  selected=object.id;setBuildMode('select');dirty();refresh();compile().catch(error=>notice(error.message));
}
function attachedMove(before,after) {
  moveDoors(before,after);
  const old=before.rotation*Math.PI/180,next=after.rotation*Math.PI/180;
  for(const child of floor().objects.filter(o=>o.auto_link&&(o.bed_id===before.id||o.elevator_id===before.id))) {
    const dx=child.x-before.x,dy=child.y-before.y;
    const x=dx*Math.cos(old)+dy*Math.sin(old);
    let y=-dx*Math.sin(old)+dy*Math.cos(old);
    if(before.kind==='bed'&&before.height!==after.height)y=Math.sign(y||-1)*(after.height/2+Math.max(.65,Math.abs(y)-before.height/2));
    child.x=after.x+x*Math.cos(next)-y*Math.sin(next);child.y=after.y+x*Math.sin(next)+y*Math.cos(next);child.rotation=(child.rotation||0)+after.rotation-before.rotation;
  }
}
function handles(object) {
  const a=object.rotation*Math.PI/180;
  const project=(x,y)=>[object.x+x*Math.cos(a)-y*Math.sin(a),object.y+x*Math.sin(a)+y*Math.cos(a)];
  return {resize:project(object.width/2,-object.height/2),rotate:project(0,object.height/2+.5)};
}
function footprintDimensions(start,end) {
  const width = snap(Math.abs(end[0]-start[0]));
  const height = snap(Math.abs(end[1]-start[1]));
  return {width,height,area:width*height};
}
function roomBounds(start,end,level) {
  const walls = level.objects.filter(object=>object.kind==='wall').map(wallAxis);
  const corners = [start,end].map(point=>point.map((value,axis)=>{
    const limit = (axis===0?level.width:level.height)/2;
    const within = Math.max(-limit,Math.min(limit,value));
    const coordinates = [-limit,limit];
    for (const line of walls) {
      if (Math.abs(line[1][axis]-line[0][axis])<1e-6) coordinates.push(line[0][axis]);
    }
    const closest = coordinates.reduce((a,b)=>Math.abs(a-within)<=Math.abs(b-within)?a:b);
    return Math.abs(closest-within)<=.24 ? closest : Math.max(-limit,Math.min(limit,snap(within)));
  }));
  const low = corners[0].map((value,axis)=>Math.min(value,corners[1][axis]));
  const high = corners[0].map((value,axis)=>Math.max(value,corners[1][axis]));
  return {low,high,width:high[0]-low[0],height:high[1]-low[1]};
}

function roomWallSegments(level,{low,high}) {
  const existing = level.objects.filter(object=>object.kind==='wall').map(wallAxis);
  const pieces = [];
  for (const along of [0,1]) {
    const across = 1-along;
    for (const edge of [low[across],high[across]]) {
      const occupied = existing.filter(line=>line.every(point=>Math.abs(point[across]-edge)<1e-6))
        .map(line=>line.map(point=>point[along]).sort((a,b)=>a-b))
        .sort((a,b)=>a[0]-b[0]);
      let cursor = low[along];
      for (const [from,to] of [...occupied,[high[along],high[along]]]) {
        const stop = Math.min(high[along],from);
        if (stop-cursor>1e-6) {
          const center = (cursor+stop)/2;
          pieces.push({x:along===0?center:edge,y:along===0?edge:center,
            width:stop-cursor,height:.2,rotation:along===0?0:90});
        }
        cursor = Math.max(cursor,to);
        if (cursor>=high[along]) break;
      }
    }
  }
  return pieces;
}
function createRoom(start,end) {
  const level = floor();
  const bounds = roomBounds(start,end,level);
  if (bounds.width<2 || bounds.height<2) {
    notice('病房范围至少 2 × 2 米，请重新拖框。');
    draw();
    return;
  }
  const pieces = roomWallSegments(level,bounds);
  if (!pieces.length) {
    notice('这个范围已有闭合墙体。点墙上的位置可开门。');
    setBuildMode('select');draw();
    return;
  }
  checkpoint();
  level.objects.push(...pieces.map(piece=>({
    ...piece,id:uid(),kind:'wall',asset:'wall',name:'病房墙'
  })));
  selected = null;
  setBuildMode('select');
  dirty();refresh();
  notice('已创建 '+bounds.width.toFixed(2)+' × '+bounds.height.toFixed(2)+' 米病房墙体。点击一面墙可选开门位置。');
  compile().catch(error=>notice(error.message));
}

function doorOnWall(wall,position,width) {
  const length = Math.max(wall.width,wall.height);
  const thickness = Math.min(wall.width,wall.height);
  const rotation = (wall.rotation||0)+(wall.height>wall.width?90:0);
  if (!Number.isFinite(width) || width<.4 || width>5 || length<width+.1) return null;
  const angle = rotation*Math.PI/180;
  const along = (position[0]-wall.x)*Math.cos(angle)+(position[1]-wall.y)*Math.sin(angle);
  const limit = (length-width)/2-.05;
  const offset = Math.max(-limit,Math.min(limit,snap(along)));
  return {pose:{x:wall.x+offset*Math.cos(angle),y:wall.y+offset*Math.sin(angle),
    width,height:thickness,rotation},offset,angle,length,thickness};
}
function clearWallDoorTarget() {
  wallDoorTarget = null;
  $('wallDoorTools').hidden = true;
  $('wallDoorError').textContent = '';
  $('addWallDoor').disabled = false;
  $('wallDoorWidth').disabled = false;
  $('wallFixtureKind').disabled = false;
  $('wallRoomNumber').disabled = false;
  $('wallRoomNumber').value = '';
  $('wallLift').disabled = false;
}
function updateWallFixturePrompt() {
  const elevator = $('wallFixtureKind').value==='elevator';
  $('wallDoorLocation').textContent = elevator?'是否创建电梯入口？':'是否开辟门洞？';
  $('wallFixtureKindField').hidden = false;
  $('wallFixtureWidthField').hidden = false;
  $('wallFixtureWidthLabel').textContent = elevator?'入口宽度（米）':'门宽（米）';
  $('wallRoomNumberField').hidden = elevator;
  $('wallLiftField').hidden = !elevator;
  $('wallLiftDetails').hidden = true;
  $('addWallDoor').textContent = '是';
  $('cancelWallDoor').textContent = '否';
  if(elevator) {
    const choices=liftChoices(floor().id);
    const chosen=[pendingLiftPlacement,managedLiftId,$('wallLift').value]
      .find(id=>choices.some(([liftId])=>liftId===id)) ?? choices[0]?.[0] ?? '';
    options('wallLift',[...choices,['','新建一部电梯']],chosen);
    const lift=documentMap.elevators.find(item=>item.id===$('wallLift').value);
    if(lift) $('wallDoorWidth').value=lift.default_width;
  }
  $('wallDoorError').textContent = '';
}
$('wallFixtureKind').onchange = () => {updateWallFixturePrompt();draw();};
$('wallLift').onchange=()=>{const lift=documentMap.elevators.find(item=>item.id===$('wallLift').value);if(lift)$('wallDoorWidth').value=lift.default_width;draw();};
function showWallDoorPrompt(press,kind='door') {
  wallDoorTarget = {id:press.wall.id,level:floor(),position:press.position};
  $('wallFixtureKind').value = kind;
  updateWallFixturePrompt();
  positionWallFixturePrompt(press.x,press.y);
}
function positionWallFixturePrompt(clientX,clientY) {
  const panel = $('wallDoorTools');
  panel.hidden = false;
  const viewport = panel.parentElement.getBoundingClientRect();
  const x = clientX-viewport.left, y = clientY-viewport.top;
  const left = x+panel.offsetWidth+18<=viewport.width ? x+12 : x-panel.offsetWidth-12;
  const top = y+panel.offsetHeight+18<=viewport.height ? y+12 : y-panel.offsetHeight-12;
  panel.style.left = Math.max(8,Math.min(viewport.width-panel.offsetWidth-8,left))+'px';
  panel.style.top = Math.max(8,Math.min(viewport.height-panel.offsetHeight-8,top))+'px';
  $('addWallDoor').focus({preventScroll:true});
}
function showLiftLandingPrompt(entryId) {
  const level = floor();
  const entry = level.objects.find(object=>object.id===entryId&&object.kind==='elevator');
  const lift = documentMap.elevators.find(item=>item.id===entry?.lift_id);
  const landing = lift?.landings[level.id];
  if (replay || landing?.entrance_id!==entryId || !canConfirmLiftLanding(lift,level.id)) return;
  clearWallDoorTarget();
  wallDoorTarget = {entryId,liftId:lift.id,level};
  $('wallDoorLocation').textContent = '确认这部电梯的入口？';
  for (const id of ['wallFixtureKindField','wallFixtureWidthField','wallRoomNumberField','wallLiftField']) $(id).hidden = true;
  const details = $('wallLiftDetails');
  details.textContent = lift.name+' · '+level.name+' · 入口宽度 '+entry.width+' 米';
  details.hidden = false;
  $('wallDoorError').textContent = liftReports?.[lift.id]?.find(row=>row.floor_id===level.id)?.issues.join('；')||'';
  $('addWallDoor').textContent = '确认入口';
  $('cancelWallDoor').textContent = '关闭';
  const bounds = canvas.getBoundingClientRect();
  const [x,y] = point(entry.x,entry.y);
  positionWallFixturePrompt(bounds.left+x*bounds.width/canvas.width,bounds.top+y*bounds.height/canvas.height);
}
function currentWallDoor() {
  if (!wallDoorTarget || wallDoorTarget.entryId || wallDoorTarget.level!==floor()) return null;
  const wall = floor().objects.find(object=>object.id===wallDoorTarget.id);
  if (!wall || wall.kind!=='wall') return null;
  return {wall,placement:doorOnWall(wall,wallDoorTarget.position,Number($('wallDoorWidth').value))};
}
$('wallDoorWidth').oninput = () => {
  $('wallDoorError').textContent = '';
  draw();
};
action('cancelWallDoor',()=>{clearWallDoorTarget();draw();});
function makeWallElevator(level,wall,pose,click,angle) {
  const normal = [-Math.sin(angle),Math.cos(angle)];
  const side = (click[0]-pose.x)*normal[0]+(click[1]-pose.y)*normal[1];
  const entrance = {...pose,id:uid(),kind:'elevator',asset:'elevator',name:'电梯入口',
    wall_id:wall.id};
  for (const sign of side<0?[-1,1]:[1,-1]) {
    const point = (kind,name,along,distance,size) => ({
      id:uid(),kind,name,elevator_id:entrance.id,auto_link:true,
      x:pose.x+Math.cos(angle)*along+normal[0]*distance*sign,
      y:pose.y+Math.sin(angle)*along+normal[1]*distance*sign,
      width:size,height:size,rotation:pose.rotation
    });
    const waiting = point('waiting','候梯点',-.62,1.15,.35);
    const exit = point('exit','出梯区域',.62,1.15,.8);
    const fits = [waiting,exit].every(o=>footprintCorners(o).every(([x,y])=>
      Math.abs(x)<=level.width/2 && Math.abs(y)<=level.height/2));
    if (fits) return [{...entrance,waiting_id:waiting.id,exit_id:exit.id},waiting,exit];
  }
  throw Error('墙边空间不足，无法放置候梯点和出梯区域。');
}
async function confirmLiftLanding(target) {
  const original = documentMap, revision = compileRevision;
  const button = $('addWallDoor'), error = $('wallDoorError');
  button.disabled = true;
  error.textContent = '';
  try {
    const inspected = await api('/api/maps/elevators',{map:original,models:configuration.models,
      action:'inspect',lift_id:target.liftId});
    if (target!==wallDoorTarget || original!==documentMap || revision!==compileRevision) return;
    const result = await confirmLiftStops(inspected,target.liftId,target.level.id);
    if (target!==wallDoorTarget || original!==documentMap || revision!==compileRevision) return;
    checkpoint();
    const geometry = checkedGeometry?.map===original ? checkedGeometry : null;
    documentMap = result.map;
    rememberLiftPlacements(false);
    dirty();
    if (geometry) checkedGeometry={...geometry,map:documentMap};
    liftReports = result.reports;
    clearWallDoorTarget();
    refresh();
    notice(liftLandingNotice(result.reports[target.liftId]));
  } catch (failure) {
    if (target===wallDoorTarget) error.textContent = failure.message;
  } finally {
    if (target===wallDoorTarget) button.disabled = false;
  }
}
action('addWallDoor',async()=>{
  const target = wallDoorTarget;
  const confirm = $('addWallDoor');
  if (!target || confirm.disabled || replay) return;
  if (target.entryId) return confirmLiftLanding(target);
  const result = currentWallDoor();
  const error = $('wallDoorError');
  if (!result) return;
  const {wall,placement} = result;
  const elevator = $('wallFixtureKind').value==='elevator';
  const fixtureName = elevator?'电梯入口':'门洞';
  if (!placement) {
    error.textContent = fixtureName+'宽度须为 0.4 至 5 米，且两端需留在墙内。';
    return;
  }
  const roomNumber = elevator?'':$('wallRoomNumber').value.trim();
  const numberError = roomNumberError(target.level,roomNumber);
  if (numberError) {error.textContent=numberError;return;}
  const {pose,offset,angle,length,thickness} = placement;
  const doors = floor().objects.filter(object=>['door','elevator'].includes(object.kind) && object.wall_id===wall.id);
  if (doors.some(door=>{
    const center=(door.x-wall.x)*Math.cos(angle)+(door.y-wall.y)*Math.sin(angle);
    return Math.abs(center-offset)<(door.width+pose.width)/2+.001;
  })) {
    error.textContent = '与已有门洞或电梯入口重叠，请换一个位置。';
    return;
  }
  const revision = compileRevision;
  const original = documentMap;
  const reshape = elevator ? {} : {width:length,height:thickness,rotation:pose.rotation};
  let objects;
  if (elevator) {
    try {objects=makeWallElevator(target.level,wall,pose,target.position,angle);}
    catch (failure) {error.textContent=failure.message;return;}
  } else {
    const door = {...pose,id:uid(),kind:'door',asset:'door',name:'病房门',wall_id:wall.id};
    if (roomNumber) door.room_number = roomNumber;
    objects = [door];
  }
  let candidate = clone(original);
  const candidateFloor = candidate.floors.find(level=>level.id===target.level.id);
  Object.assign(candidateFloor.objects.find(object=>object.id===wall.id),reshape);
  candidateFloor.objects.push(...objects);
  if(elevator) {
    try {attachLiftLanding(candidate,candidateFloor.id,objects[0].id,$('wallLift').value);}
    catch(failure) {error.textContent=failure.message;return;}
  }
  confirm.disabled = true;
  $('wallDoorWidth').disabled = true;
  $('wallFixtureKind').disabled = true;
  $('wallRoomNumber').disabled = true;
  $('wallLift').disabled = true;
  error.textContent = '';
  try {
    let elevatorResult;
    if (elevator) {
      elevatorResult = await placeLiftLanding(candidate,objects[0].lift_id,candidateFloor.id);
      if (target!==wallDoorTarget || original!==documentMap || revision!==compileRevision) return;
      candidate = elevatorResult.map;
    }
    const compiledDoor = await api('/api/maps/compile',candidate);
    if (target!==wallDoorTarget || original!==documentMap || revision!==compileRevision) return;
    if (!compiledDoor.validation.valid) {
      const issues=[...compiledDoor.validation.structure,...compiledDoor.validation.geometry];
      error.textContent = '暂不能创建'+fixtureName+'：'+issues[0];
      return;
    }
    checkpoint();
    documentMap=candidate;
    selected = elevator?objects[0].id:null;
    if(elevator) {managedLiftId=objects[0].lift_id;pendingLiftPlacement='';}
    setBuildMode('select');
    if(elevator) rememberLiftPlacements(false);
    dirty();
    if(elevator) liftReports=elevatorResult.reports;
    compiled = compiledDoor.floors;
    checkedGeometry = {...compiledDoor.validation,map:documentMap};
    refresh();
    if (elevator) {
      const rows = liftReports[managedLiftId];
      const source = rows.find(row=>row.floor_id===candidateFloor.id);
      notice(source.status==='ready'?liftLandingNotice(rows):
        '本层电梯入口已创建，需调整：'+source.issues.join('；')+'。');
    } else notice('已切开 '+pose.width.toFixed(2)+' 米宽的门洞。');
  } catch (failure) {
    if (target===wallDoorTarget) error.textContent = fixtureName+'生成失败，请重试。'+failure.message;
  } finally {
    if (target===wallDoorTarget) {confirm.disabled = false;$('wallDoorWidth').disabled = false;$('wallFixtureKind').disabled = false;$('wallRoomNumber').disabled = false;$('wallLift').disabled = false;}
  }
});
function applyFootprint(start,end) {
  const {width,height,area} = footprintDimensions(start,end);
  if(width<2||height<2){notice('楼层范围至少 2 × 2 米，请重新拖框');return;}
  const f=floor(),center=[start[0]+Math.sign(end[0]-start[0])*width/2,
    start[1]+Math.sign(end[1]-start[1])*height/2];
  checkpoint();
  for(const object of f.objects){object.x-=center[0];object.y-=center[1];}
  if(f.background){f.background.x-=center[0];f.background.y-=center[1];}
  for(const instance of configuration?.instances||[])if(instance.floor_id===f.id){instance.pose[0]-=center[0];instance.pose[1]-=center[1];}
  const oldWalls=Object.fromEntries(f.objects.filter(o=>o.boundary_side).map(o=>[o.boundary_side,o]));
  f.objects=f.objects.filter(o=>!o.boundary_side);f.width=width;f.height=height;f.area_defined=true;
  for(const [side,x,y,length,rotation] of [['north',0,height/2,width,0],['south',0,-height/2,width,0],['west',-width/2,0,height,90],['east',width/2,0,height,90]]) {
    const wall={id:oldWalls[side]?.id||uid(),kind:'wall',asset:'wall',name:'楼层外墙',boundary_side:side,x,y,width:length,height:.2,rotation};
    f.objects.push(wall);
    for(const door of f.objects.filter(o=>o.wall_id===wall.id && ['door','elevator'].includes(o.kind))){
      const previous=door.kind==='elevator'?clone(door):null;
      const a=rotation*Math.PI/180,offset=Math.max(-length/2+door.width/2,Math.min(length/2-door.width/2,(door.x-x)*Math.cos(a)+(door.y-y)*Math.sin(a)));
      door.x=x+offset*Math.cos(a);door.y=y+offset*Math.sin(a);door.rotation=rotation;
      if (previous) attachedMove(previous,door);
    }
  }
  selected=null;setBuildMode('select');dirty();refresh();compile().catch(error=>notice(error.message));
  notice(`楼层范围 ${width.toFixed(2)} × ${height.toFixed(2)} 米，面积 ${area.toFixed(2)} 平方米，已生成四周墙体`);
}
canvas.onpointerdown=event=>{
  if(replay)return;
  if(calibration){originalPointerDown(event);return;}
  const pos=world(event);
  if ($('tool').value==='elevator') {placeItem(catalogItems.find(item=>item.kind==='elevator'),pos);return;}
  if(buildMode==='paste'){pasteGroup(pos);return;}
  if(buildMode==='place'&&activeCard){placeItem(activeCard,pos);return;}
  if(buildMode==='floor'||buildMode==='room'||buildMode==='wall'||buildMode==='box') {const start=buildMode==='wall'?wallSnap(pos):pos;buildingGesture={kind:buildMode,start,end:start};canvas.setPointerCapture(event.pointerId);draw();return;}
  const object=floor().objects.find(o=>o.id===selected);
  if(object&&!object.boundary_side){const controls=handles(object),tolerance=12/transform().scale;
    for(const name of ['resize','rotate'])if(Math.hypot(pos[0]-controls[name][0],pos[1]-controls[name][1])<tolerance){checkpoint();buildingGesture={kind:name,object,original:clone(object),start:pos};canvas.setPointerCapture(event.pointerId);return;}}
  clearWallDoorTarget();
  const wall = $('tool').value==='select' ? hit(pos) : null;
  if (wall?.kind==='wall') {
    wallPress = {wall,position:pos,event,x:event.clientX,y:event.clientY};
    canvas.setPointerCapture(event.pointerId);
    return;
  }
  originalPointerDown(event);
  if(dragging?.object.boundary_side){dragging=null;notice('外墙跟随楼层范围；用“拖框创建楼层范围”调整整层面积');}
};
canvas.onpointermove=event=>{
  if (wallPress) {
    if (Math.hypot(event.clientX-wallPress.x,event.clientY-wallPress.y)<5) return;
    const press=wallPress;
    wallPress=null;
    if (isOuterWall(press.wall,floor())) return;
    originalPointerDown(press.event);
  }
  if (buildMode==='paste' && groupPlacement) {groupPlacement.target=world(event);draw();return;}
  if (!buildingGesture && buildMode==='wall') {wallSnap(world(event));draw();return;}
  if(buildingGesture){const pos=world(event),gesture=buildingGesture;
    if(['floor','room','wall','box'].includes(gesture.kind)){gesture.end=gesture.kind==='wall'?wallSnap(pos):pos;draw();return;}
    const object=gesture.object,before=clone(object),angle=object.rotation*Math.PI/180;
    if(gesture.kind==='rotate')object.rotation=Math.round((Math.atan2(pos[1]-object.y,pos[0]-object.x)*180/Math.PI-90)/15)*15;
    else {const dx=pos[0]-object.x,dy=pos[1]-object.y;object.width=Math.max(.1,snap(2*Math.abs(dx*Math.cos(angle)+dy*Math.sin(angle))));object.height=Math.max(.1,snap(2*Math.abs(-dx*Math.sin(angle)+dy*Math.cos(angle))));}
    attachedMove(before,object);dirty();draw();return;
  }
  if(dragging){const before=clone(dragging.object);originalPointerMove(event);const after=dragging.object;
    if(after.kind==='door'){const attached=nearestWall([after.x,after.y]);if(attached){const a=attached.wall.rotation*Math.PI/180;after.wall_id=attached.wall.id;after.x=attached.wall.x+attached.along*Math.cos(a);after.y=attached.wall.y+attached.along*Math.sin(a);after.rotation=attached.wall.rotation;}}
    if (after.kind==='elevator' && after.wall_id) {
      const wall=floor().objects.find(object=>object.id===after.wall_id);
      const placement=wall && doorOnWall(wall,[after.x,after.y],after.width);
      Object.assign(after,placement?.pose || before);
    }
    // Original handler already carries wall fixtures; other linked points follow here.
    if(before.kind!=='wall')attachedMove(before,after);
    draw();return;
  }
  originalPointerMove(event);
};
canvas.onpointerup=()=>{
  if (wallPress) {
    const press = wallPress;
    wallPress = null;
    selected = press.wall.id;
    showWallDoorPrompt(press);
    inspector();draw();
    return;
  }
  if(buildingGesture){const gesture=buildingGesture;buildingGesture=null;
    if(gesture.kind==='box'){selectObjectsInBox(gesture.start,gesture.end);setBuildMode('select');refresh();return;}
    if(gesture.kind==='room'){createRoom(gesture.start,gesture.end);return;}
    if(gesture.kind==='floor'){applyFootprint(gesture.start,gesture.end);return;}
    if(gesture.kind==='wall'){const length=Math.hypot(gesture.end[0]-gesture.start[0],gesture.end[1]-gesture.start[1]);if(length>=.2){checkpoint();const object={id:uid(),kind:'wall',asset:'wall',name:'隔墙',x:(gesture.start[0]+gesture.end[0])/2,y:(gesture.start[1]+gesture.end[1])/2,width:length,height:.2,rotation:Math.atan2(gesture.end[1]-gesture.start[1],gesture.end[0]-gesture.start[0])*180/Math.PI};floor().objects.push(object);selected=object.id;dirty();}setBuildMode('select');}
    refresh();compile().catch(error=>notice(error.message));return;
  }
  originalPointerUp();
};
canvas.onpointercancel=()=>{buildingGesture=null;dragging=null;snapHint=null;wallPress=null;draw();};
draw=function(){
  originalDraw();if(!documentMap)return;
  const f=floor(),scale=transform().scale;$('floorArea').textContent=`${f.width.toFixed(1)} × ${f.height.toFixed(1)} m · ${(f.width*f.height).toFixed(1)} m²`;
  for(const object of f.objects){const item=catalogItems.find(item=>item.key===(object.asset||object.kind));if(!item||['wall','door','elevator'].includes(object.kind))continue;
    const [x,y]=point(object.x,object.y);ctx.save();ctx.translate(x,y);ctx.rotate(-object.rotation*Math.PI/180);symbol(ctx,item,object.width*scale,object.height*scale);ctx.restore();}
  const object=f.objects.find(o=>o.id===selected);
  if(object&&!object.boundary_side&&!replay&&(typeof workspaceAllowsEditing!=='function'||workspaceAllowsEditing())){rectangle(object,'#167364',true);const controls=handles(object);ctx.strokeStyle='#167364';ctx.beginPath();ctx.moveTo(...point(object.x,object.y));ctx.lineTo(...point(...controls.rotate));ctx.stroke();for(const key of ['resize','rotate']){const [x,y]=point(...controls[key]);ctx.fillStyle='white';ctx.strokeStyle='#167364';ctx.beginPath();if(key==='rotate')ctx.arc(x,y,7,0,Math.PI*2);else ctx.rect(x-6,y-6,12,12);ctx.fill();ctx.stroke();}}
  if(ghostObject){ctx.globalAlpha=.6;rectangle({x:snap(ghostObject.pos[0]),y:snap(ghostObject.pos[1]),width:ghostObject.item.width,height:ghostObject.item.height,rotation:0},ghostObject.item.color);ctx.globalAlpha=1;}
  if (buildingGesture?.kind==='wall' && buildingGesture.end) {
    ctx.save();
    ctx.strokeStyle='#167364';ctx.lineWidth=3;ctx.setLineDash([8,5]);
    ctx.beginPath();ctx.moveTo(...point(...buildingGesture.start));
    ctx.lineTo(...point(...buildingGesture.end));ctx.stroke();
    ctx.restore();
  }
};
// All edits share an undo entry, including vehicle poses moved by re-centering a floor.
checkpoint=function(){
  history.push({map:clone(documentMap),config:clone(configuration),floorId:floor().id});
  if (history.length>80) history.shift();
};
action('undo', async () => {
  if (!canUndoMap()) return;
  hideModelTooltip();
  const entry = history.pop();
  documentMap = entry.map || entry;
  if (entry.config) {
    configuration = entry.config;
    configOptions();
  }
  selected = null;
  setBuildMode('select');
  refresh(entry.floorId);
  await compile();
});
function canUndoMap() {
  return (typeof workspaceAllowsEditing!=='function'||workspaceAllowsEditing()) && history.length > 0 && !replay && !dragging && !buildingGesture && !catalogDrag && !cameraDrag;
}
action('deleteFloor',async()=>{
  if (!documentMap || replay || documentMap.floors.length<=1 || dragging ||
      buildingGesture || catalogDrag || cameraDrag) return;
  const level = floor();
  const index = documentMap.floors.indexOf(level);
  checkpoint();
  documentMap.floors.splice(index,1);
  for (const remaining of documentMap.floors) {
    for (const object of remaining.objects) {
      if (!Array.isArray(object.service_floors) || !object.service_floors.includes(level.id)) continue;
      object.service_floors = object.service_floors.filter(id=>id!==level.id);
      if (object.kind==='elevator' && !object.service_floors.length) object.service_floors.push(remaining.id);
    }
  }
  // Match the parking point as well because instance settings are shared across maps.
  const parking = new Set(level.objects.filter(object=>object.kind==='parking').map(object=>object.id));
  const count = configuration.instances.length;
  configuration.instances = configuration.instances.filter(instance=>
    instance.floor_id!==level.id || !parking.has(instance.parking_id));
  const removedInstances = count-configuration.instances.length;
  if (removedInstances) configOptions();
  selected = null;
  setBuildMode('select');
  dirty();
  refresh(documentMap.floors[Math.min(index,documentMap.floors.length-1)].id);
  notice('已删除「'+level.name+'」'+(removedInstances?'及 '+removedInstances+' 台关联车辆':'')+
    '。按 Ctrl+Z 撤销，点击「保存新版本」保留修改。');
  await compile();
});
const oldBlank=$('blank').onclick;
$('blank').onclick=async()=>{await oldBlank();setBuildMode('floor');notice('先在画布拖出楼层范围，四周会自动生成墙体；再从物品栏拖入病区用品');};
const oldAddFloor=$('addFloor').onclick;
$('addFloor').onclick=async()=>{await oldAddFloor();setBuildMode('floor');notice('在新楼层画布拖出面积范围，然后拖入物品');};
action('resizeFloor',()=>{const width=Number($('floorWidth').value),height=Number($('floorHeight').value);if(!Number.isFinite(width)||!Number.isFinite(height)||width<2||height<2||width>100||height>100)throw Error('楼层长宽应在 2 至 100 米之间');applyFootprint([-width/2,-height/2],[width/2,height/2]);});
action('rotate',async()=>{const object=floor().objects.find(o=>o.id===selected);if(!object||object.boundary_side)return;checkpoint();const before=clone(object);object.rotation=(object.rotation+15)%360;attachedMove(before,object);dirty();refresh();await compile();});
async function deleteSelectedObject() {
  if (!documentMap || replay || dragging || buildingGesture || catalogDrag || cameraDrag) return;
  const objects = floor().objects;
  const object = objects.find(item=>item.id===selected);
  if (!object) return;
  hideModelTooltip();
  checkpoint();
  const removed = new Set([object.id]);
  let count;
  do {
    count=removed.size;
    for (const child of objects) {
      if (removed.has(child.wall_id) ||
          (child.auto_link && (removed.has(child.bed_id) || removed.has(child.elevator_id)))) removed.add(child.id);
    }
  } while (removed.size!==count);
  floor().objects = objects.filter(item=>!removed.has(item.id));
  for (const remaining of floor().objects) {
    for (const key of ['bed_id','wall_id','waiting_id','exit_id','elevator_id']) {
      if (removed.has(remaining[key])) delete remaining[key];
    }
  }
  selected = null;
  dirty();
  refresh();
  await compile();
}
action('deleteObject',deleteSelectedObject);
window.addEventListener('keydown',event=>{
  if (event.defaultPrevented || event.isComposing ||
      document.activeElement?.closest('input,textarea,select,[contenteditable]') ||
      (typeof workspaceAllowsEditing==='function'&&!workspaceAllowsEditing())) return;
  if (event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey &&
      event.key.toLowerCase()==='z') {
    if (!canUndoMap()) return;
    event.preventDefault();
    if (!event.repeat) $('undo').click();
  } else if (event.key==='Delete' && !event.repeat && !event.altKey &&
      !event.ctrlKey && !event.metaKey && !event.shiftKey && selected && !replay) {
    event.preventDefault();
    $('deleteObject').click();
  }
});
window.addEventListener('scroll',hideModelTooltip,true);
/* Orthographic raised geometry, using the same compiled wall pieces as physics. */
let raisedView = true;
const planDraw = draw;
const planTransform = transform;
const planPoint = point;
const planWorld = world;
const planHit = hit;
const viewButton = document.createElement('button');
viewButton.textContent = '切换平面编辑';
$('drawFloor').parentElement.append(viewButton);
viewButton.onclick = () => {
  raisedView = !raisedView;
  viewButton.textContent = raisedView ? '切换平面编辑' : '切换立体建模';
  for (const id of ['orbitCamera','cameraLeft','cameraRight','cameraTop']) $(id).hidden = !raisedView;
  $('cameraZoom').textContent = '100%';
  Object.assign(camera,cameraDefaults);
  updateCanvasCursor();
  draw();
};
const radians = Math.PI / 180;
const cameraDefaults = {azimuth: 14, elevation: 59, zoom: 1, focusX: 0, focusY: 0};
const camera = {...cameraDefaults};
const buildingCameraDefaults = {azimuth:17,elevation:32,zoom:1};
const buildingCamera = {...buildingCameraDefaults};
const buildingSpinSpeed = 1.5; // Degrees per second, clockwise.
let buildingSpinEnabled = true;
let buildingSpinFrame = null;
let lastBuildingFrame = null;
let resumeBuildingSpinAt = 0;

function stopBuildingSpin() {
  if (buildingSpinFrame!==null) cancelAnimationFrame(buildingSpinFrame);
  buildingSpinFrame = null;
  lastBuildingFrame = null;
}
function animateBuilding(time) {
  buildingSpinFrame = null;
  if (!buildingOverview || !buildingSpinEnabled) return;
  if (cameraDrag || time<resumeBuildingSpinAt) {
    lastBuildingFrame = null;
  } else if (lastBuildingFrame===null) {
    lastBuildingFrame = time;
  } else if (time-lastBuildingFrame>=50) {
    const seconds = Math.min(time-lastBuildingFrame,100)/1000;
    lastBuildingFrame = time;
    buildingCamera.azimuth = (buildingCamera.azimuth+seconds*buildingSpinSpeed)%360;
    draw();
  }
  buildingSpinFrame = requestAnimationFrame(animateBuilding);
}
function updateBuildingSpin() {
  const button = $('buildingSpin');
  button.hidden = !buildingOverview;
  button.textContent = buildingSpinEnabled ? '暂停旋转' : '继续旋转';
  if (buildingOverview && buildingSpinEnabled) {
    if (buildingSpinFrame===null) buildingSpinFrame = requestAnimationFrame(animateBuilding);
  } else stopBuildingSpin();
}
$('buildingSpin').onclick = () => {
  buildingSpinEnabled = !buildingSpinEnabled;
  resumeBuildingSpinAt = 0;
  updateBuildingSpin();
};
function holdBuildingSpin() {
  if (buildingOverview) resumeBuildingSpinAt = performance.now()+4000;
}
function updateZoomLabel() {
  zoomLabel.textContent = Math.round((buildingOverview?buildingCamera.zoom:camera.zoom)*100)+'%';
}
let fittedViewport = null;
let cameraDrag = null;
let frameProjection = null;
const orbitButton = $('orbitCamera');
const zoomLabel = $('cameraZoom');

function cameraAxes() {
  const azimuth = camera.azimuth * radians;
  const elevation = camera.elevation * radians;
  return {
    cosAz: Math.cos(azimuth), sinAz: Math.sin(azimuth),
    sinEl: Math.sin(elevation), cosEl: Math.cos(elevation)
  };
}
transform = function() {
  if (frameProjection) return frameProjection;
  if (!raisedView) {
    const plan = planTransform(), scale = plan.scale*camera.zoom;
    return {scale,x:plan.x-camera.focusX*scale,y:plan.y+camera.focusY*scale,
      cosAz:1,sinAz:0,sinEl:1,cosEl:0};
  }
  const f = floor();
  const {cosAz, sinAz, sinEl, cosEl} = cameraAxes();
  const viewport = fittedFloor(f);
  const scale = camera.zoom * viewport.scale;
  const right = cosAz*camera.focusX + sinAz*camera.focusY;
  const away = -sinAz*camera.focusX + cosAz*camera.focusY;
  return {scale, x:canvas.width/2 - right*scale,
    y:canvas.height/2 + (away*sinEl + viewport.centerHeight*cosEl)*scale,
    cosAz, sinAz, sinEl, cosEl};
};
// Fit using the default view once per set of floor dimensions. Orbiting does
// not recalculate the scale or move the center of rotation.
function fittedFloor(floor) {
  if (fittedViewport?.width === floor.width && fittedViewport.height === floor.height &&
      fittedViewport.canvasWidth === canvas.width && fittedViewport.canvasHeight === canvas.height) return fittedViewport;
  const azimuth = cameraDefaults.azimuth*radians, elevation = cameraDefaults.elevation*radians;
  const width = Math.cos(azimuth)*floor.width + Math.sin(azimuth)*floor.height;
  const depth = Math.sin(azimuth)*floor.width + Math.cos(azimuth)*floor.height;
  const modelHeight = 2.2;
  const scale = Math.min((canvas.width-48)/width,
    (canvas.height-80)/(Math.sin(elevation)*depth + Math.cos(elevation)*(modelHeight+.15)));
  fittedViewport = {width:floor.width,height:floor.height,canvasWidth:canvas.width,canvasHeight:canvas.height,scale,centerHeight:(modelHeight-.15)/2};
  return fittedViewport;
}
function project3(x, y, z=0, t=transform()) {
  const right = t.cosAz*x + t.sinAz*y;
  const away = -t.sinAz*x + t.cosAz*y;
  return [t.x + right*t.scale, t.y - (away*t.sinEl + z*t.cosEl)*t.scale];
}
point = function(x,y) {return raisedView ? project3(x,y) : planPoint(x,y);};
function canvasPosition(event) {
  const bounds = canvas.getBoundingClientRect();
  return [(event.clientX-bounds.left)*canvas.width/bounds.width,
    (event.clientY-bounds.top)*canvas.height/bounds.height];
}
function groundPosition(px, py, t=transform()) {
  const right = (px-t.x)/t.scale;
  const away = (t.y-py)/(t.sinEl*t.scale);
  return [t.cosAz*right-t.sinAz*away, t.sinAz*right+t.cosAz*away];
}
world = function(event) {
  return raisedView ? groundPosition(...canvasPosition(event)) : planWorld(event);
};
function zoomCamera(factor, anchor) {
  if (!documentMap) return;
  if (buildingOverview) {
    holdBuildingSpin();
    buildingCamera.zoom = Math.max(.4,Math.min(3,buildingCamera.zoom*factor));
    updateZoomLabel();
    draw();
    return;
  }
  const ground = groundPosition(...anchor);
  camera.zoom = Math.max(.4, Math.min(4, camera.zoom*factor));
  const after = groundPosition(...anchor);
  camera.focusX += ground[0]-after[0];
  camera.focusY += ground[1]-after[1];
  updateZoomLabel();
  draw();
}
function orbitCamera(dx, dy) {
  holdBuildingSpin();
  const view = buildingOverview ? buildingCamera : camera;
  view.azimuth = (view.azimuth+dx)%360;
  view.elevation = Math.max(12, Math.min(buildingOverview?75:90,view.elevation+dy));
  draw();
}
const viewCenter = () => [canvas.width/2,canvas.height/2];
$('cameraIn').onclick = () => zoomCamera(1.2, viewCenter());
$('cameraOut').onclick = () => zoomCamera(1/1.2, viewCenter());
$('cameraLeft').onclick = () => orbitCamera(-30,0);
$('cameraRight').onclick = () => orbitCamera(30,0);
$('cameraFit').onclick = () => {
  if (buildingOverview) {
    Object.assign(buildingCamera,buildingCameraDefaults);
    holdBuildingSpin();
  }
  else Object.assign(camera,cameraDefaults);
  updateZoomLabel();
  draw();
};
$('cameraTop').onclick = () => {
  camera.azimuth = 0;
  camera.elevation = 90;
  draw();
};
function updateCanvasCursor() {
  canvas.style.cursor = buildingOverview ? (hoveredLevel ? 'pointer' : 'default') :
    cameraDrag ? 'grabbing' : buildMode==='pan' ? 'grab' : taskPicking ? 'crosshair' :
    buildMode==='select' ? 'default' : 'crosshair';
}
const editPointerDown = canvas.onpointerdown;
const editPointerMove = canvas.onpointermove;
const editPointerUp = canvas.onpointerup;
const editPointerCancel = canvas.onpointercancel;
function startCameraDrag(event, surface, pan) {
  event.preventDefault();
  cameraDrag = {pointer:event.pointerId,position:canvasPosition(event),pan,
    clientX:event.clientX,clientY:event.clientY};
  surface.setPointerCapture(event.pointerId);
  updateCanvasCursor();
}
function pickCanvasTaskBed(event) {
  const level=floor();
  const ground=world(event);
  const marker=hit(ground,object=>object.kind==='service');
  let bed;
  if (!marker && raisedView) {
    const t=transform(), [x,y]=canvasPosition(event);
    bed=level.objects.findLast(object=>object.kind==='bed' &&
      containsPoint(object,groundPosition(x,y+(objectHeight(object)+.15)*t.cosEl*t.scale,t)));
  }
  bed=bed||hit(ground,object=>object.kind==='bed');
  const service=marker||(bed&&level.objects.find(object=>object.kind==='service' && object.bed_id===bed.id));
  if (service) selectTaskBeds([service.id]);
  else if (bed) taskFeedback('该床位还未关联床旁服务点。');
}
function pickCanvasTaskRoom(event) {
  const position=world(event);
  const door=doorAtRoomLabel(position) || doorAtPosition(position);
  if (!door) {taskFeedback('请点击病房门。',true);return;}
  const room=taskRoomsOn(floor()).find(item=>item.id===door.id);
  if (!room?.beds.length) {
    taskFeedback('这扇门未识别到病房床位。可在地图建模中填写门的病房编号和床位的所属病房。',true);
    return;
  }
  selectTaskRoom(room);
}
canvas.onpointerdown = event => {
  hideModelTooltip();
  if (event.button!==0 || cameraDrag) return;
  if (buildingOverview) {
    const level = overviewFloorAt(canvasPosition(event));
    if (level) {
      $('floor').value = level;
      $('floor').onchange();
    }
    return;
  }
  if (buildMode==='pan') {
    if (documentMap) startCameraDrag(event,canvas,true);
    return;
  }
  if (documentMap && pickingObstaclePosition && viewingCurrentRun() && !replay) {
    pickObstaclePosition(world(event));
    return;
  }
  if (documentMap && taskPicking && !replay) {
    if (taskPicking==='room') pickCanvasTaskRoom(event);
    else pickCanvasTaskBed(event);
    return;
  }
  if (typeof workspaceAllowsEditing==='function'&&!workspaceAllowsEditing()) return;
  editPointerDown(event);
};
function moveCameraDrag(event) {
  if (cameraDrag.pointer!==event.pointerId) return;
  const position = canvasPosition(event);
  if (cameraDrag.pan) {
    const projection = transform();
    const previous = groundPosition(...cameraDrag.position,projection);
    const current = groundPosition(...position,projection);
    camera.focusX += previous[0]-current[0];
    camera.focusY += previous[1]-current[1];
    draw();
  } else {
    orbitCamera((event.clientX-cameraDrag.clientX)*.35,(event.clientY-cameraDrag.clientY)*.25);
  }
  cameraDrag.position = position;
  cameraDrag.clientX = event.clientX;
  cameraDrag.clientY = event.clientY;
}
canvas.onpointermove = event => {
  if (buildingOverview) {
    const level = overviewFloorAt(canvasPosition(event));
    if (level!==hoveredLevel) {hoveredLevel=level;updateCanvasCursor();draw();}
    return;
  }
  if (cameraDrag) {moveCameraDrag(event);return;}
  editPointerMove(event);
  if (event.pointerType!=='mouse' || event.buttons || !documentMap || dragging || calibration ||
      buildingGesture || catalogDrag || buildMode!=='select' || $('tool').value!=='select') {
    hideModelTooltip();
    return;
  }
  if (!taskPicking && showTaskRouteTooltip(event)) return;
  const object=hit(world(event));
  if (object) showModelTooltip(object,event.clientX,event.clientY);
  else hideModelTooltip();
};
canvas.addEventListener('pointerleave',()=>{
  hideModelTooltip();
  if (buildingOverview && hoveredLevel) {hoveredLevel=null;updateCanvasCursor();draw();}
});
function endCameraDrag(event) {
  if (!cameraDrag) return false;
  if (cameraDrag.pointer===event.pointerId) {
    cameraDrag = null;
    holdBuildingSpin();
    updateCanvasCursor();
  }
  return true;
}
canvas.onpointerup = event => {if (!buildingOverview && !endCameraDrag(event)) editPointerUp(event);};
canvas.onpointercancel = event => {if (!endCameraDrag(event)) editPointerCancel(event);};
canvas.addEventListener('lostpointercapture',endCameraDrag);
orbitButton.onpointerdown = event => {
  if (event.button===0 && documentMap && (raisedView || buildingOverview) && !cameraDrag) startCameraDrag(event,orbitButton,false);
};
orbitButton.onpointermove = event => {if (cameraDrag) moveCameraDrag(event);};
orbitButton.onpointerup = endCameraDrag;
orbitButton.onpointercancel = endCameraDrag;
orbitButton.addEventListener('lostpointercapture',endCameraDrag);
orbitButton.onclick = event => {if (event.detail===0 && documentMap) orbitCamera(30,0);};
function objectHeight(object) {return object.z ?? (object.kind==='wall'?1.5:.6);}
function polygon(points,fill,stroke) {
  ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();
  if(fill){ctx.fillStyle=fill;ctx.fill();}
  if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=.7;ctx.stroke();}
}
function corners3(object,z) {
  const angle=(object.rotation||0)*Math.PI/180;
  const projection=transform();
  return [[-1,-1],[1,-1],[1,1],[-1,1]].map(([x,y])=>{
    x*=object.width/2;y*=object.height/2;
    return project3(object.x+x*Math.cos(angle)-y*Math.sin(angle),object.y+x*Math.sin(angle)+y*Math.cos(angle),z,projection);
  });
}
function block(object,height,colors,base=0) {
  const bottom=corners3(object,base),top=corners3(object,base+height);
  for(let i=0;i<4;i++) {
    const j=(i+1)%4;
    const [x,y]=bottom[i], [right,down]=bottom[j], [upperX,upperY]=top[j];
    const facing=(right-x)*(upperY-y)-(down-y)*(upperX-x)<-1e-6;
    if(facing) polygon([bottom[i],bottom[j],top[j],top[i]],colors[i%2===0?2:1],'#53686e55');
  }
  polygon(top,colors[0],'#53686e55');
}
function drawVehicleCylinder(xy,radius,color) {
  const t=transform();
  const height=.45;
  const ring=z=>Array.from({length:24},(_,i)=>{
    const angle=i*Math.PI/12;
    return project3(xy[0]+radius*Math.cos(angle),xy[1]+radius*Math.sin(angle),z,t);
  });
  const bottom=ring(0),top=ring(height);
  for (let i=0;i<bottom.length;i++) {
    const j=(i+1)%bottom.length;
    if ((bottom[j][0]-bottom[i][0])*(top[j][1]-bottom[j][1])>=-1e-6) continue;
    const side=[bottom[i],bottom[j],top[j],top[i]];
    polygon(side,color);
    polygon(side,'#10243355');
  }
  polygon(top,color,'#243c49');
}

function runningFleetOnFloor(level) {
  if (!replay && (!viewingCurrentRun() || !state.started || state.run_id===editedFleetRunId)) return null;
  // In the robot view, other vehicles are shown only through measurement returns.
  return (state?.robots||[]).filter(robot=>(robot.floor_id===undefined?documentMap.floors[0].id:robot.floor_id)===level.id &&
    (!robotPerceptionView() || robot.id===$('perceptionRobot').value));
}
function routeScreenPoints(robot,projection) {
  return [robot.xy,...(robot.path||[])].map(([x,y])=>project3(x,y,0,projection));
}
function distanceToRouteSegment(point,start,end) {
  const [dx,dy]=[end[0]-start[0],end[1]-start[1]];
  const lengthSquared=dx*dx+dy*dy;
  if (!lengthSquared) return Math.hypot(point[0]-start[0],point[1]-start[1]);
  const fraction=Math.max(0,Math.min(1,((point[0]-start[0])*dx+(point[1]-start[1])*dy)/lengthSquared));
  return Math.hypot(point[0]-start[0]-fraction*dx,point[1]-start[1]-fraction*dy);
}
function showTaskRouteTooltip(pointer) {
  const level=floor(), robots=runningFleetOnFloor(level);
  if (!robots?.length) return false;
  const position=canvasPosition(pointer), projection=transform();
  let nearest=null, threshold=7;
  for (const robot of robots) {
    const points=routeScreenPoints(robot,projection);
    for (let i=1;i<points.length;i++) {
      const distance=distanceToRouteSegment(position,points[i-1],points[i]);
      if (distance<threshold) {nearest=robot;threshold=distance;}
    }
  }
  if (!nearest) return false;
  const task=(state.tasks||[]).find(item=>nearest.task_id ? item.task_id===nearest.task_id :
    item.status==='assigned' && item.robot_id===nearest.id);
  if (!task) return false;
  const spec=state.task_specs?.[task.task_id]||{};
  const id=spec.patrol_id||task.task_id;
  const record=replay?null:taskRecords.find(item=>item.id===id);
  const destination=taskDestinations().find(item=>item.id===task.bed_id);
  const serviceTypes={dwell:'停留计时',manual:'人工确认',mqtt:'MQTT 采样'};
  modelTitle.textContent=nearest.id+' · '+(spec.content||'巡查路线');
  modelSize.textContent='任务 '+(record?.display_number||spec.display_number||id);
  modelGuide.textContent='目标：'+(destination?.label||task.bed_id);
  modelControls.textContent=[taskQueueStatus[task.status]||task.status,serviceTypes[spec.service],
    '优先级 '+taskPriorityLabels[taskPriorityLevel(spec.priority)],
    spec.deadline==null?'':'截止 '+spec.deadline+' 仿真秒'].filter(Boolean).join(' · ');
  hoveredRoutePointer={clientX:pointer.clientX,clientY:pointer.clientY};
  positionModelTooltip(pointer.clientX,pointer.clientY);
  return true;
}

function drawFleet(level,showLabels=true) {
  const parking=level.objects.filter(object=>object.kind==='parking');
  const robots=runningFleetOnFloor(level) ??
    (configuration?.instances||[]).filter(instance=>instance.floor_id===level.id).flatMap(instance=>{
      const spot=parking.find(point=>point.id===instance.parking_id);
      return spot?[{...instance,xy:[spot.x,spot.y]}]:[];
    });
  const models=replay?.input?.models||configuration?.models||[];
  const projection=transform();
  ctx.save();
  ctx.textAlign='center';
  ctx.textBaseline='middle';
  ctx.font='600 12px sans-serif';
  if (showLabels && (viewingCurrentRun() || replay)) {
    for (const visit of Object.values(state?.dispatch_plan||{})) {
      if (robotPerceptionView() && visit.robot_id!==$('perceptionRobot').value) continue;
      const robot=state.robots.find(item=>item.id===visit.robot_id);
      const color=Array.isArray(robot?.color)
        ? 'rgb('+robot.color.slice(0,3).map(value=>Math.round(value*255)).join(',')+')'
        : (vehicleColors[robot?.color]||vehicleColors.blue)[1];
      ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.setLineDash([5,5]);ctx.globalAlpha=.55;
      for (const leg of visit.legs.filter(item=>item.floor_id===level.id && item.path.length)) {
        ctx.beginPath();
        leg.path.forEach(([x,y],index)=>{
          const position=project3(x,y,0,projection);
          if (index) ctx.lineTo(...position); else ctx.moveTo(...position);
        });
        ctx.stroke();
      }
    }
    ctx.setLineDash([]);ctx.globalAlpha=1;
  }
  if (showLabels) {
    const numbers=parkingNumbers(level);
    for (const spot of parking) {
      const [x,y]=project3(spot.x,spot.y,0,projection);
      ctx.fillStyle='#25424f';
      ctx.fillText(numbers.get(spot.id),x,y+spot.height*projection.scale/2+9);
    }
  }
  for (const robot of robots) {
    const color=Array.isArray(robot.color)
      ? 'rgb('+robot.color.slice(0,3).map(value=>Math.round(value*255)).join(',')+')'
      : (vehicleColors[robot.color]||vehicleColors.blue)[1];
    if (showLabels && robot.path?.length) {
      const [start,...points]=routeScreenPoints(robot,projection);
      ctx.beginPath();ctx.moveTo(...start);
      for (const point of points) ctx.lineTo(...point);
      ctx.lineJoin='round';ctx.lineCap='round';
      ctx.strokeStyle='#ffffffdd';ctx.lineWidth=6;ctx.stroke();
      ctx.strokeStyle=color;ctx.lineWidth=3;ctx.stroke();
    }
    const model=models.find(item=>item.id===robot.model_id);
    const radius=model?Math.min(model.width,model.length)/2:.25;
    drawVehicleCylinder(robot.xy,radius,color);
    if (showLabels) {
      const [x,y]=project3(...robot.xy,.45,projection);
      ctx.fillStyle='#183442';
      ctx.fillText(robot.id,x,y-radius*projection.scale-7);
    }
  }
  ctx.restore();
}
function detailObject(object,dx,dy,width,height) {
  const a=(object.rotation||0)*Math.PI/180;
  return {...object,x:object.x+dx*Math.cos(a)-dy*Math.sin(a),y:object.y+dx*Math.sin(a)+dy*Math.cos(a),width,height};
}
function raisedObject(object) {
  const height=objectHeight(object);
  if(object.kind==='wall'){block(object,height,['#9eafb1','#72888c','#829a9d']);return;}
  if(object.kind==='bed') {
    block(object,height,['#6a9dad','#345f72','#47798b']);
    block(detailObject(object,0,0,object.width*.92,object.height*.92),.15,['#e2eff0','#adc6cb','#bfd8db'],height);
    block(detailObject(object,0,object.height*.28,object.width*.78,object.height*.22),.12,['#f6fbf9','#c6d9dc','#dbe9e9'],height+.15);
    for(const end of [-1,1])block(detailObject(object,0,end*object.height*.47,object.width,.07),.45,['#ccd9db','#8fa7ae','#a9bec4'],height*.7);
    return;
  }
  const station=object.asset==='nurse_station'||object.name?.includes('station');
  const colors=station?['#64b4bd','#287989','#3698a6']:['#cbb58f','#968266','#b39c78'];
  block(object,height,colors);
  if(station||object.asset==='desk'||object.asset==='equipment') {
    block(detailObject(object,-object.width*.2,0,object.width*.22,object.height*.25),.08,['#314f5c','#193d4a','#275666'],height);
    block(detailObject(object,-object.width*.2,object.height*.06,object.width*.22,.07),.3,['#b4dfe6','#335765','#4c8594'],height+.08);
  }
}
function doorRoomLabel(door,text) {
  const [x,y] = point(door.x,door.y);
  const width = Math.ceil(ctx.measureText(text).width)+14;
  return {x,y:y-13,width};
}
function taskDoorLabels(level) {
  return taskPicking==='room'
    ? new Map(taskRoomsOn(level).filter(room=>room.beds.length).map(room=>[room.id,room.name]))
    : new Map();
}
function doorAtPosition(position) {
  return floor().objects.find(door=>{
    if (door.kind!=='door') return false;
    const angle=(door.rotation||0)*Math.PI/180;
    const dx=position[0]-door.x,dy=position[1]-door.y;
    return Math.abs(dx*Math.cos(angle)+dy*Math.sin(angle))<=door.width/2 &&
      Math.abs(-dx*Math.sin(angle)+dy*Math.cos(angle))<=Math.max(.2,door.height/2);
  });
}
function doorAtRoomLabel(position) {
  const [x,y]=point(...position);
  const level=floor(), labels=taskDoorLabels(level);
  ctx.save();
  ctx.font='600 12px sans-serif';
  const hitLabel=level.objects.find(door=>{
    if (door.kind!=='door') return false;
    const text=labels.get(door.id)||door.room_number;
    if (!text) return false;
    const label=doorRoomLabel(door,text);
    return Math.abs(x-label.x)<=label.width/2 && Math.abs(y-label.y)<=10;
  });
  ctx.restore();
  return hitLabel;
}
function drawWallElevators(level,elevated=raisedView) {
  for (const entrance of level.objects) {
    if (entrance.kind!=='elevator' || !entrance.wall_id) continue;
    const wall=level.objects.find(object=>object.id===entrance.wall_id);
    if (!wall) continue;
    const height=elevated?objectHeight(wall):0;
    polygon(corners3({...entrance,height:Math.max(.32,entrance.height)},height),elevatorAccent,'#71421f');
  }
}
function wallElevatorAt(screenPosition,level) {
  return level.objects.find(object=>{
    if (object.kind!=='elevator' || !object.wall_id) return false;
    const wall=level.objects.find(item=>item.id===object.wall_id);
    if (!wall) return false;
    const height=raisedView?objectHeight(wall):0;
    const ends=wallAxis(object).map(([x,y])=>project3(x,y,height));
    const nearest=pointOnSegment(screenPosition,...ends);
    return Math.hypot(nearest[0]-screenPosition[0],nearest[1]-screenPosition[1])<=7;
  });
}
function drawDoorRoomLabels(level) {
  const labels=taskDoorLabels(level);
  ctx.save();
  ctx.font='600 12px sans-serif';
  ctx.textAlign='center';
  ctx.textBaseline='middle';
  for (const door of level.objects) {
    if (door.kind!=='door') continue;
    const text=labels.get(door.id)||door.room_number;
    if (!text) continue;
    const {x,y,width}=doorRoomLabel(door,text);
    ctx.fillStyle=labels.has(door.id)||door.id===selected?'#146759':'#224952';
    ctx.fillRect(x-width/2,y-9,width,18);
    ctx.fillStyle='#fff';
    ctx.fillText(text,x,y);
  }
  ctx.restore();
}
hit = function(pos) {
  const door = doorAtRoomLabel(pos) || doorAtPosition(pos);
  if (door) return door;
  const entrance=wallElevatorAt(point(...pos),floor());
  if (entrance) return entrance;
  if(!raisedView)return planHit(pos);
  const t=transform();
  const candidates=[...floor().objects].sort((a,b)=>depth(a,t)-depth(b,t));
  for(const object of candidates) {
    const height=['wall','bed','furniture'].includes(object.kind)?objectHeight(object):0;
    for(const fraction of [1,.5,0]) {
      const lift=t.cosEl*height*fraction/t.sinEl;
      const y=pos[1]-t.cosAz*lift, x=pos[0]+t.sinAz*lift;
      const a=(object.rotation||0)*Math.PI/180,dx=x-object.x,dy=y-object.y;
      if(Math.abs(dx*Math.cos(a)+dy*Math.sin(a))<=Math.max(.15,object.width/2)&&Math.abs(-dx*Math.sin(a)+dy*Math.cos(a))<=Math.max(.15,object.height/2))return object;
    }
  }
};
function depth(object,t) {
  const angle=(object.rotation||0)*radians;
  const azimuth=camera.azimuth*radians;
  const extent=(Math.abs(Math.sin(angle-azimuth))*object.width+
    Math.abs(Math.cos(angle-azimuth))*object.height)/2;
  return -t.sinAz*object.x + t.cosAz*object.y - extent;
}
draw = function() {
  if(!raisedView){planDraw();return;}
  if(!documentMap)return;
  const f=floor(),t=transform();
  ctx.fillStyle='#b5b6cb';ctx.fillRect(0,0,canvas.width,canvas.height);
  $('floorArea').textContent=`${f.width.toFixed(1)} × ${f.height.toFixed(1)} m · ${(f.width*f.height).toFixed(1)} m²`;
  const slab={x:0,y:0,width:f.width,height:f.height,rotation:0};
  polygon(corners3({...slab,x:.3,y:-.35},-.12),'#777f9560');
  block(slab,.15,['#d8e1e2','#a4b4b9','#b9c9cc'],-.15);
  if(f.background) {
    if(backgroundUrl!==f.background.data){backgroundUrl=f.background.data;backgroundImage=new Image();backgroundImage.onload=draw;backgroundImage.src=backgroundUrl;}
    if(backgroundImage?.complete&&backgroundImage.naturalWidth){const [x,y]=point(f.background.x,f.background.y);ctx.save();ctx.globalAlpha=.35;ctx.transform(t.cosAz*t.scale,t.sinAz*t.sinEl*t.scale,-t.sinAz*t.scale,t.cosAz*t.sinEl*t.scale,x,y);const width=f.background.width_m;ctx.drawImage(backgroundImage,0,0,width,width*backgroundImage.height/backgroundImage.width);ctx.restore();}
  }
  ctx.strokeStyle='#bdccce80';ctx.lineWidth=.5;
  for(let x=-f.width/2;x<=f.width/2;x+=1){ctx.beginPath();ctx.moveTo(...point(x,-f.height/2));ctx.lineTo(...point(x,f.height/2));ctx.stroke();}
  for(let y=-f.height/2;y<=f.height/2;y+=1){ctx.beginPath();ctx.moveTo(...point(-f.width/2,y));ctx.lineTo(...point(f.width/2,y));ctx.stroke();}
  for(const object of f.objects.filter(o=>!['wall','bed','furniture','door'].includes(o.kind) && !(o.kind==='elevator' && o.wall_id))) {
    const colors={forbidden:'#d77e7e66',one_way:'#d4bc6d77',single_lane:'#9aa9d888',service:'#43ad83',parking:'#6d8fb7',elevator:elevatorAccent,waiting:'#c8ad5c',exit:'#6caeb566'};
    polygon(corners3(object,.02),colors[object.kind]||'#5aa597');
  }
  for(const route of preview.filter(r=>r.floor_id===f.id&&r.path.length)){ctx.strokeStyle='#278b70';ctx.lineWidth=2;ctx.beginPath();route.path.forEach((p,i)=>i?ctx.lineTo(...point(...p)):ctx.moveTo(...point(...p)));ctx.stroke();}
  const geometry=compiled.find(c=>c.id===f.id)?.rectangles||f.objects.filter(o=>['wall','bed','furniture'].includes(o.kind));
  const solids=geometry.map(o=>({...o}));
  // Moving walls show their current pose immediately while a compile is pending.
  const moving=dragging?.object||buildingGesture?.object;
  if(moving && ['wall','bed','furniture'].includes(moving.kind)){
    for(let i=solids.length-1;i>=0;i--)if(solids[i].id===moving.id)solids.splice(i,1);
    solids.push(moving);
  }
  solids.sort((a,b)=>depth(b,t)-depth(a,t));
  for(const object of solids) {
    const shadow=corners3({...object,x:object.x+.25,y:object.y-.4},.01);polygon(shadow,'#566e7525');
    raisedObject(object);
  }
  const namedBeds = bedsWithServiceNames(f);
  for(const object of f.objects.filter(o=>(o.kind==='bed'&&!namedBeds.has(o.id))||o.asset==='nurse_station'||o.kind==='service')){const p=project3(object.x,object.y,object.kind==='service'?.1:objectHeight(object)+.6);ctx.fillStyle='#25424f';ctx.font='13px sans-serif';ctx.textAlign='center';ctx.fillText(object.name||labels[object.kind],p[0],p[1]-5);}
  drawFleet(f);
  const object=f.objects.find(o=>o.id===selected);
  if(object&&!replay&&(typeof workspaceAllowsEditing!=='function'||workspaceAllowsEditing())){polygon(corners3(object,0),null,'#ffb83b');if(!object.boundary_side){const controls=handles(object);for(const key of ['resize','rotate']){const [x,y]=point(...controls[key]);ctx.fillStyle='#fff6dd';ctx.strokeStyle='#b87717';ctx.beginPath();if(key==='rotate')ctx.arc(x,y,7,0,Math.PI*2);else ctx.rect(x-6,y-6,12,12);ctx.fill();ctx.stroke();}}}
  if(ghostObject){ctx.globalAlpha=.65;raisedObject({x:snap(ghostObject.pos[0]),y:snap(ghostObject.pos[1]),width:ghostObject.item.width,height:ghostObject.item.height,rotation:0,kind:ghostObject.item.kind,asset:ghostObject.item.key});ctx.globalAlpha=1;}
  if (buildingGesture?.kind==='wall' && buildingGesture.end) {
    ctx.save();
    ctx.strokeStyle='#137b64';ctx.lineWidth=3;ctx.setLineDash([7,4]);
    ctx.beginPath();ctx.moveTo(...point(...buildingGesture.start));
    ctx.lineTo(...point(...buildingGesture.end));ctx.stroke();
    ctx.restore();
  }
  ctx.textAlign='left';
};

function drawFootprintPreview() {
  if (!['floor','room'].includes(buildingGesture?.kind) || !buildingGesture.end) return;
  const {start,end} = buildingGesture;
  const room = buildingGesture.kind==='room';
  const bounds = room ? roomBounds(start,end,floor()) : null;
  const dimensions = bounds || footprintDimensions(start,end);
  const {width,height} = dimensions;
  const area = width*height;
  const origin = room ? bounds.low : start;
  const x = room ? bounds.high[0] : start[0]+Math.sign(end[0]-start[0])*width;
  const y = room ? bounds.high[1] : start[1]+Math.sign(end[1]-start[1])*height;
  const corner = room ? point(end[0]>=start[0]?x:origin[0],end[1]>=start[1]?y:origin[1]) : point(x,y);
  const valid = width>=2 && height>=2;
  ctx.save();
  ctx.setLineDash([7,4]);
  polygon([point(...origin),point(x,origin[1]),point(x,y),point(origin[0],y)],
    valid?'#56b8a044':'#d8ab6244',valid?'#167364':'#9c651d');
  ctx.setLineDash([]);
  const format = value => value.toFixed(2).replace(/\.?0+$/,'');
  const size = format(width)+' × '+format(height)+' m';
  const detail = format(area)+' m²'+(height>0 && width>0?' · 长宽比 '+format(width/height)+':1':'');
  ctx.font='bold 14px sans-serif';
  const sizeWidth=ctx.measureText(size).width;
  ctx.font='12px sans-serif';
  const boxWidth=Math.max(sizeWidth,ctx.measureText(detail).width)+20;
  const left=Math.max(8,Math.min(corner[0]+12,canvas.width-boxWidth-8));
  const top=Math.max(44,Math.min(corner[1]+12,canvas.height-91));
  ctx.fillStyle='#173542';
  ctx.fillRect(left,top,boxWidth,42);
  ctx.textAlign='left';ctx.textBaseline='alphabetic';ctx.fillStyle='#fff';
  ctx.font='bold 14px sans-serif';ctx.fillText(size,left+10,top+17);
  ctx.font='12px sans-serif';ctx.fillText(detail,left+10,top+34);
  ctx.restore();
}

function drawModelingGuides() {
  syncObjectSelection();
  if (wallDoorTarget && (wallDoorTarget.level!==floor() ||
    (wallDoorTarget.entryId ? !floor().objects.some(object=>object.id===wallDoorTarget.entryId) : !currentWallDoor()))) clearWallDoorTarget();
  const doorPreview = currentWallDoor()?.placement?.pose;
  if (doorPreview) {
    const elevator=$('wallFixtureKind').value==='elevator';
    polygon(footprintCorners(doorPreview).map(p=>point(...p)),elevator?(elevatorAccent+'99'):'#ffc16ba8','#9c5516');
  }
  const report=wallReport(floor());
  const status=$('wallStatus');
  const message=report.gaps.length
    ? '外墙未闭合（门洞不计为缺口）：'+report.gaps.map(gap=>gap.name+'缺 '+gap.length.toFixed(2)+' m').join('、')
    : report.ends.length ? '外墙已闭合。'
    : '外墙已闭合，未发现悬空墙端。';
  const issues=checkedGeometry?.map===documentMap && !checkedGeometry.valid
    ? [...checkedGeometry.structure,...checkedGeometry.geometry] : [];
  const wallMessage=message+(report.ends.length
    ? ' · 紫色圆点：'+report.ends.length+' 个未连接墙端' : '');
  const detail=issues.length ? wallMessage+' · 地图校验：'+issues[0]+(issues.length>1?'（共 '+issues.length+' 项）':'') : wallMessage;
  if (status.textContent!==detail) status.textContent=detail;
  status.dataset.warning=String(!!(report.gaps.length || report.ends.length || issues.length));
  ctx.save();
  for (const [positions,color] of [[report.gaps.map(g=>g.point),'#ba4d24'],[report.ends,'#8638d1'],
      [snapHint?[snapHint]:[],'#12876c']]) {
    for (const position of positions) {
      const [x,y]=point(...position);
      ctx.beginPath();ctx.arc(x,y,positions===report.ends?7:5,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();
      ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke();
    }
  }
  const level=floor();
  for (const object of copyOutline(level,level.objects.filter(o=>groupSelection.has(o.id)))) {
    polygon(footprintCorners(object).map(p=>point(...p)),'#16847033','#167364');
  }
  if (buildingGesture?.kind==='box') {
    const [x,y]=buildingGesture.start,[xx,yy]=buildingGesture.end;
    ctx.setLineDash([6,4]);
    polygon([[x,y],[xx,y],[xx,yy],[x,yy]].map(p=>point(...p)),'#16847033','#167364');
    ctx.setLineDash([]);
  }
  if (groupPlacement?.target) {
    for (const object of translatedGroup(groupPlacement,groupPlacement.target,groupPlacement.outline)) {
      polygon(footprintCorners(object).map(p=>point(...p)),'#35ad8b66','#167364');
    }
  }
  ctx.restore();
}

function drawScaleBar(pixelsPerMeter) {
  // Screen-horizontal measurements follow the camera's unforeshortened ground axis.
  const capacity = 150 / pixelsPerMeter;
  const unit = 10 ** Math.floor(Math.log10(capacity));
  const meters = (capacity >= 5*unit ? 5 : capacity >= 2*unit ? 2 : 1)*unit;
  const width = meters*pixelsPerMeter;
  const text = meters < 1 ? Math.round(meters*100)+' cm' : meters+' m';
  const right = canvas.width-30, bottom = canvas.height-31;
  const left = right-width;
  ctx.save();
  ctx.font = 'bold 15px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillStyle = '#ffffffed';
  ctx.fillRect(right-Math.max(90,width+24)+12,bottom-33,Math.max(90,width+24),50);
  ctx.fillStyle = ctx.strokeStyle = '#263e49';
  ctx.fillText(text,(left+right)/2,bottom-11);
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(left,bottom-5);ctx.lineTo(left,bottom+5);
  ctx.moveTo(left,bottom);ctx.lineTo(right,bottom);
  ctx.moveTo(right,bottom-5);ctx.lineTo(right,bottom+5);
  ctx.stroke();
  ctx.restore();
}

function updateViewportHelp() {
  $('viewportHelp').textContent = buildingOverview
    ? '左键点击楼层进入单层。用 ＋／− 缩放，拖右上角旋转整栋楼。'
    : buildMode==='pan' ? '移动画布已开启：按住左键拖动。点「结束移动」或按 Esc 返回编辑。'
    : taskPicking ? (taskPicking==='room'?'左键点击病房门':'左键点选床位或服务点')+
      '，切换楼层可继续选择。已选 '+taskBeds.size+' 个。'
    : typeof workspaceAllowsEditing==='function'&&!workspaceAllowsEditing() ? '地图为浏览模式。可切换楼层，使用缩放、旋转或移动画布查看。'
    : '左键编辑物件。点「移动画布」后可拖动平移。';
}

function setBuildingOverview(enabled) {
  buildingOverview = enabled;
  hoveredLevel = null;
  hideModelTooltip();
  const button = $('buildingView');
  button.textContent = enabled ? '返回单层' : '查看整栋楼';
  button.setAttribute('aria-pressed',String(enabled));
  for (const id of ['orbitCamera','cameraLeft','cameraRight']) $(id).hidden = !enabled && !raisedView;
  $('cameraTop').hidden = enabled || !raisedView;
  updateZoomLabel();
  viewButton.hidden = enabled;
  $('wallStatus').hidden = enabled;
  updateBuildingSpin();
  $('panCamera').hidden = enabled;
  updateViewportHelp();
  renderFloorTabs();
  updateCanvasCursor();
}
action('buildingView',()=>{
  if (!documentMap || buildingGesture || dragging || catalogDrag || cameraDrag) return;
  if (!buildingOverview) {
    calibration = null;
    setBuildMode('select');
  }
  setBuildingOverview(!buildingOverview);
  draw();
});
function overviewFloorAt([x,y]) {
  return overviewTargets.find(target=>x>=target.left && x<=target.right &&
    y>=target.top && y<=target.bottom)?.id || null;
}
function drawBuilding() {
  const levels = documentMap.floors;
  const latest = visibleBedVitals();
  const azimuth = buildingCamera.azimuth*radians, elevation = buildingCamera.elevation*radians;
  const cosAz=Math.cos(azimuth),sinAz=Math.sin(azimuth);
  const cosEl=Math.cos(elevation),sinEl=Math.sin(elevation);
  const topInset=48, availableHeight=canvas.height-topInset-12;
  const gap=Math.min(14,Math.max(6,availableHeight/levels.length*.07));
  const gapTotal=gap*(levels.length-1);
  const modelSpace=Math.max(1,availableHeight-gapTotal);
  const labelSpace=Math.min(150,canvas.width*.3);
  const bodyWidth=canvas.width-labelSpace-32;
  const centerX=16+bodyWidth/2;
  const floorSpans=levels.map(level=>Math.hypot(level.width,level.height));
  const heights=levels.map(level=>level.objects.reduce(
    (max,object)=>Math.max(max,objectHeight(object)+.4),1.9));
  const fitEl=buildingCameraDefaults.elevation*radians;
  const fitHeight=floorSpans.reduce((sum,span,index)=>
    sum+span*Math.sin(fitEl)+(heights[index]+.15)*Math.cos(fitEl),0);
  const baseScale=Math.min(bodyWidth/Math.max(...floorSpans),modelSpace/fitHeight);
  const scale=buildingCamera.zoom*baseScale;
  const slotHeights=levels.map((level,index)=>(
    (level.width*Math.abs(sinAz)+level.height*Math.abs(cosAz))*sinEl+
    (heights[index]+.15)*cosEl)*baseScale);
  const stackHeight=slotHeights.reduce((sum,height)=>sum+height,0);
  const slotFactor=Math.min(1,modelSpace/stackHeight);
  let rowTop=topInset+(availableHeight-stackHeight*slotFactor-gapTotal)/2;
  overviewTargets=[];
  ctx.fillStyle='#b5b6cb';
  ctx.fillRect(0,0,canvas.width,canvas.height);
  for (let index=levels.length-1;index>=0;index--) {
    const level=levels[index];
    const rowHeight=slotHeights[index]*slotFactor;
    const centerY=rowTop+rowHeight/2;
    const maxHeight=heights[index];
    const active=level.id===floor().id;
    const hovered=level.id===hoveredLevel;
    const t={scale,x:centerX,y:centerY+maxHeight*cosEl*scale/2,cosAz,sinAz,sinEl,cosEl};
    frameProjection=t;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0,rowTop,bodyWidth+32,rowHeight);
    ctx.clip();
    try {
      const slab={x:0,y:0,width:level.width,height:level.height,rotation:0};
      block(slab,.15,hovered?['#bde0d9','#769f99','#94c2ba']:['#d8e1e2','#a4b4b9','#b9c9cc'],-.15);
      const solids=compiled.find(entry=>entry.id===level.id)?.rectangles ||
        level.objects.filter(object=>['wall','bed','furniture'].includes(object.kind));
      [...solids].sort((a,b)=>(-sinAz*b.x+cosAz*b.y)-(-sinAz*a.x+cosAz*a.y)).forEach(raisedObject);
      drawBedVitals(level,latest,true);
      drawFleet(level,false);
      drawWallElevators(level,true);
      if (active || hovered) polygon(corners3(slab,0),null,hovered?'#146759':'#2f6570');
      const slabPoints=[...corners3(slab,-.15),...corners3(slab,maxHeight)];
      const left=Math.max(0,Math.min(...slabPoints.map(point=>point[0]))-5);
      const right=Math.min(bodyWidth+32,Math.max(...slabPoints.map(point=>point[0]))+5);
      const top=Math.max(rowTop,Math.min(...slabPoints.map(point=>point[1]))-4);
      const bottom=Math.min(rowTop+rowHeight,Math.max(...slabPoints.map(point=>point[1]))+4);
      overviewTargets.push({id:level.id,left,right,top,bottom});
    } finally {ctx.restore();frameProjection=null;}
    const labelX=canvas.width-labelSpace-8;
    const labelHeight=Math.min(24,rowHeight*.9);
    const labelTop=centerY-labelHeight/2;
    ctx.fillStyle=hovered?'#146759':active?'#236c6b':'#f5faf9';
    ctx.fillRect(labelX,labelTop,labelSpace,labelHeight);
    ctx.fillStyle=active||hovered?'#fff':'#163b49';
    ctx.font='600 '+Math.min(13,labelHeight*.65)+'px sans-serif';
    ctx.textAlign='left';
    ctx.textBaseline='middle';
    ctx.fillText(level.name,labelX+6,centerY,labelSpace-12);
    overviewTargets.push({id:level.id,left:labelX,right:labelX+labelSpace,
      top:labelTop,bottom:labelTop+labelHeight});
    rowTop += rowHeight+gap;
  }
  ctx.textBaseline='alphabetic';
}

// Reuse the camera transform for all vertices and paths in a single frame.
const drawWard = draw;
function drawPerception(level) {
  if ((!replay && !viewingCurrentRun()) || !state?.perception) return;
  if (robotPerceptionView()) {
    const local=state.perception[$('perceptionRobot').value], scan=local?.scan;
    if (!scan || scan.floor_id!==level.id) return;
    for (const [kind,color] of [['free','#57ad8240'],['occupied','#ed8a38a8']]) {
      for (const [x,y] of local[kind]) {
        polygon(corners3({x,y,width:local.cell_size,height:local.cell_size},.04),color);
      }
    }
    ctx.save();
    const origin=project3(...scan.origin,.08);
    for (const beam of scan.beams) {
      const end=project3(...beam.end,.08);
      ctx.beginPath();ctx.moveTo(...origin);ctx.lineTo(...end);
      ctx.strokeStyle='#137e9673';ctx.lineWidth=1;ctx.stroke();
      if (beam.kind!=='free') {
        ctx.beginPath();ctx.arc(...end,2.6,0,Math.PI*2);
        ctx.fillStyle=beam.kind==='solid'?'#185772':'#d45a1b';ctx.fill();
      }
    }
    ctx.restore();
    return;
  }
  for (const object of state.road_closures||[]) {
    if (object.floor_id===level.id) polygon(corners3(object,.04),'#de554b70','#9b2934');
  }
  for (const object of state.dynamic_obstacles||[]) {
    if (object.floor_id!==level.id) continue;
    const [x,y]=object.xy, [width,height,z]=object.size;
    const colors=object.kind==='person'?['#ba73ae','#754066','#99547f']:['#ffa84c','#995214','#c77325'];
    block({x,y,width,height},z,colors);
  }
}
function visibleBedVitals() {
  return (replay || viewingCurrentRun()) ? latestVitals(state?.samples) : new Map();
}
function drawBedVitals(level,latest,elevated) {
  if (!latest.size) return;
  const beds = new Map();
  for (const service of level.objects) {
    if (service.kind!=='service' || !latest.has(service.id)) continue;
    const id = service.bed_id || service.id;
    const result = latest.get(service.id);
    if (!beds.has(id) || beds.get(id).seq < result.seq) beds.set(id,result);
  }
  ctx.save();
  ctx.font='600 12px sans-serif';
  ctx.textAlign='center';
  for (const object of level.objects) {
    if (!beds.has(object.id)) continue;
    const {color,label} = beds.get(object.id);
    const height = elevated && object.kind==='bed' ? objectHeight(object)+.28 : .04;
    polygon(corners3(object,height),color+'55');
    ctx.strokeStyle=color;
    ctx.lineWidth=3;
    ctx.stroke();
    const [x,y] = project3(object.x,object.y,height);
    ctx.fillStyle=color;
    ctx.fillRect(x-17,y-8,34,16);
    ctx.fillStyle='#fff';
    ctx.fillText(label,x,y+4);
  }
  ctx.restore();
}
function drawTaskBedSelection(level) {
  if ($('taskEditor').hidden || !taskBeds.size) return;
  for (const service of level.objects) {
    if (service.kind!=='service' || !taskBeds.has(service.id)) continue;
    const bed=level.objects.find(object=>object.id===service.bed_id);
    const object=bed||service;
    const height=raisedView && bed ? objectHeight(bed)+.17 : .04;
    polygon(corners3(object,height),'#1de3aa44','#146c53');
    const [x,y]=project3(service.x,service.y,.06);
    ctx.save();
    ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);
    ctx.fillStyle='#146c53';ctx.fill();
    ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke();
    ctx.restore();
  }
}
draw = function() {
  if (!documentMap) {drawWard();return;}
  if (buildingOverview) {drawBuilding();return;}
  frameProjection = transform();
  try {
    drawWard();
    drawPerception(floor());
    drawTaskBedSelection(floor());
    drawBedVitals(floor(),visibleBedVitals(),raisedView);
    drawModelingGuides();
    drawWallElevators(floor());
    drawDoorRoomLabels(floor());
    drawScaleBar(frameProjection.scale);
    drawFootprintPreview();
    if (hoveredRoutePointer && !showTaskRouteTooltip(hoveredRoutePointer)) hideModelTooltip();
  } finally {
    frameProjection = null;
  }
};

// Match the drawing buffer to the displayed viewport so resizing does not stretch the map.
new ResizeObserver(() => {
  const width=canvas.clientWidth, height=canvas.clientHeight;
  if (!width || !height || (canvas.width===width && canvas.height===height)) return;
  canvas.width=width;
  canvas.height=height;
  draw();
}).observe(canvas);
