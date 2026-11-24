#!/usr/bin/env bash
# Usage: sudo scripts/capture.sh start <tag> | stop
# Writes pcapng files (dumpcap) on R1 inside, R1 outside and R2 server-side interfaces.
source "$(dirname "$0")/lib.sh"; need_root
OUT="$ROOT/results/pcap"; mkdir -p "$OUT"; PIDS=/tmp/cn-cap.pids
case "${1:-}" in
  start) TAG=${2:?tag}; [[ "$TAG" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "invalid capture tag" >&2; exit 1; }; : > "$PIDS"
    for pair in "$NS_R1 eth-in r1-inside" "$NS_R1 eth-out r1-outside" "$NS_R2 eth-srv r2-server"; do
      set -- $pair
      nsx $1 dumpcap -q -i $2 -w "$OUT/${TAG}__$3.pcapng" 2>/dev/null &
      echo $! >> $PIDS
    done; sleep 1; echo "capturing: $TAG" ;;
  stop) [ -f $PIDS ] && { for p in $(cat $PIDS); do kill -INT $p 2>/dev/null || true; done; sleep 1; rm -f $PIDS; } ;;
  *) echo "usage: capture.sh start <tag> | stop"; exit 1 ;;
esac
