#!/usr/bin/env bash
# Live POC. Usage: sudo scripts/poc.sh <passive|active> <N0|N1|N2> [LOSS%]
set -euo pipefail
source "$(dirname "$0")/lib.sh"; need_root
MODE=${1:?passive|active}; NAT=${2:?N0|N1|N2}; LOSS=${3:-0}
"$ROOT/scripts/nat.sh" "$NAT"; "$ROOT/scripts/impair.sh" "$LOSS"
echo; echo "---- nft ruleset on R1 ----"; nsx $NS_R1 nft list ruleset
echo; echo "---- FTP session ($MODE, $NAT, loss $LOSS%) ----"
nsx $NS_C python3 "$ROOT/client/ftp_client.py" --mode "$MODE" --ops list,retr --verbose --hold 5 --pretty &
CP=$!; sleep 3
echo; echo "---- conntrack -L on R1 (during transfer) ----"; nsx $NS_R1 conntrack -L 2>/dev/null
echo; echo "---- conntrack expectations ----"; nsx $NS_R1 conntrack -L expect 2>/dev/null || true
echo; echo "---- nft counters ----"; nsx $NS_R1 nft list ruleset | grep -i counter || true
wait $CP || true
