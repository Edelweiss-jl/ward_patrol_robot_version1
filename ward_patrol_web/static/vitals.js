'use strict';

const vitalsAppearance = new Map([
  ['normal', {label:'正常', color:'#12a15a'}],
  ['warning', {label:'预警', color:'#e8722a'}],
  ['critical', {label:'危急', color:'#b00511'}],
]);

function latestVitals(samples) {
  const latest = new Map();
  for (const {request, accepted, result} of Object.values(samples || {})) {
    const appearance = vitalsAppearance.get(result?.verdict?.status);
    if (!accepted || !appearance) continue;
    if (!latest.has(request.bed_id) || latest.get(request.bed_id).seq < request.seq) {
      latest.set(request.bed_id, {...appearance, seq:request.seq});
    }
  }
  return latest;
}
