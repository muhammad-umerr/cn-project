"""Flask contracts; no namespace operations are performed by these tests."""
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

from web import app as module


def client():
    module.app.testing = True
    return module.app.test_client()


def test_single_page_has_only_run_and_download_controls():
    page = client().get('/')
    assert page.status_code == 200
    assert b'Run live FTP experiment' in page.data
    assert b'Download current run PCAPNG' in page.data
    assert b'Build success matrix' not in page.data
    assert b'Tear down' not in page.data


def test_invalid_experiment_rejected():
    with patch.object(module.os, 'geteuid', return_value=0), patch.object(module, 'startup', {'phase':'ready','message':'Ready'}):
        response = client().post('/api/experiment', json={'nat':'N9','mode':'active','operation':'retr','loss':0})
    assert response.status_code == 400


def test_invalid_loss_type_rejected():
    with patch.object(module.os, 'geteuid', return_value=0), patch.object(module, 'startup', {'phase':'ready','message':'Ready'}):
        response = client().post('/api/experiment', json={'nat':'N1','mode':'active','operation':'retr','loss':'2'})
    assert response.status_code == 400


def test_extra_web_endpoints_removed():
    for path in ('/api/results','/api/diagnostics','/api/artifacts/raw.csv','/api/jobs'):
        assert client().get(path).status_code == 404
    assert client().post('/api/lab/teardown').status_code == 404
    assert client().post('/api/batch/matrix').status_code == 404


def test_capture_only_current_process_job(tmp_path):
    assert client().get('/api/jobs/00000000-0000-0000-0000-000000000000/capture').status_code == 404
    jobid = '00000000-0000-0000-0000-000000000001'
    fake = tmp_path / 'run.pcapng'
    fake.write_bytes(b'0' * 120)
    with patch.dict(module.jobs, {jobid: {'status':'completed', 'capture_path':str(fake),
                                          'result': {'capture_available':True,'capture_filename':'run.pcapng'}}}):
        response = client().get(f'/api/jobs/{jobid}/capture')
        assert response.status_code == 200
        assert response.data == b'0' * 120


def test_bootstrap_keeps_healthy_network():
    with patch.object(module.os, 'geteuid', return_value=0), \
         patch.object(module, 'topology_healthy', return_value=True), \
         patch.object(module, 'server_listening', return_value=True), \
         patch.object(module, 'command') as run, \
         patch.object(Path, 'is_file', return_value=True), \
         patch.object(Path, 'read_text', return_value='N1'):
        assert module.bootstrap() is True
        run.assert_not_called()


def test_run_one_finishes_capture_before_merging():
    spec = {'nat':'N1','mode':'passive','operation':'retr','loss':0}
    job = {'id':'00000000-0000-0000-0000-000000000002','step':''}
    order = []
    def cmd(args, timeout=90, json_output=False):
        if any(str(x).endswith('capture.sh') for x in args):
            order.append(args[-2] if len(args) >= 3 else args[-1])
        return {'control_ok': True, 'retr_ok': True} if json_output else ''
    with patch.object(module, 'command', side_effect=cmd), \
         patch.object(module, 'capture_bundle', side_effect=lambda *_: (order.append('merge') or Path('/tmp/example.pcapng'))):
        result = module.run_one(spec, job)
    assert order == ['start', 'stop', 'merge']
    assert result['capture_available'] is True
    assert result['capture_url'].endswith('/capture')


def test_command_uses_argv_not_shell():
    completed = subprocess.CompletedProcess(args=['ftp'], returncode=0,
        stdout=json.dumps({'control_ok': True}), stderr='')
    with patch('web.app.subprocess.run', return_value=completed) as run:
        result = module.command(['ip','netns','exec','ftp-client','python3','client/ftp_client.py'],json_output=True)
    assert result['control_ok'] is True
    assert run.call_args.kwargs['check'] is False
    assert run.call_args.kwargs.get('shell') is None


def test_presentation_visuals_use_real_recorded_events():
    html = (module.ROOT / 'web' / 'templates' / 'index.html').read_text()
    js = (module.ROOT / 'web' / 'static' / 'app.js').read_text()
    assert 'id="topo"' in html
    assert 'id="log"' in html
    assert 'id="play"' in html and 'id="next"' in html and 'id="reset"' in html
    assert 'Download current run PCAPNG' in html
    assert 'loadTimeline(result.transcript)' in js
    assert 'showCapture(result)' in js
    assert 'Expected matrix' not in html
    assert 'Re-roll loss' not in html
    assert not (module.ROOT / 'presentation').exists()
