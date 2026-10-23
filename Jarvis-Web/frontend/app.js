'use strict';
const $ = id => document.getElementById(id);
const TYPES = {
  object_missing: {label:'Object missing', tone:'missing', icon:'−'},
  new_object: {label:'New object', tone:'added', icon:'+'},
  object_returned: {label:'Object returned', tone:'returned', icon:'↩'},
  person_count_changed: {label:'People changed', tone:'people', icon:'◉'}
};
let currentRuns = [], selectedFolder = null, viewMode = 'original', followLatest = true;
let capturesConnected = false, monitorConnected = false, changesOnly = false;
let events = [], eventFilter = 'all', searchText = '', historyId = null, totalEvents = 0;
let hasOlder = false, olderCursor = null, olderLoading = false, monitorLoading = false;
let lastMonitorCheck = null, monitorStateAvailable = false, failedImage = null;
const selectedRun = () => currentRuns.find(run => run.folder === selectedFolder);
const visibleRuns = () => changesOnly ? currentRuns.filter(r => Array.isArray(r.change_log?.changes) && r.change_log.changes.length) : currentRuns;
const el = (tag, className, text) => {const node=document.createElement(tag); if(className)node.className=className; if(text!==undefined)node.textContent=text; return node;};
function captureDate(run) {
  if (!run) return null;
  if (run.captured_at) {const date=new Date(run.captured_at); if(!isNaN(date))return date;}
  const m=/^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})/.exec(run.folder || '');
  return m ? new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5],+m[6]) : null;
}
function dateText(date, options) {return date && !isNaN(date) ? date.toLocaleString(undefined,options) : 'Time unavailable';}
function captureText(run) {return dateText(captureDate(run),{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit'});}
function safeImage(url) {return typeof url==='string' && url.startsWith('/runs/') && !url.startsWith('//') ? url : null;}
function normalizeRun(run) {
  return {...run, original:safeImage(run.original),overlay:safeImage(run.overlay)};
}
function typeInfo(type) {return TYPES[type] || {label:'Observation',tone:'added',icon:'·'};}
function setView(mode) {viewMode=mode; failedImage=null; renderDisplay();renderGallery();}
function selectCapture(folder) {
  selectedFolder=folder;followLatest=false;failedImage=null;
  renderDisplay();renderGallery();
}
function renderSelectedChanges(run) {
  const container=$('selected-changes');container.replaceChildren();
  const changes=run?.change_log?.changes;
  if(!run){container.textContent='Select a capture to inspect its changes.';return;}
  if(!Array.isArray(changes)){container.textContent='This capture has no recorded change analysis.';return;}
  if(!changes.length){container.textContent='No confirmed changes recorded for this capture.';return;}
  for(const event of changes){const type=typeInfo(event.event);container.append(el('span','change-line '+type.tone,`${type.icon} ${event.message || type.label}`));}
}
function renderDisplay() {
  const run=selectedRun(), img=$('featured-image'), url=run?.[viewMode];
  const unavailable=!url || failedImage===url;
  img.hidden=unavailable;$('empty-state').hidden=!unavailable;$('frame-label').hidden=unavailable;
  if(url && img.getAttribute('src')!==url)img.src=url;
  $('empty-state').querySelector('h3').textContent=failedImage===url && url ? 'Image could not load' : run ? 'This view is unavailable' : 'Waiting for a capture';
  $('empty-state').querySelector('p').textContent=run ? 'Choose another view or capture.' : capturesConnected ? 'Saved frames will appear here.' : 'Waiting for the capture archive connection.';
  $('frame-label').textContent=viewMode==='original'?'ORIGINAL FRAME':'DETECTION OVERLAY';
  $('original-btn').setAttribute('aria-pressed',String(viewMode==='original'));
  $('overlay-btn').setAttribute('aria-pressed',String(viewMode==='overlay'));
  $('image-timestamp').textContent=run?captureText(run)+(run.captured_at?'':' · camera local time'):'No frame selected';
  const list=visibleRuns(), index=list.findIndex(r=>r.folder===selectedFolder);
  $('frame-position').textContent=`${String(index+1).padStart(2,'0')} / ${String(list.length).padStart(2,'0')}`;
  $('prev-btn').disabled=index<=0;$('next-btn').disabled=index<0||index>=list.length-1;
  $('expand-btn').disabled=unavailable;
  $('latest-btn').textContent=followLatest?'Following latest ↗':'Follow latest ↗';
  $('latest-btn').setAttribute('aria-pressed',String(followLatest));
  renderSelectedChanges(run);
}
function renderGallery() {
  const grid=$('image-grid'), focusedFolder=document.activeElement?.dataset?.folder;
  grid.replaceChildren();
  for(const run of visibleRuns()) {
    const card=el('button','capture-card');card.dataset.folder=run.folder;
    card.setAttribute('aria-pressed',String(run.folder===selectedFolder));
    card.setAttribute('aria-label',`Inspect capture ${captureText(run)}`);
    const img=el('img');img.src=run[viewMode]||run.original||run.overlay;img.alt='';img.loading='lazy';
    const info=el('span','capture-info');
    info.append(el('strong','',dateText(captureDate(run),{hour:'numeric',minute:'2-digit',second:'2-digit'})),el('small','',dateText(captureDate(run),{month:'short',day:'numeric',year:'numeric'})));
    if(run.folder===currentRuns[0]?.folder)info.append(el('small','new-tag','LATEST'));
    const changes=run.change_log?.changes, count=Array.isArray(changes)?changes.length:null;
    const summary=el('span','capture-summary'+(count?' has-changes':''),count===null?'Not analyzed':count===0?'No confirmed changes':`${count} recorded ${count===1?'change':'changes'} · inspect frame`);
    card.append(img,info,summary);card.onclick=()=>selectCapture(run.folder);grid.append(card);
  }
  if(focusedFolder){const card=Array.from(grid.children).find(c=>c.dataset.folder===focusedFolder);card?.focus({preventScroll:true});}
  $('capture-count').textContent=String(currentRuns.length).padStart(2,'0');
  $('capture-filter-count').textContent=`${visibleRuns().length} of ${currentRuns.length} recent captures shown`;
  $('gallery-empty').hidden=visibleRuns().length>0;
  $('gallery-empty').textContent=changesOnly?'No recent captures with recorded changes.':capturesConnected?'No captures saved yet.':'Capture archive unavailable. Retrying automatically.';
}
function associatedRun(event) {
  return currentRuns.find(run=>Array.isArray(run.change_log?.changes)&&run.change_log.changes.some(change=>change&&change.time===event.time && change.event===event.event && change.message===event.message));
}
function renderHistory() {
  const container=$('object-events');const previousScroll=container.scrollTop;
  container.replaceChildren();
  const filtered=events.filter(event=>(eventFilter==='all'||event.event===eventFilter)&&`${event.message||''} ${typeInfo(event.event).label}`.toLowerCase().includes(searchText));
  let lastDay='';
  for(const event of filtered){
    const date=new Date(event.time), valid=!isNaN(date), day=valid?date.toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric',year:'numeric'}):'Date unavailable';
    if(day!==lastDay){container.append(el('h3','day-heading',day));lastDay=day;}
    const type=typeInfo(event.event), row=el('article','event '+type.tone);
    const body=el('div','event-body');body.append(el('p','event-type',type.label),el('p','event-message',event.message||type.label));
    const run=associatedRun(event);
    if(run){const context=el('div','event-context');const button=el('button','','Inspect capture ↗');button.onclick=()=>{changesOnly=false;$('changes-filter').checked=false;selectCapture(run.folder);$('captures').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});};context.append(button);body.append(context);}
    const time=el('time','',valid?date.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit',second:'2-digit'}):'Time unavailable');if(valid)time.dateTime=date.toISOString();
    const symbol=el('span','event-symbol',type.icon);symbol.setAttribute('aria-hidden','true');row.append(symbol,body,time);container.append(row);
  }
  container.scrollTop=previousScroll;
  $('history-empty').hidden=filtered.length>0;
  $('history-empty').querySelector('h3').textContent=!monitorConnected&&!events.length?'Monitoring is unavailable':events.length?'No matching changes':'No recorded changes yet';
  $('history-empty').querySelector('p').textContent=events.length?'Try another filter, change your search, or load older events.':monitorConnected?'Saved monitoring events will appear here.':'The page will retry automatically. Existing captures remain available.';
  $('history-count').textContent=`${filtered.length} matching ${filtered.length===1?'event':'events'} · ${events.length} loaded of ${totalEvents} recorded`;
  $('clear-filters').hidden=eventFilter==='all'&&!searchText;
  $('load-older').hidden=!hasOlder;$('load-older').disabled=olderLoading;
  $('load-older').textContent=olderLoading?'Loading older events…':'Load older events ↓';
  $('history-scope').textContent=!monitorConnected?'Waiting for the monitoring connection. Previously loaded history is kept on screen.':hasOlder?'Filters and search apply to loaded history. Load older events to search further back.':'All available history is loaded. Filters and search apply to this history.';
}
function updateFreshness() {
  const date=captureDate(currentRuns[0]), age=date?Math.max(0,Date.now()-date.getTime()):null;
  const stale=age!==null&&age>120000;
  $('status-badge').textContent=monitorConnected&&capturesConnected?'Archive connected':monitorConnected||capturesConnected?'Partial connection':'Disconnected · retrying';
  $('status-dot').classList.toggle('online',monitorConnected&&capturesConnected);
  $('monitor-sync').textContent=lastMonitorCheck?`${monitorConnected?'History checked':'Last successful history check'} at ${lastMonitorCheck.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit',second:'2-digit'})}`:'Waiting for monitoring data';
  $('freshness').classList.toggle('stale',stale||!capturesConnected);
  $('freshness').textContent=!capturesConnected?'Capture archive unavailable · retrying':!date?'No saved captures yet':`Latest capture: ${captureText(currentRuns[0])}${stale?' · no recent capture':''}`;
}
async function fetchRuns() {
  try{
    const response=await fetch('/api/latest',{cache:'no-store',signal:AbortSignal.timeout(8000)});
    if(!response.ok)throw Error('Capture archive unavailable');
    const data=await response.json();if(!Array.isArray(data.runs))throw Error('Invalid capture response');
    const runs=data.runs.filter(r=>r&&typeof r.folder==='string').map(normalizeRun).filter(r=>r.original||r.overlay);
    const changed=JSON.stringify(runs)!==JSON.stringify(currentRuns)||!capturesConnected;
    currentRuns=runs;capturesConnected=true;
    const list=visibleRuns();
    if(followLatest||!list.some(r=>r.folder===selectedFolder)){selectedFolder=list[0]?.folder||null;failedImage=null;}
    renderDisplay();if(changed){renderGallery();renderHistory();}
    if(data.preview)$('demo-notice').hidden=false;
  }catch{capturesConnected=false;if(!currentRuns.length)renderGallery();}
  updateFreshness();
}
async function fetchMonitor(older=false) {
  if(monitorLoading)return;
  monitorLoading=true;if(older){olderLoading=true;renderHistory();}
  try{
    const response=await fetch('/api/object-monitor?limit=50'+(older&&olderCursor?`&before=${olderCursor}`:''),{cache:'no-store',signal:AbortSignal.timeout(8000)});
    if(!response.ok)throw Error('Object monitor unavailable');
    const data=await response.json();if(!Array.isArray(data.recent_events))throw Error('Invalid monitor response');
    const incoming=data.recent_events.filter(e=>e&&TYPES[e.event]&&Number.isInteger(e.sequence));
    const reset=historyId!==null&&data.history_id!==historyId;
    if(reset){events=[];hasOlder=false;olderCursor=null;}
    historyId=data.history_id;
    const existing=new Map(events.map(event=>[event.sequence,event]));for(const event of incoming)existing.set(event.sequence,event);
    const merged=Array.from(existing.values()).sort((a,b)=>b.sequence-a.sequence);
    const changed=JSON.stringify(merged)!==JSON.stringify(events)||!monitorConnected||reset;
    const firstLoad=events.length===0;events=merged;totalEvents=data.total_events??events.length;
    if(older||reset||firstLoad){hasOlder=!!data.has_more;olderCursor=data.next_before;}
    monitorStateAvailable=!!data.state_available;
    const objects=Object.values(data.objects||{}).filter(o=>o&&typeof o==='object');
    $('objects-present').textContent=monitorStateAvailable?objects.filter(o=>o.status==='present').length:'—';
    $('objects-missing').textContent=monitorStateAvailable?objects.filter(o=>o.status==='missing'||o.status==='removed').length:'—';
    $('people-count').textContent=monitorStateAvailable&&Number.isFinite(data.person_count)?data.person_count:'—';
    $('event-total').textContent=String(totalEvents);
    $('inventory-time').textContent=data.updated_at?'Inventory saved '+dateText(new Date(data.updated_at),{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'No inventory timestamp yet';
    monitorConnected=true;lastMonitorCheck=new Date();
    const notes=Array.isArray(data.warnings)?data.warnings:[];
    $('monitor-notice').hidden=notes.length===0&&monitorStateAvailable;
    $('monitor-notice').textContent=notes.join(' ')||'No saved object inventory yet. Counts remain unavailable until the monitor records an observation.';
    if(changed||older)renderHistory();
    if(data.preview)$('demo-notice').hidden=false;
  }catch{
    monitorConnected=false;$('monitor-notice').hidden=false;
    $('monitor-notice').textContent=events.length?'Monitoring connection lost. Showing previously loaded history; retrying automatically.':'Monitoring data is unavailable. The page will retry automatically.';
    renderHistory();
  }finally{monitorLoading=false;olderLoading=false;$('load-older').disabled=false;$('load-older').textContent='Load older events ↓';updateFreshness();}
}
async function refresh(){const button=$('refresh-btn');button.disabled=true;try{await Promise.all([fetchRuns(),fetchMonitor()]);}finally{button.disabled=false;}}
async function poll(){if(!document.hidden)await refresh();setTimeout(poll,5000);}
for(const button of document.querySelectorAll('[data-filter]'))button.onclick=()=>{eventFilter=button.dataset.filter;for(const other of document.querySelectorAll('[data-filter]'))other.setAttribute('aria-pressed',String(other===button));$('object-events').scrollTop=0;renderHistory();};
$('event-search').oninput=event=>{searchText=event.target.value.trim().toLowerCase();$('object-events').scrollTop=0;renderHistory();};
$('clear-filters').onclick=()=>{eventFilter='all';searchText='';$('event-search').value='';for(const button of document.querySelectorAll('[data-filter]'))button.setAttribute('aria-pressed',String(button.dataset.filter==='all'));renderHistory();};
$('load-older').onclick=()=>fetchMonitor(true);$('refresh-btn').onclick=refresh;
$('original-btn').onclick=()=>setView('original');$('overlay-btn').onclick=()=>setView('overlay');
$('changes-filter').onchange=event=>{changesOnly=event.target.checked;const list=visibleRuns();if(!list.some(r=>r.folder===selectedFolder))selectedFolder=list[0]?.folder||null;renderDisplay();renderGallery();};
$('latest-btn').onclick=()=>{followLatest=true;selectedFolder=visibleRuns()[0]?.folder||null;failedImage=null;renderDisplay();renderGallery();};
function navigate(step){const list=visibleRuns(),i=list.findIndex(r=>r.folder===selectedFolder),next=list[i+step];if(next)selectCapture(next.folder);}
$('prev-btn').onclick=()=>navigate(-1);$('next-btn').onclick=()=>navigate(1);
$('featured-image').onerror=()=>{failedImage=selectedRun()?.[viewMode];renderDisplay();};
$('expand-btn').onclick=()=>{const run=selectedRun(),url=run?.[viewMode];if(!url)return;$('expanded-image').src=url;$('dialog-caption').textContent=captureText(run);$('dialog-title').textContent=viewMode==='original'?'Original capture':'Detection overlay';$('image-dialog').showModal();};
$('close-dialog').onclick=()=>$('image-dialog').close();
$('image-dialog').onclick=event=>{if(event.target===$('image-dialog')){const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)event.target.close();}};
renderDisplay();renderGallery();renderHistory();poll();setInterval(updateFreshness,30000);
