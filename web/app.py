#!/usr/bin/env python3
"""Local-only Flask interface for FTP/NAT single-run demonstrations.

Run as root with `sudo .venv/bin/python -m web.app`. The server bootstraps
missing lab components, and each experiment exports a merged, real PCAPNG.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import uuid

from flask import Flask, abort, jsonify, render_template, request, send_file

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
jobs: dict[str, dict] = {}
lock = threading.Lock()
active_id: str | None = None
startup = {"phase": "pending", "message": "Laboratory startup not yet run"}


def command(argv, timeout=90, json_output=False):
    """Execute a fixed command vector, with no shell expansion."""
    args = [str(item) for item in argv]
    try:
        proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Could not execute {args[0]}: {exc}") from exc
    output, error = (proc.stdout or "")[-75000:], (proc.stderr or "")[-12000:]
    if json_output:
        if not output.strip():
            raise RuntimeError(f"FTP client returned no JSON (exit {proc.returncode}): {error}")
        try:
            result = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"FTP client returned invalid JSON: {output[-2000:]} {error}") from exc
        result["process_returncode"] = proc.returncode
        result["stderr"] = error
        return result
    if proc.returncode:
        raise RuntimeError(f"Command failed (exit {proc.returncode}): {' '.join(args)}\n{error}\n{output}")
    return output


def namespace_exists():
    try:
        listing = command(["ip", "netns", "list"], 5)
    except RuntimeError:
        return False
    return all(re.search(r"^" + re.escape(ns) + r"(?:\s|$)", listing, re.M)
               for ns in ("ftp-client", "ftp-server", "r1", "r2"))


def topology_healthy():
    if not namespace_exists():
        return False
    for ns, iface in (("ftp-client", "eth0"), ("r1", "eth-in"),
                      ("r1", "eth-out"), ("r2", "eth-in"),
                      ("r2", "eth-srv"), ("ftp-server", "eth0")):
        try:
            command(["ip", "netns", "exec", ns, "ip", "link", "show", iface], 5)
        except RuntimeError:
            return False
    return True


def server_listening():
    if not namespace_exists():
        return False
    try:
        output = command(["ip", "netns", "exec", "ftp-server", "ss", "-ltn"], 5)
        return any(re.search(r"(?:\S+:)?21\s", line) for line in output.splitlines())
    except RuntimeError:
        return False


def bootstrap():
    """Initialize missing components, without recreating a healthy topology.

    Must run before accepting HTTP requests. Intentionally does not run at
    module import so offline tests can import the Flask app without root.
    """
    global startup
    startup = {"phase": "initializing", "message": "Checking network namespaces"}
    try:
        if os.geteuid() != 0:
            raise RuntimeError("Start with sudo; configuring namespaces requires root privileges")
        for executable in ("ip", "dumpcap", "mergecap", "nft", "tc", "vsftpd"):
            if shutil.which(executable) is None:
                raise RuntimeError(f"Required command not installed: {executable}; see README")
        if not topology_healthy():
            startup["message"] = "Building missing Linux namespace topology"
            command([SCRIPTS / "setup_topology.sh"], 90)
        if not server_listening():
            startup["message"] = "Starting the FTP server in ftp-server"
            command([SCRIPTS / "setup_server.sh"], 90)
        if not server_listening():
            raise RuntimeError("FTP server is not listening on TCP port 21")
        # Initialize N1 only on a fresh topology or when no state has been set;
        # a healthy existing lab retains its current NAT configuration.
        nat_state = Path("/tmp/cn-nat-state")
        if not nat_state.is_file() or nat_state.read_text().strip() not in NATS:
            startup["message"] = "Applying default N1 NAT and 0% loss"
            command([SCRIPTS / "nat.sh", "N1"], 20)
            command([SCRIPTS / "impair.sh", "0"], 20)
        startup = {"phase": "ready", "message": "Network and FTP server ready"}
    except Exception as exc:
        startup = {"phase": "failed", "message": str(exc)}
    return startup["phase"] == "ready"


def capture_bundle(jobid, tag):
    """Merge the three capture interfaces into one multi-interface PCAPNG."""
    folder = RESULTS / "pcap"
    files = [folder / f"{tag}__{name}.pcapng"
             for name in ("r1-inside", "r1-outside", "r2-server")]
    missing = [p.name for p in files if not p.is_file() or p.stat().st_size < 60]
    if missing:
        raise RuntimeError("Capture missing or empty: " + ", ".join(missing))
    merged_dir = RESULTS / "web_runs" / "captures"
    merged_dir.mkdir(parents=True, exist_ok=True)
    final = merged_dir / (jobid + ".pcapng")
    # mergecap preserves per-interface metadata and timestamp ordering.
    command(["mergecap", "-w", final, *files], timeout=45)
    if not final.is_file() or final.stat().st_size < 100:
        raise RuntimeError("Merged PCAPNG was not created")
    return final


def run_one(spec, job):
    nat, mode, loss, op = (spec[k] for k in ("nat", "mode", "loss", "operation"))
    job["step"] = "Applying NAT and controlled packet loss"
    command([SCRIPTS / "nat.sh", nat], 20)
    command([SCRIPTS / "impair.sh", str(loss)], 20)
    tag = "web_" + job["id"].replace("-", "")
    capture_started = False
    result = None
    capture_error = None
    try:
        job["step"] = "Starting three real packet captures"
        command([SCRIPTS / "capture.sh", "start", tag], 20)
        capture_started = True
        job["step"] = f"Running {mode.upper()} FTP {op.upper()}"
        result = command(["ip", "netns", "exec", "ftp-client", "python3", CLIENT,
                          "--mode", mode, "--ops", op,
                          "--hold", "0.8", "--timeout", "12", "--op-timeout", "120"],
                         timeout=220, json_output=True)
    finally:
        if capture_started:
            job["step"] = "Closing and saving packet captures"
            try:
                command([SCRIPTS / "capture.sh", "stop"], 25)
            except Exception as exc:
                capture_error = str(exc)
    if result is None:
        raise RuntimeError("FTP execution did not return a result")
    result["configuration"] = spec
    job["step"] = "Creating a single Wireshark capture"
    try:
        bundle = capture_bundle(job["id"], tag)
        job["capture_path"] = str(bundle)
        result["capture_available"] = True
        result["capture_url"] = f"/api/jobs/{job['id']}/capture"
        result["capture_filename"] = f"ftp_{nat}_{mode}_{op}_{loss}pct_{job['id'][:8]}.pcapng"
    except Exception as exc:
        result["capture_available"] = False
        result["capture_error"] = str(exc)
    if capture_error:
        result["capture_error"] = (result.get("capture_error", "") + " " + capture_error).strip()
    return result


def start_job(spec):
    global active_id
    with lock:
        if active_id is not None:
            return None
        jobid = str(uuid.uuid4())
        job = {"id": jobid, "kind": "experiment", "status": "running",
               "step": "Queued", "started": dt.datetime.now(dt.timezone.utc).isoformat(),
               "result": None, "error": None}
        jobs[jobid] = job
        active_id = jobid

    def runner():
        global active_id
        try:
            job["result"] = run_one(spec, job)
            job["status"] = "completed"
        except Exception as exc:
            job["error"] = str(exc)
            job["status"] = "failed"
        finally:
            job["finished"] = dt.datetime.now(dt.timezone.utc).isoformat()
            with lock:
                active_id = None
            folder = RESULTS / "web_runs"
            folder.mkdir(parents=True, exist_ok=True)
            try:
                # The private filesystem path is never exposed in API JSON.
                record = {k: v for k, v in job.items() if k != "capture_path"}
                (folder / (jobid + ".json")).write_text(json.dumps(record, indent=2))
            except OSError:
                pass
    threading.Thread(target=runner, daemon=True).start()
    return job


def public_job(job):
    return {k: v for k, v in job.items() if k != "capture_path"}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    natfile = Path("/tmp/cn-nat-state")
    try:
        nat = natfile.read_text().strip() if natfile.is_file() else "unknown"
    except OSError:
        nat = "unknown"
    return jsonify({"ready": startup["phase"] == "ready" and topology_healthy() and server_listening(),
                    "startup": startup, "nat": nat, "active_job": active_id,
                    "server_listening": server_listening()})


@app.post("/api/experiment")
def experiment():
    if os.geteuid() != 0:
        return jsonify({"error": "Controller needs root privileges; see README"}), 503
    if startup["phase"] != "ready":
        return jsonify({"error": "Laboratory not ready: " + startup["message"]}), 503
    body = request.get_json(silent=True) or {}
    if (body.get("nat") not in NATS or body.get("mode") not in MODES
            or body.get("operation") not in OPERATIONS
            or type(body.get("loss")) is not int or body["loss"] not in LOSSES):
        return jsonify({"error": "Invalid NAT, FTP mode, operation, or packet loss value"}), 400
    if not topology_healthy() or not server_listening():
        return jsonify({"error": "Laboratory components stopped. Restart the Flask application to initialize them."}), 503
    job = start_job({k: body[k] for k in ("nat", "mode", "operation", "loss")})
    return (jsonify(public_job(job)), 202) if job else (jsonify({"error": "An experiment is already running"}), 409)


@app.get("/api/jobs/<jobid>")
def job_status(jobid):
    if not re.fullmatch(r"[0-9a-f-]{36}", jobid) or jobid not in jobs:
        abort(404)
    return jsonify(public_job(jobs[jobid]))


@app.get("/api/jobs/<jobid>/capture")
def download_capture(jobid):
    """Only finished captures from jobs in the current server session."""
    if not re.fullmatch(r"[0-9a-f-]{36}", jobid) or jobid not in jobs:
        abort(404)
    job = jobs[jobid]
    if job["status"] != "completed" or not job.get("result", {}).get("capture_available"):
        abort(404)
    path = job.get("capture_path")
    if not path or not Path(path).is_file():
        abort(404)
    return send_file(path, mimetype="application/octet-stream", as_attachment=True,
                     download_name=job["result"]["capture_filename"])


if __name__ == "__main__":
    if not bootstrap():
        raise SystemExit("FTP/NAT startup failed: " + startup["message"])
    # Privileged lab controller: never expose to a network interface.
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False, threaded=True)
