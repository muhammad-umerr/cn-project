#!/usr/bin/env bash
# Builds: ftp-client -- R1 (NAT) -- R2 -- ftp-server using namespaces and veth pairs.
set -euo pipefail
source "$(dirname "$0")/lib.sh"; need_root
"$ROOT/scripts/teardown.sh" quiet || true
modprobe nf_conntrack; modprobe nf_conntrack_ftp; modprobe nf_nat_ftp 2>/dev/null || true
for ns in $NS_C $NS_R1 $NS_R2 $NS_S; do ip netns add $ns; ip -n $ns link set lo up; done
link() { # nsA ifA ipA nsB ifB ipB
  ip link add tmp-a type veth peer name tmp-b
  ip link set tmp-a netns "$1" name "$2"; ip link set tmp-b netns "$4" name "$5"
  ip -n "$1" addr add "$3" dev "$2"; ip -n "$4" addr add "$6" dev "$5"
  ip -n "$1" link set "$2" up;        ip -n "$4" link set "$5" up
  nsx "$1" ethtool -K "$2" tso off gso off gro off >/dev/null 2>&1 || true
  nsx "$4" ethtool -K "$5" tso off gso off gro off >/dev/null 2>&1 || true
}
link $NS_C  eth0    192.168.10.2/24 $NS_R1 eth-in  192.168.10.1/24
link $NS_R1 eth-out 10.0.12.1/30    $NS_R2 eth-in  10.0.12.2/30
link $NS_R2 eth-srv 172.16.20.1/24  $NS_S  eth0    172.16.20.10/24
ip -n $NS_C route add default via 192.168.10.1
ip -n $NS_R1 route add default via 10.0.12.2
ip -n $NS_S route add default via 172.16.20.1
for r in $NS_R1 $NS_R2; do
  nsx $r sysctl -qw net.ipv4.ip_forward=1 net.ipv4.conf.all.rp_filter=0 net.ipv4.conf.default.rp_filter=0
done
echo "Topology up. Next: sudo scripts/setup_server.sh && sudo scripts/nat.sh N1"
