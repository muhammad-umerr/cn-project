#!/usr/bin/env bash
source "$(dirname "$0")/lib.sh"; need_root
"$ROOT/scripts/capture.sh" stop >/dev/null 2>&1 || true
[ -f /tmp/cn-vsftpd.pid ] && kill "$(cat /tmp/cn-vsftpd.pid)" 2>/dev/null || true
pkill -f "vsftpd /etc/vsftpd-lab.conf" 2>/dev/null || true
for ns in $NS_C $NS_R1 $NS_R2 $NS_S; do ip netns del $ns 2>/dev/null || true; done
rm -f /tmp/cn-vsftpd.pid /tmp/cn-nat-state
[ "${1:-}" = quiet ] || echo "Topology removed."
