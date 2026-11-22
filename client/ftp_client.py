#!/usr/bin/env python3
"""Raw-socket FTP client. Issues PASV/PORT by hand so every step is visible and timed separately.

Run inside the client namespace:  ip netns exec ftp-client python3 client/ftp_client.py --mode passive --ops list,retr
Prints one JSON line (the result) on stdout; --verbose prints the FTP dialogue on stderr.
Timing uses time.monotonic():
  control_setup_ms : start of TCP connect to :21  ->  230 reply
  data_setup_ms    : data command (LIST/RETR/STOR) sent -> 150 reply
  transfer_s       : RETR/STOR sent -> 226 reply   (throughput = size / transfer_s)
"""
import argparse, hashlib, json, os, re, socket, sys, time


class Ctl:
    def __init__(self, sock, verbose):
        self.s, self.buf, self.v, self.events = sock, b"", verbose, []

    def _p(self, d, t):
        self.events.append({"direction": "server" if d == "<" else "client", "message": t})
        if self.v:
            print(f"  {d} {t}", file=sys.stderr, flush=True)

    def _line(self, deadline):
        while b"\n" not in self.buf:
            rem = deadline - time.monotonic()
            if rem <= 0:
                raise socket.timeout("timed out waiting for FTP reply")
            self.s.settimeout(rem)
            d = self.s.recv(4096)
            if not d:
                raise ConnectionError("control connection closed")
            self.buf += d
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode(errors="replace").rstrip("\r")

    def reply(self, timeout):
        dl = time.monotonic() + timeout
        line = self._line(dl); self._p("<", line)
        code = line[:3]
        if line[3:4] == "-":
            while True:
                l = self._line(dl); self._p("<", l)
                if l[:3] == code and l[3:4] == " ":
                    line = l; break
        return int(code), line

    def send(self, cmd):
        self._p(">", "PASS ********" if cmd.startswith("PASS") else cmd)
        self.s.sendall((cmd + "\r\n").encode())


def data_op(ctl, a, cmd, payload=None):
    r = {"ok": False, "stage": None, "error": None, "data_setup_ms": None, "transfer_s": None,
         "bytes": 0, "throughput_mbps": None, "data_conn_ms": None, "data_connected": False, "sha256": None}
    ds = ls = None
    try:
        if a.mode == "passive":
            ctl.send("PASV"); code, line = ctl.reply(a.timeout)
            if code != 227:
                r.update(stage="pasv", error=line); return r
            n = list(map(int, re.search(r"(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)", line).groups()))
            ip, port = ".".join(map(str, n[:4])), n[4] * 256 + n[5]
            ds = socket.socket(); ds.settimeout(a.timeout)
            t = time.monotonic()
            try:
                ds.connect((ip, port))
            except OSError as e:
                r.update(stage="data_connect", error=f"connect {ip}:{port}: {e}"); return r
            r["data_conn_ms"] = (time.monotonic() - t) * 1000
            r["data_connected"] = True
        else:
            ls = socket.socket(); ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            ls.bind((a.client_ip, 0)); ls.listen(1); port = ls.getsockname()[1]
            h = a.client_ip.split(".")
            ctl.send(f"PORT {','.join(h)},{port // 256},{port % 256}")
            code, line = ctl.reply(a.timeout)
            if code != 200:
                r.update(stage="port", error=line); return r
        t_cmd = time.monotonic()
        ctl.send(cmd)
        try:
            code, line = ctl.reply(a.timeout + 15)
        except socket.timeout:
            r.update(stage="data_connection", error="no 150 reply (timeout)"); return r
        if code not in (125, 150):
            r.update(stage="data_connection", error=line); return r
        r["data_setup_ms"] = (time.monotonic() - t_cmd) * 1000
        if a.mode == "active":
            ls.settimeout(a.timeout)
            try:
                ds, _ = ls.accept()
                r["data_connected"] = True
            except OSError as e:
                r.update(stage="data_accept", error=str(e)); return r
        if a.hold:
            time.sleep(a.hold)
        deadline = time.monotonic() + a.op_timeout
        ds.settimeout(a.timeout)
        if payload is None:
            digest = hashlib.sha256()
            total = 0
            while True:
                if time.monotonic() > deadline:
                    r.update(stage="transfer", error="op timeout"); return r
                chunk = ds.recv(65536)
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
        else:
            ds.sendall(payload); total = len(payload); ds.close(); ds = None
            digest = hashlib.sha256(payload)
        code, line = ctl.reply(a.timeout + 30)
        t_end = time.monotonic()
        if code != 226:
            r.update(stage="transfer", error=line); return r
        r.update(ok=True, bytes=total, transfer_s=t_end - t_cmd, sha256=digest.hexdigest())
        if cmd.startswith(("RETR", "STOR")):
            r["throughput_mbps"] = total * 8 / (t_end - t_cmd) / 1e6
        return r
    except (OSError, ConnectionError) as e:
        r.update(stage=r["stage"] or "transfer", error=str(e)); return r
    finally:
        for s in (ds, ls):
            if s:
                try: s.close()
                except OSError: pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["passive", "active"], default="passive")
    p.add_argument("--ops", default="retr", help="comma list of list,retr,stor ('' = login only)")
    p.add_argument("--host", default="172.16.20.10"); p.add_argument("--client-ip", default="192.168.10.2")
    p.add_argument("--user", default="ftpuser"); p.add_argument("--password", default="ftppass")
    p.add_argument("--file", default="10MB.bin"); p.add_argument("--size-mb", type=float, default=10)
    p.add_argument("--timeout", type=float, default=20); p.add_argument("--op-timeout", type=float, default=300)
    p.add_argument("--hold", type=float, default=0, help="pause after 150 so conntrack can be inspected")
    p.add_argument("--verbose", action="store_true"); p.add_argument("--pretty", action="store_true")
    a = p.parse_args()
    out = {"mode": a.mode, "control_ok": False, "control_setup_ms": None, "failure_stage": None, "error": None}
    t0 = time.monotonic()
    try:
        s = socket.create_connection((a.host, 21), timeout=a.timeout)
        ctl = Ctl(s, a.verbose)
        code, _ = ctl.reply(a.timeout)
        ctl.send(f"USER {a.user}"); ctl.reply(a.timeout)
        ctl.send(f"PASS {a.password}"); code, line = ctl.reply(a.timeout)
        if code != 230:
            raise RuntimeError(line)
        out.update(control_ok=True, control_setup_ms=(time.monotonic() - t0) * 1000)
    except (OSError, RuntimeError, ConnectionError) as e:
        out.update(failure_stage="control", error=str(e)); print(json.dumps(out)); return
    out["transcript"] = ctl.events
    ops = [o for o in a.ops.split(",") if o]
    for op in ops:
        if op == "list":
            r = data_op(ctl, a, "LIST")
        elif op == "retr":
            r = data_op(ctl, a, f"RETR {a.file}")
        elif op == "stor":
            name = f"upload_{os.getpid()}.bin"
            r = data_op(ctl, a, f"STOR {name}", payload=os.urandom(int(a.size_mb * 1024 * 1024)))
            try:
                ctl.send(f"DELE {name}"); ctl.reply(a.timeout)
            except (OSError, ConnectionError):
                pass
        else:
            continue
        for k, v in r.items():
            out[f"{op}_{k}"] = v
        if not r["ok"] and out["failure_stage"] is None:
            out["failure_stage"], out["error"] = f"{op}:{r['stage']}", r["error"]
        if not r["ok"] and str(r["error"]).startswith("no 150"):
            try:  # resync the control channel after a failed data command
                ctl.reply(3)
            except (OSError, ConnectionError):
                pass
    try:
        ctl.send("QUIT"); ctl.reply(3); s.close()
    except (OSError, ConnectionError):
        pass
    out["transcript"] = ctl.events
    print(json.dumps(out, indent=2 if a.pretty else None))


if __name__ == "__main__":
    main()
