#!/usr/bin/env bash
# Routing evidence: routing tables, traceroute, ping, iperf3 baseline. Output saved to results/verify.txt
source "$(dirname "$0")/lib.sh"; need_root
{
echo "== NAT state: $(cat /tmp/cn-nat-state 2>/dev/null || echo unknown)"
for ns in $NS_C $NS_R1 $NS_R2 $NS_S; do echo; echo "== routes in $ns"; nsx $ns ip -4 route; done
echo; echo "== traceroute client -> server"; nsx $NS_C traceroute -n -w 1 -q 1 172.16.20.10 2>&1 || true
echo; echo "== ping client -> server"; nsx $NS_C ping -c 3 -W 1 172.16.20.10 2>&1 || true
if command -v iperf3 >/dev/null; then
  echo; echo "== iperf3 baseline (5 s)"
  nsx $NS_S timeout 25 iperf3 -s -1 -4 >/dev/null 2>&1 &
  sleep 1
  nsx $NS_S ss -ltn | grep -q ':5201 ' || echo "iperf3 server not listening"
  nsx $NS_C timeout 15 iperf3 -4 -c 172.16.20.10 -t 5 --connect-timeout 3000 2>&1 \
    || echo "iperf3 baseline failed or timed out (skipped; check NAT state and tc qdisc)"
fi
} | tee "$ROOT/results/verify.txt"
