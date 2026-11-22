#!/usr/bin/env bash
# Usage: sudo scripts/nat.sh N0|N1|N2   (N0 routing only, N1 masquerade, N2 masquerade + FTP helper)
set -euo pipefail
source "$(dirname "$0")/lib.sh"; need_root
C=${1:?usage: nat.sh N0|N1|N2}
case "$C" in
  N0) nsx $NS_R1 nft flush ruleset
      ip -n $NS_R2 route replace 192.168.10.0/24 via 10.0.12.1 ;;   # return route for the baseline
  N1|N2) nsx $NS_R1 nft -f "$ROOT/nft/$C.nft"
      ip -n $NS_R2 route del 192.168.10.0/24 2>/dev/null || true ;; # R2 must not know the private LAN
  *) echo "unknown condition $C"; exit 1 ;;
esac
nsx $NS_R1 conntrack -F >/dev/null 2>&1 || true
echo "$C" > /tmp/cn-nat-state
echo "NAT condition $C active on R1"
