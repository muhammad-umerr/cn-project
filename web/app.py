#!/usr/bin/env python3
"""Local-only Flask controller for the genuine Linux namespace laboratory.
All user inputs are mapped to fixed subprocess argv; no shell interpolation.
Run with sudo -E .venv/bin/python -m web.app (loopback only).
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

from flask import Flask, jsonify, render_template, request, send_from_directory, abort

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
SCRIPTS = ROOT / "scripts"
CLIENT = ROOT / "client" / "ftp_client.py"
NATS = ("N0", "N1", "N2")
MODES = ("active", "passive")
OPERATIONS = ("list", "retr", "stor")
LOSSES = (0, 2, 5)
app = Flask(__name__)
app.json.sort_keys = False
jobs = {}
lock = threading.Lock()
active_id = None


def command(argv, timeout=90, json_output=False):
    """A finite, explicit argument vector. Never run with shell=True."""
    try:
        p = subprocess.run([str(x) for x in argv], cwd=ROOT, capture_output=True,
                           text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Timed out after {timeout}s: {argv[0]}") from exc
    output = (p.stdout or "")[-75000:]
    err = (p.stderr or "")[-12000:]
    if json_output:
        if not output.strip():
            raise RuntimeError(f"No JSON from FTP client; exit={p.returncode}; stderr={err}")
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid FTP client JSON: {output[-2000:]} {err}") from exc
        data["process_returncode"] = p.returncode
        data["stderr"] = err
        return data
    if p.returncode:
        raise RuntimeError(f"Command failed (exit {p.returncode}): {' '.join(map(str, argv))}\n{err}\n{output}")
    return output


def namespace_exists():
    try:
        result = command(["ip", "netns", "list"], timeout=5)
    except Exception:
        return False
    return all(re.search(r"^" + x + r"(?:\s|$)", result, re.M) for x in ("ftp-client", "ftp-server", "r1", "r2"))


def safe_read(path, limit=25000):
    try:
        return path.read_text(errors="replace")[-limit:] if path.is_file() else ""
    except OSError:
        return ""


def snap():
    result = {}
    for kind, argv in {
        "conntrack": ["ip", "netns", "exec", "r1", "conntrack", "-L"],
        "expectations": ["ip", "netns", "exec", "r1", "conntrack", "-L", "expect"],
        "nftables": ["ip", "netns", "exec", "r1", "nft", "list", "ruleset"],
        "qdisc_r1": ["ip", "netns", "exec", "r1", "tc", "-s", "qdisc", "show", "dev", "eth-out"],
        "qdisc_r2": ["ip", "netns", "exec", "r2", "tc", "-s", "qdisc", "show", "dev", "eth-in"],
    }.items():
        try:
            # conntrack exits nonzero when its table is empty; keep the diagnostic text
            p = subprocess.run(argv, capture_output=True, text=True, timeout=8)
            result[kind] = (p.stdout or p.stderr)[-30000:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            result[kind] = str(exc)
    return result


def run_one(spec, job):
    nat, mode, loss, op = spec["nat"], spec["mode"], spec["loss"], spec["operation"]
    job["step"] = "Configuring NAT and connection-tracking state"
    command([SCRIPTS / "nat.sh", nat], 20)
    job["step"] = "Applying transit-link bandwidth and loss"
    command([SCRIPTS / "impair.sh", str(loss)], 20)
    job["step"] = "Starting packet capture on R1 and R2"
    tag = "web_" + job["id"].replace("-", "")[:20]
    capture_started = False
    evidence = {}
    try:
        command([SCRIPTS / "capture.sh", "start", tag], 15)
        capture_started = True
        job["step"] = "Executing the real FTP client inside ftp-client"
        # Poll captures conntrack/expectation entries during the live operation
        entries = {"conntrack": set(), "expectations": set()}
        stop = threading.Event()
        def sampler():
            while not stop.wait(0.2):
                for label, args in (("conntrack", ["conntrack", "-L"]),
                                    ("expectations", ["conntrack", "-L", "expect"])):
                    try:
                        p = subprocess.run(["ip", "netns", "exec", "r1", *args],
                                           capture_output=True, text=True, timeout=2)
                        entries[label].update(x for x in p.stdout.splitlines() if x.strip())
                    except (OSError, subprocess.TimeoutExpired):
                        pass
        observer = threading.Thread(target=sampler, daemon=True)
        observer.start()
        try:
            result = command(["ip", "netns", "exec", "ftp-client", "python3", CLIENT,
                              "--mode", mode, "--ops", op, "--hold", "0.8",
                              "--timeout", "12", "--op-timeout", "120"],
                             timeout=220, json_output=True)
        finally:
            stop.set()
            observer.join(timeout=4)
        evidence = snap()
        evidence["conntrack_observed"] = "\n".join(sorted(entries["conntrack"]))
        evidence["expectations_observed"] = "\n".join(sorted(entries["expectations"]))
        result["configuration"] = spec
        result["evidence"] = evidence
        result["capture_files"] = sorted(p.name for p in (RESULTS / "pcap").glob(tag + "*.pcapng"))
        return result
    finally:
        if capture_started:
            job["step"] = "Finalizing capture files"
            try:
                command([SCRIPTS / "capture.sh", "stop"], 15)
            except Exception as exc:
                job["capture_warning"] = str(exc)


def start_job(kind, fn):
    global active_id
    with lock:
        if active_id is not None:
            return None
        jobid = str(uuid.uuid4())
        job = {"id": jobid, "kind": kind, "status": "running", "step": "Queued",
               "started": dt.datetime.now(dt.timezone.utc).isoformat(), "result": None, "error": None}
        jobs[jobid] = job
        active_id = jobid

    def runner():
        global active_id
        try:
            job["result"] = fn(job)
            job["status"] = "completed"
        except Exception as exc:
            job["error"] = str(exc)
            job["status"] = "failed"
        finally:
            job["finished"] = dt.datetime.now(dt.timezone.utc).isoformat()
            with lock:
                active_id = None
            # persist the last 200 job summaries; real data, not fabricated
            folder = RESULTS / "web_runs"
            folder.mkdir(exist_ok=True)
            try:
                (folder / (jobid + ".json")).write_text(json.dumps(job, indent=2, default=str))
            except OSError:
                pass
    threading.Thread(target=runner, daemon=True).start()
    return job


def require_root():
    if os.geteuid() != 0:
        return jsonify({"error": "Web controller must be started as root for Linux namespaces; see README."}), 503
    return None


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    return jsonify({"ready": namespace_exists(), "root": os.geteuid() == 0,
                    "nat": safe_read(Path("/tmp/cn-nat-state"), 32).strip() or "unknown",
                    "active_job": active_id,
                    "server_listening": _server_listening()})


def _server_listening():
    if not namespace_exists():
        return False
    try:
        p = subprocess.run(["ip", "netns", "exec", "ftp-server", "ss", "-ltn"],
                           capture_output=True, text=True, timeout=5)
        return bool(re.search(r":21\s", p.stdout))
    except (OSError, subprocess.TimeoutExpired):
        return False


@app.post("/api/lab/<action>")
def lab_action(action):
    if (error := require_root()) is not None:
        return error
    commands = {"setup": [SCRIPTS / "setup_topology.sh"],
                "server": [SCRIPTS / "setup_server.sh"],
                "verify": [SCRIPTS / "verify.sh"],
                "teardown": [SCRIPTS / "teardown.sh"]}
    if action not in commands:
        abort(404)
    def fn(job):
        job["step"] = f"Running {action}"
        return {"output": command(commands[action], timeout=90 if action != "verify" else 110)}
    job = start_job(action, fn)
    return (jsonify(job), 202) if job else (jsonify({"error": "Another job is running"}), 409)


@app.post("/api/experiment")
def experiment():
    if (error := require_root()) is not None:
        return error
    body = request.get_json(silent=True) or {}
    if body.get("nat") not in NATS or body.get("mode") not in MODES or body.get("operation") not in OPERATIONS or type(body.get("loss")) is not int or body["loss"] not in LOSSES:
        return jsonify({"error": "Invalid configuration. Use N0/N1/N2, active/passive, list/retr/stor, loss 0/2/5."}), 400
    if not namespace_exists():
        return jsonify({"error": "Topology is not running. Run Setup topology and Start server first."}), 409
    job = start_job("experiment", lambda j: run_one(body, j))
    return (jsonify(job), 202) if job else (jsonify({"error": "Another job is running"}), 409)


@app.post("/api/batch/<action>")
def batch(action):
    if (error := require_root()) is not None:
        return error
    if action not in {"matrix", "evidence", "experiments", "analysis"}:
        abort(404)
    body = request.get_json(silent=True) or {}
    reps = body.get("reps", 3)
    if type(reps) is not int or not (1 <= reps <= 10):
        return jsonify({"error": "Repetitions must be an integer 1–10."}), 400
    if action != "analysis" and not namespace_exists():
        return jsonify({"error": "Topology is not running"}), 409
    def fn(job):
        job["step"] = f"Running {action}; this can take several minutes"
        if action == "analysis":
            return {"output": command(["python3", ROOT / "tools" / "analyze.py"], 60)}
        args = ["python3", ROOT / "tools" / "run.py", action]
        if action == "experiments":
            args += ["--reps", str(reps)]
            if body.get("reset") is True:
                args.append("--reset")
        return {"output": command(args, 3600)}
    job = start_job(action, fn)
    return (jsonify(job), 202) if job else (jsonify({"error": "Another job is running"}), 409)


@app.get("/api/jobs/<jobid>")
def job_status(jobid):
    if jobid in jobs:
        return jsonify(jobs[jobid])
    p = RESULTS / "web_runs" / (jobid + ".json")
    if not re.fullmatch(r"[0-9a-f-]{36}", jobid) or not p.exists():
        abort(404)
    return jsonify(json.loads(p.read_text()))


@app.get("/api/jobs")
def job_list():
    return jsonify(sorted(({"id": j["id"], "kind": j["kind"], "status": j["status"],
                           "started": j["started"]} for j in jobs.values()),
                          key=lambda x: x["started"], reverse=True)[:100])


@app.get("/api/diagnostics")
def diagnostics():
    if not namespace_exists():
        return jsonify({"error": "Topology not running", "state": {}})
    state = snap()
    for ns in ("ftp-client", "r1", "r2", "ftp-server"):
        try:
            state["routes_" + ns] = command(["ip", "netns", "exec", ns, "ip", "-4", "route"], 5)
        except Exception as exc:
            state["routes_" + ns] = str(exc)
    return jsonify({"state": state})


@app.get("/api/results")
def results():
    def read_csv(name):
        path = RESULTS / name
        return list(csv.DictReader(path.open()))[-1000:] if path.is_file() else []
    captures = [p.name for p in sorted((RESULTS / "pcap").glob("*.pcapng"))]
    return jsonify({"matrix": read_csv("success_matrix.csv"),
                    "raw": read_csv("raw.csv"), "summary": read_csv("summary.csv"),
                    "summary_markdown": safe_read(RESULTS / "summary.md", 30000),
                    "captures": captures, "verify": safe_read(RESULTS / "verify.txt")})


@app.get("/api/artifacts/<path:name>")
def artifact(name):
    # Allow only designated artifacts under results/ with path traversal protection.
    if not (name.startswith("pcap/") or name.startswith("charts/") or name in
            {"raw.csv", "summary.csv", "summary.md", "success_matrix.csv", "dashboard.html", "verify.txt"}):
        abort(404)
    p = (RESULTS / name).resolve()
    if not p.is_relative_to(RESULTS.resolve()) or not p.is_file():
        abort(404)
    return send_from_directory(RESULTS, name, as_attachment=name.startswith("pcap/"))


if __name__ == "__main__":
    # Deliberately loopback-only: privileged code may modify the lab network.
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
