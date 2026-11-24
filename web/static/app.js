const $ = selector => document.querySelector(selector);
let running = false;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let payload;
  try { payload = await response.json(); }
  catch { throw new Error('The server did not return JSON.'); }
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}
function post(path, body) {
  return api(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
}
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const value = x => x === undefined || x === null ? '—' : String(x);
const metric = (x, suffix) => typeof x === 'number' ? `${x.toFixed(2)} ${suffix}` : '—';
const yes = x => x === true ? '✓ Success' : '✕ Failed';

function clearCapture(note = 'Available after a completed experiment.') {
  const download = $('#downloadCapture');
  download.removeAttribute('href');
  download.classList.add('disabled');
  download.setAttribute('aria-disabled', 'true');
  $('#captureNote').textContent = note;
}
function captureLink(result) {
  if (result.capture_available && result.capture_url) {
    const download = $('#downloadCapture');
    download.href = result.capture_url;
    download.classList.remove('disabled');
    download.removeAttribute('aria-disabled');
    $('#captureNote').textContent = 'One multi-interface Wireshark file for this experiment. The next run will replace this link.';
  } else {
    clearCapture(`Capture unavailable: ${result.capture_error || 'No capture was produced.'}`);
  }
}
async function refreshStatus() {
  try {
    const state = await api('/api/status');
    $('#statNat').textContent = state.nat || '—';
    $('#statTopology').textContent = state.ready ? 'Ready' : 'Offline';
    $('#statServer').textContent = state.server_listening ? 'Listening :21' : 'Offline';
    $('#statJob').textContent = state.active_job ? 'Running' : 'Idle';
    $('#statusText').textContent = state.ready ? 'Laboratory ready' : state.startup.message;
    $('#statusDot').classList.toggle('ok', state.ready);
    if (!running) $('#run').disabled = !state.ready;
  } catch (e) {
    $('#statusText').textContent = 'Web backend unavailable';
    $('#run').disabled = true;
  }
}
function showResult(result) {
  const op = result.configuration.operation;
  const success = result[`${op}_ok`];
  const connected = result[`${op}_data_connected`];
  const metrics = [
    ['Control', yes(result.control_ok)],
    ['Data connection', yes(connected)],
    [op.toUpperCase(), yes(success)],
    ['Throughput', metric(result[`${op}_throughput_mbps`], 'Mbit/s')]
  ];
  $('#resultCards').replaceChildren(...metrics.map(([name, output]) => {
    const item = document.createElement('div');
    item.className = 'resultcard';
    const title = document.createElement('small'); title.textContent = name;
    const body = document.createElement('b'); body.textContent = output;
    body.className = output.startsWith('✓') ? 'good' : output.startsWith('✕') ? 'bad' : '';
    item.append(title, body);
    return item;
  }));
  $('#transcript').textContent = (result.transcript || [])
    .map(event => `${event.direction === 'client' ? 'CLIENT →' : 'SERVER ←'} ${event.message}`)
    .join('\n') || 'No FTP transcript returned.';
  $('#response').textContent = JSON.stringify({
    configuration: result.configuration,
    control_setup_ms: result.control_setup_ms,
    operation_ok: success,
    data_connected: connected,
    bytes: result[`${op}_bytes`],
    data_setup_ms: result[`${op}_data_setup_ms`],
    transfer_s: result[`${op}_transfer_s`],
    throughput_mbps: result[`${op}_throughput_mbps`],
    failure_stage: result.failure_stage,
    error: result.error
  }, null, 2);
  captureLink(result);
}
async function run() {
  if (running) return;
  running = true;
  $('#run').disabled = true;
  $('#jobBadge').textContent = 'Running';
  $('#resultCards').replaceChildren();
  $('#transcript').textContent = 'Executing the FTP client…';
  $('#response').textContent = 'Waiting for experimental result…';
  clearCapture('The previous run is no longer the current run. Capturing new packets…');
  try {
    const job = await post('/api/experiment', {
      nat: $('#nat').value, mode: $('#mode').value,
      operation: $('#operation').value, loss: Number($('#loss').value)
    });
    let finished = false;
    for (let attempt = 0; attempt < 300; attempt++) {
      await delay(1000);
      const state = await api(`/api/jobs/${job.id}`);
      $('#jobProgress').textContent = state.step || 'Running';
      if (state.status === 'completed') {
        finished = true;
        $('#jobBadge').textContent = 'Completed';
        $('#jobProgress').textContent = 'Experiment finished. Real capture available below if saved successfully.';
        showResult(state.result);
        break;
      }
      if (state.status === 'failed') {
        finished = true;
        $('#jobBadge').textContent = 'Failed';
        $('#jobProgress').textContent = state.error || 'Experiment failed';
        clearCapture('Capture unavailable because the experiment did not finish.');
        break;
      }
    }
    if (!finished) $('#jobProgress').textContent = 'Still running; refresh the page to check system status.';
  } catch (error) {
    $('#jobBadge').textContent = 'Error';
    $('#jobProgress').textContent = error.message;
  } finally {
    running = false;
    await refreshStatus();
  }
}
$('#run').addEventListener('click', run);
refreshStatus();
setInterval(refreshStatus, 6000);
