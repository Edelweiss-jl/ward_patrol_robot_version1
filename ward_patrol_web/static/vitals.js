'use strict';

const vitalsAppearance = new Map([
  ['normal', {label:'正常', color:'#12a15a'}],
  ['observe', {label:'低分观察', color:'#947318'}],
  ['unassessed', {label:'未评估', color:'#627384'}],
  ['warning', {label:'预警', color:'#e8722a'}],
  ['critical', {label:'危急', color:'#b00511'}],
  ['vacant', {label:'空床位', color:'#536678'}],
  ['unrecorded', {label:'入住未登记', color:'#665a78'}],
  ['pending', {label:'已登记待入住', color:'#947318'}],
]);

function latestVitals(samples, revisions = {}) {
  const latest = new Map();
  for (const {request, accepted, result} of Object.values(samples || {})) {
    const status = result?.bed_status==='pending' ? 'pending' : result?.verdict?.status;
    const appearance = vitalsAppearance.get(status) ||
      (Object.keys(result?.vitals || {}).length ? {label:'已采样', color:'#347384'} : null);
    if (!accepted || !appearance) continue;
    if (Object.hasOwn(revisions, request.bed_id) &&
        (request.profile?.revision ?? null) !== revisions[request.bed_id]) continue;
    if (!latest.has(request.bed_id) || latest.get(request.bed_id).seq < request.seq) {
      latest.set(request.bed_id, {...appearance, result, seq:request.seq, simTime:request.sim_time});
    }
  }
  return latest;
}

function bedVitalsOnFloor(level, latest) {
  const beds = new Map();
  for (const service of level.objects) {
    if (service.kind!=='service' || !latest.has(service.id)) continue;
    const id = service.bed_id || service.id;
    const result = latest.get(service.id);
    if (!beds.has(id) || beds.get(id).seq < result.seq) beds.set(id,result);
  }
  return beds;
}

function bedInspectionDetails({label, result, simTime}) {
  const status = [
    result.bed_status==='occupied' ? '已有入住' : '',
    label,
    Number.isFinite(simTime) ? '巡检于仿真 '+simTime.toFixed(1)+' 秒' : '',
  ].filter(Boolean).join(' · ');
  const {heart_rate, spo2, systolic_bp, diastolic_bp, respiratory_rate, temperature} = result.vitals || {};
  const measurements = [
    heart_rate==null ? '' : '心率 '+heart_rate+' bpm',
    spo2==null ? '' : '血氧 '+spo2+'%',
    systolic_bp==null && diastolic_bp==null ? '' : '血压 '+(systolic_bp ?? '—')+'/'+(diastolic_bp ?? '—')+' mmHg',
    respiratory_rate==null ? '' : '呼吸 '+respiratory_rate+' 次/分',
    temperature==null ? '' : '体温 '+temperature+' ℃',
  ].filter(Boolean).join(' · ');
  const reasons = (result.verdict?.reasons || []).join('。');
  return {status, measurements, reasons};
}
