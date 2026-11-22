# FTP Through NAT — Active vs Passive | CS3001 Computer Networks

> **A real, reproducible Ubuntu networking experiment with a Flask control dashboard.** Four Linux network namespaces simulate a client, an FTP server, and two routers. The experiment compares FTP Active (`PORT`) and Passive (`PASV`) transfers using routing-only (N0), NAT (N1), and NAT with an FTP connection-tracking helper (N2), under 0%, 2%, and 5% packet loss.

**Status:** The scripts and frontend are provided as an integrated implementation. Bash parsing and Python compilation can be checked off-host; **kernel namespace, nftables, FTP helper, and throughput outcomes must be validated on a privileged Ubuntu installation**. No sample measurements or successful network executions are claimed. `results/` is intentionally empty until you conduct experiments.

## Quick links

- [Start and stop the lab](#1-installation-and-quick-start)
- [What happens when a button is clicked](#4-how-the-web-application-works-behind-the-curtain)
- [Network internals](#2-understanding-the-network)
- [Experiments and analysis](#5-experimental-methodology)
- [Packet captures and Wireshark](#6-evidence-and-wireshark)
- [Troubleshooting](#8-troubleshooting)
- [Class demonstration and deliverables](#9-classroom-demonstration-and-submission)

## Repository map

```text
cn-ftp-nat/
├── README.md                  ← this guide
├── .gitignore                 ← excludes real data captures, which may contain FTP credentials
├── requirements.txt           ← Flask
├── requirements-dev.txt       ← Flask and pytest
├── LICENSE
├── scripts/
│   ├── lib.sh                 ← namespace names, helpers
│   ├── setup_topology.sh      ← create namespaces, veths, routes, kernel modules
│   ├── setup_server.sh        ← FTP user, vsftpd server and 10 MiB file
│   ├── nat.sh                 ← N0 / N1 / N2 and return-route control
│   ├── impair.sh              ← tc netem and tbf on the transit link
│   ├── capture.sh             ← start / stop dumpcap at three interfaces
│   ├── poc.sh                 ← one terminal-based demonstration
│   ├── verify.sh              ← routing/traceroute/ping/iperf3 evidence
│   └── teardown.sh            ← stop server and remove namespaces
├── nft/
│   ├── N1.nft                 ← masquerade, no FTP helper
│   └── N2.nft                 ← masquerade + FTP helper assignment
├── client/
│   ├── ftp_client.py          ← socket-based FTP client, JSON metrics, redacted transcript
│   └── ftplib_client.py       ← independent library cross-check
├── tools/
│   ├── run.py                 ← matrix, evidence, 54/90-run campaign
│   └── analyze.py             ← CSV → mean/SD/range, PNG charts and standalone dashboard
├── web/
│   ├── app.py                 ← Flask API, subprocess orchestration, job queue, diagnostic snapshots
│   ├── templates/index.html  ← operator dashboard
│   └── static/{app.js,style.css}
├── presentation/ftp-nat-lab.html ← **educational simulation, not real measurements**
├── docs/                     ← topology diagram, report/presentation/screenshot/AI guides
├── tests/                    ← unit + API contract smoke tests
└── results/                  ← real generated CSV, JSON, PCAPNG, charts, evidence (initially empty)
```

## 1. Installation and quick start

### Requirements

A **native Ubuntu 22.04/24.04 installation or a VM with its own Linux kernel and root privileges**, not Windows PowerShell. Many managed containers, hosted sandboxes, WSL installations and unprivileged Linux containers do not expose namespace, veth, module-loading or nftables capabilities. Run locally on a disposable Ubuntu VM if uncertain. **Do not run this on a production host**: setup modifies the host's FTP user and `/etc/vsftpd-lab.conf`, and the web process requires elevated privileges.

Install Linux packages:

```bash
sudo apt update
sudo apt install -y iproute2 iputils-ping nftables conntrack vsftpd \
  python3 python3-venv python3-pip python3-matplotlib \
  tcpdump tshark wireshark-common iperf3 traceroute ethtool kmod unzip
```

Ubuntu may ask about enabling packet captures for non-root users; for this isolated lab, non-root access is not required. `dumpcap` is supplied by Wireshark packages.

Clone this repository or extract the ZIP:

```bash
unzip ftp-through-nat-complete.zip
cd cn-ftp-nat
# or: git clone <your-own-repository-url> && cd cn-ftp-nat
```

Set script permissions (included in ZIP, but helpful on cross-platform downloads):

```bash
chmod +x scripts/*.sh
```

Create a local Python environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

**Recommended one-time topology setup (terminal):**

```bash
sudo ./scripts/setup_topology.sh
sudo ./scripts/setup_server.sh
sudo ./scripts/nat.sh N0
sudo ./scripts/verify.sh
```

Then launch the real web dashboard:

```bash
sudo .venv/bin/python -m web.app
```

Open **http://127.0.0.1:5000** in the same machine's browser. Flask runs bound only to loopback; *do not change it to `0.0.0.0`*. The controller intentionally has no remote login system and can change network state as root.

**Web-only approach:** You may launch the backend first and then click **Create topology → Start FTP server → Verify routes**, followed by **Run live experiment**. The backend exposes those same underlying shell scripts. If your browser is on a different computer, do not expose this privileged server to the LAN; use a browser on Ubuntu itself (or a deliberately secured SSH tunnel managed by an experienced operator).

To stop the lab:

```bash
# stop the web process with Ctrl+C, then:
sudo ./scripts/teardown.sh
```

Keep in mind that teardown removes the four namespaces and stops the FTP lab process; it **does not** remove the test FTP account, generated `/srv/ftp-lab/10MB.bin` file, or `/etc/vsftpd-lab.conf` on the host. Clean those up manually only after confirming they are exclusively lab-created resources.

### First five-minute validation

```bash
sudo ip netns list
sudo ip netns exec ftp-client ip -4 addr
sudo ip netns exec r1 ip -4 route
sudo ip netns exec r2 ip -4 route
sudo ip netns exec ftp-client ping -c 3 172.16.20.10
sudo ip netns exec ftp-client traceroute -n 172.16.20.10
sudo ip netns exec ftp-server ss -ltn
sudo ip netns exec ftp-client python3 client/ftplib_client.py passive
sudo ip netns exec ftp-client python3 client/ftplib_client.py active
```

These should be performed in **N0 first**, which adds a return route on R2. Do not mistake a missing route for a NAT limitation.

## 2. Understanding the network

### Topology and addressing

```text
ftp-client               r1                         r2                  ftp-server
192.168.10.2/24          eth-in 192.168.10.1/24      eth-in 10.0.12.2     172.16.20.10/24
     │                     │                        │                        │
     └── veth pair ────────┤                        │                        │
                           eth-out 10.0.12.1/30 ────┘                        │
                                                   eth-srv 172.16.20.1 ─────┘
                              transit: 10.0.12.0/30         server LAN
```

- A **network namespace** isolates routes, interfaces, socket state and firewall rules, effectively creating virtual network nodes inside the Ubuntu kernel.
- A **veth pair** is a virtual Ethernet cable whose endpoints are placed in different namespaces.
- R1 and R2 have `net.ipv4.ip_forward=1`; they act as routers, not mere hosts.
- The client has default gateway `192.168.10.1`. R1 routes toward R2 via `10.0.12.2`; the server's gateway is `172.16.20.1`.
- **N0:** R1 routes without NAT; R2 has an explicit route back to `192.168.10.0/24 via 10.0.12.1`.
- **N1 and N2:** R2's private-client route is removed; R1 SNAT/masquerades packets exiting `eth-out` so server responses can return to `10.0.12.1` and be reverse translated.

The lack of an R2 route to the client LAN in N1/N2 is intentional to model a private client that the remote server cannot route to directly. The combination of missing return route *and* plain FTP PORT payload explains expected Active-mode behavior; the comparison must be interpreted with both design choices documented.

### Why FTP is special

FTP is not one TCP connection: the client opens an outgoing *control* connection to `server:21` for `USER/PASS`, `LIST`, `RETR`, `STOR`, plus a separate *data* connection for each listing/file operation.

**Active / PORT:** the client binds a listening socket to `192.168.10.2:<ephemeral>`, sends `PORT h1,h2,h3,h4,p1,p2`, and the FTP server **initiates** the data connection back to that advertised address. In N1, NAT changes packet *headers* on the control path but generally does not rewrite an address embedded inside the FTP `PORT` command. The server may thus try to reach an unrouteable private address. The control login might still work.

**Passive / PASV:** the client asks the server for a passive endpoint; the server replies with `227 (172,16,20,10,p1,p2)` and listens on a port in the configured range **40000–40100**. The client **initiates** that outgoing data TCP connection, which simple SNAT can track. Port = `p1 × 256 + p2`. The implementation requests PASV explicitly rather than EPSV, to keep IPv4 payloads visible.

**N2 / helper:** `nf_conntrack_ftp` can parse the cleartext FTP control channel and produce an *expectation* for the related data connection; `nf_nat_ftp` can assist with FTP-aware NAT transformations. `nft/N2.nft` creates a helper object and assigns it to matching port 21 control traffic. **Whether N2 succeeds is an observation, not a promise**. Verify the kernel modules, helper assignment, expectation list while transfers run, NAT table and packets on both sides of R1. There may be timing, firewall or kernel-version differences. This does not apply to encrypted FTPS control traffic unless decrypted upstream.

### What each major script actually changes

| Script | Real action | Evidence |
|---|---|---|
| `setup_topology.sh` | Creates 4 namespaces and 3 veth links; IP addresses/default gateways; forwarding; attempts to load FTP modules | `ip netns list`, `ip -n r1 route` |
| `setup_server.sh` | Creates local lab FTP account/config, generates 10 MiB test file and starts vsftpd inside `ftp-server` | `ip netns exec ftp-server ss -ltn` |
| `nat.sh N0` | Flushes R1 nftables rules; adds R2 return route | No NAT translation |
| `nat.sh N1` | Loads `nft/N1.nft` SNAT masquerade; removes R2 return route; flushes conntrack | `nft list ruleset`, `conntrack -L` |
| `nat.sh N2` | Loads `nft/N2.nft`, assigning the FTP helper; removes return route; clears tracking state | Helper/expectation traces |
| `impair.sh 2` | Applies 2% configured random loss and 10mbit tbf per direction on R1↔R2 link | `tc -s qdisc show` |
| `capture.sh start TAG` | Launches `dumpcap` in router namespaces; writes 3 PCAPNGs | `results/pcap/*.pcapng` |
| `ftp_client.py` | Performs TCP+FTP commands with raw sockets and prints a JSON result | Redacted transcript, times, bytes, hash |
| `run.py` | Sequential matrix/evidence/repeated campaigns | `results/*.csv`, conntrack, pcap |
| `analyze.py` | Aggregates observations and plots only real measurements | `results/summary.*`, charts |

## 3. Core CLI commands

Perform a single test in a terminal, bypassing the web UI:

```bash
sudo ./scripts/nat.sh N0
sudo ./scripts/impair.sh 0
sudo ip netns exec ftp-client python3 client/ftp_client.py \
  --mode active --ops list,retr,stor --verbose --pretty

sudo ./scripts/nat.sh N1
sudo ip netns exec ftp-client python3 client/ftp_client.py \
  --mode passive --ops retr --pretty

sudo ./scripts/poc.sh active N2 0
sudo ip netns exec r1 conntrack -L
sudo ip netns exec r1 conntrack -L expect
sudo ip netns exec r1 nft list ruleset
```

Observe the **actual results**; Active N2 is not marked successful in advance. `ftp_client.py` redacts `PASS` in the JSON transcript, but plaintext credentials still traverse the test FTP control socket and can appear in PCAPNG captures.

## 4. How the web application works behind the curtain

The dashboard at `/` is HTML/CSS/JS served by Flask, not an imitation of FTP traffic. The source is `web/templates/index.html`, `web/static/app.js` and `web/app.py`.

### Control path for a single experiment

```text
Browser: POST /api/experiment {"nat":"N1","mode":"passive","operation":"retr","loss":2}
          │
          ▼
Flask validates ALL four fields against predefined options; no dynamic shell commands
          │
          ▼
An exclusive in-memory job ID is allocated (second concurrent job = HTTP 409)
          │
          ├── scripts/nat.sh N1              → R1 nft rules + R2 return route + flush conntrack
          ├── scripts/impair.sh 2            → netem/tbf on both transit ends
          ├── scripts/capture.sh start TAG   → three real pcapng recordings
          ├── poll conntrack and expectations during transfer
          └── ip netns exec ftp-client python3 client/ftp_client.py --mode passive --ops retr
                        │
                        └── client FTP TCP:21 login → PASV → TCP data → RETR → 226
          │
          ├── collect R1 nftables, conntrack and traffic-control diagnostics
          └── scripts/capture.sh stop       → finalize PCAPNG files
          │
          ▼
Backend stores results in results/web_runs/<job-id>.json
          │
          ▼
Browser polls GET /api/jobs/<id> once per second, then paints ONLY measured fields
```

The `transcript` is captured inside the real socket FTP client (password redacted in returned JSON); `control_ok`, `<op>_data_connected`, `<op>_ok`, timings, byte count, SHA-256, FTP errors and the capture list are returned as JSON. Importantly, **TCP data-channel established** and **FTP operation completed** are separate flags. The UI never decides that a transfer succeeded based on the NAT mode.

`capture.sh` writes files with names like `web_<id>__r1-inside.pcapng`, `...r1-outside.pcapng` and `...r2-server.pcapng`. The browser downloads them via `/api/artifacts/pcap/<filename>`; use Wireshark for full packet detail. `conntrack -L expect` entries may be short-lived, so the web runner polls during the operation and saves unique observed lines. It does **not** guarantee catching every ephemeral expectation; packet captures and direct conntrack monitoring are complementary.

### Dashboard pages

1. **Live laboratory:** topology, namespace/server health, setup/verify/teardown buttons, N0/N1/N2, Active/Passive, LIST/RETR/STOR, packet loss, transfer results and redacted FTP command transcript.
2. **Packet evidence:** current nftables/conntrack/expectations/TC and route snapshots; links to genuine captures.
3. **Results & analysis:** actual success matrix, charts and raw data export, generated with `tools/analyze.py`.
4. **Protocol guide:** explanatory text only. The separate legacy `presentation/ftp-nat-lab.html` is a **SIMULATION** for teaching concepts; it never modifies the router or transfers files.

### HTTP endpoints

| Endpoint | Verb | What it does |
|---|---|---|
| `/api/status` | GET | Namespace + FTP listening status and active NAT mode |
| `/api/lab/setup` | POST | Creates network topology |
| `/api/lab/server` | POST | Starts isolated FTP server |
| `/api/lab/verify` | POST | Collects routes, traceroute, ping, iperf3 |
| `/api/lab/teardown` | POST | Removes namespace lab |
| `/api/experiment` | POST | Runs a single **real** FTP test |
| `/api/batch/matrix` | POST | Six-case success matrix |
| `/api/batch/evidence` | POST | Scripted capture scenarios |
| `/api/batch/experiments` | POST | Repeated loss campaign (`reps` 1–10, optional `reset`) |
| `/api/batch/analysis` | POST | Aggregate CSV / create charts |
| `/api/jobs/<id>` | GET | Poll job progress/result |
| `/api/jobs` | GET | Recent in-memory jobs |
| `/api/diagnostics` | GET | Router routes, conntrack, helper, nftables, TC |
| `/api/results` | GET | Actual CSV rows + capture list and summary |
| `/api/artifacts/<path>` | GET | Allowlisted measured files and packet captures |

### Privileges and safety

Flask launches only on `127.0.0.1:5000`, `debug=False`, `use_reloader=False`. `sudo .venv/bin/python -m web.app` is needed because network namespaces/nftables require privileges. Validated enum values become a fixed subprocess argument list (`shell=False`), so browser input cannot become arbitrary shell syntax. All modifying jobs are sequential. **Do not expose this privileged controller to the internet or a school LAN.** There is deliberately no authentication, CSRF control, or hardened multi-user permissions; local-only use is a security boundary. Captures may contain plaintext FTP credentials; avoid uploading them to a public GitHub repository.

The Flask process keeps active job states in memory and also persists completed jobs to `results/web_runs/*.json`. A hard reboot or Flask restart can interrupt an experiment; the controller does not automatically resume interrupted work. Recreate network state if necessary.

## 5. Experimental methodology

**Design:** 3 NAT modes × 2 FTP modes × 3 packet-loss levels = **18 conditions**. Minimum three repetitions = **54 runs**; preferred five repetitions = **90 runs**. `run.py` uses a 10 MiB file and applies a nominal 10 Mbit/s bottleneck using `tc tbf` on both transit directions. `tc netem` applies 0%, 2% or 5% configured independent packet-loss probability. Clear conntrack before each run; do not infer outcomes from expectations.

```bash
sudo python3 tools/run.py matrix
sudo python3 tools/run.py evidence
sudo python3 tools/run.py experiments --reps 1 --reset  # smoke test / discards old raw.csv
sudo python3 tools/run.py experiments --reps 5 --reset  # FINAL campaign (resets raw.csv)
python3 tools/analyze.py
```

Or use the corresponding UI buttons. Each experiment includes a separate control TCP connection and, for each `LIST`, `RETR` or `STOR`, a separate data connection. The matrix records control success, data connection observation, operation completion and failure stage. Statistical summary includes mean, sample standard deviation (when n ≥ 2) and range. Failed RETR transfers **are not** counted as successful throughput observations.

**Measurement caveat:** `retr_data_setup_ms` is the latency from issuing `RETR` to the `125/150` reply, per the proposal; it is *not* directly comparable to the duration of the data TCP handshake (in Passive mode the client opens that TCP connection before `RETR`). The client separately records `retr_data_conn_ms` for Passive connect; the packet capture is authoritative for full TCP handshake timing. `control_setup_ms` covers initial TCP connect through `230` login. RETR transfer duration is the interval from sending `RETR` through completion reply `226`; reported throughput is `bytes * 8 / duration / 1e6` Mbit/s. The observed 10 MiB test size is 10 × 1,048,576 bytes.

**Success is not a fabricated target.** The expected pattern is: N0 both modes usually succeed; N1 Active may fail at data connect due to private PORT address while N1 Passive usually succeeds; N2 Active may recover if kernel helper/NAT and forwarding behave as configured. Record what the captures actually show. A failing N2 with a documented root cause is valid experimental evidence.

### Results generated by scripts

| File | Content |
|---|---|
| `results/success_matrix.csv` | N0/N1/N2 × Active/Passive control/data/LIST/RETR/STOR outcomes |
| `results/raw.csv` | Individual test runs, failure reason, setup times and throughput |
| `results/summary.csv` | Success counts, mean/SD/min/max for each experimental condition |
| `results/summary.md` | Presentation-ready statistical tables |
| `results/dashboard.html` | Self-contained measured-data dashboard (no Flask required to view) |
| `results/charts/*.png` | Mean ± SD charts |
| `results/nft/*.txt` | Captured R1 rule configurations |
| `results/conntrack/*.txt` | Tracking/expectation observations |
| `results/pcap/*.pcapng` | Router-interface packet traces |
| `results/verify.txt` | Routes, traceroute, ping, iperf3 |
| `results/web_runs/*.json` | Local web job results with protocol transcripts/metadata |

The repository intentionally does not ship raw results. That folder is `.gitignore`d to avoid implying that unmeasured findings were produced and to avoid accidentally publishing cleartext passwords from captures. After real experiments, hand in a separately archived set of evidence files as required by the instructor.

## 6. Evidence and Wireshark

Download a capture from the web UI or open a local file in Wireshark:

```bash
wireshark results/pcap/your_run__r1-inside.pcapng
```

Useful display filters:

```text
tcp.port == 21
ftp.request.command == "PORT"
ftp.request.command == "PASV"
ftp.response.code == 227
ftp.response.code == 150
ftp.response.code == 226
tcp.flags.syn == 1 && tcp.flags.ack == 0
tcp.analysis.retransmission || tcp.analysis.duplicate_ack
```

For each run: find the `SYN/SYN-ACK/ACK` of the control connection; identify `USER/PASS/230`; inspect the PASV reply or PORT command and compute its endpoint; **find the TCP data connection separately**, and determine which host initiated its SYN. Compare R1 `eth-in` and `eth-out` for source translation. For N2 compare PORT *payload* on both sides and identify any `conntrack -L expect` state. If a transfer fails, locate SYN retransmissions, RSTs, unreachable addresses or FTP error replies, and explain together with routing/NAT state. Highlight only actual packet evidence in the report.

`dumpcap` captures may contain usernames/passwords because FTP uses plaintext control messages. Treat PCAPNG as potentially sensitive; do not put them in a public GitHub repo. When needed, sanitize before sharing.

## 7. Development and checks

On any machine with Python (no namespace privilege required):

```bash
.venv/bin/python -m compileall -q client tools web
for f in scripts/*.sh; do bash -n "$f"; done
.venv/bin/python -m pytest -q
```

These tests validate parsing, utility behavior and HTTP contracts using mocks. They **do not** prove that NAT helpers, packet forwarding, real vsftpd transfers or 90 experiments succeeded. Complete a live Ubuntu acceptance run before submission. See [docs/UBUNTU_ACCEPTANCE.md](docs/UBUNTU_ACCEPTANCE.md).

## 8. Troubleshooting

| Symptom | Investigation |
|---|---|
| Web status says no root | Start with `sudo .venv/bin/python -m web.app` |
| `Operation not permitted` creating namespaces | Use a privileged native Ubuntu/VM; check Linux capabilities |
| Missing `dumpcap` | `command -v dumpcap`; install `wireshark-common` / `tshark` |
| FTP server missing | `sudo ip netns exec ftp-server ss -ltn`, `cat /tmp/vsftpd-start.log` |
| Login fails | `cat /tmp/vsftpd-lab.log`; check lab user and PAM configuration |
| N0 fails to route | R2 must have `192.168.10.0/24 via 10.0.12.1`; check `ip -n r2 route` |
| N1 control works, Active RETR fails | Inspect PORT payload, R2 route, and SYN direction; this may be the phenomenon under study |
| N2 fails | `lsmod | grep -E 'nf_(conntrack|nat)_ftp'`; `ip netns exec r1 nft list ruleset`; `conntrack -L expect` *during transfer* |
| nft helper syntax error | Check installed `nft --version`, adjust `l3proto ip;` if unsupported by your nft/kernel version |
| Conntrack expectation empty after session | Expectations are transient; capture/poll *during* the operation |
| Charts missing | Run campaign then `python3 tools/analyze.py`; matplotlib optional but recommended |
| UI says another job running | Experiments are serialized to prevent race conditions. Allow the current job to finish or restart after diagnosing a hung job |
| Incorrect rates / unexpected retransmissions | Inspect `tc -s qdisc` and offload toggles; record kernel versions |

Host-level cleanup caution: the server setup creates a local test user and writes files under `/srv/ftp-lab` and `/etc`. Do not delete resources you did not create.

## 9. Classroom demonstration and submission

**Suggested 12–15-minute live sequence:** (1) explain control versus data channel with the protocol guide; (2) display namespaces, route tables and traceroute; (3) N0 Active + Passive baseline; (4) N1 Active and Passive comparison with real FTP transcript; (5) N2 Active and R1 conntrack/expectations; (6) compare before/after NAT packet captures in Wireshark; (7) show raw matrix + three packet-loss plots; (8) demonstrate reproducibility from README.

**Team roles from the proposal:** Umer — topology, NAT, helper, conntrack, traffic control and web/backend integration; Filza — raw socket FTP client, Active/Passive tests, timing and transcript UI; Hammad — server, captures, packet analysis and statistics. All three verify the integrated system and report conclusions. The final result must reflect each student's actual contribution.

**Final instructor submission:** GitHub repository URL, source ZIP, real `success_matrix.csv`, `raw.csv`, `summary.csv`, Wireshark `.pcapng` and annotated screenshots, conntrack and nft snapshots, routing/traceroute proof, 6–10 page report and reproducibility README. No packet captures/results are bundled before execution. The proposal is provided separately by the team, and all AI assistance must be disclosed as required by course policy (see `docs/AI_DISCLOSURE.md`).

## 10. GitHub publishing

```bash
cd cn-ftp-nat
git init
git add .
git commit -m "Build FTP NAT laboratory and live Flask control dashboard"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

Replace the remote with a repository you own. The ZIP is **structured like a GitHub repository but is not a pre-existing remote repository**; `git init` creates one locally. `.gitignore` protects runtime results; distribute sanitized proof-of-experiment captures through a separate secure submission attachment if needed.

## Academic integrity and attribution

The experimental findings must come from the team's own Linux runs. This repository was assembled with AI assistance and incorporates scripts from the submitted project ZIP; see `docs/AI_DISCLOSURE.md` and update it to accurately match the team's final code review and work. Confirm the course rules on generated code, and ensure all members can explain every component before submission.
