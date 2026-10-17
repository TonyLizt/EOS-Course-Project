/* Pure UTC and viewport calculations; original task times remain unchanged. */
(function (root) {
  'use strict';
  function parseTime(value) {
    const text = String(value || '').trim();
    return Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : text + 'Z');
  }
  function normalize(assignments) {
    return assignments.map((a, index) => ({...a, index, start: parseTime(a.sat_start_time), end: parseTime(a.sat_end_time)}))
      .filter(a => Number.isFinite(a.start) && Number.isFinite(a.end) && a.end > a.start)
      .sort((a, b) => a.start - b.start || a.index - b.index);
  }
  function clampRange(start, end, domain) {
    const span = Math.min(domain[1] - domain[0], Math.max(1000, end - start));
    const left = Math.max(domain[0], Math.min(start, domain[1] - span));
    return [left, left + span];
  }
  function zoom(range, factor, anchor, domain) {
    const position = (anchor - range[0]) / (range[1] - range[0]);
    const span = Math.max(1000, (range[1] - range[0]) * factor);
    return clampRange(anchor - span * position, anchor + span * (1 - position), domain);
  }
  function tickStep(span, width) {
    const steps = [1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000, 600000, 900000, 1800000, 3600000, 7200000, 21600000, 43200000, 86400000, 172800000, 604800000];
    const wanted = span / Math.max(2, Math.floor(width / 145));
    return steps.find(s => s >= wanted) || Math.ceil(wanted / 86400000) * 86400000;
  }
  function fmt(value) { return new Date(value).toISOString().replace('T', ' ').replace('.000Z', ' UTC'); }
  function magneticHit(point, rects, radius=12) {
    const candidates=rects.map(r=>{
      const dx=Math.max(r.left-point.x,point.x-r.right,0),dy=Math.max(r.top-point.y,point.y-r.bottom,0);
      return {id:r.id,distance:Math.hypot(dx,dy),center:Math.hypot((r.left+r.right)/2-point.x,(r.top+r.bottom)/2-point.y)};
    }).filter(r=>Number.isFinite(r.distance)&&r.distance<=radius)
      .sort((a,b)=>a.distance-b.distance||a.center-b.center);
    if(!candidates.length)return null;
    // Equidistant dense records are genuinely ambiguous: never pick an arbitrary
    // neighbour just to show a tooltip. Exact hits and lane geometry win first.
    if(candidates[1]&&Math.abs(candidates[0].distance-candidates[1].distance)<1e-6
       &&Math.abs(candidates[0].center-candidates[1].center)<1e-6)return null;
    return candidates[0].id;
  }
  const api = {parseTime, normalize, clampRange, zoom, tickStep, fmt, magneticHit};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ScheduleTimeline = api;
})(typeof window === 'undefined' ? globalThis : window);
