/* The visual style is adapted from the team's original presentation simulator.
   All result states and FTP messages below come from the real Flask experiment API.
   Timeline animation shows control-message direction, not replayed packet timestamps. */
'use strict';
const $ = selector => document.querySelector(selector);
const config = { nat: 'N1', mode: 'passive', operation: 'retr', loss: 0 };
let running = false, events = [], shown = -1, playback = null, dotMotion = null, lastResult = null;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let payload;
  try { payload = await response.json(); }
  catch { throw new Error('The backend did not return JSON.'); }
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}
const post = (path, data) => api(path, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const metric = (value, suffix) => typeof value === 'number' ? `${value.toFixed(2)} ${suffix}` : '—';
const yes = value => value === true ? '✓ Success' : value === false ? '✕ Failed' : '—';

function describeNat() {
  $('#natDescription').textContent = ({N0:'N0 · routing only', N1:'N1 · masquerading', N2:'N2 · FTP helper'})[config.nat];
}
function clearCapture(note='Available when the capture has been saved.') {
  const a = $('#downloadCapture');
  a.removeAttribute('href'); a.removeAttribute('download'); a.classList.add('disabled');
  a.setAttribute('aria-disabled','true'); $('#captureNote').textContent = note;
}
function showCapture(result) {
  if (result.capture_available && result.capture_url) {
    const a = $('#downloadCapture');
    a.href = result.capture_url;
    a.setAttribute('download', result.capture_filename || 'ftp-session.pcapng');
    a.classList.remove('disabled'); a.removeAttribute('aria-disabled');
    $('#captureNote').textContent = 'Actual R1 inside/outside and R2 server captures merged into a single Wireshark file.';
  } else clearCapture(`Capture not available: ${result.capture_error || 'No capture saved.'}`);
}
function updateControls() {
  document.querySelectorAll('.segments').forEach(group => {
    const key = group.dataset.field;
    group.querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', String(String(config[key]) === button.dataset.value)));
  });
  describeNat();
}
function stopPlayback() {
  if (playback !== null) { clearInterval(playback); playback = null; }
  if (dotMotion !== null) { cancelAnimationFrame(dotMotion); dotMotion = null; }
  $('#packetDot').setAttribute('opacity', '0');
  $('#play').textContent = '▶ Play';
}
function clearTimeline(note) {
  stopPlayback(); events = []; shown = -1;
  $('#log').replaceChildren();
  const msg = document.createElement('div'); msg.className='empty'; msg.textContent=note;
  $('#log').appendChild(msg);
  $('#timelineCount').textContent='No messages';
  for(const id of ['play','next','reset']) $("#"+id).disabled=true;
  $('#flowDescription').textContent='The packet indicator illustrates control-message direction, not exact packet timing.';
}
function animateDirection(direction) {
  if (dotMotion !== null) cancelAnimationFrame(dotMotion);
  const circle = $('#packetDot');
  const from = direction === 'client' ? 100 : 760;
  const to = direction === 'client' ? 760 : 100;
  const start = performance.now();
  circle.setAttribute('opacity','1');
  function tick(now) {
    const progress = Math.min((now-start)/650,1);
    circle.setAttribute('cx', String(from+(to-from)*progress));
    if(progress < 1) dotMotion=requestAnimationFrame(tick);
    else { dotMotion=null; circle.setAttribute('opacity','0'); }
  }
  dotMotion = requestAnimationFrame(tick);
}
function displayTimeline(index) {
  shown=index;
  const log=$('#log'); log.replaceChildren();
  events.slice(0,index+1).forEach((entry,i) => {
    const row=document.createElement('div');
    const error=/^(4\d\d|5\d\d)\b/.test(entry.message || '');
    row.className=`eventrow ${entry.direction === 'client' ? 'client' : 'server'}${i===index?' current':''}${error?' error':''}`;
    const side=document.createElement('small'); side.textContent=entry.direction === 'client' ? 'CLIENT →' : '← SERVER';
    const message=document.createElement('code'); message.textContent=entry.message;
    row.append(side,message); log.appendChild(row);
  });
  log.scrollTop=log.scrollHeight;
  $('#timelineCount').textContent=`${Math.max(0,index+1)} / ${events.length} messages`;
  const current=events[index];
  if(current) {
    animateDirection(current.direction);
    $('#flowDescription').textContent=current.direction==='client' ? 'Control message: client → server (through R1 and R2)' : 'Control reply: server → client (through R2 and R1)';
  }
}
function step() {
  if(shown < events.length-1) { displayTimeline(shown+1); return true; }
  return false;
}
function replay() {
  stopPlayback();
  if(!events.length) return;
  if(shown >= events.length-1) shown=-1;
  $('#play').textContent='Ⅱ Pause';
  step();
  playback=setInterval(() => {
    if(!step()) stopPlayback();
  },850);
}
function loadTimeline(transcript) {
  clearTimeline('Preparing recorded FTP control messages…');
  events = Array.isArray(transcript) ? transcript.filter(x => x && ['client','server'].includes(x.direction) && typeof x.message === 'string') : [];
  if (!events.length) { clearTimeline('The FTP client did not record a control exchange.'); return; }
  for(const id of ['play','next','reset']) $("#"+id).disabled=false;
  $('#timelineCount').textContent=`0 / ${events.length} messages`;
  $('#log').replaceChildren();
  const help=document.createElement('div'); help.className='empty'; help.textContent=`${events.length} real FTP messages recorded. Press Play or Step to inspect them.`;
  $('#log').appendChild(help);
  replay();
}
function showResult(result) {
  lastResult=result;
  const op=result.configuration.operation;
  const metrics=[
    ['Control / login',yes(result.control_ok)],
    ['Data connection',yes(result[`${op}_data_connected`])],
    [op.toUpperCase(),yes(result[`${op}_ok`])],
    ['Transfer throughput',metric(result[`${op}_throughput_mbps`],'Mbit/s')]
  ];
  $('#resultCards').replaceChildren(...metrics.map(([label,output]) => {
    const card=document.createElement('div'); card.className='resultcard';
    const small=document.createElement('small'); small.textContent=label;
    const strong=document.createElement('b'); strong.textContent=output;
    strong.className=output.startsWith('✓')?'good':output.startsWith('✕')?'bad':'';
    card.append(small,strong);return card;
  }));
  const complete=result[`${op}_ok`]===true;
  const verdict=$('#verdict');
  verdict.className='verdict '+(complete?'good':'bad');
  verdict.textContent=complete ? `${result.configuration.nat} · ${result.configuration.mode.toUpperCase()} · ${op.toUpperCase()}: transfer completed successfully.` : `${result.configuration.nat} · ${result.configuration.mode.toUpperCase()} · ${op.toUpperCase()}: unsuccessful. ${result.error || 'Inspect the recorded FTP exchange for details.'}`;
  $('#response').textContent=JSON.stringify({
    configuration:result.configuration,
    control_setup_ms:result.control_setup_ms,
    data_connected:result[`${op}_data_connected`],
    operation_completed:result[`${op}_ok`],
    bytes:result[`${op}_bytes`],
    data_setup_ms:result[`${op}_data_setup_ms`],
    transfer_seconds:result[`${op}_transfer_s`],
    throughput_mbps:result[`${op}_throughput_mbps`],
    failure_stage:result.failure_stage,
    error:result.error
  },null,2);
  showCapture(result);
  loadTimeline(result.transcript);
}
async function refreshStatus() {
  try {
    const state=await api('/api/status');
    $('#statusText').textContent=state.ready?'Laboratory ready':(state.startup?.message||'Laboratory unavailable');
    $('#statusDot').classList.toggle('ok',state.ready);
    $('#topologyState').textContent=state.ready?'4 namespaces · FTP server ready':'Checking environment…';
    if(!running) $('#run').disabled=!state.ready;
  } catch {
    $('#statusText').textContent='Backend unavailable';
    $('#topologyState').textContent='Offline';
    $('#statusDot').classList.remove('ok');
    $('#run').disabled=true;
  }
}
async function run() {
  if(running) return;
  running=true; stopPlayback();
  $('#run').disabled=true;
  document.querySelectorAll('.segments button, #operation').forEach(el => { el.disabled = true; });
  $('#jobBadge').textContent='Running';
  $('#jobProgress').textContent='Submitting experiment…';
  $('#resultCards').replaceChildren();
  $('#response').textContent='Waiting for measured output…';
  $('#verdict').className='verdict neutral';
  $('#verdict').textContent='Executing a real FTP experiment. Results and playback will appear after it finishes.';
  clearTimeline('FTP traffic is being captured on the network interfaces…');
  clearCapture('A new capture is being recorded.');
  try {
    const job=await post('/api/experiment', {...config});
    let finished=false;
    for(let attempt=0;attempt<300;attempt++) {
      await delay(1000);
      const state=await api(`/api/jobs/${job.id}`);
      $('#jobProgress').textContent=state.step||'Experiment running…';
      if(state.status==='completed') {
        finished=true;
        $('#jobBadge').textContent='Completed';
        $('#jobProgress').textContent='Real experiment finished · control messages ready for playback';
        showResult(state.result);
        break;
      }
      if(state.status==='failed') {
        finished=true;
        $('#jobBadge').textContent='Error';
        $('#verdict').className='verdict bad';
        $('#verdict').textContent=state.error||'The backend did not complete the experiment.';
        $('#jobProgress').textContent='Execution error';
        clearCapture('No finished capture associated with this run.');
        break;
      }
    }
    if(!finished) $('#jobProgress').textContent='Experiment continues. Check the backend for its state.';
  } catch(e) {
    $('#jobBadge').textContent='Error';
    $('#verdict').className='verdict bad';
    $('#verdict').textContent=e.message;
    $('#jobProgress').textContent='Could not execute the experiment.';
  } finally {
    running=false;
    document.querySelectorAll('.segments button, #operation').forEach(el => { el.disabled = false; });
    await refreshStatus();
  }
}

document.querySelectorAll('.segments').forEach(group => group.addEventListener('click',event => {
  const button=event.target.closest('button[data-value]');
  if(!button || running) return;
  const field=group.dataset.field;
  config[field]=field==='loss'?Number(button.dataset.value):button.dataset.value;
  updateControls();
}));
$('#operation').addEventListener('change',event => {if(!running) config.operation=event.target.value;});
$('#run').addEventListener('click',run);
$('#play').addEventListener('click',()=>{
  if(playback!==null) stopPlayback(); else replay();
});
$('#next').addEventListener('click',()=>{stopPlayback();step();});
$('#reset').addEventListener('click',()=>{
  stopPlayback(); shown=-1; $('#log').replaceChildren();
  const hint=document.createElement('div');hint.className='empty';hint.textContent='Press Play or Step to replay the same recorded session.';$('#log').appendChild(hint);
  $('#timelineCount').textContent=`0 / ${events.length} messages`;
});
updateControls();
refreshStatus();
setInterval(refreshStatus,6000);
