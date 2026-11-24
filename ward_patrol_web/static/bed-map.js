'use strict';

const occupancyLabels = {vacant: '空床', pending: '已登记待入住', occupied: '已入住'};
const bedColors = {vacant: '#22815f', pending: '#ad7914', occupied: '#b63847'};
const sceneColors = {
  wall: '#516672', furniture: '#bac8cd', forbidden: '#f9dce0',
  elevator: '#6b84a9', parking: '#a9c5de', waiting: '#c6d6e6', service: '#547985',
};

function drawBedMap(stage, floor, rectangles, beds, selectedKey, selectBed, busy) {
  stage.hidden = !floor;
  const markers = stage.querySelector('.bed-map-markers');
  markers.replaceChildren();
  if (!floor) return;

  const canvas = stage.querySelector('canvas');
  const context = canvas.getContext('2d');
  const width = canvas.width, height = canvas.height;
  const scale = Math.min((width - 132) / floor.width, (height - 70) / floor.height);
  const point = (x, y) => [width / 2 + x * scale, height / 2 - y * scale];
  const left = (width - floor.width * scale) / 2, top = (height - floor.height * scale) / 2;
  const bedsById = new Map(beds.map(bed => [bed.bed_id, bed]));

  context.fillStyle = '#eef4f6';
  context.fillRect(0, 0, width, height);
  context.fillStyle = '#fff';
  context.fillRect(left, top, floor.width * scale, floor.height * scale);
  context.strokeStyle = '#e5edef';
  context.lineWidth = 1;
  const gridStep = Math.max(1, Math.ceil(Math.max(floor.width, floor.height) / 46));
  context.beginPath();
  for (let x = gridStep; x < floor.width; x += gridStep) {
    context.moveTo(left + x * scale, top);
    context.lineTo(left + x * scale, height - top);
  }
  for (let y = gridStep; y < floor.height; y += gridStep) {
    context.moveTo(left, top + y * scale);
    context.lineTo(width - left, top + y * scale);
  }
  context.stroke();
  context.strokeStyle = '#b6c7ce';
  context.strokeRect(left, top, floor.width * scale, floor.height * scale);

  const shape = (object, fill) => {
    context.save();
    context.translate(...point(object.x, object.y));
    context.rotate(-(object.rotation || 0) * Math.PI / 180);
    context.fillStyle = fill;
    context.fillRect(-object.width * scale / 2, -object.height * scale / 2,
      object.width * scale, object.height * scale);
    context.restore();
  };
  for (const object of floor.objects) {
    if (['forbidden', 'parking', 'waiting', 'elevator', 'service'].includes(object.kind)) {
      shape(object, sceneColors[object.kind]);
    }
  }
  for (const object of rectangles) {
    const bed = bedsById.get(object.id);
    shape(object, bed ? bedColors[bed.status] : (sceneColors[object.kind] || '#bdcbd0'));
    if (!bed) continue;

    const marker = document.createElement('button');
    marker.type = 'button';
    marker.className = 'bed-map-marker ' + bed.status;
    marker.disabled = busy;
    marker.setAttribute('aria-pressed', String(bed.key === selectedKey));
    marker.setAttribute('aria-label', `${bed.name} · ${occupancyLabels[bed.status]}`);
    const [x, y] = point(object.x, object.y);
    marker.style.left = `${x / width * 100}%`;
    marker.style.top = `${y / height * 100}%`;
    const name = document.createElement('strong'), status = document.createElement('span');
    name.textContent = bed.name;
    status.textContent = occupancyLabels[bed.status];
    marker.append(name, status);
    marker.onclick = () => selectBed(bed);
    markers.append(marker);
  }
}
