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
let monitorLoading = false;
let captureRequest = 0;
let lastMonitorCheck = null, monitorStateAvailable = false, failedImage = null;
let configuredMaskCategories = [], maskSourceAvailable = false;
let excludedMaskCategories = new Set();
try {const saved=JSON.parse(localStorage.getItem('jarvis-hidden-mask-categories')||'[]');if(Array.isArray(saved))excludedMaskCategories=new Set(saved.filter(value=>typeof value==='string'));} catch {}
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
function maskCategories(run=selectedRun()) {return [...new Set([...configuredMaskCategories,...(Array.isArray(run?.mask_categories)?run.mask_categories:[])])];}
function imageForRun(run, mode=viewMode) {
  if(!run)return null;
  if(mode==='original')return run.original;
  const categories=maskCategories(run).filter(category=>!excludedMaskCategories.has(category));
  const hidden=(run.mask_categories?.length?run.mask_categories:configuredMaskCategories).some(category=>excludedMaskCategories.has(category));
  if(!categories.length && maskCategories(run).length)return run.original;
  if(!hidden)return run.overlay || (run.mask_filterable?filteredMaskUrl(run,categories):null);
  if(!categories.length || !run.mask_filterable)return run.original;
  return filteredMaskUrl(run,categories);
}
function filteredMaskUrl(run,categories) {const query=new URLSearchParams();if(!categories.length)query.append('categories','');else for(const category of categories)query.append('categories',category);return `/api/overlay/${encodeURIComponent(run.folder)}?${query}`;}
function saveMaskSelection() {try{localStorage.setItem('jarvis-hidden-mask-categories',JSON.stringify([...excludedMaskCategories]));}catch{}failedImage=null;viewMode='overlay';renderDisplay();renderGallery();}
function renderMaskControls(run) {
  const container=$('mask-category-list'), focusedCategory=document.activeElement?.dataset?.maskCategory;
  container.replaceChildren();const categories=maskCategories(run);
  for(const category of categories){
    const label=el('label','mask-category'), input=el('input');input.type='checkbox';input.value=category;input.dataset.maskCategory=category;input.checked=!excludedMaskCategories.has(category);
    const name=el('span','',category.replaceAll('_',' '));
    const count=el('small','',String(run?.category_counts?.[category]??0));count.setAttribute('aria-label',`${run?.category_counts?.[category]??0} masks in selected capture`);
    input.onchange=()=>{if(input.checked)excludedMaskCategories.delete(category);else excludedMaskCategories.add(category);saveMaskSelection();};label.append(input,name,count);container.append(label);
  }
  if(focusedCategory)Array.from(container.querySelectorAll('input')).find(input=>input.value===focusedCategory)?.focus({preventScroll:true});
  $('masks-all').disabled=!categories.length;$('masks-none').disabled=!categories.length;
  $('mask-source').textContent=maskSourceAvailable?'Categories from SAM3’s detection prompts.':categories.length?'SAM3 settings unavailable; using this capture’s saved categories.':'No SAM3 category list is available for this capture.';
  const selected=categories.filter(category=>!excludedMaskCategories.has(category));
  const maskCount=selected.reduce((sum,category)=>sum+(run?.category_counts?.[category]||0),0);
  const partial=categories.some(category=>excludedMaskCategories.has(category));
  $('mask-summary').textContent=!run?'Choose a capture to inspect its masks.':!run.mask_filterable?(partial?'Individual masks are unavailable for this older capture. Showing the original when categories are hidden.':'Saved combined overlay only · individual category counts are unavailable for this capture.'):`${selected.length} of ${categories.length} categories selected · ${maskCount} masks${viewMode==='original'?' · original view':''}`;
  if($('image-dialog').open){const url=imageForRun(run);if(url)$('expanded-image').src=url;}
}
async function fetchMaskCategories() {
  try{const response=await fetch('/api/mask-categories',{cache:'no-store',signal:AbortSignal.timeout(8000)});if(!response.ok)throw Error();const data=await response.json();configuredMaskCategories=Array.isArray(data.categories)?data.categories.filter(c=>typeof c==='string'):[];maskSourceAvailable=!!data.source_available;}
  catch{maskSourceAvailable=false;}
  renderDisplay();renderGallery();
}
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
  const run=selectedRun(), img=$('featured-image'), url=imageForRun(run);
  const unavailable=!url || failedImage===url;
  img.hidden=unavailable;$('empty-state').hidden=!unavailable;$('frame-label').hidden=unavailable;
  if(url && img.getAttribute('src')!==url)img.src=url;
  $('empty-state').querySelector('h3').textContent=failedImage===url && url ? 'Image could not load' : run ? 'This view is unavailable' : 'Waiting for a capture';
  $('empty-state').querySelector('p').textContent=run ? 'Choose another view or capture.' : capturesConnected ? 'Saved frames will appear here.' : 'Waiting for the capture archive connection.';
  $('frame-label').textContent=viewMode==='original'?'ORIGINAL FRAME':!maskCategories(run).some(c=>!excludedMaskCategories.has(c))?'NO MASKS SELECTED':url===run?.original?'ORIGINAL · MASKS UNAVAILABLE':'DETECTION OVERLAY';
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
  renderMaskControls(run);
}
function renderGallery() {
  const grid=$('image-grid'), focusedFolder=document.activeElement?.dataset?.folder;
  grid.replaceChildren();
  for(const run of visibleRuns()) {
    const card=el('button','capture-card');card.dataset.folder=run.folder;
    card.setAttribute('aria-pressed',String(run.folder===selectedFolder));
    card.setAttribute('aria-label',`Inspect capture ${captureText(run)}`);
    const img=el('img');img.src=imageForRun(run)||run.original||run.overlay;img.alt='';img.loading='lazy';
    const info=el('span','capture-info');
    info.append(el('strong','',dateText(captureDate(run),{hour:'numeric',minute:'2-digit',second:'2-digit'})),el('small','',dateText(captureDate(run),{month:'short',day:'numeric',year:'numeric'})));
    if(run.folder===currentRuns[0]?.folder)info.append(el('small','new-tag','LATEST'));
    const changes=run.change_log?.changes, count=Array.isArray(changes)?changes.length:null;
    const summary=el('span','capture-summary'+(count?' has-changes':''),count===null?'Not analyzed':count===0?'No confirmed changes':`${count} recorded ${count===1?'change':'changes'} · inspect frame`);
    card.append(img,info,summary);card.onclick=()=>selectCapture(run.folder);grid.append(card);
  }
  if(focusedFolder){const card=Array.from(grid.children).find(c=>c.dataset.folder===focusedFolder);card?.focus({preventScroll:true});}
  $('capture-count').textContent=String(currentRuns.length).padStart(2,'0');
  $('capture-filter-count').textContent=`${visibleRuns().length} of ${currentRuns.length} captures on this day shown`;
  $('gallery-empty').hidden=visibleRuns().length>0;
  $('gallery-empty').textContent=changesOnly?'No captures with recorded changes on this day.':capturesConnected?'No pictures saved for this day.':'Capture archive unavailable. Retrying automatically.';
}
let selectedDay=null, roomToday=null, occupancyData=null, occupancySignature='', occupancyRequest=0;
let selectedObservationTime=null, followToday=true;
const SVG_NS='http://www.w3.org/2000/svg';
function svgNode(tag, attributes, text) {
  const node=document.createElementNS(SVG_NS,tag);
  for(const [key,value] of Object.entries(attributes||{}))node.setAttribute(key,String(value));
  if(text!==undefined)node.textContent=text;
  return node;
}
function roomTime(stamp, options={hour:'numeric',minute:'2-digit'}) {
  return new Date(stamp).toLocaleString(undefined,{...options,timeZone:occupancyData?.timezone||'UTC'});
}
function showObservation(point) {
  selectedObservationTime=point.time;
  $('occupancy-readout').textContent=`${point.count} ${point.count===1?'person':'people'} observed at ${roomTime(point.time,{hour:'numeric',minute:'2-digit',second:'2-digit'})} · ${point.source==='capture'?'saved capture':'saved monitor event'}`;
}
function renderObservationTable() {
  const body=$('observations-body');body.replaceChildren();
  for(const point of occupancyData?.observations||[]){
    const row=el('tr');row.append(el('td','',roomTime(point.time,{hour:'numeric',minute:'2-digit',second:'2-digit'})),el('td','',String(point.count)));
    const source=el('td','',point.source==='capture'?'Saved capture':'Monitor event');
    if(point.run_id&&currentRuns.some(run=>run.folder===point.run_id)){
      const button=el('button','text-button','Inspect capture ↗');button.onclick=()=>{changesOnly=false;$('changes-filter').checked=false;selectCapture(point.run_id);$('captures').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});};source.append(button);
    }
    row.append(source);body.append(row);
  }
}
function renderOccupancy() {
  const svg=$('occupancy-chart'), points=occupancyData?.observations||[];
  svg.replaceChildren(svgNode('title',{id:'occupancy-svg-title'},'Observed people across the selected day'),svgNode('desc',{id:'occupancy-svg-description'},'Horizontal axis: midnight to midnight. Vertical axis: number of people. Blank periods have no saved observations. Focus a dot to read its count and time.'));
  const left=62,right=972,top=28,bottom=244,step=Math.max(1,Math.ceil(Math.max(5,...points.map(p=>p.count))/4)),ceiling=step*4;
  const x=point=>left+(point.hour/24)*(right-left), y=count=>bottom-(count/ceiling)*(bottom-top);
  for(let i=0;i<=4;i++){
    const count=i*step,py=y(count);
    svg.append(svgNode('line',{x1:left,x2:right,y1:py,y2:py,class:'chart-grid'}),svgNode('text',{x:left-14,y:py+4,'text-anchor':'end',class:'chart-axis'},count));
  }
  for(let hour=0;hour<=24;hour+=4){
    const px=left+(hour/24)*(right-left);
    svg.append(svgNode('line',{x1:px,x2:px,y1:top,y2:bottom,class:'chart-grid vertical'}),svgNode('text',{x:px,y:bottom+28,'text-anchor':hour===0?'start':hour===24?'end':'middle',class:'chart-axis'},`${String(hour).padStart(2,'0')}:00`));
  }
  svg.append(svgNode('text',{x:left,y:16,class:'chart-axis'},'PEOPLE'));
  for(let i=1;i<points.length;i++){
    const previous=points[i-1],point=points[i],gap=new Date(point.time)-new Date(previous.time);
    if(gap>=0&&gap<=900000&&point.hour>=previous.hour)svg.append(svgNode('path',{d:`M ${x(previous)} ${y(previous.count)} H ${x(point)} V ${y(point.count)}`,class:'occupancy-line'}));
  }
  for(const point of points){
    const dot=svgNode('circle',{cx:x(point),cy:y(point.count),r:5.5,class:'occupancy-point',tabindex:0,role:'img','aria-label':`${point.count} people at ${roomTime(point.time,{hour:'numeric',minute:'2-digit',second:'2-digit'})}`});
    dot.append(svgNode('title',{},`${point.count} people · ${roomTime(point.time)}`));
    dot.onfocus=dot.onmouseenter=dot.onclick=()=>showObservation(point);svg.append(dot);
  }
  if(!points.length)svg.append(svgNode('text',{x:(left+right)/2,y:(top+bottom)/2,'text-anchor':'middle',class:'chart-empty'},occupancyData?'No saved people-count observations for this day':'Loading saved observations…'));
  $('occupancy-peak').textContent=occupancyData?.peak??'—';
  $('occupancy-total').textContent=occupancyData?`${points.length} saved ${points.length===1?'observation':'observations'} on selected day`:'No daily observations loaded';
  $('occupancy-zone').textContent=occupancyData?occupancyData.timezone.replaceAll('_',' '):'Camera local time';
  $('occupancy-day-label').textContent=selectedDay?new Date(selectedDay+'T12:00:00Z').toLocaleDateString(undefined,{timeZone:'UTC',weekday:'long',month:'long',day:'numeric',year:'numeric'})+' · 00:00–24:00':'Loading the daily graph…';
  $('next-day').disabled=!selectedDay||!roomToday||selectedDay>=roomToday;
  $('previous-day').disabled=!selectedDay;
  if(roomToday)$('occupancy-date').max=roomToday;
  if(selectedDay)$('occupancy-date').value=selectedDay;
  $('captures-date').value=selectedDay||'';
  if(roomToday)$('captures-date').max=roomToday;
  $('captures-previous-day').disabled=!selectedDay;
  $('captures-next-day').disabled=!selectedDay||!roomToday||selectedDay>=roomToday;
  $('capture-day-label').textContent=selectedDay?new Date(selectedDay+'T12:00:00Z').toLocaleDateString(undefined,{timeZone:'UTC',month:'long',day:'numeric',year:'numeric'})+' · Pacific time':'Choose a day';
  const selected=points.find(point=>point.time===selectedObservationTime)||points.at(-1);
  if(selected)showObservation(selected);else $('occupancy-readout').textContent='No count was recorded for this day. Blank hours do not mean zero people.';
  const latest=occupancyData?.latest_observation;
  $('people-observed-at').textContent=latest?'Observed '+roomTime(latest.time,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+(Date.now()-new Date(latest.time)>900000?' · not current':''):'No timestamped people observation';
  $('people-observed-at').classList.toggle('stale',!!latest&&Date.now()-new Date(latest.time)>900000);
  renderObservationTable();
}
async function fetchOccupancy() {
  const request=++occupancyRequest,requestedDay=selectedDay;
  try{
    const response=await fetch('/api/occupancy'+(requestedDay?'?day='+encodeURIComponent(requestedDay):''),{cache:'no-store',signal:AbortSignal.timeout(8000)});
    if(!response.ok)throw Error('Daily observations unavailable');
    const data=await response.json();
    if(request!==occupancyRequest)return;
    if(!Array.isArray(data.observations)||!/^\d{4}-\d{2}-\d{2}$/.test(data.day))throw Error('Invalid occupancy response');
    if(followToday&&requestedDay&&requestedDay!==data.today){selectedDay=data.today;return fetchOccupancy();}
    selectedDay=data.day;roomToday=data.today;
    const signature=JSON.stringify(data);
    occupancyData=data;
    if(signature!==occupancySignature){occupancySignature=signature;renderOccupancy();}
    const warnings=Array.isArray(data.warnings)?data.warnings:[];
    $('occupancy-warning').hidden=!warnings.length;$('occupancy-warning').textContent=warnings.join(' ');
    if(data.preview)$('demo-notice').hidden=false;
  }catch{
    if(request!==occupancyRequest)return;
    if(occupancyData?.day!==selectedDay){occupancyData=null;occupancySignature='';renderOccupancy();}
    $('occupancy-warning').hidden=false;$('occupancy-warning').textContent='People-count observations are unavailable. Retrying automatically; any displayed counts are previously saved data.';
  }
}
function changeObservationDay(day) {
  if(!/^\d{4}-\d{2}-\d{2}$/.test(day)||day>roomToday)return;
  selectedDay=day;followToday=day===roomToday;selectedObservationTime=null;occupancyData=null;occupancySignature='';captureRequest++;currentRuns=[];selectedFolder=null;capturesConnected=false;failedImage=null;renderDisplay();renderGallery();renderOccupancy();refresh();
}
function offsetObservationDay(offset){if(!selectedDay)return;const value=new Date(selectedDay+'T12:00:00Z');value.setUTCDate(value.getUTCDate()+offset);changeObservationDay(value.toISOString().slice(0,10));}
$('occupancy-date').onchange=event=>changeObservationDay(event.target.value);
$('captures-date').onchange=event=>changeObservationDay(event.target.value);
$('captures-previous-day').onclick=()=>offsetObservationDay(-1);$('captures-next-day').onclick=()=>offsetObservationDay(1);
$('captures-today').onclick=()=>{if(roomToday)changeObservationDay(roomToday);};
$('previous-day').onclick=()=>offsetObservationDay(-1);$('next-day').onclick=()=>offsetObservationDay(1);
$('today-btn').onclick=()=>{if(roomToday)changeObservationDay(roomToday);};
$('observations-toggle').onclick=()=>{const show=$('observations-table').hidden;$('observations-table').hidden=!show;$('observations-toggle').setAttribute('aria-expanded',String(show));$('observations-toggle').textContent=show?'Hide observations':'Show observations';};

function updateFreshness() {
  const latest=occupancyData?.latest_observation;
  if(latest){const staleCount=Date.now()-new Date(latest.time)>900000;$('people-observed-at').textContent='Observed '+roomTime(latest.time,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+(staleCount?' · not current':'');$('people-observed-at').classList.toggle('stale',staleCount);}
  const date=captureDate(currentRuns[0]), age=date?Math.max(0,Date.now()-date.getTime()):null;
  const stale=age!==null&&age>120000;
  $('status-badge').textContent=monitorConnected&&capturesConnected?'Archive connected':monitorConnected||capturesConnected?'Partial connection':'Disconnected · retrying';
  $('status-dot').classList.toggle('online',monitorConnected&&capturesConnected);
  $('monitor-sync').textContent=lastMonitorCheck?`${monitorConnected?'Inventory checked':'Last successful inventory check'} at ${lastMonitorCheck.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit',second:'2-digit'})}`:'Waiting for monitoring data';
  $('freshness').classList.toggle('stale',stale||!capturesConnected);
  $('freshness').textContent=!capturesConnected?'Capture archive unavailable · retrying':!date?'No saved captures yet':`Latest capture: ${captureText(currentRuns[0])}${stale?' · no recent capture':''}`;
}
async function fetchRuns() {
  const request=++captureRequest,requestedDay=selectedDay;
  if(!requestedDay)return;
  try{
    const response=await fetch('/api/latest?day='+encodeURIComponent(requestedDay),{cache:'no-store',signal:AbortSignal.timeout(8000)});
    if(!response.ok)throw Error('Capture archive unavailable');
    const data=await response.json();if(request!==captureRequest||requestedDay!==selectedDay)return;if(!Array.isArray(data.runs)||data.day!==requestedDay)throw Error('Invalid capture response');
    const runs=data.runs.filter(r=>r&&typeof r.folder==='string').map(normalizeRun).filter(r=>r.original||r.overlay);
    const changed=JSON.stringify(runs)!==JSON.stringify(currentRuns)||!capturesConnected;
    currentRuns=runs;capturesConnected=true;
    const list=visibleRuns();
    if(followLatest||!list.some(r=>r.folder===selectedFolder)){selectedFolder=list[0]?.folder||null;failedImage=null;}
    renderDisplay();if(changed){renderGallery();if(occupancyData)renderObservationTable();}
    if(data.preview)$('demo-notice').hidden=false;
  }catch{if(request!==captureRequest||requestedDay!==selectedDay)return;capturesConnected=false;if(!currentRuns.length)renderGallery();}
  updateFreshness();
}
async function fetchMonitor() {
  if(monitorLoading)return;
  monitorLoading=true;
  try{
    const response=await fetch('/api/object-monitor?limit=1',{cache:'no-store',signal:AbortSignal.timeout(8000)});
    if(!response.ok)throw Error('Object monitor unavailable');
    const data=await response.json();monitorStateAvailable=!!data.state_available;
    const objects=Object.values(data.objects||{}).filter(o=>o&&typeof o==='object');
    $('objects-present').textContent=monitorStateAvailable?objects.filter(o=>o.status==='present').length:'—';
    $('objects-missing').textContent=monitorStateAvailable?objects.filter(o=>o.status==='missing'||o.status==='removed').length:'—';
    $('people-count').textContent=monitorStateAvailable&&Number.isFinite(data.person_count)?data.person_count:'—';
    monitorConnected=true;lastMonitorCheck=new Date();
    const notes=Array.isArray(data.warnings)?data.warnings:[];
    $('monitor-notice').hidden=notes.length===0&&monitorStateAvailable;
    $('monitor-notice').textContent=notes.join(' ')||'No saved object inventory yet. Counts remain unavailable until the monitor records an observation.';
  }catch{
    monitorConnected=false;$('monitor-notice').hidden=false;
    $('monitor-notice').textContent='Monitoring connection lost. Showing the last loaded inventory; retrying automatically.';
  }finally{monitorLoading=false;updateFreshness();}
}

async function refresh(){const button=$('refresh-btn');button.disabled=true;try{await Promise.all([fetchMonitor(),fetchMaskCategories(),fetchOccupancy()]);await fetchRuns();}finally{button.disabled=false;}}
async function poll(){if(!document.hidden)await refresh();setTimeout(poll,5000);}
$('refresh-btn').onclick=refresh;
$('original-btn').onclick=()=>setView('original');$('overlay-btn').onclick=()=>setView('overlay');
$('changes-filter').onchange=event=>{changesOnly=event.target.checked;const list=visibleRuns();if(!list.some(r=>r.folder===selectedFolder))selectedFolder=list[0]?.folder||null;renderDisplay();renderGallery();};
$('latest-btn').onclick=()=>{followLatest=true;selectedFolder=visibleRuns()[0]?.folder||null;failedImage=null;renderDisplay();renderGallery();};
function navigate(step){const list=visibleRuns(),i=list.findIndex(r=>r.folder===selectedFolder),next=list[i+step];if(next)selectCapture(next.folder);}
$('prev-btn').onclick=()=>navigate(-1);$('next-btn').onclick=()=>navigate(1);
$('featured-image').onerror=()=>{failedImage=imageForRun(selectedRun());renderDisplay();};
$('expand-btn').onclick=()=>{const run=selectedRun(),url=imageForRun(run);if(!url)return;$('expanded-image').src=url;$('dialog-caption').textContent=captureText(run);$('dialog-title').textContent=viewMode==='original'?'Original capture':'Detection overlay';$('image-dialog').showModal();};
$('masks-all').onclick=()=>{for(const category of maskCategories())excludedMaskCategories.delete(category);saveMaskSelection();};
$('masks-none').onclick=()=>{for(const category of maskCategories())excludedMaskCategories.add(category);saveMaskSelection();};
$('close-dialog').onclick=()=>$('image-dialog').close();
$('image-dialog').onclick=event=>{if(event.target===$('image-dialog')){const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)event.target.close();}};
renderDisplay();renderGallery();renderOccupancy();poll();setInterval(updateFreshness,30000);
