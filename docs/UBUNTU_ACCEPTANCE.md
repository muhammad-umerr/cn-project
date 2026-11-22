# Ubuntu live acceptance plan (do not skip)

The ZIP can be syntax-checked elsewhere, but only a **privileged Ubuntu kernel** can validate real namespaces, nftables helper behavior, traffic control and PCAPNG captures. Tick these checks after running them; record your OS and Linux kernel versions (`lsb_release -a`, `uname -r`).

| Test | Command / action | Passing evidence |
|---|---|---|
| 1. Network | `sudo scripts/setup_topology.sh` | four namespaces, three veth links |
| 2. Addressing | `ip -n r1 addr`, `ip -n r2 addr` | address plan matches proposal |
| 3. No-NAT routing | `sudo scripts/nat.sh N0; sudo scripts/verify.sh` | traceroute, ping, R2 return route |
| 4. Server | `sudo scripts/setup_server.sh` | `ss` port 21 and FTP login |
| 5. Baseline clients | `ftplib_client.py passive` and `active` in client namespace | completed 10 MiB transfers |
| 6. N1 passive | `sudo scripts/poc.sh passive N1` | actual result + translated addresses |
| 7. N1 active | `sudo scripts/poc.sh active N1` | outcome and explanation with PORT/SYN evidence |
| 8. N2 active | `sudo scripts/poc.sh active N2` | result, observed helpers/expectations and packet proof |
| 9. Capture | `sudo python3 tools/run.py evidence` | valid .pcapng opened in Wireshark |
| 10. Link impairment | `sudo scripts/impair.sh 2` + `tc -s qdisc` | loss and rate qdiscs visible |
| 11. Matrix | `sudo python3 tools/run.py matrix` | 6 rows with real control/list/retr/stor outcomes |
| 12. Experiments | `sudo python3 tools/run.py experiments --reps 5 --reset` | 90 rows with real outcomes |
| 13. Analysis | `python3 tools/analyze.py` | 18 condition summaries and 3 PNG charts |
| 14. Web app | `sudo .venv/bin/python -m web.app` | UI at localhost:5000, buttons run real tests |
| 15. Web data | run N0 Passive RETR and inspect PCAP & JSON | transcript/redacted password, bytes, SHA and measured status |
| 16. Clean up | `sudo scripts/teardown.sh` | namespace removal |

**Expected outcomes are not grading facts:** in N0 both modes should ordinarily succeed; under N1 Passive is expected to work and Active may fail due to embedded private address; N2 behavior depends on FTP helper/NAT kernel behavior. When results differ, document actual packet evidence and do not replace measurements with theory.

**Failure diagnosis order:** interfaces/IPs → routes → IP forwarding → FTP server/listening port → NAT tables/counters → FTP PORT/PASV payload → conntrack entries and expectations → data TCP SYN/RST → packet loss/retransmissions.
