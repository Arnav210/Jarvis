let currentRuns = [];
let selectedFolder = null;
let viewMode = 'original';
let followLatest = true;
let connected = false;
let changesOnly = false;
const $ = id => document.getElementById(id);
const selectedRun = () => currentRuns.find(run => run.folder === selectedFolder);
function captureDate(folder) {
  const match = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})/.exec(folder || '');
  return match ? new Date(+match[1], +match[2]-1, +match[3], +match[4], +match[5], +match[6]) : null;
}
function dateText(folder, options) {
  const date = captureDate(folder);
  return date && !isNaN(date) ? date.toLocaleString(undefined, options) : 'Time unavailable';
}
function setView(mode) {
  viewMode = mode;
  $('original-btn').setAttribute('aria-pressed', String(mode === 'original'));
  $('overlay-btn').setAttribute('aria-pressed', String(mode === 'overlay'));
  renderDisplay();
  renderGallery();
}
function renderDisplay() {
  const run = selectedRun();
  const img = $('featured-image');
  const url = run?.[viewMode];
  img.hidden = !url;
  $('empty-state').hidden = !!url;
  $('frame-label').hidden = !url;
  if (url && img.getAttribute('src') !== url) img.src = url;
  $('empty-state').querySelector('h3').textContent = run ? 'This view is unavailable' : 'Waiting for a capture';
  $('empty-state').querySelector('p').textContent = run ? 'Choose another view or capture.' : 'Available frames will appear here.';
  $('frame-label').textContent = viewMode === 'original' ? 'ORIGINAL FRAME' : 'DETECTION OVERLAY';
  $('image-timestamp').textContent = run ? dateText(run.folder, {month:'short', day:'numeric', year:'numeric', hour:'numeric',minute:'2-digit',second:'2-digit'}) + ' · camera local time' : 'No frame selected';
  const index = currentRuns.findIndex(r => r.folder === selectedFolder);
  $('frame-position').textContent = `${String(index + 1).padStart(2,'0')} / ${String(currentRuns.length).padStart(2,'0')}`;
  $('prev-btn').disabled = index <= 0;
  $('next-btn').disabled = index < 0 || index >= currentRuns.length - 1;
  $('latest-btn').textContent = followLatest ? 'Following latest ↗' : 'Follow latest ↗';
}
function select(folder) {
  selectedFolder = folder;
  followLatest = false;
  renderDisplay();
  renderGallery();
}
function renderGallery() {
  const grid = $('image-grid');
  grid.replaceChildren();
  const visibleRuns = changesOnly
    ? currentRuns.filter(run =>
        Array.isArray(run.change_log?.changes) &&
        run.change_log.changes.length > 0
      )
    : currentRuns;

  visibleRuns.forEach((run) => {
    const card = document.createElement('button');
    card.className = 'capture-card';
    card.setAttribute('aria-pressed', String(run.folder === selectedFolder));
    const img = document.createElement('img');
    img.src = run[viewMode] || run.original || run.overlay;
    img.alt = '';
    img.loading = 'lazy';
    const info = document.createElement('span');
    info.className = 'capture-info';
    const time = document.createElement('strong');
    time.textContent = dateText(run.folder,{hour:'numeric',minute:'2-digit',second:'2-digit'});
    const day = document.createElement('small');
    day.textContent = dateText(run.folder,{month:'short',day:'numeric',year:'numeric'});
    info.append(time, day);
    card.append(img, info);

    const log = document.createElement('span');
    log.className = 'capture-change-log';

    const changes = run.change_log?.changes;

    if (!Array.isArray(changes)) {
      log.textContent = 'Not analyzed';
      log.classList.add('change-unavailable');
    } else if (changes.length === 0) {
      log.textContent = '✓ No confirmed changes';
      log.classList.add('change-none');
    } else {
      changes.forEach(event => {
        const line = document.createElement('span');
        line.className = 'capture-change-event';

        if (event.event === 'object_missing') {
          line.classList.add('change-missing');
          line.textContent = '− ' + event.message;
        } else if (event.event === 'new_object') {
          line.classList.add('change-added');
          line.textContent = '+ ' + event.message;
        } else if (event.event === 'object_returned') {
          line.classList.add('change-returned');
          line.textContent = '↩ ' + event.message;
        } else {
          line.textContent = event.message;
        }

        log.append(line);
      });
    }

    card.append(log);
    if (run.folder === currentRuns[0]?.folder) { const tag = document.createElement('span'); tag.className='new-tag'; tag.textContent='LATEST'; card.append(tag); }
    card.onclick = () => select(run.folder);
    grid.append(card);
  });
  $('capture-count').textContent = String(currentRuns.length).padStart(2,'0');
  $('gallery-empty').hidden = visibleRuns.length > 0;
  $('gallery-empty').textContent = changesOnly
    ? 'No captures with recorded changes yet.'
    : connected
      ? 'No captures yet. New frames will appear automatically.'
      : 'Unable to load captures. Reconnecting automatically…';
}
function updateFreshness() {
  const date = captureDate(currentRuns[0]?.folder);
  const age = date ? Math.max(0, Date.now() - date.getTime()) : null;
  const stale = age !== null && age > 120000;
  const status = !connected ? 'Disconnected' : !date ? 'Dashboard connected' : stale ? 'No recent capture' : 'Captures updating';
  $('status-badge').textContent = status;
  $('status-dot').classList.toggle('online', connected && !stale);
  $('freshness').classList.toggle('stale', stale);
  $('freshness').textContent = !connected ? 'Connection lost · retrying' : !date ? 'Waiting for the first capture' : 'Latest capture: ' + dateText(currentRuns[0].folder,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}) + ' (camera time)';
}
async function fetchLatestRuns() {
  try {
    const response = await fetch('/api/latest', {signal:AbortSignal.timeout(8000)});
    if (!response.ok) throw Error('Unable to load captures');
    const data = await response.json();
    const runs = (data.runs || []).filter(run => run && typeof run.folder === 'string' && (run.original || run.overlay));
    const changed = JSON.stringify(runs) !== JSON.stringify(currentRuns);
    connected = true;
    currentRuns = runs;
    if (followLatest || !selectedRun()) selectedFolder = runs[0]?.folder || null;
    renderDisplay();
    if (changed || !$('image-grid').childElementCount) renderGallery();
  } catch {
    connected = false;
    if (!currentRuns.length) renderGallery();
  } finally {
    updateFreshness();
    setTimeout(fetchLatestRuns, 2500);
  }
}
$('original-btn').onclick = () => setView('original');
$('overlay-btn').onclick = () => setView('overlay');
$('latest-btn').onclick = () => {followLatest=true; selectedFolder=currentRuns[0]?.folder || null; renderDisplay(); renderGallery();};
$('prev-btn').onclick = () => {const i=currentRuns.findIndex(r=>r.folder===selectedFolder);if(i>0)select(currentRuns[i-1].folder);};
$('next-btn').onclick = () => {const i=currentRuns.findIndex(r=>r.folder===selectedFolder);if(i>=0 && i<currentRuns.length-1)select(currentRuns[i+1].folder);};
$('featured-image').onerror = () => { $('featured-image').hidden=true; $('empty-state').hidden=false; $('empty-state').querySelector('h3').textContent='Image could not load'; $('empty-state').querySelector('p').textContent='Try another capture or switch views.'; };
$('changes-filter-btn').onclick = () => {
  changesOnly = !changesOnly;
  $('changes-filter-btn').setAttribute(
    'aria-pressed', String(changesOnly)
  );
  $('changes-filter-btn').textContent = changesOnly
    ? 'Show all captures'
    : 'Show changes only';
  renderGallery();
};

renderDisplay();
fetchLatestRuns();
// ============================================================
// JARVIS OBJECT MONITOR
// ============================================================

async function fetchObjectMonitor() {
  try {
    const response = await fetch('/api/object-monitor');

    if (!response.ok) {
      throw new Error('Object monitor unavailable');
    }

    const data = await response.json();

    const objects = Object.values(data.objects || {});

    const present = objects.filter(
      obj => obj.status === 'present'
    ).length;

    const missing = objects.filter(
      obj => obj.status === 'missing'
    ).length;

    $('objects-present').textContent = present;
    $('objects-missing').textContent = missing;
    $('people-count').textContent = data.person_count ?? '—';

    // Display historical monitoring events
    const eventsContainer = $('object-events');
    eventsContainer.replaceChildren();

    const events = (data.recent_events || [])
      .filter(event =>
        ['new_object', 'object_missing',
         'object_returned', 'person_count_changed']
        .includes(event.event)
      )
      .reverse();

    if (events.length === 0) {
      eventsContainer.textContent = 'No monitoring events recorded yet.';
    }

    events.forEach(event => {
      const item = document.createElement('div');
      item.className = 'monitor-event';
      item.classList.add('monitor-' + event.event.replaceAll('_', '-'));

      const message = document.createElement('strong');
      message.textContent = event.message;

      const timestamp = document.createElement('small');
      const date = new Date(event.time);
      timestamp.textContent = Number.isNaN(date.getTime())
        ? 'Time unavailable'
        : date.toLocaleString();

      item.append(message, timestamp);
      eventsContainer.append(item);
    });

  } catch (error) {
    console.error('Object monitor error:', error);
  }
}

// Refresh monitoring data every 5 seconds
fetchObjectMonitor();
setInterval(fetchObjectMonitor, 5000);
