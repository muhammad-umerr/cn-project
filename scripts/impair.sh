#!/usr/bin/env bash
# Usage: sudo scripts/impair.sh LOSS_PERCENT [RATE]   e.g. impair.sh 2 10mbit
# Applies netem loss + tbf rate limit to BOTH ends of the R1-R2 link (both directions impaired equally).
set -euo pipefail
source "$(dirname "$0")/lib.sh"; need_root
LOSS=${1:?loss percent}; RATE=${2:-10mbit}; DELAY=${DELAY_MS:-0}
for pair in "$NS_R1 eth-out" "$NS_R2 eth-in"; do
  set -- $pair
  nsx $1 tc qdisc del dev $2 root 2>/dev/null || true
  nsx $1 tc qdisc add dev $2 root handle 1: netem loss ${LOSS}% delay ${DELAY}ms
  nsx $1 tc qdisc add dev $2 parent 1:1 handle 10: tbf rate $RATE burst 128kbit latency 400ms
done
echo "Link impairment: loss=${LOSS}% rate=${RATE} delay=${DELAY}ms (each direction)"
