#!/usr/bin/env python3
"""Experiment driver. Run as root after setup_topology.sh, setup_server.sh.
  sudo python3 tools/run.py matrix        Groups A+B: success matrix + conntrack snapshots + nft rulesets
  sudo python3 tools/run.py experiments   Group C: loss 0/2/5 %, every mode x NAT, N repeats  -> results/raw.csv
  sudo python3 tools/run.py evidence      Saves .pcapng captures for each key exchange
  sudo python3 tools/run.py all
"""
import argparse, csv, json, os, pathlib, re, subprocess, sys, threading, time, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
RES, SCR, CLIENT = ROOT / "results", ROOT / "scripts", ROOT / "client" / "ftp_client.py"
NATS, MODES, LOSSES = ["N0", "N1", "N2"], ["passive", "active"], [0, 2, 5]
RAW_COLS = ["timestamp", "nat", "mode", "loss", "rep", "size_mb", "control_ok", "control_setup_ms",
            "retr_ok", "retr_data_connected", "retr_sha256", "retr_data_setup_ms", "retr_transfer_s", "retr_throughput_mbps", "failure_stage", "error"]


def sh(cmd):
    return subprocess.run(cmd, text=True, capture_output=True)


def set_nat(n):
    subprocess.run([str(SCR / "nat.sh"), n], check=True, stdout=subprocess.DEVNULL)


def set_loss(l):
    subprocess.run([str(SCR / "impair.sh"), str(l)], check=True, stdout=subprocess.DEVNULL)


def r1(*cmd):
    return sh(["ip", "netns", "exec", "r1", *cmd]).stdout


def norm(line):  # strip fields that change every poll so snapshots deduplicate
    line = re.sub(r"^(\w+\s+\d+)\s+\d+\s+", r"\1 ", line)
    return re.sub(r"\s*(packets|bytes)=\d+", "", line).strip()


class Poller(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True); self.lines, self.stop = {}, False

    def run(self):
        while not self.stop:
            for kind, cmd in (("CONNTRACK", ["conntrack", "-L"]), ("EXPECT", ["conntrack", "-L", "expect"])):
                for l in r1(*cmd).splitlines():
                    if l.strip():
                        self.lines.setdefault(f"[{kind}] {norm(l)}", None)
            time.sleep(0.4)

    def finish(self):
        self.stop = True; self.join(2); return "\n".join(self.lines)


def run_client(mode, ops, size_mb, hold=0):
    cmd = ["ip", "netns", "exec", "ftp-client", "python3", str(CLIENT), "--mode", mode, "--ops", ops,
           "--size-mb", str(size_mb), "--hold", str(hold)]
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=1800)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"control_ok": False, "failure_stage": "client_crash", "error": (p.stderr or "no output")[-200:]}


def yn(v):
    return "yes" if v else "no"


def matrix(a):
    set_loss(0); rows = []
    (RES / "conntrack").mkdir(exist_ok=True); (RES / "nft").mkdir(exist_ok=True)
    for nat in NATS:
        set_nat(nat)
        (RES / "nft" / f"{nat}.txt").write_text(r1("nft", "list", "ruleset") or "(empty ruleset: routing only)")
        for mode in MODES:
            set_nat(nat); poll = Poller(); poll.start()
            res = run_client(mode, "list,retr,stor", a.size_mb, hold=2)
            (RES / "conntrack" / f"{nat}_{mode}.txt").write_text(poll.finish() or "(no entries seen)")
            row = {"nat": nat, "mode": mode, "control_ok": yn(res.get("control_ok")),
                   "list_data_conn": yn(res.get("list_data_connected")), "list_ok": yn(res.get("list_ok")),
                   "retr_ok": yn(res.get("retr_ok")), "stor_ok": yn(res.get("stor_ok")),
                   "failure_stage": res.get("failure_stage") or "", "error": res.get("error") or ""}
            rows.append(row); print(row)
    with open(RES / "success_matrix.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print("saved results/success_matrix.csv and results/conntrack/*.txt")


def experiments(a):
    if a.reset and (RES / "raw.csv").exists():
        (RES / "raw.csv").unlink()
    new = not (RES / "raw.csv").exists()
    f = open(RES / "raw.csv", "a", newline=""); w = csv.DictWriter(f, fieldnames=RAW_COLS)
    if new:
        w.writeheader()
    total = len(LOSSES) * len(NATS) * len(MODES) * a.reps; n = 0
    for loss in LOSSES:
        set_loss(loss)
        for nat in NATS:
            for mode in MODES:
                for rep in range(1, a.reps + 1):
                    set_nat(nat)  # also flushes conntrack: fresh NAT state each run
                    time.sleep(0.5)
                    res = run_client(mode, "retr", a.size_mb); n += 1
                    row = {"timestamp": datetime.datetime.now().isoformat(timespec="seconds"), "nat": nat, "mode": mode,
                           "loss": loss, "rep": rep, "size_mb": a.size_mb}
                    for k in RAW_COLS[6:]:
                        row[k] = res.get(k, "")
                    w.writerow(row); f.flush()
                    print(f"[{n}/{total}] loss={loss}% {nat} {mode} #{rep}: retr_ok={res.get('retr_ok')} "
                          f"thr={res.get('retr_throughput_mbps')} stage={res.get('failure_stage')}")
    set_loss(0)


SCENARIOS = [("01_control_handshake_login", "N1", "passive", ""),
             ("02_passive_pasv_N1", "N1", "passive", "list,retr"),
             ("03_active_port_N1_data_fails", "N1", "active", "list"),
             ("04_active_port_N2_helper", "N2", "active", "list,retr"),
             ("05_passive_no_nat_N0", "N0", "passive", "list,retr"),
             ("06_active_no_nat_N0", "N0", "active", "list,retr")]


def evidence(a):
    set_loss(0)
    for tag, nat, mode, ops in SCENARIOS:
        set_nat(nat); time.sleep(0.5)
        subprocess.run([str(SCR / "capture.sh"), "start", tag], check=True)
        poll = Poller(); poll.start()
        res = run_client(mode, ops, a.size_mb, hold=1.5)
        time.sleep(1); subprocess.run([str(SCR / "capture.sh"), "stop"])
        (RES / "conntrack" / f"evidence_{tag}.txt").write_text(poll.finish() or "(no entries seen)")
        print(tag, "->", res.get("failure_stage") or "ok")
    print("pcapng files are in results/pcap/ (open them in Wireshark)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["matrix", "experiments", "evidence", "all"])
    p.add_argument("--reset", action="store_true", help="replace existing raw.csv for a fresh campaign"); p.add_argument("--reps", type=int, default=3); p.add_argument("--size-mb", type=float, default=10)
    a = p.parse_args()
    if os.geteuid() != 0:
        sys.exit("run with sudo")
    if not (sh(["ip", "netns", "list"]).stdout.count("r1")):
        sys.exit("topology missing: run scripts/setup_topology.sh and scripts/setup_server.sh first")
    for name, fn in (("matrix", matrix), ("evidence", evidence), ("experiments", experiments)):
        if a.cmd in (name, "all"):
            print(f"== {name}"); fn(a)
    set_nat("N1")


if __name__ == "__main__":
    main()
