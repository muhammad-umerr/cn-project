# Annotated screenshot guide
Open the matching `.pcapng` from `results/pcap/` in Wireshark. Annotate with boxes/arrows (Snipping tool, Flameshot, or Wireshark's own coloring rules). Use the R1-inside and R1-outside captures side by side to show translation.

| Figure | File | Display filter | Annotate |
|---|---|---|---|
| 1 Control handshake + login | 01_control_handshake_login__r1-inside / r1-outside | `tcp.port==21` | SYN / SYN-ACK / ACK flags; client 192.168.10.2:eph vs 10.0.12.1:eph outside; 220, USER, PASS, 230 |
| 2 PASV exchange | 02_passive_pasv_N1 | `ftp.request.command=="PASV" \|\| ftp.response.code==227` | 227 payload (172,16,20,10,x,y) and computed port; payload address equals the real server |
| 3 Passive data connection | 02_passive_pasv_N1 | `tcp.port>=40000 && tcp.port<=40100` | Who sends the SYN (client), translated source on outside |
| 4 PORT with private address | 03_active_port_N1_data_fails__r1-outside | `ftp.request.command=="PORT"` | Payload still 192,168,10,2: the core of the problem |
| 5 Failed Active data | 03_...__r2-server | `tcp.port==20` | Server SYN to 192.168.10.2 retransmitting, no SYN-ACK; then `425` on control |
| 6 PORT rewritten by helper | 04_active_port_N2_helper__r1-inside vs r1-outside | `ftp.request.command=="PORT"` | Inside 192,168,10,2 vs outside 10,0,12,1; server SYN from port 20 succeeds |
| 7 No-NAT baseline | 05_/06_ ... N0 | `ftp \|\| ftp-data` | addresses unchanged on all interfaces |
| 8 Loss effects | rerun with `scripts/impair.sh 5` + `capture.sh start loss5` | `tcp.analysis.retransmission \|\| tcp.analysis.duplicate_ack` | retransmissions on control vs data |
Also screenshot: `conntrack -L` and `conntrack -L expect` (from `results/conntrack/`), `nft list ruleset`, routing tables and traceroute (`results/verify.txt`).
Caption template: "Fig. N: <what> at <capture point>. Source/destination, flags and payload highlighted; shows <conclusion>."
