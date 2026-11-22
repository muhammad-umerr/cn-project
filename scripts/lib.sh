#!/usr/bin/env bash
# Shared helpers. Source this file; do not run it.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS_C=ftp-client; NS_R1=r1; NS_R2=r2; NS_S=ftp-server
need_root() { [ "$(id -u)" -eq 0 ] || { echo "Please run with sudo." >&2; exit 1; }; }
nsx() { local ns=$1; shift; ip netns exec "$ns" "$@"; }
