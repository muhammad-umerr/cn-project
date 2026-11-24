# FTP Through NAT — Live Demonstration

A streamlined, **real** FTP networking laboratory for CS3001 Computer Networks. The Flask web application has **one page**: the presentation simulator’s clearer SVG topology, segmented experiment selectors, step-by-step playback of **recorded** FTP control messages, measured results, and **one download link for the current run's Wireshark `.pcapng` file**.

There are no batch controls, diagnostics panel, result-history page, setup/teardown buttons, or previous-capture browser in the web application. The existing networking scripts and analysis utilities are retained for reproducibility and command-line use.

## Quick start (Ubuntu)

Run on an Ubuntu machine with Linux network namespaces and root access. The server is bound **only to 127.0.0.1** because it controls privileged networking operations.

```bash
sudo apt update
sudo apt install -y python3 python3-venv iproute2 nftables conntrack \
  vsftpd tcpdump wireshark-common tshark ethtool iperf3 traceroute

cd cn-project
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo .venv/bin/python -m web.app
```

If Ubuntu does not include `mergecap` in your installed Wireshark packages, install the `wireshark-common` package (and verify `command -v mergecap`). Likewise verify `command -v dumpcap`.

Open **http://127.0.0.1:5000**.

**No manual setup button is necessary.** On startup the controller checks for the four namespaces, their interfaces, and the FTP listener. It only runs `scripts/setup_topology.sh` when the network is missing or incomplete, and only runs `scripts/setup_server.sh` when TCP 21 isn't listening. On a new lab it initializes **N1 (masquerading)** and **0% loss**. If a healthy lab already exists, it preserves its current NAT setting. On setup errors, the server exits with a diagnostic message instead of displaying a fake ready state.

> Starting the lab creates network namespaces and veth pairs, modifies namespace firewall and routing state, creates a dedicated local `ftpuser` account, and writes `/etc/vsftpd-lab.conf` and `/srv/ftp-lab/10MB.bin`. Use a dedicated Ubuntu lab system. These are existing behaviors of `scripts/setup_server.sh`.

### Run a transfer

Choose:

- **NAT:** N0 (routing only), N1 (NAT masquerade), N2 (NAT + FTP helper)
- **FTP:** Active (`PORT`) or Passive (`PASV`)
- **Operation:** LIST (directory listing), RETR (download), STOR (upload)
- **Packet loss:** 0%, 2%, or 5%

Click **Run live FTP experiment**. Wait until the status displays Completed. It displays the real FTP outcome, control transcript, and connection/transfer metrics. The **Play / Step / Restart** buttons replay the FTP control dialogue that the client actually recorded. The moving marker is an explanatory illustration of message direction, **not a packet-by-packet reproduction or precise capture timing**; open the PCAPNG in Wireshark for packet timestamps, data connection SYNs, and NAT translations. Then click **Download current run PCAPNG** to save a single Wireshark file. Even if FTP fails at the protocol level, the capture is available if the recording itself succeeded; that failed negotiation is useful evidence.

You do **not** need to run an experiment matrix or packet collection batch from the web interface.

## Behind the web application

The browser sends `POST /api/experiment` to Flask with a fixed, validated JSON object:

```json
{"nat":"N2","mode":"active","operation":"retr","loss":0}
```

The backend runs the following operations in this order:

1. `scripts/nat.sh N2` applies routing/NAT/FTP-helper rules to R1 and flushes old connection-tracking state.
2. `scripts/impair.sh 0` applies `tc netem` packet loss and `tc tbf` bandwidth limiting on the R1–R2 transit link (both directions).
3. `scripts/capture.sh start web_<unique-id>` starts real `dumpcap` on **R1 inside**, **R1 outside**, and **R2 server-side** interfaces.
4. `ip netns exec ftp-client python3 client/ftp_client.py --mode active --ops retr ...` negotiates FTP over TCP with `vsftpd` running in the server namespace.
5. `scripts/capture.sh stop` closes and copies the three recorded `.pcapng` files into `results/pcap/`.
6. `mergecap` merges these three captures into **one multi-interface `.pcapng`** under `results/web_runs/captures/`. A packet's originating interface can be identified in Wireshark.
7. Flask returns the real JSON results and a *job-scoped* capture download URL. The browser enables its **single download link only after the merged file exists**.

The browser polls `GET /api/jobs/<id>` for progress. `GET /api/jobs/<id>/capture` returns that run's PCAPNG. It cannot browse previous application sessions or arbitrary files. Only one experiment can alter network state at a time; other submissions receive HTTP 409.

**No experiment outcome is simulated.** The topology playback visually illustrates the direction of *real, recorded* FTP control messages; it does not predict outcomes or replay individual TCP packets. All connection success/failure states and metrics come from the FTP client. The PCAPNG contains the authoritative packet-level record.

## Network topology and addresses

```text
ftp-client         r1 NAT/PAT                  r2             ftp-server
192.168.10.2 ── 192.168.10.1 | 10.0.12.1 ── 10.0.12.2 | 172.16.20.1 ── 172.16.20.10
             192.168.10.0/24        10.0.12.0/30              172.16.20.0/24
```

- FTP control: client → server TCP 21.
- Active data: server TCP 20 → client-advertised listening port.
- Passive data: client → server TCP 40000–40100.
- N0: no NAT; R2 has a return route to the client LAN.
- N1: R1 masquerades the client source address, without FTP helper. Active `PORT` negotiation may fail.
- N2: R1 masquerades and assigns FTP-aware connection tracking; Active `PORT` negotiation may be rewritten and the return data connection permitted.

## Inspecting the capture in Wireshark

After download, open the file in Wireshark. It includes packets from three interfaces, often showing the same packets at different points along the path. These duplicates are expected and allow comparison of NAT before/after:

| Wireshark display filter | Purpose |
|---|---|
| `tcp.port == 21` | FTP control handshake and login |
| `ftp.request.command == "PORT"` | Active FTP advertised data endpoint |
| `ftp.request.command == "PASV"` | Passive FTP request |
| `ftp.response.code == 227` | Passive FTP server endpoint |
| `tcp.flags.syn == 1 && tcp.flags.ack == 0` | Initiator of each TCP connection |
| `tcp.srcport == 20` | Active FTP server-originated data |
| `tcp.analysis.retransmission` | Retransmissions under packet loss |

FTP is plaintext; `.pcapng` files can contain the laboratory credentials (`ftpuser` / `ftppass`) and file contents. Use only disposable lab credentials, rotate them before publishing, and don't publish arbitrary user traffic.

## Existing command-line workflows

The scripts are intentionally kept so a second group can reproduce the protocol experiments without the web UI:

```bash
sudo bash scripts/setup_topology.sh
sudo bash scripts/setup_server.sh
sudo bash scripts/nat.sh N0
sudo bash scripts/impair.sh 0
sudo ip netns exec ftp-client python3 client/ftp_client.py --mode active --ops list,retr
sudo python3 tools/run.py matrix
sudo python3 tools/run.py evidence
sudo python3 tools/run.py experiments --reps 3 --reset
python3 tools/analyze.py
sudo bash scripts/teardown.sh
```

The CLI batch commands produce the experimental success matrix, six scenarios of PCAPNGs, and repeated throughput/setup measurements in `results/`. **These commands are no longer available as web UI actions.** Save existing `results/raw.csv` before using `--reset`.

## Troubleshooting

- **Startup says root privileges required:** Start with `sudo .venv/bin/python -m web.app` (ensure `.venv` belongs to your user, not root).
- **`mergecap` not found:** Install `wireshark-common`; test `mergecap -v`.
- **`dumpcap` permission denied:** `scripts/capture.sh` uses a temporary writable capture directory and copies closed files back into `results/pcap/`. Do not pass a directory alone to `dumpcap -w`.
- **Capture unavailable but FTP ran:** The UI shows a capture error. Check `results/pcap/web_*.log` and whether `mergecap` is present. Captures are finalized *before* merging.
- **N1 or N2 won't apply:** Validate `sudo ip netns exec r1 nft -c -f nft/N1.nft` or `nft/N2.nft`.
- **Server not listening:** Inspect `/tmp/vsftpd-start.log` and `sudo ip netns exec ftp-server ss -ltn`.
- **Port 5000 occupied:** Stop the older Flask process before starting the new one.
- **A previous crash left capture state:** After ensuring no `dumpcap` process is capturing, run `sudo bash scripts/capture.sh stop` and inspect the saved log.
- **Network has been taken down while Flask is running:** Restart the Flask process; it will reinitialize the missing components.

## File layout

- `web/` — single-page Flask user interface (presentation simulator layout integrated here, no standalone `presentation/` directory) and experiment-only API
- `scripts/` — network setup, NAT, traffic control, FTP server, packet capture, teardown
- `client/` — custom raw-socket and standard-library FTP clients
- `nft/` — N1 and N2 nftables rules
- `tools/` — optional standalone experiment evaluation and analysis
- `results/` — generated captures/results, excluded from Git by default
- `tests/` — offline API contracts
- `docs/` — architecture/report and demonstration evidence retained from the original project

## Verification

```bash
bash -n scripts/capture.sh
python3 -m compileall -q web client tools
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q tests
```

Offline tests do not execute real network namespaces. The live FTP/NAT experiments must be verified on an Ubuntu host with root access.

## AI-use disclosure

AI assistants supported portions of project development, debugging, documentation, and report preparation. Experimental outputs must come from real laboratory runs and be independently verified by the team, in accordance with course requirements.
