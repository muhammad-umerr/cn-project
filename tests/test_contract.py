"""Offline API and experiment contract tests. These do not run real networking."""
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

from web import app as app_module


def client():
    app_module.app.testing = True
    return app_module.app.test_client()


def test_homepage_is_live_controller():
    r = client().get('/')
    assert r.status_code == 200
    assert b'Run live experiment' in r.data
    assert b'FTP Through NAT' in r.data


def test_invalid_experiment_rejected_even_when_root():
    with patch.object(app_module, 'require_root', return_value=None):
        r = client().post('/api/experiment', json={
            'nat': 'N9', 'mode': 'active', 'operation': 'retr', 'loss': 0})
    assert r.status_code == 400


def test_invalid_loss_type_rejected():
    with patch.object(app_module, 'require_root', return_value=None):
        r = client().post('/api/experiment', json={
            'nat': 'N1', 'mode': 'active', 'operation': 'retr', 'loss': '2'})
    assert r.status_code == 400


def test_unknown_action_rejected():
    with patch.object(app_module, 'require_root', return_value=None):
        assert client().post('/api/lab/arbitrary').status_code == 404


def test_artifact_path_not_exposed():
    assert client().get('/api/artifacts/../README.md').status_code == 404
    assert client().get('/api/artifacts/foo.txt').status_code == 404


def test_no_measured_results_does_not_invent_data():
    with patch.object(app_module, 'RESULTS', Path('/tmp/definitely-no-network-results-838229')):
        body = client().get('/api/results').get_json()
    assert body['matrix'] == []
    assert body['raw'] == []
    assert body['summary'] == []


def test_run_client_mock_contract():
    completed = subprocess.CompletedProcess(args=['client'], returncode=0,
        stdout=json.dumps({'control_ok': True, 'retr_data_connected': True, 'retr_ok': True}), stderr='')
    with patch('web.app.subprocess.run', return_value=completed) as run:
        got = app_module.command(['ip', 'netns', 'exec', 'ftp-client', 'python3', 'client/ftp_client.py'], json_output=True)
    assert got['retr_ok'] is True
    assert run.call_args.kwargs['capture_output'] is True
    assert run.call_args.kwargs['check'] is False
    assert run.call_args.kwargs.get('shell') is None
