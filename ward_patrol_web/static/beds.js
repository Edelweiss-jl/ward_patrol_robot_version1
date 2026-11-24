'use strict';

const byId = id => document.getElementById(id);
const mapSelect = byId('bedMap');
const floorSelect = byId('bedFloor');
const form = byId('patientForm');
const fields = form.elements;
const sexLabels = {male: '男', female: '女', unknown: '未记录'};
const dateFormat = new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Shanghai',
});
const sampleDateFormat = new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'short', timeStyle: 'medium', timeZone: 'Asia/Shanghai',
});

let beds = [];
let selectedKey = null;
let requestedBedKey = new URLSearchParams(location.search).get('bed_key');
let editing = false;
let busy = false;
let maps = [];
let floorMap = null;
let compiled = [];
let historyOwner = null;
let samples = [];
let historyRequest = null;

const selection = () => beds.find(bed => bed.key === selectedKey);
const mapIdentity = () => JSON.parse(mapSelect.value);

function notice(message, isError = false) {
  const status = byId('bedStatus');
  status.textContent = message;
  status.dataset.error = String(isError);
}

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}

function appendText(parent, tag, value) {
  const child = document.createElement(tag);
  child.textContent = value;
  parent.append(child);
  return child;
}

function lock(value) {
  busy = value;
  mapSelect.disabled = value;
  byId('refreshBeds').disabled = value;
  for (const control of fields) control.disabled = value;
  for (const id of ['editPatient', 'checkInPatient', 'cancelRegistration', 'dischargePatient']) byId(id).disabled = value;
  for (const button of document.querySelectorAll('#bedRows button, #bedMapStage button, #bedFloorTabs button')) button.disabled = value;
}

function selectBed(bed) {
  if (busy || (editing && bed.key !== selectedKey && !window.confirm('放弃当前表单并切换床位？'))) return;
  if (editing && bed.key === selectedKey) return;
  selectedKey = bed.key;
  editing = !bed.patient;
  renderMap();
  renderRows();
  renderDetails(true);
  (editing ? fields.name : byId('editPatient')).focus({preventScroll: true});
  if (window.matchMedia('(max-width: 850px)').matches) byId('bedHeading').scrollIntoView({block: 'start'});
}

function renderMap() {
  const floors = floorMap?.floors || [];
  const floor = floors.find(item => item.id === floorSelect.value) || floors[0];
  const floorBeds = beds.filter(bed => bed.floor_id === floor?.id);
  const tabs = byId('bedFloorTabs');
  tabs.replaceChildren();
  for (const level of floors) {
    const button = appendText(tabs, 'button', level.name || level.id);
    button.type = 'button';
    button.disabled = busy;
    button.dataset.floor = level.id;
    button.setAttribute('aria-pressed', String(level === floor));
    button.onclick = () => {
      floorSelect.value = level.id;
      renderMap();
      renderRows();
      [...tabs.children].find(tab => tab.dataset.floor === level.id)?.focus();
    };
  }
  byId('mapNoBeds').hidden = !floor || floorBeds.length > 0;
  const rectangles = compiled.find(level => level.id === floor?.id)?.rectangles
    || floor?.objects.filter(object => ['wall', 'bed', 'furniture'].includes(object.kind));
  drawBedMap(byId('bedMapStage'), floor, rectangles, floorBeds, selectedKey, selectBed, busy);
}

function renderRows() {
  const rows = byId('bedRows');
  rows.replaceChildren();
  const shown = beds.filter(bed => {
    const filter = byId('occupancy').value;
    return (!floorSelect.value || floorSelect.value === bed.floor_id)
      && (!filter || filter === bed.status);
  });
  byId('bedCounts').textContent = Object.entries(occupancyLabels)
    .map(([status, label]) => `${label} ${shown.filter(bed => bed.status === status).length} 张`).join(' · ');
  byId('emptyBeds').hidden = shown.length !== 0;
  for (const bed of shown) {
    const row = rows.insertRow();
    row.classList.toggle('selected', bed.key === selectedKey);
    row.insertCell().textContent = bed.name;
    row.insertCell().textContent = bed.floor;
    const status = appendText(row.insertCell(), 'span', occupancyLabels[bed.status]);
    status.className = 'occupancy ' + bed.status;
    row.insertCell().textContent = bed.patient?.name || '—';
    const button = appendText(row.insertCell(), 'button', bed.patient ? '查看' : '登记');
    button.type = 'button';
    button.disabled = busy;
    button.setAttribute('aria-label', `${button.textContent} · ${bed.floor} ${bed.name}`);
    button.onclick = () => selectBed(bed);
  }
}

function renderAssessment(assessment) {
  const panel = byId('assessment');
  panel.replaceChildren();
  if (!assessment) {
    return;
  }
  const appearance = vitalsAppearance.get(assessment.status);
  const rule = {news2: '成人 NEWS2（室内空气、意识清醒）',
    pediatric_reference: '儿科年龄参考', pregnancy_unassessed: '妊娠期'}[assessment.rule];
  const summary = appendText(panel, 'p', [appearance?.label, rule,
    assessment.score == null ? null : `${assessment.score} 分`].filter(Boolean).join(' · '));
  summary.style.color = appearance?.color || '';
  if (assessment.source) {
    const link = appendText(panel, 'a', '查看评分或参考来源');
    link.href = assessment.source;
  }
  if (assessment.reasons.length) {
    const reasons = document.createElement('ul');
    for (const reason of assessment.reasons) appendText(reasons, 'li', reason);
    panel.append(reasons);
  }
  const table = document.createElement('table');
  table.setAttribute('aria-label', '本次采样的模拟体征');
  for (const item of assessment.findings) {
    const row = table.insertRow();
    row.insertCell().textContent = item.label;
    row.insertCell().textContent = item.value == null ? '缺失' : `${item.value} ${item.unit}`;
    const reference = row.insertCell();
    if (item.reference) {
      const label = `${item.reference.join('–')} ${item.unit}${item.outside_reference ? '（参考范围外）' : ''}`;
      if (item.reference_source) {
        const link = appendText(reference, 'a', `静息脉搏 P5–P95 ${label}`);
        link.href = item.reference_source;
      } else {
        reference.textContent = label;
      }
    }
    if (item.points != null) appendText(reference, 'div', `${item.points} 分`);
  }
  panel.append(table);
}

function sampleLabel(sample) {
  const time = sample.sampled_at ? sampleDateFormat.format(new Date(sample.sampled_at)) : `仿真 ${sample.sim_time ?? '—'} 秒`;
  const source = sample.source === 'task' ? `机器人 ${sample.robot_id || '—'}` : '手动采样';
  return [time, source, sample.task_id].filter(Boolean).join(' · ');
}

function showHistorySample() {
  const sample = samples.find(record => record.sample_id === byId('bedSamples').value);
  renderAssessment(sample?.assessment);
}

async function loadHistory() {
  const owner = historyOwner;
  if (!owner || editing || historyRequest === owner || document.hidden) return;
  historyRequest = owner;
  try {
    const entries = await api('/api/bed-census/history?' + new URLSearchParams(owner));
    if (historyOwner !== owner) return;
    byId('bedHistoryStatus').textContent = entries.length ? '' : '本次入住暂无采样记录。';
    if (entries.length === samples.length && entries[0]?.sample_id === samples[0]?.sample_id) return;
    const picker = byId('bedSamples');
    const selected = picker.value === samples[0]?.sample_id ? '' : picker.value;
    samples = entries;
    picker.replaceChildren(...samples.map(sample => new Option(sampleLabel(sample), sample.sample_id)));
    if (selected && samples.some(sample => sample.sample_id === selected)) picker.value = selected;
    byId('samplePicker').hidden = !samples.length;
    showHistorySample();
  } catch (error) {
    if (historyOwner === owner) {
      samples = [];
      byId('bedSamples').replaceChildren();
      byId('samplePicker').hidden = true;
      byId('bedHistoryStatus').textContent = error.message;
      renderAssessment(null);
    }
  } finally {
    if (historyRequest === owner) historyRequest = null;
  }
}

function bindHistory(bed) {
  const revision = bed?.patient?.revision;
  if (bed?.status === 'occupied' && historyOwner?.key === bed.key && historyOwner.revision === revision) {
    void loadHistory();
    return;
  }
  historyOwner = bed?.status === 'occupied' ? {key: bed.key, revision} : null;
  samples = [];
  byId('bedSamples').replaceChildren();
  byId('samplePicker').hidden = true;
  byId('bedHistoryStatus').textContent = bed?.status === 'pending'
    ? '确认入住后，机器人巡检时会记录体征。' : '正在读取巡检体征…';
  renderAssessment(null);
  void loadHistory();
}

function updateAgeBounds() {
  const months = fields.ageUnit.value === 'month';
  fields.age.min = months ? '0' : '1';
  fields.age.max = months ? '11' : '130';
}

function renderDetails(resetForm = false) {
  const bed = selection();
  const patient = bed?.patient;
  byId('bedHeading').textContent = bed ? `${bed.floor} · ${bed.name}` : '床位详情';
  byId('chooseBed').hidden = Boolean(bed && (patient || editing));
  byId('chooseBed').textContent = bed ? '床位空闲。点击地图床位或列表中的“登记”填写患者资料。' : '在地图或列表中选择床位。';
  byId('patientView').hidden = !patient || editing;
  form.hidden = !bed || !editing;
  byId('checkInPatient').hidden = bed?.status !== 'pending';
  byId('cancelRegistration').hidden = bed?.status !== 'pending';
  byId('dischargePatient').hidden = bed?.status !== 'occupied';
  bindHistory(bed);
  if (patient && !editing) {
    const details = byId('patientFields');
    details.replaceChildren();
    const age = patient.age_months;
    const values = [
      ['姓名', patient.name], ['年龄', age < 12 ? `${age} 月龄` : `${age / 12} 岁`],
      ['性别', sexLabels[patient.sex]], ['妊娠期', patient.pregnant ? '是' : '否'],
      ['床位状态', occupancyLabels[bed.status]],
      ['登记时间', (patient.registered_at || patient.admitted_at) && dateFormat.format(new Date(patient.registered_at || patient.admitted_at))],
      ['入住时间', patient.admitted_at ? dateFormat.format(new Date(patient.admitted_at)) : '待入住'],
      ['科室', patient.department], ['诊断信息', patient.diagnosis], ['备注', patient.notes],
    ];
    for (const [label, value] of values) {
      appendText(details, 'dt', label);
      appendText(details, 'dd', value || '—');
    }
  }
  if (editing && resetForm) {
    form.reset();
    if (patient) {
      for (const key of ['name', 'sex', 'department', 'diagnosis', 'notes']) fields[key].value = patient[key];
      fields.pregnant.checked = patient.pregnant;
      fields.ageUnit.value = patient.age_months < 12 ? 'month' : 'year';
      fields.age.value = patient.age_months < 12 ? patient.age_months : patient.age_months / 12;
    }
    updateAgeBounds();
    byId('savePatient').textContent = patient ? '保存修改' : '登记待入住';
  }
}

async function loadBeds() {
  const identity = mapIdentity();
  const map = maps.find(item => item.id === identity.map_id && item.version === identity.version);
  const [records, geometry] = await Promise.all([
    api('/api/bed-census?' + new URLSearchParams(identity)),
    floorMap !== map ? api('/api/maps/compile', map) : Promise.resolve(null),
  ]);
  if (records.some(bed => !bed.status)) throw new Error('请重启巡查 Web 服务，再刷新床位管理页面。');
  beds = records;
  floorMap = map;
  if (geometry) compiled = geometry.floors;
  const previous = floorSelect.value;
  floorSelect.replaceChildren(new Option('全部楼层', ''));
  for (const floor of map.floors) {
    floorSelect.add(new Option(floor.name || floor.id, floor.id));
  }
  if ([...floorSelect.options].some(option => option.value === previous)) floorSelect.value = previous;
  const requestedBed = beds.find(bed => bed.key === requestedBedKey);
  requestedBedKey = null;
  if (requestedBed) {
    selectedKey = requestedBed.key;
    floorSelect.value = requestedBed.floor_id;
  }
  if (!selection()) selectedKey = null;
  renderMap();
  renderRows();
  renderDetails();
}

async function refreshBeds(resetSelection = false) {
  if (busy || !mapSelect.value) return;
  if (editing && !window.confirm('放弃当前表单并重新加载床位？')) {
    if (resetSelection) mapSelect.value = mapSelect.dataset.loaded;
    return;
  }
  if (resetSelection) selectedKey = null;
  editing = false;
  lock(true);
  notice('正在加载床位…');
  try {
    await loadBeds();
    mapSelect.dataset.loaded = mapSelect.value;
    notice('');
  } catch (error) {
    mapSelect.value = mapSelect.dataset.loaded || mapSelect.value;
    renderRows();
    renderMap();
    renderDetails();
    notice(error.message, true);
  } finally {
    lock(false);
  }
}

async function changeBed(action, patient) {
  const bed = selection();
  if (busy || !bed) return;
  lock(true);
  try {
    const result = await api('/api/bed-census', {
      ...mapIdentity(), action, patient, key: bed.key, revision: bed.patient?.revision,
    });
    bed.patient = result.patient;
    bed.status = result.status;
    editing = false;
    renderRows();
    renderMap();
    renderDetails();
    notice({register: '已登记，等待确认入住。', check_in: '已确认入住。',
      edit: '患者资料已保存。', cancel_registration: '已取消登记，床位已空出。',
      discharge: '出院已登记，床位已空出。'}[action]);
  } catch (error) {
    notice(error.message, true);
  } finally {
    lock(false);
  }
}

fields.ageUnit.onchange = updateAgeBounds;
form.onsubmit = event => {
  event.preventDefault();
  const patient = Object.fromEntries(new FormData(form));
  delete patient.age;
  delete patient.ageUnit;
  patient.age_months = fields.age.valueAsNumber * (fields.ageUnit.value === 'year' ? 12 : 1);
  patient.pregnant = fields.pregnant.checked;
  changeBed(selection()?.patient ? 'edit' : 'register', patient);
};
byId('cancelPatient').onclick = () => {
  editing = false;
  renderDetails();
};
byId('editPatient').onclick = () => {
  editing = true;
  renderDetails(true);
  fields.name.focus();
};
byId('checkInPatient').onclick = () => changeBed('check_in');
byId('cancelRegistration').onclick = () => {
  const bed = selection();
  if (bed?.status === 'pending' && window.confirm(`确认取消 ${bed.patient.name} 的床位登记？`)) changeBed('cancel_registration');
};
byId('dischargePatient').onclick = () => {
  const bed = selection();
  if (bed?.patient && window.confirm(`确认办理 ${bed.patient.name} 出院并腾出 ${bed.name}？`)) changeBed('discharge');
};
mapSelect.onchange = () => refreshBeds(true);
floorSelect.onchange = () => {
  renderMap();
  renderRows();
};
byId('occupancy').onchange = renderRows;
byId('refreshBeds').onclick = () => refreshBeds();
byId('bedSamples').onchange = showHistorySample;
window.setInterval(loadHistory, 5000);
document.addEventListener('visibilitychange', loadHistory);

async function initialize() {
  const query = new URLSearchParams(location.search);
  maps = await api('/api/maps');
  for (const map of maps.sort((a, b) => (a.display_name || a.name).localeCompare(b.display_name || b.name, 'zh-CN')
    || b.version - a.version)) {
    mapSelect.add(new Option(`${map.display_name || map.name} · v${map.version}`,
      JSON.stringify({map_id: map.id, version: map.version})));
  }
  if (!mapSelect.options.length) {
    notice('没有可用地图。请先在巡查工作台保存地图。');
    return;
  }
  const target = maps.find(map => map.id === (query.get('map_id') || 'corridor')
    && map.version === Number(query.get('version') || 1));
  if (target) mapSelect.value = JSON.stringify({map_id: target.id, version: target.version});
  await refreshBeds();
}
initialize().catch(error => notice(error.message, true));
